// Test du classement en ligne du score total dans Chromium (Playwright), Supabase simulé en mémoire.
// Le téléphone lit sa ligne et n'envoie son total que s'il est plus haut que celui en ligne.
// Lancement : node tests/leaderboard.test.mjs   (CI : .github/workflows/tests.yml)
import { chromium, startServer } from "./helpers.mjs";

const server = await startServer();
let failures = 0;
const check = (ok, what) => { console.log((ok ? "  ok   " : "  ÉCHEC ") + what); if (!ok) failures++; };
const browser = await chromium.launch();

// Same rules as supabase/leaderboard.sql: the total never goes down, the pseudo is replaced.
function fakeBoard() {
  const rows = new Map(); // secret -> { name, total, at }
  const state = { rows, calls: [], offline: false };
  let clock = 0;
  const ranked = () => [...rows.entries()].sort((a, b) => b[1].total - a[1].total || a[1].at - b[1].at);
  const meRow = (secret) => {
    const r = rows.get(secret); if (!r) return [];
    return [{ name: r.name, total: r.total, rank: ranked().findIndex(([s]) => s === secret) + 1, players: rows.size }];
  };
  state.handler = async (route) => {
    const req = route.request(), fn = req.url().split("/rpc/")[1], p = JSON.parse(req.postData() || "{}");
    state.calls.push({ fn, p, apikey: req.headers().apikey });
    if (state.offline) return route.abort();
    if (fn === "board_me") return route.fulfill({ json: meRow(p.p_secret) });
    if (fn === "board_submit") {
      const old = rows.get(p.p_secret);
      rows.set(p.p_secret, { name: p.p_name, total: Math.max(old ? old.total : 0, p.p_total), at: old && old.total >= p.p_total ? old.at : ++clock });
      return route.fulfill({ json: meRow(p.p_secret) });
    }
    if (fn === "board_top") return route.fulfill({ json: ranked().map(([s, r], i) => ({ rank: i + 1, name: r.name, total: r.total, is_me: s === p.p_secret })) });
    return route.fulfill({ status: 404, json: { message: "inconnu" } });
  };
  state.submits = () => state.calls.filter((c) => c.fn === "board_submit");
  return state;
}

const CONFIG = `window.REDLESS_BOARD = { url: "https://test.supabase.co", key: "sb_publishable_test" };`;
async function open(board, save, { config = CONFIG, secret = null } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 780 } });
  await ctx.route(/taild80a87\.ts\.net/, (r) => r.abort()); // the game's other server (accounts): offline here
  await ctx.route(/supabase\.co\/rest\/v1\/rpc\//, board.handler);
  await ctx.route(/js\/leaderboard-config\.js$/, (r) => r.fulfill({ contentType: "text/javascript", body: config }));
  await ctx.addInitScript(([s, sec]) => {
    if (localStorage.getItem("ntplr-save-v1")) return; // kept across reloads
    localStorage.setItem("redless-guest-at", String(Date.now()));
    localStorage.setItem("ntplr-save-v1", JSON.stringify({ tutorialDone: true, track: "synth", ...s }));
    if (sec) localStorage.setItem("redless-board-secret", JSON.stringify(sec));
  }, [save, secret]);
  const p = await ctx.newPage();
  p.errors = []; p.on("pageerror", (e) => p.errors.push(e.message));
  await p.goto(server.url); await p.waitForTimeout(1500);
  return p;
}
const secretOf = (p) => p.evaluate(() => JSON.parse(localStorage.getItem("redless-board-secret")));

