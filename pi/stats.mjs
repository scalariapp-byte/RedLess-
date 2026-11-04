// Statistiques de fréquentation, lues dans les données du serveur (rien n'est envoyé nulle part).
// SUR le Pi : node pi/stats.mjs      (autre dossier de données : DATA_DIR=... node pi/stats.mjs)
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const DIR = process.env.DATA_DIR || "/var/lib/redless";
const db = JSON.parse(readFileSync(join(DIR, "base.json"), "utf8"));
const events = existsSync(join(DIR, "journal.jsonl"))
  ? readFileSync(join(DIR, "journal.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean)
  : [];
const users = Object.values(db.users), installs = Object.values(db.installs);
const since = (ms) => events.filter((e) => e.e === "points" && Date.parse(e.t) > Date.now() - ms);
const actifs = (ms) => new Set(since(ms).map((e) => e.uid)).size;

console.log("Vue d'ensemble");
console.table({
  installations: installs.length,
  "comptes (appareils)": users.length,
  "joueurs classés": Object.keys(db.players).length,
  "comptes avec e-mail": users.filter((u) => u.email).length,
  "sauvegardes en ligne": readdirSync(join(DIR, "saves")).length,
  "parties classées": events.filter((e) => e.e === "points").reduce((n, e) => n + e.games, 0),
  "actifs 24 h": actifs(864e5),
  "actifs 7 j": actifs(7 * 864e5),
  bannis: Object.values(db.players).filter((p) => p.banned).length,
});

console.log("14 derniers jours");
const days = {};
for (let i = 13; i >= 0; i--) days[new Date(Date.now() - i * 864e5).toISOString().slice(0, 10)] = { installations: 0, "nouveaux comptes": 0, "joueurs actifs": new Set(), parties: 0 };
for (const e of events) {
  const d = days[e.t.slice(0, 10)];
  if (!d) continue;
  if (e.e === "installation") d.installations++;
  if (e.e === "compte") d["nouveaux comptes"]++;
  if (e.e === "points") { d["joueurs actifs"].add(e.uid); d.parties += e.games; }
}
for (const d of Object.values(days)) d["joueurs actifs"] = d["joueurs actifs"].size;
console.table(days);

const plateformes = {};
for (const i of installs) plateformes[i.platform] = (plateformes[i.platform] || 0) + 1;
console.log("Installations par plateforme");
console.table(plateformes);
