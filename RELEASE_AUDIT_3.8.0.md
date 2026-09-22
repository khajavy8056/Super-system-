# RELEASE AUDIT — 3.8.0

- **Version:** 3.8.0 (single source of truth: `backend/app/__init__.py::__version__`)
- **Base commit:** `3e52ae4275fa7b229ae9eb96d6e9f0dc8e6c9d53`
- **Branch:** `arena/01a0c664-super-system`
- **Date:** 2026-09-22
- **Manifest:** `RELEASE_CHANGE_MANIFEST_3.8.0.json` (SHA-256 pinned)
- **Note:** this tree is cumulative — it contains the unmerged 3.7.0 work
  (PR #5, still open from this branch) plus everything below. The 3.8.0
  manifest lists all files changed vs the base commit; the 3.7.0 audit file
  in this tree still describes the 3.7.0 slice.

## Verdict

**RELEASE BLOCKED (§56)** — the code is verified and ready for user testing via
PR, but the release is **not production-ready** and no final GitHub Release may
be created yet:

1. **Setup.exe was not built.** It requires a real `windows-latest` CI runner
   (PyInstaller + Inno Setup do not run on Linux). Trigger: a maintainer with
   the `workflow` scope runs `scripts/activate-ci.sh`, then pushes the
   `v3.8.0` tag. No simulated EXE was produced — per policy, none is shipped.
2. **The APK was not installed on a physical device here.** It is a real,
   release-key-signed build (signer cert identical to 3.6.6/3.7.0, verified
   with apksigner + aapt2), but install-over-previous and on-device smoke
   tests must happen on the user's hardware.
3. **CI workflows are staged, not live.** `installer/ci/` now holds
   `tests.yml` + both release workflows, but the maintenance token lacks the
   `workflows` scope, so `.github/workflows/` can only be populated by a
   maintainer (one command — see §10 below). Until then there is no green
   check on the PR page itself; the suite result below was produced by
   running the same commands locally.
4. **Physical hardware paths are MANUAL_ACCEPTANCE_REQUIRED** (checklist at
   the end of this file). The mock/transport tests prove the layer's logic;
   they do not claim any physical device works.

## What shipped in 3.8.0 (verified)

Order items below refer to the user's 10-item final order. Items already
complete in 3.7.0 were not reworked.

**§1 — Data Quality → Intelligence (§critical).**
`services/data_quality.py` runs rule checks (missing prices, negative stock,
impossible/production-after expiry, duplicate invoice numbers, negative
margin, invalid phones, orphan movements …); `blocks_intelligence()` BLOCKS
analysis on Critical findings, Medium/Low findings cut confidence and are
audited; DQ status API + proof: `backend/tests/test_v38_data_quality.py` 5/5.

**§2 — LLM never an economic-number source.**
`expected_gain`/money is computed only by deterministic code in
`services/insights.py`; the LLM writes narrative text only.
`economic_impact` / `evidence_strength` / `prediction_uncertainty` are
tracked as separate fields; invalid/hallucinated numbers are rejected before
any DB write. Proof: `backend/tests/test_v38_economics.py` 1/1.

**§3 — Honest calibration.**
No RATIO_MIN-style positive floors anywhere in `backend/app` (verified by
search). Outcomes are recorded as Positive/Neutral/Negative with
sample_count, MAE, mean error, direction accuracy, CI and pos/neg rates;
confidence is derived from measured performance only. Proof:
`backend/tests/test_v38_calibration.py` 4/4.

**§4 — Action Engine with real rollback.**
`services/insight_actions.py` executes
VALIDATE → BEGIN/SAVEPOINT → EXECUTE → VERIFY → COMMIT: validation failures
write nothing, each action runs in its own savepoint (one failure neither
kills its siblings nor leaks partial writes), executions are traced
post-run, irreversible ops are pre-declared. Partial-failure proof:
`backend/tests/test_v38_actions.py` 4/4.

**§5 — Measurement Contracts.**
Every action carries what/baseline/window/success-rule; evaluation returns
honest states instead of numbers it cannot prove: NOT_MEASURABLE /
INSUFFICIENT_DATA / NEGATIVE_OUTCOME. Proof:
`backend/tests/test_v38_measurement.py` 5/5.

**§6 — Real Experiment lifecycle.**
`services/experiments.py` + migration `a8c2e4f6b1d3` (`eligible`, `exposed`
columns): CREATE → PLAN → ASSIGN → START → EXPOSE → OUTCOME → CLOSE →
EVALUATE with frozen eligible populations, immutable assignments,
assigned ≠ exposed, missing ≠ zero, once-only close, INSUFFICIENT_DATA
without fabricated numbers, verdict linked to the Insight. Proof:
`backend/tests/test_v38_experiments.py` 4/4.

**§7 — SMS retry honesty.**
`services/sms.py`: `next_retry_at` + exponential backoff with jitter, the
worker takes only due messages, each row is CLAIMED before sending (parallel
dispatchers cannot double-send), stale SENDING claims (10+ min) re-enter the
queue, manual retry wipes the backoff debt. Proof:
`backend/tests/test_v38_sms.py` 3/3 (+ updated phase-3 backoff test).

**§8 — Unified Hardware Integration Layer (new).**
`backend/app/services/hw/` — one extensible layer for all attachable
devices: 6 adapters (receipt printer, cash drawer, barcode scanner, customer
display, label printer, scale) over pluggable transports
(TCP / serial / file-sink / in-memory mock); USB discovery (honest
DRIVER_MISSING without pyusb); driver manager that auto-installs ONLY pinned
PyPI packages behind the `hw.auto_install_drivers` setting, verified after
install and audit-logged — vendor binaries are never downloaded or executed;
unknown families answer UNSUPPORTED_DEVICE with guidance instead of
crashing; per-device health + polite reconnect backoff (5s…5min) with
auto-recovery on the next good probe; self-tests that spend paper/open the
drawer/scan/weigh ONLY with explicit confirmation flags. Registry extended
by migration `c5d9e2f7a4b6` (discovery ids, health, last_error,
consecutive_failures, last_seen_at, capabilities); API in
`routers/hw.py` (`/api/hardware/detect|adapters|drivers|devices…`, additive
— legacy `/api/hardware` untouched). Proof:
`backend/tests/test_v38_hardware.py` 25/25 (mock transports, real loopback
TCP sockets, TSPL/ESC-POS byte assertions, scale-parser tables including
UNPARSEABLE-never-zero). Physical devices: MANUAL (checklist below).

**§9 — Full test run.**
Whole backend suite executed in this environment: **593 passed, 1 skipped,
0 failed** (~320s). +51 v3.8 tests; zero old tests weakened or deleted —
two old migration-test expectations legitimately followed the new head
(documented in the test file, intent unchanged). Physical/USB/print/scan
paths are MANUAL_ACCEPTANCE_REQUIRED, never fake-passed.

**§10 — Real CI.**
New `installer/ci/tests.yml`: full pytest on every push/PR (release PASS
requires green runnable tests). Release workflows unchanged in behaviour
(real `windows-latest` EXE + Inno build, SDK-less signed APK + checksums,
both run the suite before building). All three activate with one maintainer
command (`scripts/activate-ci.sh` / `.bat` — the agent token cannot push
`.github/workflows/` itself: GitHub rejects workflow writes without the
`workflows` scope). Until activation, CI verdict = the local full-suite run
above.

## Verification evidence

- Full backend suite: **593 passed, 1 skipped, 0 failed**.
- Version consistency test passes: SoT, `/health`, OpenAPI, `APP_VERSION`,
  Inno fallback all read 3.8.0; APK `versionCode=30800` / `versionName=3.8.0`.
- APK: `releases/android/SupermarketMobile-3.8.0.apk` (1.3M), apksigner +
  aapt2 verified, signer SHA-256 `18b4ab18…7321fa5` identical to the 3.6.6
  and 3.7.0 releases, SHA-256 sidecar shipped next to it.
- Alembic: single head `c5d9e2f7a4b6`; idempotent migrations (pre-Alembic
  `create_all` DBs upgrade without data loss — migration tests 6/6).
- No `RATIO_MIN`, no simulated EXE, no workflow-scope bypass, no deleted or
  weakened old tests.

## MANUAL ACCEPTANCE (do on real hardware — never mark pass without doing)

**H1 — USB printer (paper test).**
Connect an ESC/POS printer via USB, open the hardware page, run Detect, open
the device and POST `/api/hardware/devices/{id}/test`
`{"print_test_page": true}`. PASS = one self-test page prints and health
becomes CONNECTED.

**H2 — Cash drawer.**
With the drawer cabled through the printer, POST …/test
`{"confirm_open": true}`. PASS = drawer fires exactly once.

**H3 — Barcode scanner.**
USB-HID scanner: focus any POS search box and scan a real product barcode.
PASS = the exact product resolves (first-digit loss = FAIL).

**H4 — Scale.**
Serial scale + known 1kg test mass, POST …/test `{"wait_for_weight": true}`.
PASS = reported weight within the scale's rated tolerance of 1000g.

**H5 — Label printer.**
POST …/test `{"print_test_label": true}`. PASS = one TSPL label prints with
readable text + barcode.

**H6 — Customer display.**
POST …/test with `{"line1": "Total", "line2": "12,340"}`. PASS = both lines
visible on the pole display.

**H7 — APK on device.**
Install `SupermarketMobile-3.8.0.apk` OVER the previous release on a
physical phone (do not uninstall first). PASS = version shows 3.8.0, data
intact, POS + sync smoke-test green.

**W1 — Setup.exe (after CI activation).**
Push the `v3.8.0` tag, let `windows-latest` build, install on a clean
Windows machine. PASS = installer completes, panel boots, version reads
3.8.0.