try {
  console.log("Premier lancement, aucun point");
  {
    const b = fakeBoard(), p = await open(b, {});
    check(b.submits().length === 0, "rien n'est envoyé tant que le total est à 0");
    await p.context().close();
  }

  console.log("Total local plus haut que le classement : envoyé");
  {
    const b = fakeBoard(), p = await open(b, { name: "Testeur", xp: 1200 });
    const s = b.submits();
    check(s.length === 1 && s[0].p.p_total === 1200 && s[0].p.p_name === "Testeur", "au démarrage, le total 1200 est envoyé avec le pseudo");
    check(b.calls[0].fn === "board_me", "le téléphone lit d'abord sa ligne en ligne");
    check(b.calls.every((c) => c.apikey === "sb_publishable_test"), "clé publique envoyée dans apikey");
    const sec = await secretOf(p);
    check(/^[0-9a-f-]{36}$/.test(sec) && s[0].p.p_secret === sec, "le téléphone est reconnu par un secret aléatoire gardé en local");

    console.log("Même total au relancement : rien n'est renvoyé");
    await p.reload(); await p.waitForTimeout(1500);
    check(b.submits().length === 1, "total en ligne égal : pas d'envoi");
    check(b.calls.filter((c) => c.fn === "board_me").length === 2, "mais la ligne a bien été relue");

    console.log("Partie terminée : le nouveau total part");
    await p.evaluate(() => {
      NT.S.mode = "sudden"; // one mistake ends the run
      // Bot: taps the greens for 4 s (points), then stops; the next missed green ends the run.
      const bot = setInterval(() => {
        for (const el of document.querySelectorAll("#board .tile.green, #board .tile.gold"))
          el.closest(".cell").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      }, 30);
      setTimeout(() => clearInterval(bot), 5500);
    });
    await p.click("#btn-play");
    await p.waitForSelector("#over:not([hidden])", { timeout: 30000 });
    await p.waitForTimeout(800);
    const xp = await p.evaluate(() => NT.S.xp), last = b.submits().at(-1);
    const text = await p.textContent("#over-online");
    if (xp > 1200) check(last.p.p_total === xp, `nouveau total ${xp} envoyé`);
    else check(b.submits().length === 1, "partie à 0 point : total inchangé, rien envoyé");
    check(/En ligne : 1er sur 1/.test(text) && text.includes("ton total"), `écran de fin : « ${text.trim()} »`);

    console.log("Écran Classement");
    b.rows.set("autre-1", { name: "Alice", total: 999999, at: 0 });
    b.rows.set("autre-2", { name: "Bob", total: 10, at: 0 });
    await p.evaluate(() => document.querySelector("#btn-board").click()); await p.waitForTimeout(1200);
    const rows = await p.$$eval("#board-list li", (ls) => ls.map((l) => l.textContent.replace(/\s+/g, " ").trim()));
    check(rows.length === 3 && rows[0].includes("Alice") && rows[1].includes("Testeur") && rows[1].includes("toi") && rows[2].includes("Bob"), `classement trié, ligne du joueur marquée : ${rows.join(" | ")}`);

    console.log("Changement de pseudo : renvoyé même sans nouveaux points");
    await p.evaluate(() => { document.querySelector("#tabbar .tab-btn")?.click(); });
    const before = b.submits().length;
    await p.evaluate(async () => { const f = document.querySelector("#name-set-form"); f.querySelector("#set-name").value = "Nouveau"; f.requestSubmit(); });
    await p.waitForTimeout(800);
    const ls = b.submits();
    check(ls.length === before + 1 && ls.at(-1).p.p_name === "Nouveau", "le nouveau pseudo est envoyé");
    check(p.errors.length === 0, "aucune erreur JavaScript" + (p.errors.length ? " : " + p.errors.join(" ; ") : ""));
    await p.context().close();
  }

  console.log("Total en ligne plus haut (autre téléphone, ancienne version…) : rien n'est envoyé");
  {
    const b = fakeBoard(), sec = "11111111-1111-4111-8111-111111111111";
    b.rows.set(sec, { name: "Testeur", total: 5000, at: 0 });
    const p = await open(b, { name: "Testeur", xp: 1200 }, { secret: sec });
    check(b.submits().length === 0, "total local 1200 < 5000 en ligne : pas d'envoi");
    check(b.rows.get(sec).total === 5000, "le total en ligne n'a pas baissé");
    await p.context().close();
  }

  console.log("Hors ligne");
  {
    const b = fakeBoard(); b.offline = true;
    const p = await open(b, { name: "Testeur", xp: 1200 });
    await p.evaluate(() => document.querySelector("#btn-board").click()); await p.waitForTimeout(1200);
    check((await p.textContent("#board-list")).includes("Pas de connexion"), "le classement dit qu'il n'y a pas de connexion");
    b.offline = false;
    await p.evaluate(() => window.dispatchEvent(new Event("online"))); await p.waitForTimeout(800);
    check(b.submits().length === 1 && b.submits()[0].p.p_total === 1200, "retour du réseau : le total part");
    check(p.errors.length === 0, "aucune erreur JavaScript");
    await p.context().close();
  }

  console.log("Pas configuré");
  {
    const b = fakeBoard(), p = await open(b, { name: "Testeur", xp: 1200 }, { config: `window.REDLESS_BOARD = { url: "", key: "" };` });
    await p.evaluate(() => document.querySelector("#btn-board").click()); await p.waitForTimeout(800);
    check(b.calls.length === 0, "aucun appel réseau");
    check((await p.textContent("#board-list")).includes("pas encore activé"), "le classement dit qu'il n'est pas activé");
    await p.context().close();
  }
} finally {
  await browser.close(); server.close();
}
console.log(failures ? `\n${failures} échec(s)` : "\nTout est bon");
process.exit(failures ? 1 : 0);
