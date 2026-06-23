/* Arsenal Tracker service worker (static PWA).
   Strategy:
     - App shell (html/css/js/icons): cache-first, so the app opens instantly.
     - Data (snapshot.json): network-first, so you always see the latest news
       when online, and fall back to the last cached copy when offline.
   Bump CACHE when the shell changes to force an update. */
const CACHE = "arsenal-tracker-static-v1";
const SHELL = [
  "./", "./index.html", "./style.css", "./app.js",
  "./manifest.webmanifest", "./icon-192.png", "./icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);

  // network-first for the data snapshot (always try fresh, fall back to cache)
  if (url.pathname.endsWith("/data/snapshot.json") || url.pathname.endsWith("snapshot.json")) {
    e.respondWith(
      fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // cache-first for the shell (fall back to network, then cache the result)
  e.respondWith(
    caches.match(e.request).then((cached) =>
      cached || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      }).catch(() => cached)
    )
  );
});
