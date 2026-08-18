// Zenoscribe's offline-capable shell. Registered from "/" (see server.py's
// dedicated /service-worker.js route, which serves this with
// Service-Worker-Allowed: / so its scope covers the whole app, not just
// /static/ where the rest of the build output lives) - registration itself
// happens in index.html/login.html.
const CACHE_NAME = "zenoscribe-shell-v1";

// Only same-origin GET requests for the app shell/static assets are worth
// handling - never /api/* (session-bearing data that must always be fresh,
// not something to serve stale from cache) and never non-GET requests.
// WebSocket upgrade requests for /ws and /ws/translate never reach here at
// all - they bypass the Fetch API/service worker entirely.
function shouldHandle(request, url) {
  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith("/api/")) return false;
  return true;
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

// Network-first, cache-fallback: online users always get the latest build
// (this app's JS/CSS/HTML are served with Cache-Control: no-cache
// specifically so updates roll out immediately - see NoCacheStaticFiles in
// server.py - and this mirrors that intent instead of undermining it).
// Offline, or on a connection too flaky for the request to complete, users
// get the last successfully loaded shell instead of a browser error page.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (!shouldHandle(event.request, url)) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || Response.error())),
  );
});
