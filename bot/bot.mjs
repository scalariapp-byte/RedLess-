// Bot Redless : joue en boucle dans Chromium, apprend ses réglages, signale les bugs.
// Lancement : node bot/bot.mjs        (options par variables d'environnement, voir bot/README.md)
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, appendFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { extname, join, normalize } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const DIR = join(ROOT, "bot", "donnees");
const E = process.env;
const MODE = E.BOT_MODE || "classic";
const GAMES_PER_TRIAL = +E.BOT_PARTIES || 3;        // parties pour juger un réglage (le hasard du jeu est grand)
const MAX_GAME_MS = (+E.BOT_MAX_MIN || 15) * 60e3;  // au-delà, partie arrêtée et signalée
const NTFY = (E.NTFY_TOPIC || "").trim();           // sujet ntfy.sh pour les notifications sur le téléphone
const MAX_GAMES = +E.BOT_MAX_PARTIES || Infinity;   // pour les essais : arrêter après N parties

// ---------- Chromium : Playwright si présent, sinon playwright-core + Chromium du système ----------
const req = createRequire(import.meta.url);
function loadPw() {
  for (const name of ["playwright", "playwright-core"]) {
    try { return req(name); } catch {}
    try { return req(join(execSync("npm root -g").toString().trim(), name)); } catch {}
  }
  throw new Error("Playwright introuvable : lance bot/installer.sh");
}
const { chromium } = loadPw();
const SYS_CHROME = ["/usr/bin/chromium", "/usr/bin/chromium-browser"].find(existsSync);

