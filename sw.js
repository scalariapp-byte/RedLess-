// Offline support for the installed web app (iPhone "Sur l'écran d'accueil", Android Chrome).
// Core files are cached at install; everything else (music included) on first use.
// The music is served from cache with byte ranges, because Safari streams audio with Range requests.
const CACHE = "redless-v3.24";
const CORE = [
  "./", "index.html", "manifest.webmanifest", "css/style.css",
  "js/config.js", "js/levels.js", "js/online-config.js", "js/online.js", "js/audio.js", "js/visuals.js", "js/minigame.js", "js/game.js",
  "fonts/oxanium.woff2", "fonts/chakra-500.woff2", "fonts/chakra-600.woff2", "fonts/chakra-700.woff2",
  "assets/city.jpg", "assets/icon-180.png", "assets/icon-192.png", "assets/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function rangeResponse(request, full) {
  const buf = await full.arrayBuffer();
  const m = /bytes=(\d*)-(\d*)/.exec(request.headers.get("range") || "");
  const start = m && m[1] ? +m[1] : 0, end = m && m[2] ? Math.min(+m[2], buf.byteLength - 1) : buf.byteLength - 1;
  return new Response(buf.slice(start, end + 1), {
    status: 206,
    headers: {
      "Content-Type": full.headers.get("Content-Type") || "audio/mpeg",
      "Content-Range": `bytes ${start}-${end}/${buf.byteLength}`,
      "Content-Length": String(end - start + 1),
      "Accept-Ranges": "bytes",
    },
  });
}

self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.endsWith("/version.json")) return; // always asked to the server: it announces updates
  const isAudio = url.pathname.endsWith(".mp3");
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const key = isAudio ? url.pathname : req;
    let hit = await cache.match(key, { ignoreSearch: true });
    if (!hit) {
      try {
        // Fetch the whole file once (no Range) so the cached copy is complete.
        const res = await fetch(isAudio ? new Request(url.pathname) : req);
        if (res.ok && res.status === 200) await cache.put(key, res.clone());
        if (!isAudio || !req.headers.get("range")) return res;
        hit = res;
      } catch (err) {
        if (req.mode === "navigate") { const home = await cache.match("index.html"); if (home) return home; }
        throw err;
      }
    }
    if (isAudio && req.headers.get("range")) return rangeResponse(req, hit.clone());
    // Serve the cached copy now, refresh it in the background so updates arrive on the next launch.
    if (!isAudio) e.waitUntil(fetch(req).then((r) => r.ok && r.status === 200 && cache.put(key, r)).catch(() => {}));
    return hit;
  })());
});
