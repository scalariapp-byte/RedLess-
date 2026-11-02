// Test du mode Chaos dans Chromium : rotation, événements, changement de grille, téléportation
// dans le mini-jeu de la poule (un robot saute au bon moment), retour au plateau.
// Pour aller vite, la téléportation a lieu dès le 1er palier (au lieu de tous les 3).
// Lancement : node tests/chaos.test.mjs   (option : dossier où enregistrer des captures)
import { chromium, startServer } from "./helpers.mjs";

const shots = process.argv[2];
const server = await startServer();
let failures = 0;
const check = (ok, what) => { console.log((ok ? "  ok   " : "  ÉCHEC ") + what); if (!ok) failures++; };

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 780 } });
  await ctx.route(/supabase\.co|taild80a87\.ts\.net/, (r) => r.fulfill({ json: [] }));
  await ctx.route(/js\/config\.js$/, async (r) => {
    const res = await r.fetch();
    r.fulfill({ response: res, body: (await res.text()).replace("TELEPORT_EVERY: 3", "TELEPORT_EVERY: 1") });
  });
  await ctx.addInitScript(() => {
    localStorage.setItem("redless-guest-at", String(Date.now()));
    localStorage.setItem("ntplr-save-v1", JSON.stringify({ tutorialDone: true, mode: "chaos", track: "synth" }));
  });
  const p = await ctx.newPage();
  const errors = []; p.on("pageerror", (e) => errors.push(e.message));
  const dbg = () => p.evaluate(() => window.__debug());
  await p.goto(server.url); await p.waitForTimeout(1000);
  check((await p.textContent("#mode-current")) === "Chaos", "le mode Chaos est proposé et choisi");

  await p.click("#btn-play"); await p.waitForTimeout(3000);
  const tf1 = await p.evaluate(() => document.querySelector("#board").style.transform);
  await p.waitForTimeout(500);
  const tf2 = await p.evaluate(() => document.querySelector("#board").style.transform);
  check(/rotate\(/.test(tf1) && tf1 !== tf2, "le plateau tourne et zoome en continu");
  if (shots) await p.screenshot({ path: shots + "/chaos-play.png" });

  // Touch every green/gold tile until the teleport (level 2), noting the chaos events seen.
  const events = new Set();
  let cellsBefore = (await dbg()).cells, teleported = false;
  for (let k = 0; k < 400 && !teleported; k++) {
    await p.evaluate(() => {
      for (const el of document.querySelectorAll("#board .tile.green, #board .tile.gold"))
        el.closest(".cell").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    });
    const d = await dbg();
    if (d.chaosEvent) events.add(d.chaosEvent);
    teleported = !!d.mini;
    await p.waitForTimeout(60);
  }
  check(teleported, "téléportation dans le mini-jeu au palier prévu");
  check((await dbg()).cells !== cellsBefore, "la grille a changé de taille au palier");

  // Robot: jump when a tree comes close.
  const lives = (await dbg()).lives;
  await p.evaluate(() => {
    window.__bot = setInterval(() => {
      const m = window.__debug().mini; if (!m) return;
      if (m.y < 1 && m.obstacles.some((o) => o.x - 100 > 6 && o.x - 100 < 40))
        document.querySelector("#mini").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true }));
    }, 16);
  });
  await p.waitForTimeout(2500);
  if (shots) await p.screenshot({ path: shots + "/chaos-mini.png" });
  check(await p.isVisible("#mini-cv"), "le mini-jeu de la poule s'affiche");
  await p.waitForTimeout(8500);
  check(!(await dbg()).mini && (await p.isHidden("#mini")), "retour au plateau après 10 s");
  check((await dbg()).lives === lives, "en sautant au bon moment, aucune vie perdue");
  check(/Retour/.test(await p.textContent("#banner")), "bannière de retour avec le bonus");

  // Keep playing a little to see more chaos events.
  for (let k = 0; k < 150; k++) {
    await p.evaluate(() => {
      for (const el of document.querySelectorAll("#board .tile.green, #board .tile.gold"))
        el.closest(".cell").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    });
    const d = await dbg(); if (d.chaosEvent) events.add(d.chaosEvent);
    await p.waitForTimeout(60);
  }
  check(events.size >= 1, `événements de chaos déclenchés : ${[...events].join(", ") || "aucun"}`);
  check(errors.length === 0, "aucune erreur JavaScript" + (errors.length ? " : " + errors.join(" | ") : ""));
} finally {
  await browser.close();
  server.close();
}
console.log(failures ? `\n${failures} échec(s)` : "\nTout est bon");
process.exit(failures ? 1 : 0);
