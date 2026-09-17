import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from app.services import simulation_checkpoint as cp


@pytest.fixture
def engine(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'state.db'))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE events(id INTEGER PRIMARY KEY, label TEXT)'))
    yield engine
    engine.dispose()


def test_graph_preserves_aliases_tuples_dates_sets_and_random_state(engine):
    shared = {'stock': 19, 'arrives': date(2020, 1, 3)}
    rng = random.Random(42); rng.gauss(0, 1)
    state = {'products': [shared], 'customers': [{'fav': [shared]}],
             'pairs': {(1, 2): .2}, 'active': {7, 8}, 'rng': rng.getstate()}
    with cp.ReplaySession(bind=engine) as db:
        restored = cp.decode(json.loads(json.dumps(cp.encode(state))), db)
    assert restored['products'][0] is restored['customers'][0]['fav'][0]
    restored['products'][0]['stock'] = 5
    assert restored['customers'][0]['fav'][0]['stock'] == 5
    assert restored['pairs'] == {(1, 2): .2} and restored['active'] == {7, 8}
    assert restored['products'][0]['arrives'] == date(2020, 1, 3)
    replay = random.Random(); replay.setstate(restored['rng'])
    assert [rng.random() for _ in range(10)] == [replay.random() for _ in range(10)]


def test_commits_inside_day_do_not_publish_partial_work(engine):
    with cp.ReplaySession(bind=engine) as db:
        cp.save(db, {'v': 1}, {'day': 0}); db.commit()
        with pytest.raises(RuntimeError, match='power cut'):
            with db.atomic_day():
                db.execute(text("INSERT INTO events VALUES(1,'half day')")); db.commit()
                with db.begin_nested():
                    db.execute(text("INSERT INTO events VALUES(2,'nested commit')"))
                cp.save(db, {'v': 1}, {'day': 1})
                raise RuntimeError('power cut')
        assert db.execute(text('SELECT COUNT(*) FROM events')).scalar() == 0
        assert cp.load(db, {'v': 1}) == {'day': 0}
        with db.atomic_day():
            db.execute(text("INSERT INTO events VALUES(1,'complete')"))
            cp.save(db, {'v': 1}, {'day': 1})
        assert cp.load(db, {'v': 1}) == {'day': 1}


def test_swallowed_whole_session_rollback_still_aborts_day(engine):
    with cp.ReplaySession(bind=engine) as db:
        with pytest.raises(RuntimeError, match='DAY_ABORTED'):
            with db.atomic_day():
                db.execute(text("INSERT INTO events VALUES(1,'invalid')"))
                try:
                    db.rollback()
                except RuntimeError:
                    pass
        assert db.execute(text('SELECT COUNT(*) FROM events')).scalar() == 0


def test_real_process_death_after_nested_commit_keeps_last_checkpoint(engine):
    url = str(engine.url)
    with cp.ReplaySession(bind=engine) as db:
        cp.save(db, {'v': 1}, {'day': 0}); db.commit()
    code = '''
import os, sys
from sqlalchemy import create_engine, text
from app.services.simulation_checkpoint import ReplaySession, save
with ReplaySession(bind=create_engine(sys.argv[1])) as db:
    with db.atomic_day():
        with db.begin_nested():
            db.execute(text("INSERT INTO events VALUES(1,'must not survive')"))
        db.commit()
        save(db, {'v': 1}, {'day': 1})
        os._exit(17)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, '-c', code, url], env=env, timeout=30)
    assert result.returncode == 17
    with cp.ReplaySession(bind=engine) as db:
        assert cp.load(db, {'v': 1}) == {'day': 0}
        assert db.execute(text('SELECT COUNT(*) FROM events')).scalar() == 0


def test_config_change_rejected(engine):
    with cp.ReplaySession(bind=engine) as db:
        cp.save(db, {'days': 365}, {'phase': 'running'}); db.commit()
        with pytest.raises(ValueError, match='CONFIG_OR_CODE_CHANGED'):
            cp.load(db, {'days': 3})


def test_locks_and_workspace_protect_existing_data(tmp_path):
    with cp.workspace(tmp_path, False):
        with pytest.raises(RuntimeError, match='ALREADY_RUNNING'):
            with cp.workspace(tmp_path, False):
                pass
    (tmp_path / 'important.txt').write_text('preserve')
    with pytest.raises(ValueError, match='NOT_EMPTY'):
        with cp.workspace(tmp_path, False):
            pass
    assert (tmp_path / 'important.txt').read_text() == 'preserve'


def test_decode_rejects_executable_or_unknown_tags(engine):
    with cp.ReplaySession(bind=engine) as db:
        with pytest.raises(ValueError, match='UNKNOWN_CHECKPOINT_TAG'):
            cp.decode({'nodes': [['pickle', 'anything']], 'root': {'ref': 0}}, db)


@pytest.mark.parametrize("days,pause_after", [(2, 1), (46, 27)])
def test_generator_resume_matches_uninterrupted_business_records(tmp_path, days, pause_after):
    from app.services.demo_store import generate_backup_file
    work = tmp_path / 'resumed.work'
    args = dict(days=days, seed=187, invoices_per_day=20, full_catalog=False, compress=False)
    resumed = tmp_path / 'resumed.db'
    baseline = tmp_path / 'baseline.db'
    with pytest.raises(cp.SimulationPaused):
        generate_backup_file(resumed, work_dir=work, pause_after_days=pause_after, **args)
    assert not resumed.exists(), 'a pause must not publish a partial backup'
    with sqlite3.connect(work / 'demo.db') as db:
        before = db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0]
    assert before > 0
    result = generate_backup_file(resumed, work_dir=work, resume=True, **args)
    original = generate_backup_file(baseline, work_dir=tmp_path/'baseline.work', **args)
    assert result['invoices'] == original['invoices'] > before
    assert result['sales'] == original['sales']
    if days > 20:
        assert result['accepted_insights'] == original['accepted_insights'] > 0
    with sqlite3.connect(resumed) as a, sqlite3.connect(baseline) as b:
        assert not a.execute("SELECT 1 FROM sqlite_master WHERE name='_simulation_checkpoint'").fetchone()
        for query in [
            'SELECT id,customer_id,subtotal,discount,total_amount,status,created_at FROM invoices ORDER BY id',
            'SELECT invoice_id,product_id,batch_id,qty,unit_sell_price,subtotal FROM invoice_items ORDER BY id',
            'SELECT id,product_id,current_qty FROM product_batches ORDER BY id',
            'SELECT customer_id,amount,balance_after FROM customer_ledger_entries ORDER BY id',
        ]:
            assert a.execute(query).fetchall() == b.execute(query).fetchall()
    # Re-export of a completed run must not regenerate a single sale.
    again = generate_backup_file(tmp_path/'reexport.db', work_dir=work, resume=True, **args)
    assert again['invoices'] == result['invoices']
