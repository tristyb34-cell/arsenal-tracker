/* Arsenal Tracker service worker - minimal, network-first.
   Exists to make the app installable (PWA) and resilient offline for the shell.
   We do NOT cache feed HTML aggressively (news must stay fresh); we only cache
   the static shell assets. */
const CACHE = "arsenal-tracker-v1";
const SHELL = ["/static/style.css", "/static/app.js", "/static/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // network-first for everything; fall back to cache for static shell only
  e.respondWith(
    fetch(e.request).catch(() =>
      caches.match(e.request).then((r) => r || Response.error())
    )
  );
});
