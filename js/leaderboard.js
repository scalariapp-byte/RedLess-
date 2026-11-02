// Online leaderboard of the player's total score, on Supabase (js/leaderboard-config.js, supabase/leaderboard.sql).
// The phone computes the total itself (sum of the scores of all its games). It reads its own row
// on the board and sends its total only if the local one is higher (or the pseudo changed).
// The phone is recognised by a random secret drawn once; the server keeps only its hash.
(() => {
  "use strict";
  const SECRET = "redless-board-secret", LAST = "redless-board-last";
  const cfg = window.REDLESS_BOARD || {};
  const URL_ = (cfg.url || "").trim().replace(/\/+$/, "");
  const KEY = (cfg.key || "").trim();
  const enabled = !!(URL_ && KEY);

  const read = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };

  function uuid() {
    try { return crypto.randomUUID(); } catch {
      return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => { const r = (Math.random() * 16) | 0; return (c === "x" ? r : (r & 3) | 8).toString(16); });
    }
  }
  function secret() {
    let s = read(SECRET, null);
    if (!s) { s = uuid(); write(SECRET, s); }
    return s;
  }

  async function rpc(name, params) {
    const ctrl = new AbortController(), t = setTimeout(() => ctrl.abort(), 9000);
    try {
      const res = await fetch(URL_ + "/rest/v1/rpc/" + name, {
        method: "POST", signal: ctrl.signal,
        // Legacy anon key (a JWT) also goes in Authorization; a sb_publishable_ key only in apikey.
        headers: { apikey: KEY, "Content-Type": "application/json", ...(KEY.split(".").length === 3 ? { Authorization: "Bearer " + KEY } : {}) },
        body: JSON.stringify(params),
      });
      const text = await res.text();
      const data = text ? JSON.parse(text) : null;
      if (!res.ok) { const e = new Error((data && (data.message || data.error)) || "HTTP " + res.status); e.status = res.status; throw e; }
      return data;
    } catch (e) {
      if (e.name === "AbortError" || e instanceof TypeError) { const err = new Error("hors ligne"); err.offline = true; throw err; }
      throw e;
    } finally { clearTimeout(t); }
  }
  const one = (rows) => (Array.isArray(rows) ? rows[0] : rows) || null;
  const toRow = (r) => r && { name: r.name, total: Number(r.total), rank: Number(r.rank), players: Number(r.players) };

  // Own row on the board, or null if this phone never sent anything.
  const me = async () => toRow(one(await rpc("board_me", { p_secret: secret() })));

  // Reads the board, sends the local total only if it is higher (or the pseudo changed).
  // Returns {name, total, rank, players, sent} or null (nothing to send yet / disabled).
  let running = null;
  async function sync(total, name) {
    total = Math.max(0, Math.floor(Number(total) || 0));
    name = String(name || "").trim();
    if (!enabled || !name || total <= 0) return null;
    if (running) await running.catch(() => {});
    const run = (async () => {
      const online = await me();
      if (online && online.total >= total && online.name === name) { write(LAST, online); return { ...online, sent: false }; }
      const r = toRow(one(await rpc("board_submit", { p_secret: secret(), p_name: name, p_total: total })));
      write(LAST, r);
      return { ...r, sent: true };
    })();
    running = run;
    try { return await run; } finally { if (running === run) running = null; }
  }

  // Top of the board (is_me marks this phone's row, added at the end when it is lower).
  async function top(limit = 100) {
    const rows = (await rpc("board_top", { p_secret: secret(), p_limit: limit })) || [];
    return rows.map((r) => ({ rank: Number(r.rank), name: r.name, total: Number(r.total), is_me: !!r.is_me }));
  }

  NT.board = { enabled, sync, top, me, last: () => read(LAST, null) };
})();
