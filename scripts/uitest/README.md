# UI smoke tests (jsdom) — dev only

Run against a live server on http://127.0.0.1:8000 (admin/admin123):

    cd scripts && npm i && npm run smoke

* `smoke-views.js` — loads the real `app.js` in jsdom, logs in, visits all 14 desktop views;
  fails on any runtime error **or** an in-view error card (`p.error`).
* `smoke-mobile.js` — mobile PWA boot.
* `smoke-v1_1.js` / `smoke-v1_2.js` — feature-specific assertions (warehouses, discount modal,
  void-password modal, starter catalog card, monthly report, logo upload, update channel, hardware hints).
* `smoke-v4_8.js` — **the suggestion → execution path with real clicks** (v4.8.0): loads the real
  panel, finds a ladder card, clicks «اجرا کن», confirms the dialog, then asks the server whether the
  batch price really dropped and the verification report says «برقرار»; also checks the expiry chip
  (Persian digits + colour) and the POS whisper nudge. Run `npm run smoke-v48` against a live server.

Screenshots / PDF (real headless Chromium; needs NSS libs on hosts without them — the
`@sparticuz/chromium` package bundles them in `bin/al2023.tar.br`):

    npm run shots   # docs/screenshots/*.png from shots.json
    npm run pdf     # docs/SCREENSHOTS.pdf
