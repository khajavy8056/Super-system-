/* RASA SYSTEM — Service Worker Cleaner (build-493).
 *
 * ویندوز (WebView2) و اندروید (Native) نیازی به کش مرورگری ندارند و کش کردن
 * فایل‌های JS/HTML در Service Worker باعث بالا آمدن نسخهٔ قدیمی پس از آپدیت می‌شد.
 * این فایل در صورت وجود ثبت قدیمی از نسخه‌های پیشین (مانند rasa-shell-v100)،
 * تمام کش‌های Cache Storage را پاک کرده و خودش را لغو ثبت (unregister) می‌کند.
 */
const CACHE = "rasa-shell-v100-no-sw-v494";
const PURGE_ASSETS = [
  "/",
  "/index.html",
  "/styles.css",
  "/desktop.css",
  "/ui-refresh.css",
  "/rasa-ui.css",
  "/app.js",
  "/accounting.js",
  "/insights.js",
  "/onboarding.js",
];

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.map((k) => caches.delete(k))))
      .then(() => self.registration.unregister())
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((clients) => {
        clients.forEach((c) => {
          try { c.postMessage({ type: "SW_PURGED", version: CACHE, assets: PURGE_ASSETS.length }); } catch (_) {}
        });
      })
      .catch(() => {})
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api")) return;
  // عبوردهی مستقیم شبکه/لوکال بدون هیچ کش قدیمی
});
