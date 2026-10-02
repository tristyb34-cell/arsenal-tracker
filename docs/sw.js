/* Arsenal Tracker service worker.
   Strategy:
     - App shell (html/css/js/icons): cache-first, so the app opens instantly.
     - Data (data/snapshot.json, data/match/*.json, data/sagas.json): network-
       first, so you always see the latest when online and the last copy when
       offline.
   Bump CACHE when the shell changes so phones pick up the new version. */
const CACHE = "arsenal-tracker-static-v11";
const SHELL = [
  "./", "./index.html", "./style.css", "./app.js", "./crest-96.png",
  "./manifest.webmanifest", "./icon-192-v2.png", "./icon-512-v2.png",
  "./favicon.ico", "./favicon-32-v2.png",
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

  // Never intercept cross-origin requests. The match centre polls ESPN live
  // and the crests come from ESPN's CDN; the browser cache handles those.
  if (url.origin !== self.location.origin) return;

  if (url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(e.request).then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

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
