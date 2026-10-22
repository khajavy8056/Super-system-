# Release Audit — v4.8.0 (Round 16)

**Date:** 2026-09-28 · **Scope:** expiry timeline before the last day · «اجرا» really executes · Android POS nudge · verified actions across the shop · a more professional UI on Windows **and** Android · orderly invoice SMS

## What the owner asked (verbatim intent)

1. «وقتی پیشنهاد می‌دهد که ۰ روز مانده، یعنی کالا فاسد شده» — store intelligence suggested tiered discounts **only at zero days left**; advice must come **days or at least a week before** expiry.
2. Clicking **«اجرا»** must genuinely perform the work (the markdown must really land on the batch).
3. The POS/checkout suggestion was **missing on Android**; the owner also asked for a **shop-wide check system** covering the suggestion → execution path.
4. Both the **Android** app and the **Windows** app need a **more professional / modern UI**.
5. Invoice **SMS must be sent in an orderly sequence** — the text was arriving jumbled.
6. Test everything, fix what is found, release the new version.

## What was delivered

### 1. Expiry timeline — advice weeks earlier, never at day zero

| Item | Evidence |
|---|---|
| Root cause | The old engine asked «will it sell before expiry?» with a **single optimistic 28-day average and no safety margin** — one busy week (or a promotion) pushed the average up and silenced the warning until the last day |
| Conservative velocity | New `services/expiry_plan.py` uses the **slowest observed rate** (min of 7/28/90-day windows): the decision must survive a quiet week, not the best one |
| Safety buffer | `insights.expiry_safety` (default **1.15**) — «almost all of it sells» is not enough; real risk ⇒ real action |
| Dated ladder | Every step carries a **Jalali date + suggested price**; 3 steps for ≥7 days runway, 2 for 3–6, 1 for ≤2. **Last step lands ≥2 days before expiry**; never below buy price (discount ceiling 60 %) |
| Expired = honest, no discount | An expired batch gets a **«ثبت ضایعات»** card (real waste: stock down + WASTE movement + accounting) instead of a discount nobody can sell |
| Not silenced by volume | Card cap raised **8 → 25** (`EXPIRY_DRAFTS_CAP`): a shop with dozens of at-risk batches used to never see the later ones |
| Settings | `insights.expiry_lead_days` (21) · `insights.expiry_safety` (1.15) · `insights.pos_expiry_days` (30) |

### 2. «اجرا» really executes — and stays executed

| Item | Evidence |
|---|---|
| Same-moment verification | VALIDATE → SAVEPOINT → EXECUTE → **VERIFY**; an action whose effect is not in the data is **never** recorded as done (`markdown` = plan stored **and** applied non-empty **and** price < base) |
| Ladder really moves the price | `apply_markdown_steps` keys steps by **index** (two equal percentages both apply), writes price version + history + audit + notification, and keeps the plan until the last step |
| Checkout guarantee | The same function runs **before every checkout** (server `pos.py` and Android `Db.localSale`), so a shop with the worker off still sells at today's step |
| Shop-wide check (new) | `GET /api/insights/actions/report` (OK / LOST / FAILED / UNVERIFIED / UNKNOWN per action) and `POST /api/insights/actions/health-scan` (live re-check); the worker notifies **once** when an executed effect is gone. «بررسی اجراها» dialog in the web panel and Android both render this report |
| Android parity | `Insights.java` mirrors the engine (`expiry()`, `nudges()`, `execute()` incl. **write_off_waste**, `healthReport()`/`healthScan()`) |

### 3. POS suggestion on Android (named bug) + one consistent card

| Item | Evidence |
|---|---|
| Root cause | The phone's offline path only fell back to the local engine for **GET** calls; `/insights/nudges` is a **POST**, so on a stand-alone phone (or with the PC unreachable) it returned nothing and the bar never appeared |
| Fix | The phone till now answers from its own local engine offline; `days_left` / `batch_id` / `near_expiry` / `reason` and the «near-expiry first» ordering are **identical** to the PC |
| UI | The duplicate legacy nudge bar (v3.0) is gone; one violet «whisper» card with a «⏰ N روز» badge, refreshed on every cart change |
| Persian text | The nudge reason is Persian-digit formatted on all three surfaces (server, router manual rules, Android) — «تا ۱۲ روز» not «تا 12 روز» |

### 4. Invoice SMS in order

* Fixed layout: «فروشگاه | فاکتور N | تاریخ شمسی» → one line per item («۱. نام qty × قیمت = جمع») → subtotal/discount/tax line → «پرداختی» → coupon → signature; Persian digits and thousands separators throughout.
* `sms.invoice_max_items` cap with an explicit «و N قلم دیگر» row — never a silent omission; old one-line templates are upgraded, never truncated.
* **Melipayamak pattern mode** sends the **short** form (`‹store› | فاکتور N | مبلغ … ‹currency›`) because a pattern body has a fixed variable count — on the server (`render_invoice_for_mode`) and on the phone (`SmsLocal.patternMode()`).
* Android settings now advertise the same placeholders as the server (incl. `{items}`).

### 5. A more professional look — both programs

