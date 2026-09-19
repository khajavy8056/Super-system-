"""Atomic simulation checkpoints. JSON graph, not pickle; never restores executable code.

The checkpoint lives in the same SQLite transaction as the completed day. Inner
service commits become flushes while a day is active; an attempted whole-session
rollback poisons that day so it can never accidentally be published as complete.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Customer, ExpenseCategory, Product, Supplier, User

MODELS = {c.__name__: c for c in (Customer, ExpenseCategory, Product, Supplier, User)}
FORMAT = 1


class SimulationPaused(RuntimeError):
    pass


class ReplaySession(Session):
    _atomic_day = False
    _day_failed = False

    def commit(self):
        if self._atomic_day:
            if self._day_failed:
                raise RuntimeError("SIMULATION_DAY_ABORTED")
            self.flush()
        else:
            super().commit()

    def rollback(self):
        if self._atomic_day:
            self._day_failed = True
            raise RuntimeError("SIMULATION_DAY_ROLLBACK_REQUIRED")
        super().rollback()

    @contextmanager
    def atomic_day(self):
        if self._atomic_day:
            raise RuntimeError("NESTED_SIMULATION_DAY")
        self._atomic_day, self._day_failed = True, False
        try:
            # sqlite3's legacy mode does NOT BEGIN for SELECT or SAVEPOINT.
            # An explicit outer transaction is essential before service savepoints.
            connection = self.connection()
            if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql('BEGIN')
            yield
            if self._day_failed:
                raise RuntimeError("SIMULATION_DAY_ABORTED")
            self._atomic_day = False
            super().commit()
        except BaseException:
            self._atomic_day = False
            super().rollback()
            raise
        finally:
            self._atomic_day = False


def signature(days, seed, rate, full_catalog):
    app_dir = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(app_dir.rglob('*.py')):
        digest.update(str(path.relative_to(app_dir)).encode())
        digest.update(path.read_bytes())
    catalog = app_dir / 'data' / 'default_catalog.csv'
    if catalog.exists():
        with catalog.open('rb') as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(chunk)
    return {'format': FORMAT, 'code': digest.hexdigest(), 'days': days,
            'seed': seed, 'rate': float(rate), 'full_catalog': bool(full_catalog)}


def encode(value):
    nodes, identities = [], {}

    def visit(obj):
        if obj is None or type(obj) in (bool, int, float, str):
            return obj
        key = id(obj)
        if key in identities:
            return {'ref': identities[key]}
        idx = len(nodes)
        identities[key] = idx
        nodes.append(None)
        if type(obj).__name__ in MODELS and isinstance(obj, MODELS[type(obj).__name__]):
            node = ['orm', type(obj).__name__, obj.id]
        elif isinstance(obj, datetime):
            node = ['datetime', obj.isoformat()]
        elif isinstance(obj, date):
            node = ['date', obj.isoformat()]
        elif isinstance(obj, Decimal):
            node = ['decimal', str(obj)]
        elif isinstance(obj, dict):
            node = ['dict', [[visit(k), visit(v)] for k, v in obj.items()]]
        elif type(obj) in (list, tuple, set):
            node = [type(obj).__name__, [visit(x) for x in obj]]
        else:
            raise TypeError(f'UNSUPPORTED_CHECKPOINT_TYPE:{type(obj).__name__}')
        nodes[idx] = node
        return {'ref': idx}

    root = visit(value)
    return {'nodes': nodes, 'root': root}


def decode(graph, db):
    nodes, cache = graph['nodes'], {}
    # Fetch ORM references in bounded groups, not a query per customer/product.
    objects = {}
    for name, model in MODELS.items():
        ids = list({node[2] for node in nodes if node[0] == 'orm' and node[1] == name})
        for start in range(0, len(ids), 500):
            for obj in db.execute(select(model).where(model.id.in_(ids[start:start+500]))).scalars():
                objects[(name, obj.id)] = obj

    def visit(value):
        if not isinstance(value, dict):
            return value
        idx = value['ref']
        if idx in cache:
            return cache[idx]
        node = nodes[idx]
        tag, data = node[0], node[1]
        if tag == 'dict':
            result = {}; cache[idx] = result
            for k, v in data:
                result[visit(k)] = visit(v)
        elif tag in ('list', 'set'):
            result = [] if tag == 'list' else set(); cache[idx] = result
            for item in data:
                (result.append if tag == 'list' else result.add)(visit(item))
        elif tag == 'tuple':
            result = tuple(visit(x) for x in data)
        elif tag == 'orm':
            if data not in MODELS or (data, node[2]) not in objects:
                raise ValueError('CHECKPOINT_MISSING_RECORD')
            result = objects[(data, node[2])]
        elif tag == 'date':
            result = date.fromisoformat(data)
        elif tag == 'datetime':
            result = datetime.fromisoformat(data)
        elif tag == 'decimal':
            result = Decimal(data)
        else:
            raise ValueError('UNKNOWN_CHECKPOINT_TAG')
        cache[idx] = result
        return result

    return visit(graph['root'])


def save(db, config, state):
    db.flush()
    payload = json.dumps({'config': config, 'state': encode(state)}, ensure_ascii=False, allow_nan=False)
    db.execute(text('CREATE TABLE IF NOT EXISTS _simulation_checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)'))
    db.execute(text('INSERT OR REPLACE INTO _simulation_checkpoint(id,payload) VALUES(1,:payload)'), {'payload': payload})


def load(db, config):
    exists = db.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='_simulation_checkpoint'")).first()
    if not exists:
        return None
    row = db.execute(text('SELECT payload FROM _simulation_checkpoint WHERE id=1')).first()
    if row is None:
        raise ValueError('EMPTY_SIMULATION_CHECKPOINT')
    payload = json.loads(row[0])
    if payload['config'] != config:
        raise ValueError('CHECKPOINT_CONFIG_OR_CODE_CHANGED: use the original parameters and code or a new work directory')
    return decode(payload['state'], db)


@contextmanager
def file_lock(path):
    """OS-owned lock: a killed process cannot leave a stale PID lock behind."""
    import os
    path = Path(path)
    with path.open('a+b') as file:
        file.seek(0, 2)
        if file.tell() == 0:
            file.write(b'0'); file.flush()
        file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('SIMULATION_ALREADY_RUNNING') from exc
        try:
            yield
        finally:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def workspace(path, resume):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(path / 'run.lock'):
        if resume:
            if not (path / 'demo.db').is_file():
                raise ValueError('NO_SIMULATION_TO_RESUME')
            import sqlite3
            with sqlite3.connect((path / 'demo.db').as_uri() + '?mode=ro', uri=True) as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='_simulation_checkpoint' AND type='table'").fetchone()
                if not exists or not db.execute('SELECT 1 FROM _simulation_checkpoint WHERE id=1').fetchone():
                    raise ValueError('NO_COMPLETED_CHECKPOINT: initialization did not finish; use a new work directory')
        elif any(p.name != 'run.lock' for p in path.iterdir()):
            raise ValueError('WORK_DIRECTORY_NOT_EMPTY: use --resume or a new directory')
        yield str(path)
