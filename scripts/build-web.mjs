// Vercel build: copies the static game into public/ and writes the Supabase settings there.
import { cpSync, rmSync, mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const OUT = "public";
const FILES = ["index.html", "manifest.webmanifest", "sw.js", "PRIVACY.md", "COPYRIGHT.md", "css", "js", "fonts", "assets", "audio", "dist/redlok.apk"];

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT);
for (const f of FILES) if (existsSync(f)) cpSync(f, `${OUT}/${f}`, { recursive: true });
execFileSync(process.execPath, ["scripts/online-config.mjs", `${OUT}/js/online-config.js`], { stdio: "inherit" });

// version.json: read by every copy of the game to offer « Mettre à jour » (taken from VERSION in game.js).
const version = (readFileSync("js/game.js", "utf8").match(/const VERSION = "([^"]+)"/) || [])[1];
if (version) writeFileSync(`${OUT}/version.json`, JSON.stringify({ version }) + "\n");
console.log(`Site prêt dans public/ (version ${version || "?"})`);