| Piece | Path |
|---|---|
| Web/Windows refresh layer | `frontend/ui-refresh.css` — a single token-driven layer (radii, spacing, type scale, shadows, hairlines), sticky/zebra/wide-number tables, button hierarchy, dashed empty states, POS «whisper» bar, `prefers-reduced-motion`, print styles; linked **last** in `index.html` and cached by `sw.js` |
| Expiry chip | `batchExpiryChip()` in `app.js` + `.exp-chip` styles: amber ≤30 days, orange ≤7, dark red when expired, Persian digits — the cashier sees at a glance which batch must move first |
| Stocktake alarms / list digits | Persian digits in the alarms and the mobile report list |
| Android | `Ui.java` (cards r20, hero hairline, taller touch rows, dashed empty state, KPI bars) + violet POS «whisper» card with an expiry badge + a «بررسی اجراها» button on the intelligence screen |
| Online toast | «اجرا شد — اندازه‌گیری آغاز شد» (no more silent success) |
| Framing policy | Default stays `X-Frame-Options: DENY`; `SUPERMARKET_ALLOW_EMBED=1` opens the panel for framed hosting (cloud preview / frame-based shell) and adds `frame-ancestors *` — covered by `test_v37_security.py` |

### 6. Release artifacts

- `backend/app/__init__.py` → **4.8.0**; `installer/windows/setup.iss` → 4.8.0; Android versionCode **40800** (derived from the single source of truth)
- `releases/android/SupermarketMobile-4.8.0.apk` — 1,406,355 bytes, sha256 `90330cf170b2de1cd3baa30dc0999880d17231a5db64dc3a5f8f51fa6eed7a1b`, same signing cert as 4.7.0 (in-place update), install-preflight PASS, no native ABIs
- `releases/windows/SupermarketDesktopUI-3.7.0.zip` (sha256 in the sibling `.sha256`) — carries the new panel layer; the 3.6.6 bundle stays frozen
- `CHANGELOG.md` — Persian, owner-facing 4.8.0 entry

## Verification

### Test suite
- **652 passed / 1 skipped** (was 624 at v4.7.0; +28) — `pytest tests/ -q -p no:randomly`
- New: `test_v48_expiry_timeline.py` (15: pure timeline math, real-stock analyzer, execution + verification, waste, lost-effect detection, pre-sale application, card cap), `test_v48_release_artifacts.py` (7: version single-source, APK structure + checksum, Windows bundle carries the new layer, the frozen 3.6.6 hash, Android engine tokens, SMS placeholder parity server↔phone, Persian-digit nudges)
- Updated deliberately: `test_v47_pos_suggestions.py` (the nudge reason is now asserted to carry **Persian** digits) and the SMS layout tests (`{items}` layout) — both documented in the files

### Live end-to-end on a fresh database (`backend/tests/_e2e_v480.py`)
A 20-day batch → `EXPIRY_LADDER` card with `days_left = 20`, ladder `7 % → 14 % → 22 %` dated `۱۴۰۵/۰۷/۰۶…` → **accept → batch price really 52,000 → 48,400** + 2 price-version rows → report says **OK** («step 0 applied») → price tampered to 999,999 → health-scan returns **LOST** *("price did not drop (still 999999, base 52000)"*)* → expired batch → waste card, `write_off_waste` 12 → 0 with a WASTE movement → `POST /insights/nudges` returns the near-expiry item with `days_left`/`batch_id`/`purpose` and never the expired one → SMS pattern mode is one line. **All checks green.**

### Windows/web UI — real clicks (jsdom against the live server)
`scripts/uitest/smoke-v4_8.js` (new, run with `cd scripts && node uitest/smoke-v4_8.js`):
- `ui-refresh.css` is served and loaded after `desktop.css`; the expiry chip classes and Persian digits render (`⏰ ۳ روز` / `soon`, `⏰ منقضی شد` / `expired`)
- The insights screen shows a real ladder card with its dated timeline; clicking **«اجرا کن»** → confirming «اجرا و شروع اندازه‌گیری» → the batch price really dropped **55,000 → 49,000**, the insight became `ACCEPTED`, the verification report says **OK**, and the toast «اجرا شد» was shown
- The POS nudge returned «ماست موسیر ۹۰۰ گرمی — ۱۲ روز» with `purpose = sell_before_expiry` and Persian digits

### Live demo store for the owner
`scripts/seed_demo_v480.py` builds «فروشگاه بهار» on a running server (24 shelf items with near-expiry / expired / long-life batches, 22 real sales, store settings, one manual POS rule) and runs the analyzer — the panel then shows 12 expiry cards, waste advice and a working POS nudge. The server for the preview runs with `SUPERMARKET_LICENSE_GATE=0` (development only).

### Build
- APK built with the SDK-less toolchain (ecj + d8 + aapt2 + apksigner) after re-fetching it with `scripts/android/fetch-tools.sh`; preflight PASS; cert `CN=Khajavy Supermarket, O=Khajavy, C=IR` SHA-256 `18b4ab1868c026476c4027fe823d38a8e3965f70194cc0d65e60eac4e7321fa5` (unchanged → updates install in place); the released dex contains the new `{items}` placeholder list
- Windows UI bundle rebuilt and its sha256 sidecar refreshed

## Notes / honest limits
- The Android app is verified by compile + unit tests + server-parity tests; it is not launched on an emulator in this environment (no device). The native engine, offline POS nudge, waste action and health report are covered by `test_v48_*` + `test_v22/v20` parity checks.
- The Windows **desktop shell** itself (PySide) is still built from the frozen `tools/windows-ui` sources; this release refreshes the panel it hosts (that is what «ظاهر برنامهٔ ویندوز» means for the shop) — a native shell redesign is not part of 4.8.0.
- `sms.send_invoice` remains the owner's switch: with it off, an invoice SMS is queued but not sent (unchanged behaviour).