// ---------- serveur local des fichiers du jeu ----------
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".webmanifest": "application/manifest+json", ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".mp3": "audio/mpeg" };
const server = createServer(async (rq, rs) => {
  let p = normalize(decodeURIComponent(new URL(rq.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
  if (p.endsWith("/")) p += "index.html";
  if (/^\/(bot|android|\.git)\//.test(p)) return rs.writeHead(404).end();
  let body;
  try { body = await readFile(join(ROOT, p)); } catch { return rs.writeHead(404).end(); }
  rs.writeHead(200, { "Content-Type": TYPES[extname(p)] || "application/octet-stream" }).end(body);
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const URL_JEU = `http://127.0.0.1:${server.address().port}/`;

// ---------- mémoire du bot ----------
await mkdir(join(DIR, "bugs"), { recursive: true });
const STATE = join(DIR, "etat.json");
// Réglages appris. Bornes : un humain rapide, pas une machine (voir LIMITS).
const SPACE = {
  reaction: [150, 450],   // ms entre l'apparition d'une case et le moment où le bot peut la toucher
  stable:   [0, 250],     // ms pendant lesquels la couleur doit rester la même avant de toucher
  wGold:    [0, 3],       // priorité des cases dorées
  wAge:     [0, 3],       // priorité des cases anciennes (proches de disparaître)
  wSpecial: [-1, 3],      // priorité des bleues / violettes
  tapBlue:  [0, 1],       // > 0.5 : touche les bleues (ralenti)
  tapViolet:[0, 1],       // > 0.5 : touche les violettes (efface les rouges)
  tapHold:  [0, 1],       // > 0.5 : tient les noires
};
const LIMITS = { gapMs: 110 }; // un doigt : au plus ~9 touches par seconde, jamais deux en même temps
const mid = Object.fromEntries(Object.entries(SPACE).map(([k, [a, b]]) => [k, (a + b) / 2]));
let st = existsSync(STATE) ? JSON.parse(await readFile(STATE, "utf8")) : null;
st ||= { best: { params: { ...mid, reaction: 300 }, score: null }, sigma: 0.25, games: 0, trials: 0, record: 0, bugs: {} };

const clamp = (k, v) => Math.min(SPACE[k][1], Math.max(SPACE[k][0], v));
const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
const mutate = (p) => Object.fromEntries(Object.keys(SPACE).map((k) => [k, clamp(k, p[k] + gauss() * st.sigma * (SPACE[k][1] - SPACE[k][0]))]));
const save = () => writeFile(STATE, JSON.stringify(st, null, 1));
const log = (...a) => console.log(new Date().toISOString().slice(0, 19), ...a);

async function notify(title, body, tags = "") {
  log("NOTIF", title, "-", body);
  if (!NTFY) return;
  try {
    await fetch("https://ntfy.sh/" + encodeURIComponent(NTFY), { method: "POST", body: body.slice(0, 3000),
      headers: { Title: title.replace(/[^\x20-\x7e]/g, "?").slice(0, 200), Tags: tags } });
  } catch (e) { log("ntfy injoignable :", e.message); }
}

// ---------- bugs : un seul message par bug différent ----------
async function bug(page, kind, detail, ctx) {
  const sig = (kind + ":" + detail).replace(/\d+/g, "#").slice(0, 200);
  const known = st.bugs[sig];
  st.bugs[sig] = { kind, detail: detail.slice(0, 500), count: (known?.count || 0) + 1, first: known?.first || new Date().toISOString(), last: new Date().toISOString() };
  await save();
  if (known) return;
  const shot = join(DIR, "bugs", Date.now() + ".png");
  try { await page.screenshot({ path: shot }); } catch {}
  await notify("Redless : bug detecte (" + kind + ")", `${detail}\n\nContexte : ${JSON.stringify(ctx || {})}\nCapture : ${shot}`, "beetle");
}

// ---------- le joueur, exécuté dans la page (temps réel, sans aller-retour Node) ----------
function player(P, L) {
  const seen = new WeakMap();       // élément de case -> { t0, color, since }
  let busyUntil = 0, holdEl = null;
  const now = () => performance.now();
  const tap = (cell, type) => cell.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1 }));
  window.__botTaps = 0;
  window.__bot = setInterval(() => {
    const t = now();
    if (holdEl) {                   // doigt posé sur une noire : on attend qu'elle se remplisse
      if (!holdEl.isConnected || !holdEl.classList.contains("holding")) { window.dispatchEvent(new PointerEvent("pointerup", { pointerId: 1 })); holdEl = null; busyUntil = t + L.gapMs; }
      return;
    }
    let bestCell = null, bestScore = -Infinity, bestTile = null;
    for (const tile of document.querySelectorAll("#board .tile")) {
      const color = ["green", "gold", "red", "blue", "violet", "hold"].find((c) => tile.classList.contains(c));
      let s = seen.get(tile);
      if (!s) { s = { t0: t, color, since: t }; seen.set(tile, s); }
      if (s.color !== color) { s.color = color; s.since = t; }
      if (tile.classList.contains("hit") || t - s.t0 < P.reaction || t - s.since < P.stable) continue;
      if (color === "red" || !color) continue;
      if (color === "blue" && P.tapBlue < 0.5) continue;
      if (color === "violet" && P.tapViolet < 0.5) continue;
      if (color === "hold" && P.tapHold < 0.5) continue;
      const score = 1 + (color === "gold" ? P.wGold : 0) + ((color === "blue" || color === "violet") ? P.wSpecial : 0) + P.wAge * (t - s.t0) / 1000;
      if (score > bestScore) { bestScore = score; bestCell = tile.closest(".cell"); bestTile = tile; }
    }
    if (!bestCell || t < busyUntil) return;
    tap(bestCell, "pointerdown"); window.__botTaps++;
    if (bestTile.classList.contains("hold")) { holdEl = bestTile; return; }
    window.dispatchEvent(new PointerEvent("pointerup", { pointerId: 1 }));
    busyUntil = t + L.gapMs;
  }, 16);
}

// ---------- une partie ----------
async function playGame(browser, params) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 780 }, serviceWorkers: "block" });
  // Jamais de requête vers le vrai serveur : le bot ne doit pas polluer le classement.
  await ctx.route((u) => !u.href.startsWith(URL_JEU), (r) => r.fulfill({ json: [] }));
  await ctx.addInitScript((mode) => {
    localStorage.setItem("redless-guest-at", String(Date.now()));
    const s = JSON.parse(localStorage.getItem("ntplr-save-v1") || "{}");
    localStorage.setItem("ntplr-save-v1", JSON.stringify({ ...s, tutorialDone: true, mode, track: "synth" }));
  }, MODE);
  // BOT_TEST_BUG=1 : provoque une fausse erreur pour tester la chaîne de notification.
  if (E.BOT_TEST_BUG) await ctx.addInitScript(() => setTimeout(() => { throw new Error("Bug de test du bot (BOT_TEST_BUG)"); }, 4000));
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("Erreur JavaScript : " + e.message + (e.stack ? "\n" + e.stack.split("\n").slice(1, 4).join("\n") : "")));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("console.error : " + m.text()); });
  page.on("crash", () => errors.push("La page a planté (crash du moteur)"));
  const res = { score: 0, level: 0, ms: 0, taps: 0, end: "?" };
  try {
    await page.goto(URL_JEU); await page.waitForTimeout(1500);
    await page.click("#btn-play"); await page.waitForTimeout(500);
    await page.evaluate(`(${player})(${JSON.stringify(params)}, ${JSON.stringify(LIMITS)})`);
    const t0 = Date.now();
    let last = "", still = Date.now();
    for (;;) {
      await page.waitForTimeout(1000);
      const d = await page.evaluate(() => ({ ...(window.__debug ? window.__debug() : {}), over: !document.querySelector("#over")?.hidden, taps: window.__botTaps }));
      res.score = d.score ?? res.score; res.level = d.level ?? res.level; res.taps = d.taps; res.ms = Date.now() - t0;
      const c = { score: d.score, level: d.level, bpm: d.bpmNow, lives: d.lives, mode: MODE, minute: +(res.ms / 60e3).toFixed(1) };
      for (const e of errors.splice(0)) await bug(page, "erreur", e, c);
      if (d.over) { res.end = "perdu"; break; }
      if (![d.score, d.lives, d.bpmNow].every((v) => v == null || Number.isFinite(v))) await bug(page, "valeur", `Valeur impossible : score=${d.score} vies=${d.lives} bpm=${d.bpmNow}`, c);
      if (d.score < 0 || d.lives < 0) await bug(page, "valeur", `Valeur négative : score=${d.score} vies=${d.lives}`, c);
      if (d.tiles && d.cells && d.tiles.length > d.cells) await bug(page, "plateau", `Plus de cases (${d.tiles.length}) que d'emplacements (${d.cells})`, c);
      const sig = JSON.stringify([d.score, d.tiles, d.bpmNow, d.lives, d.mini && d.mini.obstacles?.length]);
      if (sig !== last) { last = sig; still = Date.now(); }
      else if (Date.now() - still > 20e3 && !d.mini) { await bug(page, "bloque", "Partie figée : rien ne bouge depuis 20 s (score, cases, tempo)", c); res.end = "bloque"; break; }
      if (res.ms > MAX_GAME_MS) { res.end = "temps max"; break; }
    }
    for (const e of errors.splice(0)) await bug(page, "erreur", e, { mode: MODE });
  } catch (e) {
    await bug(page, "bot", "Le bot n'a pas pu jouer : " + e.message, { mode: MODE });
    res.end = "erreur";
  } finally { await ctx.close(); }
  return res;
}

