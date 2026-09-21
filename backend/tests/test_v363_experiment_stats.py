import pytest
from app.services.experiment_stats import assign, evaluate, plan_sample


def rows(start, profit, n=100, cost=1):
    return [{'customer_id': start+i, 'profit': profit+(i % 7),
             'purchased': True, 'variable_cost': cost} for i in range(n)]


def test_assignment_is_balanced_reproducible_and_order_independent():
    ids = list(range(1, 202))
    a = assign(ids, 'frozen-random-server-seed')
    assert a == assign(ids[::-1], 'frozen-random-server-seed')
    assert len(a['treatment']) == 101 and len(a['control']) == 100
    assert not set(a['treatment']) & set(a['control'])
    assert set(a['treatment'] + a['control']) == set(ids)
    assert a != assign(ids, 'another-seed')


@pytest.mark.parametrize('ids', [[1, 1], [1], [0, 1], [True, 2]])
def test_invalid_assignment(ids):
    with pytest.raises(ValueError):
        assign(ids, 'seed')


def test_sample_plan_not_magic_small_count():
    assert plan_sample(.084, .033) > 1000
    assert plan_sample(.084, .01) > plan_sample(.084, .033)
    with pytest.raises(ValueError):
        plan_sample(.9, .2)


def test_pending_insufficient_and_unknown_cost_never_claim_profit():
    t, c = rows(1, 100), rows(101, 10)
    for kwargs, status in [({'window_closed': False}, 'OBSERVING'),
                           ({'planned_per_arm': 101}, 'INSUFFICIENT_DATA')]:
        out = evaluate(t, c, **({'window_closed': True, 'planned_per_arm': 100} | kwargs))
        assert out['status'] == status and out['decision'] == 'NO_ACTION'
        assert 'estimated_incremental_profit' not in out
    t[0]['variable_cost'] = None
    out = evaluate(t, c, planned_per_arm=100, window_closed=True)
    assert out['status'] == 'INCOMPLETE_COSTS'
    assert 'estimated_incremental_profit' not in out


def test_gross_gain_with_high_cost_is_rejected_not_recommended():
    out = evaluate(rows(1, 100, cost=150), rows(101, 10),
                   planned_per_arm=100, window_closed=True)
    assert out['decision'] == 'REJECT'
    assert out['net_profit_interval'][1] < 0


def test_net_gain_is_retest_not_permanent_activation():
    t, c = rows(1, 100), rows(101, 10)
    out = evaluate(t, c, planned_per_arm=100, window_closed=True)
    assert out['decision'] == 'ACCEPT_FOR_RETEST'
    assert out['estimated_incremental_profit'] == pytest.approx(9000)
    assert out['purchase_lift_pp'] == 0  # same revenue conversion can have different profit
    assert out == evaluate(t, c, planned_per_arm=100, window_closed=True)


def test_zero_buyers_remain_in_denominator():
    t, c = rows(1, 100), rows(101, 10)
    for row in t[:50]:
        row.update(profit=0, purchased=False)
    out = evaluate(t, c, planned_per_arm=100, window_closed=True)
    assert out['n_treatment'] == 100
    assert out['purchase_lift_pp'] == -50


def test_overlap_nonfinite_and_negative_cost_rejected():
    with pytest.raises(ValueError):
        evaluate(rows(1, 10), rows(1, 20), planned_per_arm=100, window_closed=True)
    for value in [float('nan'), float('inf')]:
        t = rows(1, 10)
        t[0]['profit'] = value
        with pytest.raises(ValueError):
            evaluate(t, rows(101, 20), planned_per_arm=100, window_closed=True)
    with pytest.raises(ValueError):
        evaluate(rows(1, 10, cost=-1), rows(101, 20), planned_per_arm=100, window_closed=True)
