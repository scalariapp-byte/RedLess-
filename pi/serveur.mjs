// Serveur de Redlok pour le Raspberry Pi : le site, le jeu, et l'API en ligne du jeu.
// Il répond aux mêmes adresses que Supabase (/auth/v1/..., /rest/v1/rpc/...), donc js/online.js
// et site/site.js marchent sans changement. Sans dépendance : Node.js 18 ou plus.
//
// Lancement : node pi/serveur.mjs          (réglages : pi/README.md)
// Données   : DATA_DIR (par défaut /var/lib/redless) : base.json, saves/, journal.jsonl, sauvegardes/
import { createServer } from "node:http";
import { createHmac, randomBytes, randomInt, randomUUID, timingSafeEqual, createHash } from "node:crypto";
import { createReadStream, existsSync, readFileSync, statSync, mkdirSync, writeFileSync, renameSync, openSync, fsyncSync, closeSync, appendFileSync, readdirSync, unlinkSync, copyFileSync } from "node:fs";
import { join, normalize, sep, extname, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createMailer } from "./courriel.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

// ---------- réglages ----------
export function settings(env = process.env) {
  return {
    port: +(env.PORT || 8787),
    host: env.HOST || "127.0.0.1",
    root: env.REDLESS_ROOT || join(HERE, ".."),
    data: env.DATA_DIR || "/var/lib/redless",
    admin: (env.ADMIN_EMAIL || "scalariapp@gmail.com").trim().toLowerCase(),
    notify: (env.NOTIFY_EMAIL || "scalariapp@gmail.com").trim(),
    // APK signé avec la clé personnelle : le seul qui s'installe par-dessus l'appli des joueurs.
    apkUrl: env.APK_URL || "https://github.com/anonyme5575/redless/releases/download/latest/redlok.apk",
    playersNeeded: +(env.PLAYERS_NEEDED || 30),
    delayMs: (+(env.EVENT_DELAY_DAYS ?? 7)) * 86400e3,
    // Tailscale Funnel transmet l'adresse du joueur dans X-Forwarded-For.
    trustProxy: env.TRUST_PROXY !== "0",
    mailer: createMailer(env),
    log: env.QUIET ? () => {} : (...a) => console.log(new Date().toISOString(), ...a),
  };
}

const MODES = ["classic", "chrono", "sudden", "feint", "expansion", "rhythm", "mirror", "chaos"];
const NAME_RE = /^[A-Za-z0-9À-ÖØ-öø-ÿ _.-]{2,14}$/;
const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,255}\.[^\s@]{2,}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ACCESS_TTL = 3600;            // s
const REFRESH_GRACE = 60e3;         // ms : un même jeton de rafraîchissement peut resservir pendant 1 min (appels en parallèle)
const CODE_TTL = 15 * 60e3;         // ms
const MAX_SAVE = 200000;            // octets
const iso = (t) => (t == null ? null : new Date(t).toISOString());

// ---------- erreurs au format Supabase ----------
class ApiError extends Error {
  constructor(status, body) { super(body.message || body.msg || "erreur"); this.status = status; this.body = body; }
}
// raise exception dans une fonction Postgres -> PostgREST répond 400 { code: "P0001", message }
const fail = (message) => { throw new ApiError(400, { code: "P0001", message, details: null, hint: null }); };
// Erreur du service d'authentification (GoTrue)
const authFail = (status, error_code, msg) => { throw new ApiError(status, { code: status, error_code, msg }); };

