// Test du parcours de connexion dans un vrai navigateur (Chromium, via Playwright).
// Le serveur Supabase est simulé : aucun appel réseau réel, aucun compte créé.
// Lancement : node tests/login.test.mjs   (CI : .github/workflows/tests.yml)
import { chromium, startServer } from "./helpers.mjs";

const server = await startServer(), SITE = server.url;

// Fake Supabase: auth always accepts, « Pris » is a taken pseudo, saves are kept in memory.
function fakeSupabase(state) {
  return async (route) => {
    const req = route.request(), url = req.url();
    state.calls.push(url.replace(/^https:\/\/[^/]+/, ""));
    if (state.offline) return route.abort();
    if (url.includes("/auth/v1/")) return route.fulfill({ json: { access_token: "t", refresh_token: "r", expires_in: 3600 } });
    if (url.includes("/rpc/visitor_count")) return route.fulfill({ json: 1234 });
    if (url.includes("/rpc/name_available")) return route.fulfill({ json: JSON.parse(req.postData()).p_name.toLowerCase() !== "pris" });
    if (url.includes("/rpc/save_progress")) { state.save = JSON.parse(req.postData()).p_data; return route.fulfill({ json: null }); }
    if (url.includes("/rpc/load_progress")) return route.fulfill({ json: state.save ? [{ data: state.save, updated_at: new Date().toISOString() }] : [] });
    return route.fulfill({ json: [] });
  };
}

let failures = 0;
const check = (ok, what) => { console.log((ok ? "  ok   " : "  ÉCHEC ") + what); if (!ok) failures++; };

const browser = await chromium.launch();
async function freshPage(state) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 780 } });
  await ctx.route(/supabase\.co|taild80a87\.ts\.net/, fakeSupabase(state));
  const page = await ctx.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(e.message));
  page.screen = () => page.evaluate(() => [...document.querySelectorAll(".screen")].find((s) => !s.hidden).id);
  page.wait = (ms = 600) => page.waitForTimeout(ms);
  await page.goto(SITE);
  await page.wait(1200);
  return page;
}

try {
  console.log("Création de compte, déconnexion, reconnexion");
  const st = { calls: [] };
  const p = await freshPage(st);
  check((await p.screen()) === "login", "l'écran Connexion s'affiche au premier lancement");
  check(st.calls.some((c) => c.startsWith("/auth/v1/signup")), "connexion anonyme automatique au démarrage");
  await p.fill("#login-name", "Pris"); await p.fill("#login-email", "a@b.fr"); await p.click("#btn-login-go"); await p.wait();
  check(!(await p.isVisible("#login-code")), "un pseudo déjà pris est refusé avant l'envoi du code");
  await p.fill("#login-name", "Testeur"); await p.click("#btn-login-go"); await p.wait();
  check(await p.isVisible("#login-code"), "pseudo libre : le champ du code apparaît");
  await p.fill("#login-code", "123456"); await p.click("#btn-login-go"); await p.wait(1000);
  check((await p.screen()) === "menu", "code validé : arrivée au menu");
  check(await p.evaluate(() => NT.S.name === "Testeur" && NT.online.email() === "a@b.fr"), "pseudo et e-mail enregistrés");
  await p.evaluate(() => { NT.S.coins = 777; localStorage.setItem("ntplr-save-v1", JSON.stringify(NT.S)); });
  await p.reload(); await p.wait(1200);
  check((await p.screen()) === "menu", "connecté : le jeu s'ouvre directement sur le menu");
  await p.wait(800);
  const visitors = (await p.textContent("#visitors")).replace(/\s/g, "");
  check(await p.isVisible("#visitors") && visitors.includes("1234") && visitors.includes("joueurssontvenus"), "le menu affiche le nombre de joueurs venus");

  await p.click("#btn-more"); await p.click("#btn-settings"); await p.wait(400); // Réglages : dans le menu « ⋯ »
  st.offline = true;
  await p.click("#btn-logout"); await p.click("#btn-logout"); await p.wait(1500);
  check(await p.evaluate(() => NT.online.email() === "a@b.fr"), "hors ligne : la déconnexion est annulée");
  st.offline = false;
  await p.click("#btn-logout"); await p.click("#btn-logout"); await p.wait(2500);
  check((await p.screen()) === "login", "déconnexion : retour à l'écran Connexion");
  check(await p.evaluate(() => NT.S.coins === 0 && !NT.online.email()), "déconnexion : le téléphone repart de zéro");
  check(st.save && st.save.coins === 777, "la progression a été sauvegardée en ligne avant la déconnexion");

  await p.click("#btn-login-switch"); await p.fill("#login-email", "a@b.fr"); await p.click("#btn-login-go"); await p.wait();
  await p.fill("#login-code", "654321"); await p.click("#btn-login-go"); await p.wait(2500);
  check((await p.screen()) === "menu" && (await p.evaluate(() => NT.S.coins)) === 777, "« J'ai déjà un compte » : la progression revient");
  check(p.errors.length === 0, "aucune erreur JavaScript" + (p.errors.length ? " : " + p.errors.join(" | ") : ""));

  console.log("Jouer sans compte");
  const g = await freshPage({ calls: [] });
  await g.click("#btn-login-guest"); await g.wait();
  check((await g.screen()) === "menu", "« Jouer sans compte » mène au menu");
  await g.reload(); await g.wait(1200);
  check((await g.screen()) === "menu", "invité : l'écran Connexion ne revient pas avant 7 jours");
  await g.evaluate(() => localStorage.setItem("redless-guest-at", String(Date.now() - 8 * 86400000)));
  await g.reload(); await g.wait(1200);
  check((await g.screen()) === "login", "invité : l'écran Connexion revient après 7 jours");

  console.log("Sans réseau");
  const o = await freshPage({ calls: [], offline: true });
  check((await o.screen()) === "login", "hors ligne : le jeu démarre quand même");
  await o.click("#btn-login-guest"); await o.wait();
  check((await o.screen()) === "menu" && o.errors.length === 0, "hors ligne : on peut jouer sans compte, sans erreur");
} finally {
  await browser.close();
  server.close();
}
console.log(failures ? `\n${failures} échec(s)` : "\nTout est bon");
process.exit(failures ? 1 : 0);