// ---------- apprentissage : on garde un réglage s'il fait mieux en moyenne ----------
const browser = await chromium.launch({
  executablePath: E.CHROMIUM || SYS_CHROME, // sur le Pi : le Chromium du système
  args: ["--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-gpu"],
});
let stop = false;
for (const s of ["SIGINT", "SIGTERM"]) process.on(s, () => { stop = true; log("Arrêt demandé, fin de la partie en cours…"); });
log(`Bot Redless démarré : mode ${MODE}, ${st.games} parties déjà jouées, record ${st.record}.`);
await notify("Redless : bot demarre", `Mode ${MODE}. ${st.games} parties deja jouees, record ${st.record}.`, "robot");

const avg = async (params) => {
  const scores = [];
  for (let i = 0; i < GAMES_PER_TRIAL && !stop && st.games < MAX_GAMES; i++) {
    const r = await playGame(browser, params);
    st.games++; scores.push(r.score);
    log(`partie ${st.games} : ${r.score} pts, niveau ${r.level}, ${(r.ms / 1000) | 0} s, ${r.taps} touches (${r.end})`);
    await appendFile(join(DIR, "parties.csv"), `${new Date().toISOString()},${MODE},${r.score},${r.level},${r.ms},${r.end}\n`);
    if (r.score > st.record) {
      const old = st.record; st.record = r.score;
      if (old > 0) await notify("Redless : nouveau record du bot", `${r.score} points (avant : ${old}), niveau ${r.level}, partie ${st.games}.`, "trophy");
    }
    await save();
  }
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : -1;
};

if (st.best.score == null) st.best.score = await avg(st.best.params);
while (!stop && st.games < MAX_GAMES) {
  const cand = mutate(st.best.params);
  const s = await avg(cand);
  st.trials++;
  if (s > st.best.score) {
    log(`Réglage gardé : moyenne ${s.toFixed(1)} (avant ${st.best.score.toFixed(1)})`);
    st.best = { params: cand, score: s }; st.sigma = Math.min(0.4, st.sigma * 1.2);
  } else {
    st.sigma = Math.max(0.03, st.sigma * 0.95);
    // Le hasard peut flatter un réglage : on réévalue doucement le meilleur pour ne pas rester bloqué sur un coup de chance.
    if (st.trials % 10 === 0) st.best.score = (st.best.score + await avg(st.best.params)) / 2;
  }
  await save();
}
await browser.close(); server.close();
log("Bot arrêté.");