// ---------- base de données : un fichier JSON en mémoire, écrit de façon atomique ----------
class Store {
  constructor(dir, log) {
    this.dir = dir; this.log = log;
    mkdirSync(join(dir, "saves"), { recursive: true });
    mkdirSync(join(dir, "sauvegardes"), { recursive: true });
    this.file = join(dir, "base.json");
    const empty = { version: 1, secret: randomBytes(32).toString("hex"), users: {}, refresh: {}, players: {}, totals: {}, installs: {}, state: {} };
    this.db = existsSync(this.file) ? { ...empty, ...JSON.parse(readFileSync(this.file, "utf8")) } : empty;
    this.byEmail = new Map(); this.byName = new Map();
    for (const [id, u] of Object.entries(this.db.users)) if (u.email) this.byEmail.set(u.email, id);
    for (const [id, p] of Object.entries(this.db.players)) this.byName.set(p.name.toLowerCase(), id);
    this.timer = null;
    if (!existsSync(this.file)) this.flush();
  }
  save() { if (!this.timer) this.timer = setTimeout(() => this.flush(), 500); }
  flush() {
    clearTimeout(this.timer); this.timer = null;
    atomicWrite(this.file, JSON.stringify(this.db));
  }
  journal(entry) {
    try { appendFileSync(join(this.dir, "journal.jsonl"), JSON.stringify({ t: iso(Date.now()), ...entry }) + "\n"); } catch (e) { this.log("journal :", e.message); }
  }
  // Une copie par jour, 14 jours gardés.
  backup() {
    const dir = join(this.dir, "sauvegardes"), day = iso(Date.now()).slice(0, 10);
    this.flush();
    copyFileSync(this.file, join(dir, `base-${day}.json`));
    const old = readdirSync(dir).filter((f) => /^base-\d{4}-\d\d-\d\d\.json$/.test(f)).sort().slice(0, -14);
    old.forEach((f) => unlinkSync(join(dir, f)));
  }
  savePath(uid) { return join(this.dir, "saves", uid + ".json"); }
}
function atomicWrite(file, text) {
  const tmp = file + ".tmp";
  writeFileSync(tmp, text);
  const fd = openSync(tmp, "r"); fsyncSync(fd); closeSync(fd);
  renameSync(tmp, file);
}

// ---------- jetons (JWT HS256, comme Supabase) ----------
const b64url = (b) => Buffer.from(b).toString("base64url");
function signJwt(secret, payload) {
  const head = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" })), body = b64url(JSON.stringify(payload));
  return `${head}.${body}.${createHmac("sha256", secret).update(`${head}.${body}`).digest("base64url")}`;
}
function verifyJwt(secret, token) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) return null;
  const want = createHmac("sha256", secret).update(`${parts[0]}.${parts[1]}`).digest();
  const got = Buffer.from(parts[2], "base64url");
  if (got.length !== want.length || !timingSafeEqual(got, want)) return null;
  try {
    const p = JSON.parse(Buffer.from(parts[1], "base64url").toString());
    return p.exp > Date.now() / 1000 ? p : null;
  } catch { return null; }
}
const sha = (s) => createHash("sha256").update(s).digest("hex");

// ---------- limites de débit (par adresse IP ou par adresse e-mail) ----------
class Limits {
  constructor() { this.hits = new Map(); setInterval(() => this.sweep(), 10 * 60e3).unref(); }
  // true si l'action est permise (au plus max fois par fenêtre de ms)
  take(key, max, ms) {
    const now = Date.now(), list = (this.hits.get(key) || []).filter((t) => t > now - ms);
    if (list.length >= max) { this.hits.set(key, list); return false; }
    list.push(now); this.hits.set(key, list); return true;
  }
  // Limite par adresse IP. Sans adresse connue (aucun X-Forwarded-For derrière Funnel), tous les joueurs
  // auraient la même : seules les limites globales s'appliquent alors.
  ip(prefix, ip, max, ms) { return ip ? this.take(prefix + ip, max, ms) : true; }
  last(key) { const l = this.hits.get(key); return l && l.length ? l[l.length - 1] : 0; }
  sweep() { const now = Date.now(); for (const [k, l] of this.hits) if (!l.length || l[l.length - 1] < now - 3600e3 * 2) this.hits.delete(k); }
}

