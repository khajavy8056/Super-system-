# Branch divergence — RESOLVED in v3.6.1

**The merge has been done.** `arena/01a076d3-super-system` (v3.6.0: 59 analyzers, the
`ai_narrator` free-provider advisor, `Ui.paged` on 22+ lists) was merged into
`arena/01a0a5c6-super-system` (v3.5.13: the device-identity/login/licence fixes, 24 customer
analyzers). v3.6.1 carries both. What follows is kept because the reasoning is still needed
by anyone touching the intelligence engine.

Two parallel lines of work existed in this repository. Neither contained the other.

| | `arena/01a0a5c6-super-system` (this branch) | `arena/01a076d3-super-system` (parent) |
|---|---|---|
| Latest tag | `v3.5.13` (`a30e031`) | `v3.6.0` (`db15fb4`) |
| Intelligence | `services/customer_intel.py` — 24 analyzers, 37 kinds total | `services/insights_pro.py` — 46 analyzers, 59 kinds total |
| AI advisor | none | `services/ai_narrator.py` — OpenAI-compatible (OpenRouter / Groq / Together / Ollama / LM Studio / resellers) with a local template fallback |
| Staged lists | `Ui.page` on 7 lists | `Ui.paged` on 22+ lists plus `pagedAppend` on web |
| Device identity / login / licence quota | **fixed** (v3.5.11–v3.5.13) | **not fixed** |

Common ancestor: `e65dc2f` ("Add files via upload").

## Merging them is not a plain conflict resolution

`git merge` auto-merges `insights.py` and `Ui.java` cleanly but conflicts in
`backend/app/__init__.py`, `backend/tests/test_v1_consolidation.py`,
`installer/windows/setup.iss`, `AdminScreens.java`, `InsightScreens.java`,
`SalesScreens.java`, `StockScreens.java` — because the two sides implement *different*
paging helpers and call their own at the same sites. Pick one helper (`Ui.paged` covers
more lists) and delete the other, or the same list gets paged twice.

The analyzers also overlap, so a naive merge shows the shop two competing cards for one
problem. Exact name collisions between the two modules:

    DISCOUNT_LEAK  OVERSTOCK  PRICE_ROUNDING   (+ PEAK_HOURS vs PEAK_HOUR)

Semantic duplicates that need one keeper each:

    PAY_CYCLE ≈ CUST_PAYDAY          TICKET_DROP ≈ CUST_BASKET_SHRINK
    FREQ_DROP ≈ CHURN                NEW_CUST_2ND ≈ CUST_NEW_SECOND
    CATEGORY_GAP ≈ CUST_CATEGORY_LOSS  CREDIT_RISK ≈ CUST_CREDIT_SLOW
    TREND_DOWN ≈ TREND_BREAK

Only present in `customer_intel.py` and worth keeping: `CUST_CONCENTRATION`,
`CUST_ANONYMOUS`, `CUST_LOYALTY_GAP`, `CUST_RETURN_ABUSE`, `MARGIN_EROSION`,
`PROMO_DEPTH`, `STOCKOUT_COST`, `ABC_DRIFT`, `DATA_HYGIENE`, `WEEKDAY_DIP`,
`SUPPLIER_CONCENTRATION`, `ATTACH_OPPORTUNITY`, `CUST_RFM`.

## Invariants that hold on this branch — keep them

* `insight_actions.ACTIONS[type]` reads its arguments from **`a["params"]`**, not from the
  top level of the action dict. A draft that puts them at the top level passes a name-only
  check and raises KeyError when the shop presses the button.
* `insights._metric_value` only understands the kinds it dispatches on; a draft naming any
  other metric can never be measured.
* `tests/test_v3513_customer_intel.py` enforces both, and actually accepts the suggestions
  to prove the actions execute. Extend it rather than adding a new guard file.
* `customer_intel` self-registers at the bottom of its own file and `insights.py` merges it
  only when it is not already mid-import — that is what makes the import order not matter.
