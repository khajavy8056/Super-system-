# UI smoke tests (jsdom) — dev only

Run against a live server on http://127.0.0.1:8000 (admin/admin123):

    cd scripts && npm i && npm run smoke

* `smoke-views.js` — loads the real `app.js` in jsdom, logs in, visits all 14 desktop views;
  fails on any runtime error **or** an in-view error card (`p.error`).
* `smoke-mobile.js` — mobile PWA boot.
* `smoke-v1_1.js` / `smoke-v1_2.js` — feature-specific assertions (warehouses, discount modal,
  void-password modal, starter catalog card, monthly report, logo upload, update channel, hardware hints).

Screenshots / PDF (real headless Chromium; needs NSS libs on hosts without them — the
`@sparticuz/chromium` package bundles them in `bin/al2023.tar.br`):

    npm run shots   # docs/screenshots/*.png from shots.json
    npm run pdf     # docs/SCREENSHOTS.pdf
