// Serveur du Raspberry Pi (pi/serveur.mjs) : API au format Supabase, fichiers du site et du jeu,
// e-mails (SMTP simulé), puis le vrai code du jeu (js/online.js) dans Chromium branché dessus.
// Lancement : node tests/serveur.test.mjs
import assert from "node:assert/strict";
import { mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { createServer as tcpServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createApp, settings } from "../pi/serveur.mjs";
import { createMailer } from "../pi/courriel.mjs";

const tmp = mkdtempSync(join(tmpdir(), "redless-serveur-"));
const outbox = join(tmp, "courriels");
let passed = 0;
const step = async (name, fn) => { await fn(); passed++; console.log("ok -", name); };

function boot(extra = {}) {
  const cfg = settings({ DATA_DIR: join(tmp, "donnees"), MAIL_OUTBOX: outbox, QUIET: "1", ADMIN_EMAIL: "admin@exemple.fr", PLAYERS_NEEDED: "3", EVENT_DELAY_DAYS: "0", ...extra });
  const app = createApp(cfg);
  return new Promise((ok) => app.server.listen(0, "127.0.0.1", () => { app.url = `http://127.0.0.1:${app.server.address().port}`; ok(app); }));
}
let app = await boot();

async function call(path, body, token, method = "POST", headers = {}) {
  const res = await fetch(app.url + path, {
    method, headers: { apikey: "redless", "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}), ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, data: text ? JSON.parse(text) : null, headers: res.headers };
}
const rpc = (name, params = {}, token) => call("/rest/v1/rpc/" + name, params, token);
const signup = async () => (await call("/auth/v1/signup", { data: {} })).data;
function lastCode(to) {
  const files = readdirSync(outbox).sort();
  for (let i = files.length - 1; i >= 0; i--) {
    const m = JSON.parse(readFileSync(join(outbox, files[i]), "utf8"));
    if (m.to === to) return /\b(\d{6})\b/.exec(m.text)[1];
  }
  throw new Error("aucun e-mail pour " + to);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------- API ----------------
let alice, bob;
await step("compte anonyme : jetons au format Supabase", async () => {
  alice = await signup();
  assert.ok(alice.access_token.split(".").length === 3 && alice.refresh_token && alice.expires_in === 3600);
  assert.equal(alice.user.is_anonymous, true);
  bob = await signup();
  assert.notEqual(alice.user.id, bob.user.id);
});

await step("rafraîchissement : rotation, et deux demandes simultanées gardent le même compte", async () => {
  const [a, b] = await Promise.all([1, 2].map(() => call("/auth/v1/token?grant_type=refresh_token", { refresh_token: alice.refresh_token })));
  assert.equal(a.status, 200); assert.equal(b.status, 200);
  assert.equal(a.data.user.id, alice.user.id); assert.equal(b.data.user.id, alice.user.id);
  const bad = await call("/auth/v1/token?grant_type=refresh_token", { refresh_token: "faux" });
  assert.equal(bad.status, 400); assert.equal(bad.data.error_code, "refresh_token_not_found");
  alice = a.data;
});

await step("fonction inconnue : 404 PGRST202 (le jeu sait s'en passer)", async () => {
  const r = await rpc("nexiste_pas");
  assert.equal(r.status, 404); assert.equal(r.data.code, "PGRST202");
});

await step("pseudos : libre, pris, invalide", async () => {
  assert.equal((await rpc("name_available", { p_name: "Alice" })).data, true);
  const r = await rpc("add_points", { p_points: 500, p_duration_ms: 60000, p_games: 1, p_name: "Alice" }, alice.access_token);
  assert.equal(r.status, 200, JSON.stringify(r.data));
  assert.deepEqual(Object.keys(r.data[0]).sort(), ["players", "rank", "season", "total"]);
  assert.equal(r.data[0].total, 500); assert.equal(r.data[0].rank, 1);
  assert.equal((await rpc("name_available", { p_name: "alice" })).data, false);
  assert.equal((await rpc("name_available", { p_name: "ALICE" }, alice.access_token)).data, true, "son propre pseudo compte comme libre");
  const taken = await rpc("add_points", { p_points: 10, p_duration_ms: 5000, p_games: 1, p_name: "aLiCe" }, bob.access_token);
  assert.equal(taken.status, 400); assert.match(taken.data.message, /déjà pris/);
  const invalid = await rpc("add_points", { p_points: 10, p_duration_ms: 5000, p_games: 1, p_name: "<script>" }, bob.access_token);
  assert.match(invalid.data.message, /pseudo invalide/);
  const none = await rpc("add_points", { p_points: 10, p_duration_ms: 5000, p_games: 1, p_name: null }, bob.access_token);
  assert.match(none.data.message, /pseudo requis/);
});

await step("points : vérifiés (invraisemblable, trop rapide), additionnés", async () => {
  const cheat = await rpc("add_points", { p_points: 100000, p_duration_ms: 10000, p_games: 1, p_name: "Bob" }, bob.access_token);
  assert.match(cheat.data.message, /invraisemblable/);
  const ok = await rpc("add_points", { p_points: 800, p_duration_ms: 90000, p_games: 2, p_name: "Bob" }, bob.access_token);
  assert.equal(ok.data[0].rank, 1); assert.equal(ok.data[0].total, 800);
  const fast = await rpc("add_points", { p_points: 5, p_duration_ms: 5000, p_games: 1, p_name: "Bob" }, bob.access_token);
  assert.match(fast.data.message, /trop rapide/);
  const noAuth = await rpc("add_points", { p_points: 5, p_duration_ms: 5000, p_games: 1, p_name: "Bob" });
  assert.equal(noAuth.status, 401);
  const badJwt = await rpc("add_points", { p_points: 5, p_duration_ms: 5000, p_games: 1 }, alice.access_token.slice(0, -2) + "xx");
  assert.equal(badJwt.status, 401);
});

await step("classement général : ordre, is_me, games, sans jeton aussi", async () => {
  const pub = await rpc("get_overall", { p_season: null, p_limit: 10 });
  assert.deepEqual(pub.data.map((r) => [r.rank, r.name, r.total, r.games, r.is_me]), [[1, "Bob", 800, 2, false], [2, "Alice", 500, 1, false]]);
  const mine = await rpc("get_overall", { p_season: null, p_limit: 1 }, alice.access_token);
  assert.deepEqual(mine.data.map((r) => r.name), ["Bob", "Alice"], "le joueur qui demande est ajouté s'il est hors du top");
  assert.equal(mine.data[1].is_me, true);
  // Un jeton invalide ne bloque pas une lecture publique.
  assert.equal((await rpc("get_overall", {}, "n.importe.quoi")).status, 200);
});

await step("événement : seuil de joueurs, saison 1, compteur de visiteurs", async () => {
  let [info] = (await rpc("event_info")).data;
  assert.equal(info.players, 2); assert.equal(info.season, 0); assert.equal(info.threshold_at, null);
  const carol = await signup();
  await rpc("add_points", { p_points: 50, p_duration_ms: 9000, p_games: 1, p_name: "Carol" }, carol.access_token);
  [info] = (await rpc("event_info")).data;
  assert.equal(info.players, 3); assert.ok(info.threshold_at);
  assert.equal(info.season, 1, "délai de 0 jour dans ce test : la saison 1 démarre tout de suite");
  assert.ok(new Date(info.season_end) > new Date(info.season_start));
  // Nouvelle saison : le classement repart de zéro (les points de Carol, envoyés au 3e joueur, comptent déjà pour la saison 1).
  assert.deepEqual((await rpc("get_overall", {})).data.map((r) => r.name), ["Carol"]);
  assert.deepEqual((await rpc("get_overall", { p_season: 0 })).data.map((r) => r.name), ["Bob", "Alice"]);
  assert.equal((await rpc("visitor_count")).data, 3);
});

await step("changement de pseudo (set_name)", async () => {
  assert.equal((await rpc("set_name", { p_name: "Bob" }, alice.access_token)).data.message, "pseudo déjà pris");
  assert.equal((await rpc("set_name", { p_name: "Alicia" }, alice.access_token)).status, 200);
  assert.equal((await rpc("name_available", { p_name: "Alice" })).data, true);
  assert.equal((await rpc("name_available", { p_name: "alicia" })).data, false);
});

let admin;
await step("compte protégé : code par e-mail, sauvegarde en ligne, retrouvé sur un autre téléphone", async () => {
  const anonSave = await rpc("save_progress", { p_data: { credits: 1 } }, alice.access_token);
  assert.match(anonSave.data.message, /Protège d'abord/);
  assert.equal((await call("/auth/v1/user", { email: "pas-une-adresse" }, alice.access_token, "PUT")).data.error_code, "email_address_invalid");
  assert.equal((await call("/auth/v1/user", { email: "Alice@Exemple.fr" }, alice.access_token, "PUT")).status, 200);
  const again = await call("/auth/v1/user", { email: "alice@exemple.fr" }, alice.access_token, "PUT");
  assert.equal(again.status, 429, "un seul code par minute");
  const wrong = await call("/auth/v1/verify", { type: "email_change", email: "alice@exemple.fr", token: "000000" }, alice.access_token);
  assert.equal(wrong.status, 403); assert.equal(wrong.data.error_code, "otp_expired");
  const code = lastCode("alice@exemple.fr");
  const linked = await call("/auth/v1/verify", { type: "email_change", email: "alice@exemple.fr", token: code }, alice.access_token);
  assert.equal(linked.status, 200); assert.equal(linked.data.user.is_anonymous, false);
  alice = linked.data;
  const saved = await rpc("save_progress", { p_data: { credits: 42, skins: ["neon"] } }, alice.access_token);
  assert.equal(saved.status, 200); assert.ok(!isNaN(new Date(saved.data)));
  assert.equal((await rpc("save_progress", { p_data: [1, 2] }, alice.access_token)).data.message, "Sauvegarde invalide");
  assert.equal((await rpc("save_progress", { p_data: { big: "x".repeat(200001) } }, alice.access_token)).data.message, "Sauvegarde invalide");
  // Bob ne peut pas prendre l'adresse d'Alice.
  assert.equal((await call("/auth/v1/user", { email: "alice@exemple.fr" }, bob.access_token, "PUT")).data.error_code, "email_exists");
  // Nouveau téléphone : adresse inconnue refusée, puis la bonne adresse et son code.
  assert.equal((await call("/auth/v1/otp", { email: "inconnu@exemple.fr", create_user: false })).data.error_code, "otp_disabled");
  // Un seul code par minute et par adresse : un redémarrage remet les limites à zéro pour la suite du test.
  await app.close(); app = await boot();
  assert.equal((await call("/auth/v1/otp", { email: "alice@exemple.fr", create_user: false })).status, 200);
  const back = await call("/auth/v1/verify", { type: "email", email: "alice@exemple.fr", token: lastCode("alice@exemple.fr") });
  assert.equal(back.status, 200); assert.equal(back.data.user.id, alice.user.id);
  const [loaded] = (await rpc("load_progress", {}, back.data.access_token)).data;
  assert.deepEqual(loaded.data, { credits: 42, skins: ["neon"] });
  assert.ok(loaded.updated_at);
  assert.deepEqual((await rpc("load_progress", {}, bob.access_token)).data, []);
  // Un code ne sert qu'une fois.
  assert.equal((await call("/auth/v1/verify", { type: "email", email: "alice@exemple.fr", token: lastCode("alice@exemple.fr") })).status, 403);
});

await step("données gardées après redémarrage (y compris le classement et les jetons)", async () => {
  assert.equal((await rpc("get_overall", { p_season: 0 })).data.length, 2);
  assert.equal((await rpc("load_progress", {}, alice.access_token)).status, 200, "le jeton d'avant le redémarrage est toujours valable");
});

await step("administrateur : bannir, liste des bannis, débannir", async () => {
  admin = await signup();
  await call("/auth/v1/user", { email: "admin@exemple.fr" }, admin.access_token, "PUT");
  admin = (await call("/auth/v1/verify", { type: "email_change", email: "admin@exemple.fr", token: lastCode("admin@exemple.fr") }, admin.access_token)).data;
  assert.equal((await rpc("am_i_admin", {}, admin.access_token)).data, true);
  assert.equal((await rpc("am_i_admin", {}, bob.access_token)).data, false);
  assert.equal((await rpc("am_i_admin", {})).data, false);
  assert.match((await rpc("ban_player", { p_name: "Carol", p_ban: true }, bob.access_token)).data.message, /administrateur/);
  await sleep(5100); // un envoi toutes les 5 s au plus par joueur
  assert.equal((await rpc("add_points", { p_points: 300, p_duration_ms: 30000, p_games: 1, p_name: "Bob" }, bob.access_token)).status, 200);
  assert.equal((await rpc("ban_player", { p_name: "bob", p_ban: true }, admin.access_token)).status, 200);
  assert.deepEqual((await rpc("get_overall", {})).data.map((r) => r.name), ["Carol"], "Bob banni disparaît du classement");
  assert.deepEqual((await rpc("banned_players", {}, admin.access_token)).data, [{ name: "Bob", total: 300 }]);
  assert.match((await rpc("add_points", { p_points: 5, p_duration_ms: 5000, p_games: 1 }, bob.access_token)).data.message, /banni/);
  await rpc("ban_player", { p_name: "Bob", p_ban: false }, admin.access_token);
  assert.equal((await rpc("get_overall", {})).data[0].name, "Bob");
});

await step("installation : signalée une fois par appareil, e-mail au propriétaire", async () => {
  const dev = "6f1c1d7e-3b7a-4c1e-9f2a-0d4b5e6f7a8b";
  assert.equal((await rpc("register_install", { p_device: dev, p_platform: "android", p_version: "3.23" })).data, true);
  assert.equal((await rpc("register_install", { p_device: dev, p_platform: "android", p_version: "3.23" })).data, false);
  assert.match((await rpc("register_install", { p_device: "x", p_platform: "android" })).data.message, /invalide/);
  await sleep(50);
  const mails = readdirSync(outbox).map((f) => JSON.parse(readFileSync(join(outbox, f), "utf8")));
  assert.ok(mails.some((m) => m.to === "scalariapp@gmail.com" && /nouvelle installation \(1 au total\)/.test(m.subject)));
});

await step("CORS : l'appli Android (origine file://) peut appeler l'API", async () => {
  const pre = await fetch(app.url + "/rest/v1/rpc/event_info", { method: "OPTIONS", headers: { Origin: "null", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "apikey,content-type,authorization" } });
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get("access-control-allow-origin"), "*");
  assert.match(pre.headers.get("access-control-allow-headers"), /authorization/);
});

// ---------------- fichiers ----------------
await step("site, jeu, version.json, APK, musique par morceaux, fichiers interdits", async () => {
  const get = (p, h) => fetch(app.url + p, { headers: h, redirect: "manual" });
  const site = await get("/");
  assert.equal(site.status, 200); assert.match(await site.text(), /Redlok/);
  assert.equal((await get("/site.js")).status, 200);
  assert.equal((await get("/?site")).status, 200);
  const jeu = await get("/jouer/");
  assert.equal(jeu.status, 200); assert.match(await jeu.text(), /online-config\.js/);
  assert.equal((await get("/jouer")).headers.get("location"), "/jouer/");
  assert.equal((await get("/jouer/js/online.js")).headers.get("content-type"), "text/javascript; charset=utf-8");
  const version = { version: readFileSync(new URL("../js/game.js", import.meta.url), "utf8").match(/const VERSION = "([^"]+)"/)[1] };
  assert.deepEqual(await (await get("/version.json")).json(), version);
  assert.deepEqual(await (await get("/jouer/version.json")).json(), version);
  const apk = await get("/redless.apk");
  assert.equal(apk.status, 302); assert.match(apk.headers.get("location"), /releases\/download\/latest\/redless\.apk$/);
  const mp3 = readdirSync(new URL("../audio/", import.meta.url)).find((f) => f.endsWith(".mp3"));
  const part = await get("/jouer/audio/" + mp3, { Range: "bytes=0-99" });
  assert.equal(part.status, 206); assert.equal((await part.arrayBuffer()).byteLength, 100);
  assert.match(part.headers.get("content-range"), /^bytes 0-99\/\d+$/);
  const etag = (await get("/jouer/index.html")).headers.get("etag");
  assert.equal((await get("/jouer/index.html", { "If-None-Match": etag })).status, 304);
  for (const p of ["/jouer/android/build.sh", "/jouer/.git/config", "/jouer/supabase/schema.sql", "/jouer/pi/serveur.mjs", "/../pi/serveur.mjs", "/jouer/%2e%2e/pi/serveur.mjs", "/.git/HEAD", "/%2e%2e%2fpi%2fserveur.mjs"]) {
    const r = await get(p);
    assert.equal(r.status, 404, p + " -> " + r.status);
  }
  const health = await (await get("/sante")).json();
  assert.equal(health.ok, true);
});

// ---------------- SMTP ----------------
await step("e-mail SMTP : dialogue complet avec un serveur simulé", async () => {
  const got = [];
  const smtp = tcpServer((s) => {
    let data = false, buf = "";
    s.write("220 test ESMTP\r\n");
    s.on("data", (d) => {
      buf += d.toString();
      let i;
      while ((i = buf.indexOf("\r\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (data) { if (line === ".") { data = false; s.write("250 ok\r\n"); } else got.push(line); continue; }
        got.push(line);
        if (/^EHLO/.test(line)) s.write("250-test\r\n250 AUTH PLAIN\r\n");
        else if (/^AUTH PLAIN/.test(line)) s.write("235 ok\r\n");
        else if (/^(MAIL|RCPT)/.test(line)) s.write("250 ok\r\n");
        else if (line === "DATA") { data = true; s.write("354 go\r\n"); }
        else if (line === "QUIT") { s.write("221 bye\r\n"); s.end(); }
      }
    });
  });
  await new Promise((ok) => smtp.listen(0, "127.0.0.1", ok));
  const mailer = createMailer({ SMTP_HOST: "127.0.0.1", SMTP_PORT: String(smtp.address().port), SMTP_SECURE: "0", SMTP_USER: "moi@gmail.com", SMTP_PASS: "secret", MAIL_FROM: "Redlok <moi@gmail.com>" });
  await mailer.send({ to: "joueur@exemple.fr", subject: "Redlok : ton code 123456", text: "Ton code Redlok : 123456 — éàü" });
  smtp.close();
  assert.ok(got.includes("MAIL FROM:<moi@gmail.com>"));
  assert.ok(got.includes("RCPT TO:<joueur@exemple.fr>"));
  assert.ok(got.some((l) => l === `AUTH PLAIN ${Buffer.from("\0moi@gmail.com\0secret").toString("base64")}`));
  const body = got.slice(got.indexOf("") + 1).join("");
  assert.match(Buffer.from(body, "base64").toString(), /123456 — éàü/);
});

// ---------------- le vrai jeu dans Chromium ----------------
await step("le jeu (js/online.js) contre ce serveur : connexion, points, classement, compte protégé", async () => {
  const { chromium } = await import("./helpers.mjs");
  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext();
    // Les appels du jeu à redless.taild80a87.ts.net partent vers ce serveur local.
    await ctx.route(/taild80a87\.ts\.net/, async (route) => {
      const req = route.request(), u = new URL(req.url());
      const res = await fetch(app.url + u.pathname + u.search, { method: req.method(), headers: req.headers(), body: req.postData() || undefined });
      route.fulfill({ status: res.status, headers: Object.fromEntries(res.headers), body: Buffer.from(await res.arrayBuffer()) });
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(app.url + "/jouer/");
    await page.waitForFunction(() => window.NT && NT.online && NT.online.enabled);
    const res = await page.evaluate(async () => {
      const o = NT.online;
      const out = {};
      out.connected = await o.connect("Dana");
      out.free = await o.nameFree("Dana");
      out.taken = await o.nameFree("bob");
      out.sent = await o.submit({ mode: "classic", score: 420, duration: 50000 }, "Dana");
      out.board = await o.overall();
      out.info = await o.eventInfo();
      out.visitors = await o.visitors();
      out.admin = await o.isAdmin();
      await o.linkEmail("dana@exemple.fr");
      return out;
    });
    assert.equal(res.connected, true);
    assert.equal(res.free, true); assert.equal(res.taken, false);
    assert.ok(res.sent && res.sent.total === 420, JSON.stringify(res.sent));
    assert.ok(res.board.some((r) => r.name === "Dana" && r.is_me && r.games === 1));
    assert.equal(res.info.season, 1);
    assert.ok(res.visitors >= 5);
    assert.equal(res.admin, false);
    const code = lastCode("dana@exemple.fr");
    const after = await page.evaluate(async (code) => {
      const o = NT.online;
      await o.confirmLink("dana@exemple.fr", code);
      await o.pushSave({ credits: 7 });
      const save = await o.pullSave();
      let wrong = null;
      try { await o.confirmLogin("dana@exemple.fr", "111111"); } catch (e) { wrong = e.message; }
      return { email: o.email(), save: save.data, wrong };
    }, code);
    assert.equal(after.email, "dana@exemple.fr");
    assert.deepEqual(after.save, { credits: 7 });
    assert.equal(after.wrong, "Code faux ou expiré. Demande un nouveau code.");
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

await app.close();
rmSync(tmp, { recursive: true, force: true });
console.log(`\n${passed} étapes réussies`);
