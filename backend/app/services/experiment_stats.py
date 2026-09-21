"""Pre-registered, customer-level experiment mathematics (no dispatch side effects).

Primary endpoint: net gross profit per assigned customer, AFTER discounts/returns.
Costs are additional variable costs, never the discount already included in profit.
Fixed horizon only; callers must include zero outcomes for non-buyers in both arms.
This module is not an automatic campaign engine. A durable assignment/exposure and
consent layer is required before enabling real sends.
"""
from __future__ import annotations

import hashlib
import math
import random
from statistics import mean


def _finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("NON_FINITE_VALUE")
    return value


def plan_sample(baseline_rate: float, minimum_lift: float) -> int:
    """Two-sided alpha .05, 80% power, equal arms; normal approximation.

    Plans the *conversion* secondary endpoint only, NOT power for gross profit.
    Profit power needs store-specific historical variance and a separate plan.
    """
    p0, lift = _finite(baseline_rate), _finite(minimum_lift)
    p1 = p0 + lift
    if not 0 < p0 < p1 < 1:
        raise ValueError("INVALID_RATE_OR_LIFT")
    pooled = (p0 + p1) / 2
    n = ((1.95996398454 * math.sqrt(2 * pooled * (1 - pooled))
          + .84162123357 * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) / lift) ** 2
    return max(100, math.ceil(n))


def assign(customer_ids: list[int], seed: str) -> dict[str, list[int]]:
    """Balanced, reproducible partition; input order cannot alter assignment.

    Seed must be server-generated and persisted before outcomes are available.
    Refuse duplicates rather than silently altering the eligible population.
    """
    if not seed or len(customer_ids) < 2 or len(customer_ids) != len(set(customer_ids)):
        raise ValueError("INVALID_ELIGIBLE_POPULATION")
    if any(type(c) is not int or c <= 0 for c in customer_ids):
        raise ValueError("INVALID_CUSTOMER_ID")
    ordered = sorted(customer_ids, key=lambda c: hashlib.sha256(f"{seed}:{c}".encode()).digest())
    return {"treatment": ordered[::2], "control": ordered[1::2]}


def evaluate(treatment: list[dict], control: list[dict], *, planned_per_arm: int,
             window_closed: bool, minimum_net_profit: float = 0, seed: int = 0) -> dict:
    """Fixed-horizon ITT bootstrap interval of mean net-profit difference.

    Rows: customer_id, profit (net of discounts/returns), purchased (bool),
    variable_cost (known nonnegative number, or None for unknown).
    All assigned customers must be passed, including zeros. The orchestration
    layer must enforce completeness against the frozen assignment registry.
    Returns NO_ACTION on pending/inadequate/unknown evidence, never a fake gain.
    2,000 deterministic percentile bootstrap replicates, customer as sampling unit.
    """
    threshold = _finite(minimum_net_profit)
    if type(planned_per_arm) is not int or planned_per_arm < 100 or threshold < 0:
        raise ValueError("INVALID_PREREGISTERED_PLAN")
    seen = set()
    unknown_cost = False
    values = []
    rates = []
    for arm in (treatment, control):
        profits, purchases = [], []
        for row in arm:
            cid = row["customer_id"]
            if type(cid) is not int or cid <= 0 or cid in seen:
                raise ValueError("DUPLICATE_OR_INVALID_CUSTOMER")
            seen.add(cid)
            profit = _finite(row["profit"])
            purchased = row["purchased"]
            if type(purchased) is not bool:
                raise ValueError("INVALID_PURCHASE_FLAG")
            cost = row["variable_cost"]
            if cost is None:
                unknown_cost = True
                cost = 0  # no net-profit result is emitted in this branch
            cost = _finite(cost)
            if cost < 0:
                raise ValueError("NEGATIVE_COST")
            profits.append(profit - cost)
            purchases.append(int(purchased))
        values.append(profits)
        rates.append(mean(purchases) if purchases else None)
    result = {"decision": "NO_ACTION", "n_treatment": len(treatment), "n_control": len(control),
              "purchase_rates": rates, "confidence_level": .95, "method": "customer_percentile_bootstrap"}
    if not window_closed:
        return {**result, "status": "OBSERVING"}
    if min(len(treatment), len(control)) < planned_per_arm:
        return {**result, "status": "INSUFFICIENT_DATA"}
    if unknown_cost:
        return {**result, "status": "INCOMPLETE_COSTS"}
    rng = random.Random(seed)
    t, c = values
    draws = sorted(mean(rng.choices(t, k=len(t))) - mean(rng.choices(c, k=len(c))) for _ in range(2000))
    low, high = draws[49], draws[1949]
    difference = mean(t) - mean(c)
    # A degenerate sample supplies no empirical uncertainty estimate; do not
    # promote a policy based on a zero-width bootstrap confidence interval.
    if low == high:
        decision = "NO_ACTION"
    else:
        decision = "ACCEPT_FOR_RETEST" if low > threshold else "REJECT" if high < 0 else "NO_ACTION"
    return {**result, "status": "COMPLETE", "decision": decision,
            "net_profit_per_customer": difference, "net_profit_interval": [low, high],
            "estimated_incremental_profit": difference * len(t),
            "purchase_lift_pp": (rates[0] - rates[1]) * 100}
