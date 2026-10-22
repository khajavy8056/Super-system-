# Release Audit — v4.7.0 (Round 15)

**Date:** 2026-09-24 · **Scope:** honest POS suggestions + one-year Colab simulator

## What the owner asked (verbatim intent)

1. «موجود نداریم نباید پیشنهاد بده» — POS suggestions must never advertise unavailable items; prioritize items whose expiry is **approaching** («نزدیک شدیم نه عبور کرده»); fix the named bug of suggesting unavailable items.
2. Suggestions must appear in the POS of **both** the mobile and the Windows versions.
3. A **one-year simulator** at ~100 big stores daily scale (customers, cheques, expenses, salaries, card terminals, shifts, stocktakes, receivings, store-intelligence suggestions executed with measured results, usage of all sections) — too slow locally → deliver a **Google Colab notebook in tools/** that downloads the project, installs it, runs fast with a clean progress bar, and produces a backup restorable on **Windows AND Android**, covering **all products in the default bank**.
4. Release the new program version.

## What was delivered

### 1. Honest POS suggestions (root-cause fix)

| Item | Evidence |
|---|---|
| Root cause | `pos.sellable_batches` excluded expired batches ONLY when `expiry.block_sale` was ON — nudges trusted it, so with the policy off, dead items were advertised |
| Fix | `insights.sellable_now()` (new): a suggestion candidate must be alive (active, not deleted) AND have an ACTIVE batch with stock AND `expiry_date IS NULL OR >= today` — **independent of store policy** |
| Manual rules | `POST /insights/nudges` merged `insights.manual_rules` WITHOUT any check — same bug through a second door; now filtered through `sellable_now()` too |
| Near-expiry priority | Among honest candidates, `0 <= days_left <= 30` ranks first (`purpose: sell_before_expiry`) with a plain-Persian `reason` («موجودی «…» تا N روز آینده تاریخ می‌خورد؛ اگر امروز نفروشد ضرر می‌شود») |
| No-expiry safe | `min(..., default=None)` — a shelf staple with no expiry dates no longer crashes the endpoint (found during this round, fixed + tested) |
| Output contract | ≤2 items: `{product_id, name, because, confidence, days_left, near_expiry, purpose, reason?}` |
| Android POS | `SalesScreens.java`: teal nudge bar above the cart, refreshed on every cart render (350 ms debounce), one-tap add via `/products/{id}` + `/pos/batch-options/{id}`, amber chip + reason for near-expiry |
| Windows POS | `frontend/insights.js`: nudge chip shows the near-expiry reason in the title + «⏰ N روز» in the label (`node --check` clean) |

### 2. One-year simulator

| Piece | Path |
|---|---|
| CLI (Colab-ready) | `tools/simulate_year.py` — Persian tqdm bar, `--days/--per-day/--seed/--out/--resume-dir/--no-full-catalog`, prints `__SIM_DONE__` marker |
| Colab notebook | `tools/colab_year_simulator.ipynb` — clones the repo, installs, configures, runs, auto-downloads (`files.download`); honest GPU note (simulation is CPU-bound) |
| New simulated data | weekly per-cashier `CashSession` shifts (opening float → real week's sales via `session_summary` → counted cash rounded to 1,000 with a small human difference → Z-report journal, back-dated) and quarterly `Stocktake`s (sample count, 18 % human variance, `complete_stocktake` → `approve_stocktake` through the REAL services: adjustments + STOCKTAKE movements + audit, back-dated) |
| Full-catalog mode | now accepts the top-12 insights (execute & measure) instead of none — the owner wants suggestions EXECUTED with results |
| Scale knobs | `--per-day 9500` ≈ 100 big stores; `full_catalog` = all 13,570 default-bank products |
| Isolation pattern | risky demo hooks run AFTER the day's commit in their own transaction (pysqlite SAVEPOINTs are unreliable — discovered the hard way, see test notes); a failed hook logs and skips, never eats the day |

### 3. Release artifacts

- `backend/app/__init__.py` → 4.7.0; `installer/windows/setup.iss` → 4.7.0; Android versionCode **40700** (derived from the single source of truth)
- `releases/android/SupermarketMobile-4.7.0.apk` — 1,398,163 bytes, sha256 `3f92a84c10dac433cac958c0c88fbf4218f13a96be2db337519f550d1f10f30e`, same signing cert as 4.6.0 (in-place update), install-preflight PASS, no native ABIs
- CHANGELOG 4.7.0 (Persian, owner-facing)

## Verification

### Test suite
- **624 passed / 1 skipped** (was 614; +10 new in `test_v47_pos_suggestions.py`)
- New coverage: the named expired-item bug with `block_sale=false`; out-of-stock silence; near-expiry ranks above a STRONGER fresh rule and explains itself; no-expiry-date products don't crash; manual rules are honest; the router gate; the simulated year contains closed shifts and approved stocktakes (validated by reading the produced .db.gz); the notebook is valid JSON that clones the real repo and runs `simulate_year`; the CLI runs
- One pre-existing test updated: the `two_batches` fixture (+30d expiry) now legitimately lands inside the near-expiry window → expected purpose changed from `sell_now` to `sell_before_expiry` (documented in the test)

### Live verification (fresh 25-day simulated store, port 8000)
- Gate OFF → `POST /api/insights/nudges` returns `[]`; gate ON via `PUT /api/settings` → returns the suggestion
- Cart with ماکارونی → رب گوجه suggested (`sell_now`, stock=1)
- Cart with خیار → گوجه‌فرنگی suggested with `days_left: 4`, `near_expiry: true`, `purpose: sell_before_expiry` + Persian reason
- Zeroing the partner's stock → the endpoint goes silent (no out-of-stock suggestion); stock restored
- **Restore:** `POST /api/system/restore` with the simulator's 5-day `.db.gz` → `ok: true`, safety backup written; the served data became exactly the simulator's (75 products, 157 invoices, 3 shifts, 3 stocktakes) — the same file the Colab notebook produces

### Build
- APK built with the SDK-less toolchain (ecj + d8 + aapt2 + apksigner), preflight PASS, cert `CN=Khajavy Supermarket, O=Khajavy, C=IR` SHA-256 `18b4ab1868c026476c4027fe823d38a8e3965f70194cc0d65e60eac4e7321fa5`

## Honest notes / known limits

- The Android POS nudge bar is compiled and preflight-passed but was not exercised on a physical phone in this round; the API it calls is live-verified above.
- The full 365-day × 9,500-invoices/day Colab run was not executed here (it needs Colab's CPU/disk budget); every ingredient is verified: the 25-day live store, the 5-day and 8-day end-to-end builds, restore of the produced file, and the notebook's JSON/flow.
- Cash-session difference is intentionally tiny (rounded to the nearest 1,000) — a huge mismatch would imply a bug, not realism.