// ---------- le service ----------
export function createApp(cfg = settings()) {
  const store = new Store(cfg.data, cfg.log);
  const db = store.db;
  const limits = new Limits();
  const codes = new Map(); // email -> { hash, purpose, uid, exp, tries } (en mémoire : un redémarrage annule les codes en cours)

  // ----- comptes -----
  function newSession(uid) {
    const u = db.users[uid], now = Math.floor(Date.now() / 1000);
    const access_token = signJwt(db.secret, {
      sub: uid, aud: "authenticated", role: "authenticated", is_anonymous: !u.email, email: u.email || "",
      iat: now, exp: now + ACCESS_TTL,
    });
    const refresh_token = randomBytes(24).toString("base64url");
    db.refresh[sha(refresh_token)] = { uid, at: Date.now() };
    store.save();
    return { access_token, token_type: "bearer", expires_in: ACCESS_TTL, expires_at: now + ACCESS_TTL, refresh_token, user: userJson(uid) };
  }
  function userJson(uid) {
    const u = db.users[uid];
    return { id: uid, aud: "authenticated", role: "authenticated", email: u.email || "", is_anonymous: !u.email, created_at: iso(u.created), user_metadata: {}, app_metadata: { provider: u.email ? "email" : "anonymous" } };
  }
  function bearer(req) {
    const m = /^Bearer\s+(.+)$/i.exec(req.headers.authorization || "");
    if (!m) return null;
    const p = verifyJwt(db.secret, m[1]);
    return p && db.users[p.sub] ? p.sub : null;
  }
  const hasBearer = (req) => /^Bearer\s+\S/i.test(req.headers.authorization || "");
  function requireUser(req) {
    const uid = bearer(req);
    if (!uid) authFail(401, "bad_jwt", "invalid JWT: unable to parse or verify signature, token is expired or the user no longer exists");
    return uid;
  }

  async function sendCode(email, purpose, uid, ip) {
    if (!cfg.mailer.configured) authFail(500, "unexpected_failure", "Error sending email: e-mail not configured on the server");
    const since = Date.now() - limits.last("mail:" + email);
    if (since < 60e3) authFail(429, "over_email_send_rate_limit", `For security purposes, you can only request this after ${Math.ceil((60e3 - since) / 1000)} seconds.`);
    if (!limits.take("mail:" + email, 5, 3600e3) || !limits.ip("mailip:", ip, 10, 3600e3) || !limits.take("mail:*", 200, 3600e3)) {
      authFail(429, "over_email_send_rate_limit", "Email rate limit exceeded");
    }
    const code = String(randomInt(0, 1e6)).padStart(6, "0");
    codes.set(email, { hash: sha(code), purpose, uid, exp: Date.now() + CODE_TTL, tries: 0 });
    try {
      await cfg.mailer.send({
        to: email,
        subject: `Redlok : ton code ${code}`,
        text: `Ton code Redlok : ${code}\n\nÉcris-le dans le jeu. Il est valable 15 minutes.\n\nTu n'as rien demandé ? Ignore cet e-mail : sans le code, personne ne peut utiliser ton adresse.\n\n— Redlok`,
      });
    } catch (e) {
      codes.delete(email);
      cfg.log("e-mail :", e.message);
      authFail(500, "unexpected_failure", "Error sending email");
    }
  }
  function checkCode(email, purpose, token) {
    const c = codes.get(email);
    if (!c || c.purpose !== purpose || c.exp < Date.now()) { codes.delete(email); authFail(403, "otp_expired", "Token has expired or is invalid"); }
    if (++c.tries > 5) { codes.delete(email); authFail(403, "otp_expired", "Token has expired or is invalid"); }
    const a = Buffer.from(sha(String(token || "").trim())), b = Buffer.from(c.hash);
    if (!timingSafeEqual(a, b)) authFail(403, "otp_expired", "Token has expired or is invalid");
    codes.delete(email);
    return c;
  }
  const cleanEmail = (s) => String(s || "").trim().toLowerCase();

  const auth = {
    // Compte anonyme : un par appareil, créé au premier lancement en ligne.
    "POST /signup": async (req, body, ip) => {
      if (body.email || body.password || body.phone) authFail(422, "email_provider_disabled", "Email signups are disabled");
      if (!limits.ip("signup:", ip, 60, 3600e3) || !limits.take("signup:*", 1000, 3600e3)) authFail(429, "over_request_rate_limit", "Request rate limit reached");
      const uid = randomUUID();
      db.users[uid] = { created: Date.now(), email: null };
      store.journal({ e: "compte", uid });
      return newSession(uid);
    },
    "POST /token": async (req, body, ip, query) => {
      if (query.get("grant_type") !== "refresh_token") authFail(400, "validation_failed", "unsupported_grant_type");
      if (!limits.ip("refresh:", ip, 300, 3600e3)) authFail(429, "over_request_rate_limit", "Request rate limit reached");
      const key = sha(String(body.refresh_token || "")), r = db.refresh[key];
      const bad = () => authFail(400, "refresh_token_not_found", "Invalid Refresh Token: Refresh Token Not Found");
      if (!r || !db.users[r.uid]) return bad();
      if (r.replacedAt) {
        // Deux demandes en même temps avec le même jeton : la seconde reçoit aussi une session.
        if (Date.now() - r.replacedAt > REFRESH_GRACE) { delete db.refresh[key]; store.save(); return bad(); }
        return newSession(r.uid);
      }
      r.replacedAt = Date.now();
      return newSession(r.uid);
    },
    "GET /user": async (req) => ({ ...userJson(requireUser(req)) }),
    // Étape 1 de « Protéger » : un code part à l'adresse, pour la lier au compte de ce téléphone.
    "PUT /user": async (req, body, ip) => {
      const uid = requireUser(req), email = cleanEmail(body.email);
      if (!email) authFail(422, "validation_failed", "Only an email address can be updated");
      if (!EMAIL_RE.test(email)) authFail(400, "email_address_invalid", `Email address "${email}" is invalid`);
      const owner = store.byEmail.get(email);
      if (owner && owner !== uid) authFail(422, "email_exists", "A user with this email address has already been registered");
      if (owner === uid) return userJson(uid);
      await sendCode(email, "email_change", uid, ip);
      return userJson(uid);
    },
    // Étape 1 de « Retrouver » : un code part si un compte utilise cette adresse.
    "POST /otp": async (req, body, ip) => {
      const email = cleanEmail(body.email);
      if (!EMAIL_RE.test(email)) authFail(400, "email_address_invalid", `Email address "${email}" is invalid`);
      const uid = store.byEmail.get(email);
      if (!uid) {
        if (!limits.ip("otpmiss:", ip, 20, 3600e3)) authFail(429, "over_email_send_rate_limit", "Email rate limit exceeded");
        authFail(422, "otp_disabled", "Signups not allowed for otp");
      }
      await sendCode(email, "email", uid, ip);
      return {};
    },
    "POST /verify": async (req, body) => {
      const email = cleanEmail(body.email);
      if (body.type === "email_change") {
        const uid = requireUser(req), c = checkCode(email, "email_change", body.token);
        if (c.uid !== uid) authFail(403, "otp_expired", "Token has expired or is invalid");
        const owner = store.byEmail.get(email);
        if (owner && owner !== uid) authFail(422, "email_exists", "A user with this email address has already been registered");
        const u = db.users[uid];
        if (u.email) store.byEmail.delete(u.email);
        u.email = email; store.byEmail.set(email, uid);
        store.journal({ e: "protege", uid });
        return newSession(uid);
      }
      if (body.type === "email" || body.type === "magiclink") {
        const c = checkCode(email, "email", body.token);
        if (!db.users[c.uid] || db.users[c.uid].email !== email) authFail(403, "otp_expired", "Token has expired or is invalid");
        store.journal({ e: "retrouve", uid: c.uid });
        return newSession(c.uid);
      }
      authFail(400, "validation_failed", "Verify requires a verification type");
    },
    "POST /logout": async () => null,
    "GET /health": async () => ({ name: "Redlok", description: "Serveur du jeu sur le Raspberry Pi" }),
  };

  // ----- saisons -----
  function addMonths(t, n) {
    const d = new Date(t), day = d.getUTCDate();
    d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + n);
    const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate();
    d.setUTCDate(Math.min(day, last));
    return d.getTime();
  }
  function eventInfo() {
    const now = Date.now(), t = db.state.threshold_at || null, st = t == null ? null : t + cfg.delayMs;
    const base = { players: Object.keys(db.players).length, players_needed: cfg.playersNeeded, threshold_at: iso(t), event_start: iso(st), server_now: iso(now) };
    if (st == null || now < st) return { ...base, season: 0, season_start: null, season_end: iso(st) };
    let n = 0;
    while (addMonths(st, n + 1) <= now) n++;
    return { ...base, season: n + 1, season_start: iso(addMonths(st, n)), season_end: iso(addMonths(st, n + 1)) };
  }
  const currentSeason = () => eventInfo().season;
  // Classement d'une saison, sans les joueurs bannis : du plus haut total au plus bas, à égalité le premier arrivé.
  function ranking(season) {
    const rows = Object.entries(db.totals[season] || {})
      .filter(([uid]) => db.players[uid] && !db.players[uid].banned)
      .sort(([, a], [, b]) => b.total - a.total || a.last - b.last);
    let rank = 0, prev = null;
    return rows.map(([uid, r], i) => {
      if (!prev || prev.total !== r.total || prev.last !== r.last) rank = i + 1;
      prev = r;
      return { uid, rank, ...r };
    });
  }

  // ----- pseudos -----
  function checkName(raw) {
    const name = String(raw ?? "").trim();
    if (!NAME_RE.test(name)) fail("pseudo invalide (2 à 14 lettres, chiffres, espace, . _ -)");
    return name;
  }
  function nameTaken(name, uid) { const o = store.byName.get(name.toLowerCase()); return o && o !== uid; }
  function setPlayerName(uid, name) {
    const p = db.players[uid];
    if (p) store.byName.delete(p.name.toLowerCase());
    if (p) p.name = name; else db.players[uid] = { name, created: Date.now(), last_submit: null, banned: false };
    store.byName.set(name.toLowerCase(), uid);
  }
  const isAdmin = (uid) => !!(uid && db.users[uid] && db.users[uid].email && db.users[uid].email === cfg.admin);
  const int = (v) => (Number.isInteger(v) ? v : typeof v === "string" && /^-?\d+$/.test(v) ? +v : NaN);

  // ----- fonctions (POST /rest/v1/rpc/<nom>) : mêmes noms, paramètres et réponses que dans Supabase -----
  // needAuth : le joueur doit être connecté (jeton valable) ; sinon le jeton est facultatif.
  const rpc = {
    event_info: { run: () => [eventInfo()] },

    visitor_count: { run: () => Object.keys(db.users).length },

    name_available: {
      run: (uid, p) => !nameTaken(String(p.p_name ?? "").trim(), uid),
    },

    // Les points des parties classées, additionnés par le téléphone (plusieurs parties possibles d'un coup).
    add_points: {
      needAuth: true,
      run: (uid, p) => {
        const points = int(p.p_points), ms = int(p.p_duration_ms), games = int(p.p_games);
        if (!(games >= 1 && games <= 100000)) fail("nombre de parties invalide");
        if (!(points >= 0 && points <= 1e9)) fail("score invalide");
        if (!(ms >= 3000 * games && ms <= 7200000 * games)) fail("durée invalide");
        // Même un joueur parfait ne dépasse pas ~40 points par seconde.
        if (points > (ms / 1000) * 40 + 60 * games) fail("score invraisemblable");
        const clean = String(p.p_name ?? "").trim() || null;
        let me = db.players[uid];
        if (!me && !clean) fail("pseudo requis");
        if (clean && (!me || clean !== me.name)) {
          checkName(clean);
          if (nameTaken(clean, uid)) fail("pseudo déjà pris");
        }
        if (me && me.banned) fail("tu es banni du classement mondial");
        if (me && me.last_submit && Date.now() - me.last_submit < 5000) fail("trop rapide");
        // Tout est vérifié : on enregistre.
        if (clean && (!me || clean !== me.name)) setPlayerName(uid, clean);
        me = db.players[uid];
        me.last_submit = Date.now();
        if (!db.state.threshold_at && Object.keys(db.players).length >= cfg.playersNeeded) db.state.threshold_at = Date.now();
        const s = currentSeason();
        const row = ((db.totals[s] ||= {})[uid] ||= { total: 0, games: 0, ms: 0, last: 0 });
        row.total += points; row.games += games; row.ms += ms; row.last = Date.now();
        store.save();
        store.journal({ e: "points", uid, s, points, games, ms });
        const board = ranking(s), mine = board.find((r) => r.uid === uid);
        return [{ season: s, total: row.total, rank: mine ? mine.rank : board.length + 1, players: board.length }];
      },
    },

    get_overall: {
      run: (uid, p) => {
        const season = p.p_season == null ? currentSeason() : int(p.p_season);
        const limit = Math.min(Math.max(int(p.p_limit) || 100, 1), 200);
        return ranking(season)
          .filter((r) => r.rank <= limit || r.uid === uid)
          .map((r) => ({ rank: r.rank, name: db.players[r.uid].name, total: r.total, games: r.games, is_me: r.uid === uid }));
      },
    },

    set_name: {
      needAuth: true,
      run: (uid, p) => {
        const name = checkName(p.p_name);
        if (!db.players[uid]) return null; // pas encore classé : le pseudo sera enregistré avec les premiers points
        if (nameTaken(name, uid)) fail("pseudo déjà pris");
        setPlayerName(uid, name); store.save();
        return null;
      },
    },

    am_i_admin: { run: (uid) => isAdmin(uid) },

    ban_player: {
      needAuth: true,
      run: (uid, p) => {
        if (!isAdmin(uid)) fail("réservé à l'administrateur");
        const target = store.byName.get(String(p.p_name ?? "").trim().toLowerCase());
        if (!target) fail("joueur introuvable");
        db.players[target].banned = p.p_ban !== false;
        store.save();
        store.journal({ e: p.p_ban !== false ? "banni" : "debanni", uid: target, par: uid });
        return null;
      },
    },

    banned_players: {
      needAuth: true,
      run: (uid) => {
        if (!isAdmin(uid)) fail("réservé à l'administrateur");
        const s = db.totals[currentSeason()] || {};
        return Object.entries(db.players).filter(([, pl]) => pl.banned)
          .map(([id, pl]) => ({ name: pl.name, total: (s[id] && s[id].total) || 0 }))
          .sort((a, b) => b.total - a.total);
      },
    },

    // Sauvegarde en ligne : seulement pour un compte protégé par une adresse e-mail.
    save_progress: {
      needAuth: true,
      run: (uid, p) => {
        if (!db.users[uid].email) fail("Protège d'abord ton compte avec ton adresse e-mail");
        const data = p.p_data;
        const text = data && typeof data === "object" && !Array.isArray(data) ? JSON.stringify(data) : null;
        if (!text || Buffer.byteLength(text) > MAX_SAVE) fail("Sauvegarde invalide");
        const t = iso(Date.now());
        atomicWrite(store.savePath(uid), JSON.stringify({ data, updated_at: t }));
        return t;
      },
    },
    load_progress: {
      needAuth: true,
      run: (uid) => {
        const f = store.savePath(uid);
        return existsSync(f) ? [JSON.parse(readFileSync(f, "utf8"))] : [];
      },
    },

    // Premier lancement de l'appli installée : un e-mail au propriétaire (au plus 30 par heure).
    register_install: {
      run: (uid, p, ip) => {
        if (!UUID_RE.test(String(p.p_device || "")) || !["android", "ios", "web-app"].includes(p.p_platform)) fail("installation invalide");
        if (!limits.ip("install:", ip, 30, 3600e3)) fail("trop d'installations");
        const dev = String(p.p_device).toLowerCase();
        if (db.installs[dev]) return false;
        db.installs[dev] = { platform: p.p_platform, version: String(p.p_version ?? "").slice(0, 20), created: Date.now() };
        store.save();
        store.journal({ e: "installation", platform: p.p_platform, version: db.installs[dev].version });
        const total = Object.keys(db.installs).length;
        if (cfg.mailer.configured && cfg.notify && limits.take("installmail", 30, 3600e3)) {
          const where = { android: "Android (APK)", ios: "iPhone / iPad (appli web)", "web-app": "Appli web installée" }[p.p_platform];
          cfg.mailer.send({
            to: cfg.notify,
            subject: `Redlok : nouvelle installation (${total} au total)`,
            text: `Une personne vient d'installer Redlok.\n\nPlateforme : ${where}\nVersion : ${db.installs[dev].version || "?"}\nDate : ${new Date().toLocaleString("fr-FR", { timeZone: "Europe/Paris" })}\nInstallations au total : ${total}\n\n— Serveur Redlok (Raspberry Pi)`,
          }).catch((e) => cfg.log("e-mail d'installation :", e.message));
        }
        return true;
      },
    },
  };

  // ---------- fichiers du site et du jeu ----------
  const TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".webmanifest": "application/manifest+json",
    ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
  };
  // Le jeu (dossier racine du dépôt) est servi sous /jouer/ ; seuls ces fichiers et dossiers en sortent.
  const GAME = new Set(["index.html", "manifest.webmanifest", "sw.js", "PRIVACY.md", "COPYRIGHT.md", "css", "js", "fonts", "assets", "audio"]);
  let versionCache = { mtime: 0, body: "{}" };
  function versionJson() {
    const f = join(cfg.root, "js", "game.js");
    try {
      const m = statSync(f).mtimeMs;
      if (m !== versionCache.mtime) {
        const v = (/const VERSION = "([^"]+)"/.exec(readFileSync(f, "utf8")) || [])[1];
        versionCache = { mtime: m, body: JSON.stringify({ version: v || null }) + "\n" };
      }
    } catch {}
    return versionCache.body;
  }
  // -> { file } | { redirect } | { special } | null
  function route(pathname) {
    if (pathname === "/jouer") return { redirect: "/jouer/" };
    const game = pathname.startsWith("/jouer/");
    let rel = game ? pathname.slice(7) : pathname.slice(1);
    if (rel === "version.json") return { special: "version" };
    // redless.apk : ancien nom (liens partagés avant la 3.24), même APK.
    if (/^(dist\/)?red(lok|less)\.apk$/.test(rel) && (!game || !rel.startsWith("dist/"))) return { redirect: cfg.apkUrl };
    if (rel === "" || rel.endsWith("/")) rel += "index.html";
    const parts = rel.split("/");
    if (parts.some((s) => !s || s.startsWith(".") || s.includes("\\") || s.includes("\0"))) return null;
    if (game && !GAME.has(parts[0])) return null;
    const base = game ? cfg.root : join(cfg.root, "site");
    const file = normalize(join(base, ...parts));
    if (!file.startsWith(base + sep)) return null;
    return { file };
  }
  function serveFile(req, res, file, headers) {
    let st;
    try { st = statSync(file); } catch { st = null; }
    if (!st || !st.isFile()) return false;
    const ext = extname(file).toLowerCase();
    const etag = `W/"${st.size.toString(16)}-${Math.floor(st.mtimeMs).toString(16)}"`;
    const longCache = /^\.(woff2|mp3|ogg|wav|jpg|jpeg|png|webp)$/.test(ext);
    const h = {
      ...headers,
      "Content-Type": TYPES[ext] || "application/octet-stream",
      "Cache-Control": longCache ? "public, max-age=86400" : "no-cache",
      ETag: etag, "Last-Modified": new Date(st.mtimeMs).toUTCString(), "Accept-Ranges": "bytes",
    };
    if (req.headers["if-none-match"] === etag) { res.writeHead(304, h).end(); return true; }
    // Safari lit la musique par morceaux (en-tête Range).
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");
    let start = 0, end = st.size - 1, status = 200;
    if (m && (m[1] || m[2])) {
      if (m[1]) { start = +m[1]; end = m[2] ? Math.min(+m[2], st.size - 1) : st.size - 1; }
      else { start = Math.max(0, st.size - +m[2]); }
      if (start > end || start >= st.size) { res.writeHead(416, { ...h, "Content-Range": `bytes */${st.size}` }).end(); return true; }
      status = 206; h["Content-Range"] = `bytes ${start}-${end}/${st.size}`;
    }
    h["Content-Length"] = String(end - start + 1);
    res.writeHead(status, h);
    if (req.method === "HEAD") { res.end(); return true; }
    createReadStream(file, { start, end }).on("error", () => res.destroy()).pipe(res);
    return true;
  }

  // ---------- HTTP ----------
  const CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "apikey, authorization, content-type, x-client-info, prefer, accept-profile, content-profile",
    "Access-Control-Max-Age": "86400",
  };
  const BASE = { ...CORS, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin" };
  function json(res, status, data) {
    const body = data === undefined ? "" : JSON.stringify(data);
    res.writeHead(status, { ...BASE, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Content-Length": Buffer.byteLength(body) }).end(body);
  }
  function clientIp(req) {
    const xff = req.headers["x-forwarded-for"];
    const local = /^(::ffff:)?127\.|^::1$/.test(req.socket.remoteAddress || "");
    if (cfg.trustProxy && local && xff) return String(xff).split(",")[0].trim();
    return local ? null : req.socket.remoteAddress || null;
  }
  function readBody(req, max = 300000) {
    return new Promise((ok, ko) => {
      let size = 0; const chunks = [];
      req.on("data", (c) => {
        size += c.length;
        if (size > max) { ko(new ApiError(413, { code: "PGRST413", message: "Payload too large" })); req.destroy(); return; }
        chunks.push(c);
      });
      req.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        if (!text.trim()) return ok({});
        try { const v = JSON.parse(text); ok(v && typeof v === "object" ? v : {}); }
        catch { ko(new ApiError(400, { code: "PGRST102", message: "Empty or invalid json", details: null, hint: null })); }
      });
      req.on("error", ko);
    });
  }

  async function handle(req, res) {
    const url = new URL(req.url, "http://redless");
    let path;
    try { path = decodeURIComponent(url.pathname); } catch { return json(res, 400, { message: "bad url" }); }
    const ip = clientIp(req);
    if (req.method === "OPTIONS") { res.writeHead(204, BASE).end(); return; }

    // ----- API -----
    if (path.startsWith("/auth/v1/") || path.startsWith("/rest/v1/")) {
      try {
        if (!limits.ip("api:", ip, 600, 60e3)) throw new ApiError(429, { code: "429", message: "Trop de requêtes, réessaie dans une minute" });
        if (path.startsWith("/auth/v1/")) {
          const fn = auth[`${req.method} ${path.slice(8)}`];
          if (!fn) throw new ApiError(404, { code: 404, error_code: "not_found", msg: "Not found" });
          const body = req.method === "GET" ? {} : await readBody(req);
          return json(res, 200, await fn(req, body, ip, url.searchParams));
        }
        const m = /^\/rest\/v1\/rpc\/([a-z_]+)$/.exec(path);
        const fn = m && Object.hasOwn(rpc, m[1]) ? rpc[m[1]] : null;
        if (!fn) throw new ApiError(404, { code: "PGRST202", message: `Could not find the function public.${m ? m[1] : "?"} in the schema cache`, details: null, hint: null });
        if (req.method !== "POST" && req.method !== "GET") throw new ApiError(405, { code: "PGRST117", message: "Unsupported HTTP method" });
        const params = req.method === "GET" ? Object.fromEntries(url.searchParams) : await readBody(req);
        let uid = bearer(req);
        if (fn.needAuth && !uid) throw new ApiError(401, hasBearer(req) ? { code: "PGRST301", message: "JWT expired", details: null, hint: null } : { code: "28000", message: "non connecté", details: null, hint: null });
        const out = fn.run(uid, params, ip);
        return json(res, 200, out === undefined ? null : out);
      } catch (e) {
        if (e instanceof ApiError) return json(res, e.status, e.body);
        cfg.log("erreur :", req.method, path, e.stack || e);
        return json(res, 500, { code: "XX000", message: "erreur du serveur" });
      }
    }

    // ----- santé (pour vérifier que le serveur tourne) -----
    if (path === "/sante") return json(res, 200, { ok: true, version: JSON.parse(versionJson()).version, comptes: Object.keys(db.users).length, joueurs: Object.keys(db.players).length, email: cfg.mailer.how });

    // ----- fichiers -----
    if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405, BASE).end(); return; }
    const r = route(path);
    if (r && r.redirect) { res.writeHead(302, { ...BASE, Location: r.redirect, "Cache-Control": "no-cache" }).end(); return; }
    if (r && r.special === "version") {
      const body = versionJson();
      res.writeHead(200, { ...BASE, "Content-Type": "application/json", "Cache-Control": "no-store", "Content-Length": Buffer.byteLength(body) }).end(req.method === "HEAD" ? undefined : body);
      return;
    }
    const headers = { ...BASE };
    if (r && r.file && /[/\\]sw\.js$/.test(r.file)) headers["Service-Worker-Allowed"] = r.file.startsWith(join(cfg.root, "site")) ? "/" : "/jouer/";
    if (r && r.file && serveFile(req, res, r.file, headers)) return;
    res.writeHead(404, { ...BASE, "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache" })
      .end(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Redlok</title><p style="font-family:sans-serif;padding:2em">Page introuvable. <a href="/">Site de Redlok</a> · <a href="/jouer/">Jouer</a></p>`);
  }

  const server = createServer((req, res) => {
    handle(req, res).catch((e) => { cfg.log("erreur :", e.stack || e); if (!res.headersSent) json(res, 500, { message: "erreur du serveur" }); else res.destroy(); });
  });
  server.headersTimeout = 20000; server.requestTimeout = 30000;

  // Ménage : jetons de rafraîchissement remplacés depuis plus d'une minute, codes expirés.
  const sweep = setInterval(() => {
    const now = Date.now(); let changed = false;
    for (const [k, r] of Object.entries(db.refresh)) if (r.replacedAt && now - r.replacedAt > REFRESH_GRACE) { delete db.refresh[k]; changed = true; }
    for (const [k, c] of codes) if (c.exp < now) codes.delete(k);
    if (changed) store.save();
  }, 5 * 60e3);
  sweep.unref();
  const daily = setInterval(() => { try { store.backup(); } catch (e) { cfg.log("sauvegarde :", e.message); } }, 24 * 3600e3);
  daily.unref();
  try { store.backup(); } catch (e) { cfg.log("sauvegarde :", e.message); }

  function close() {
    clearInterval(sweep); clearInterval(daily);
    store.flush();
    return new Promise((ok) => { server.close(() => ok()); server.closeAllConnections?.(); });
  }
  return { server, store, close, cfg };
}

// ---------- lancement direct ----------
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const cfg = settings();
  const app = createApp(cfg);
  app.server.listen(cfg.port, cfg.host, () => {
    cfg.log(`Redlok : http://${cfg.host}:${cfg.port}/  (jeu : ${cfg.root}, données : ${cfg.data}, e-mail : ${cfg.mailer.how})`);
  });
  const stop = async (sig) => { cfg.log(`${sig} : arrêt propre`); await app.close(); process.exit(0); };
  process.on("SIGTERM", () => stop("SIGTERM"));
  process.on("SIGINT", () => stop("SIGINT"));
}
