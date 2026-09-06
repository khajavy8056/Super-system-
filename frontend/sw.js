/* Supermarket System — service worker (PWA shell cache).
 *
 * Policy (honest offline):
 * - App shell (panel + mobile pages, styles, icons): cache-first, versioned.
 * - /api/**: NEVER cached or synthesized — data must come from the backend or
 *   fail visibly. The mobile app queues writes locally in IndexedDB and syncs
 *   when the network returns (§25–26); the SW does not fake responses.
 */
const CACHE = "supermarket-shell-v3";
const SHELL = [
  "/", "/app.js", "/styles.css",
  "/mobile/", "/mobile/app.js", "/mobile/styles.css",
  "/manifest.webmanifest",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/logo.svg",
  "/fonts/Vazirmatn-Regular.woff2", "/fonts/Vazirmatn-Bold.woff2",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      // add each resource independently so one 404 can't break installation
      await Promise.all(SHELL.map((url) =>
        cache.add(new Request(url, { cache: "reload" })).catch(() => null)));
      await self.skipWaiting();
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api")) return; // network-only
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(event.request, { ignoreSearch: true }).then((cached) => {
      const network = fetch(event.request).then((resp) => {
        if (resp && resp.status === 200 && resp.type === "basic") {
          const clone = resp.clone();
          caches.open(CACHE).then((c) => c.put(event.request, clone)).catch(() => null);
        }
        return resp;
      }).catch(() => cached || Response.error());
      return cached || network;
    })
  );
});
