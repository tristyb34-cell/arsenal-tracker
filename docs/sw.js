/* Arsenal Tracker service worker.
   Goal: the installed phone app is always current, with no manual update step.
     - Everything same-origin is network-first: the app shell (html/css/js/
       icons) and the data (data/snapshot.json, data/match/*.json,
       data/sagas.json) come from the network when online, revalidated past the
       browser's HTTP cache (Pages sends max-age=600), and fall back to the last
       cached copy offline. The shell also falls back to the cached copy if the
       network has not answered within SLOW_MS, so a bad signal never blocks
       opening the app; the fresh copy still lands in the cache for next time.
     - A new sw.js installs and takes over at once (skipWaiting + clients.claim)
       and app.js reloads the page once on controllerchange, so a release shows
       up on the next open or resume instead of the one after that.
   Bump CACHE when the shell changes: that changes the bytes of sw.js, which is
   how an app that was only resumed (never relaunched) notices and reloads. */
const CACHE = "arsenal-tracker-static-v12";
const SLOW_MS = 4000;
const SHELL = [
  "./", "./index.html", "./style.css", "./app.js", "./crest-96.png",
  "./manifest.webmanifest", "./icon-192-v2.png", "./icon-512-v2.png",
  "./favicon.ico", "./favicon-32-v2.png",
];

self.addEventListener("install", (e) => {
  // cache: "reload" skips the HTTP cache, so a new version never precaches old files
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// The request to send to the network: revalidate instead of trusting the HTTP
// cache. Navigations cannot be re-built from the original request, so they are
// re-issued by URL (redirect: "manual" keeps Flask's legacy redirects working).
function fresh(req) {
  if (req.mode === "navigate") {
    return new Request(req.url, { cache: "no-cache", redirect: "manual", credentials: "same-origin" });
  }
  return req.cache === "default" ? new Request(req, { cache: "no-cache" }) : req;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Never intercept cross-origin requests. The match centre polls ESPN live
  // and the crests come from ESPN's CDN; the browser cache handles those.
  if (url.origin !== self.location.origin) return;

  const net = fetch(fresh(req)).then((resp) => {
    if (resp.ok) {
      const copy = resp.clone();
      e.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {}));
    }
    return resp;
  });
  // keeps the worker alive until the network answers, even when the cached
  // copy is served first, so the fresh copy is still stored
  e.waitUntil(net.catch(() => {}));

  const isData = url.pathname.includes("/data/");
  e.respondWith(
    caches.match(req).then((cached) => {
      if (!cached) return net;
      const fallback = net.catch(() => cached);
      if (isData) return fallback;
      const slow = new Promise((resolve) => setTimeout(resolve, SLOW_MS, cached));
      return Promise.race([fallback, slow]);
    })
  );
});
