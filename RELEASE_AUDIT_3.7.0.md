# RELEASE AUDIT — 3.7.0

- **Version:** 3.7.0 (single source of truth: `backend/app/__init__.py::__version__`)
- **Base commit:** `3e52ae4275fa7b229ae9eb96d6e9f0dc8e6c9d53`
- **Branch:** `arena/01a0c664-super-system`
- **Date:** 2026-09-22
- **Manifest:** `RELEASE_CHANGE_MANIFEST_3.7.0.json` (32 files, SHA-256 pinned)

## Verdict

**RELEASE BLOCKED (§56)** — the code is verified and ready for user testing via
PR, but the release is **not production-ready** and no final GitHub Release may
be created yet:

1. **Setup.exe was not built.** It requires a real `windows-latest` CI runner
   (PyInstaller + Inno Setup do not run on Linux). Trigger: wire
   `installer/ci/release-windows.yml` (see `scripts/activate-ci.sh`), then push
   the `v3.7.0` tag. No simulated EXE was produced — per policy, none is shipped.
2. **The APK was not installed on a physical device here.** It is a real,
   release-key-signed build (signer cert identical to 3.6.6, verified with
   apksigner), but install-over-previous and on-device smoke tests must happen
   on the user's hardware.

## What shipped in 3.7.0 (verified)

**Database — Alembic is the only migration path (§5).**
`upgrade_schema()` is strict (raises `MigrationError` on drift), a lossless
legacy bridge stamps pre-Alembic databases, divergence writes a `SCHEMA_DRIFT`
audit row, restore upgrades before healing, and the new head migration
`f7a1c2d3e4b5` makes `alembic upgrade head` produce exactly the models
(new: `Experiment`, `SmsMessage.next_retry_at`). Proof:
`backend/tests/test_v37_migrations.py` 6/6.

**Till security (§34).** Users without `pricing.view_cost` (Cashier, Viewer)
now receive cost figures as `null` — keys preserved so clients don't break —
across dashboard, sales, cashiers, inventory, expiry, batches, stock, invoices,
POS (validate/checkout/search/batch-options), product detail, warehouses and
mobile sync. `/reports/profit` requires the permission outright (403 otherwise).
Web + mobile PWA render redacted values as «—», hide the finance/profit
sections, and draw the sales-only trend chart. Proof:
`backend/tests/test_v37_security.py` 8/8; `node --check` on all touched JS.

**POS integrity (§6–§8, §37).** Cart line prices are resolved from the batch
only (caller-supplied prices overwritten); the manager cap
`pos.max_manual_discount_pct` rejects over-policy manual discounts with
`DISCOUNT_OVER_POLICY` (coupons excluded); 4 concurrent checkouts take 4 unique
sequential invoice numbers. Proof: `backend/tests/test_v37_pos.py` 3/3.

**Setup hardening.** Production refuses to boot with the factory `SECRET_KEY`;
`/api/setup/complete` requires admin credentials (`ADMIN_REQUIRED`, 422);
`Permissions-Policy` header shipped (camera/mic/geolocation/payment/usb denied).

## Verification evidence

- Full backend suite: **542 passed, 1 skipped, 0 failed** (267s). Baseline at
  session start was 525 + 1; +17 new tests, zero old tests weakened or deleted.
- Version consistency test (`test_version_is_consistent_everywhere`) passes:
  SoT, `/health`, OpenAPI, `APP_VERSION`, Inno fallback all read 3.7.0.
- APK: `SupermarketMobile-3.7.0.apk`, versionCode 30700, apksigner-verified,
  signer SHA-256 `18b4ab18…7321fa` identical to the 3.6.6 release, bundled
  catalog byte-identical to the repo asset.
- Routing audit: 277 operations, zero duplicate paths (an earlier duplicate-route
  suspicion was investigated and debunked — no `contracts.py` router exists and
  `/dashboard` is registered once).

## Deliberately deferred (backlog, not in 3.7.0)

The data-quality engine (`backend/app/services/data_quality.py`) is present but
unwired and untested; SAVEPOINT-per-action, SMS retry backoff, the SPEC
registry, advisor calibration/experiments, and CI workflow wiring remain future
work. They were not rushed into this release unverified.

## Rollout notes

- Restoring a pre-Alembic backup now runs migrations first — keep a copy of the
  backup file until the restore is confirmed.
- Cashiers will see «—» wherever a cost figure used to leak; managers are
  unaffected. No client data migration is needed.
- Android: install the APK over the previous version; do not uninstall first.
