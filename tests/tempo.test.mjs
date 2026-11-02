// Test du tempo dans Chromium : départ lent selon la difficulté, croissance exponentielle,
// et au-delà de la vitesse max de la musique (2×), des cases entre les temps.
// Lancement : node tests/tempo.test.mjs
import { chromium, startServer } from "./helpers.mjs";

const server = await startServer();
let failures = 0;
const check = (ok, what) => { console.log((ok ? "  ok   " : "  ÉCHEC ") + what); if (!ok) failures++; };
const browser = await chromium.launch();
const LINES = {
  classic: "startBpm: 60, bpmStep: 9, greensPerLevel: 8, double: 150,",
  chrono: "startBpm: 66, bpmStep: 12, greensPerLevel: 7, double: 45,",
};

// Starts a run; `patch` rewrites the mode's line of config.js. Returns the page.
async function run({ mode = "classic", difficulty = "normal", patch = null, bot = false }) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 780 } });
  await ctx.route(/supabase\.co|taild80a87\.ts\.net/, (r) => r.fulfill({ json: [] }));
  if (patch) await ctx.route(/js\/config\.js$/, async (r) => {
    const res = await r.fetch(); r.fulfill({ response: res, body: (await res.text()).replace(LINES[mode], patch) });
  });
  await ctx.addInitScript(([m, d]) => {
    localStorage.setItem("redless-guest-at", String(Date.now()));
    localStorage.setItem("ntplr-save-v1", JSON.stringify({ tutorialDone: true, mode: m, track: "sync", difficulty: d }));
  }, [mode, difficulty]);
  const p = await ctx.newPage();
  if (process.env.SLOW_CPU) await (await ctx.newCDPSession(p)).send("Emulation.setCPUThrottlingRate", { rate: +process.env.SLOW_CPU });
  p.errors = []; p.on("pageerror", (e) => p.errors.push(e.message));
  await p.goto(server.url); await p.waitForTimeout(800);
  await p.evaluate((bot) => {
    window.__n = 0;
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => n.classList && n.classList.contains("tile") && window.__n++)))
      .observe(document.querySelector("#board"), { childList: true, subtree: true });
    if (bot) setInterval(() => {
      for (const el of document.querySelectorAll("#board .tile.green, #board .tile.gold, #board .tile.blue, #board .tile.violet"))
        el.closest(".cell").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    }, 30);
  }, bot);
  await p.click("#btn-play"); await p.waitForTimeout(1500);
  p.dbg = () => p.evaluate(() => window.__debug());
  p.spawned = () => p.evaluate(() => { const n = window.__n; window.__n = 0; return n; });
  return p;
}

try {
  console.log("Départ lent selon la difficulté");
  for (const [d, want] of [["facile", 48], ["normal", 60], ["impossible", 100]]) {
    const p = await run({ difficulty: d });
    const b = (await p.dbg()).bpmNow;
    check(Math.abs(b - want) < 3, `Classique ${d} : départ à ${Math.round(b)} BPM (attendu ≈ ${want})`);
    await p.context().close();
  }

  console.log("Croissance exponentielle (accélérée : double toutes les 15 s)");
  {
    const p = await run({ patch: "startBpm: 60, bpmStep: 0, greensPerLevel: 999, double: 15,", bot: true });
    const a = (await p.dbg()).bpmNow; await p.waitForTimeout(5000);
    const b = (await p.dbg()).bpmNow; await p.waitForTimeout(5000);
    const c = (await p.dbg()).bpmNow;
    const r1 = b / a, r2 = c / b, want = Math.pow(2, 5 / 15); // ≈ 1.26 every 5 s
    check(Math.abs(r1 - want) < 0.06 && Math.abs(r2 - want) < 0.06,
      `×${r1.toFixed(2)} puis ×${r2.toFixed(2)} toutes les 5 s, attendu ×${want.toFixed(2)} (${Math.round(a)} → ${Math.round(b)} → ${Math.round(c)} BPM)`);
    check(p.errors.length === 0, "aucune erreur JavaScript");
    await p.context().close();
  }

  // In Chrono (no lives, the bot never touches red) the run cannot end while tiles are counted.
  console.log("Au-delà de la vitesse max de la musique (Chrono : pas de vies, la partie dure)");
  const rates = {};
  for (const bpm of [190, 400, 800]) {
    const p = await run({ mode: "chrono", patch: `startBpm: ${bpm}, bpmStep: 0, greensPerLevel: 7, double: 1e9,` });
    await p.spawned(); await p.waitForTimeout(2000);
    const n = await p.spawned(), d = await p.dbg();
    const running = await p.isHidden("#over");
    rates[bpm] = n;
    console.log(`       ${bpm} BPM : musique ×${d.rate.toFixed(2)}, ${n} cases en 2 s`);
    check(running, `${bpm} BPM : partie toujours en cours pendant la mesure`);
    if (bpm > 200) check(d.rate > 1.95 && d.rate <= 2.001, `${bpm} BPM : la musique joue à 2×, son maximum`);
    await p.context().close();
  }
  check(rates[400] > rates[190] * 1.5 && rates[800] > rates[400] * 1.4, "les cases continuent d'accélérer au-delà de la musique");
} finally {
  await browser.close();
  server.close();
}
console.log(failures ? `\n${failures} échec(s)` : "\nTout est bon");
process.exit(failures ? 1 : 0);
