// Site de présentation de Redlok : démo jouable, classement mondial en direct, version du jeu.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);

  // Ouvert dans le jeu : les boutons « Jouer » referment le site au lieu d'ouvrir un 2e jeu dedans.
  if (window.top !== window) {
    document.addEventListener("click", (e) => {
      const a = e.target.closest('a[href^="jouer"]');
      if (!a) return;
      e.preventDefault();
      window.parent.postMessage("redless-close-site", "*");
    });
  }

  // Même serveur que le jeu (clé PUBLIQUE, lecture seule ici : on n'envoie rien).
  const SUPABASE = "https://redlok.taild80a87.ts.net"; // serveur Redlok sur le Raspberry Pi
  const KEY = "sb_publishable_1YNfBYNhh6CfBoAYC3yZOw_2pJc9GNH";

  async function rpc(name, params = {}) {
    const res = await fetch(`${SUPABASE}/rest/v1/rpc/${name}`, {
      method: "POST",
      headers: { apikey: KEY, "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(name + " " + res.status);
    return res.json();
  }

  // ---------- iPhone / Android : le bon bouton d'installation ----------
  const ua = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/.test(ua);
  // Autres navigateurs sur iPhone (Chrome, Firefox, appli Instagram…) : moins pratiques pour installer.
  const inSafari = isIOS && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\/|Instagram|FBAN|FBAV|Snapchat|TikTok/.test(ua);
  document.documentElement.classList.add(isIOS ? "is-ios" : isAndroid ? "is-android" : "is-desktop");
  const heroDl = $("#hero-dl");
  if (heroDl && isIOS) { heroDl.textContent = "Installer sur iPhone"; heroDl.href = "iphone.html"; }
  if (heroDl && isAndroid) { heroDl.textContent = "Télécharger pour Android"; heroDl.href = "redlok.apk"; heroDl.setAttribute("download", ""); }
  const notSafari = $("#ios-not-safari");
  if (notSafari && isIOS && !inSafari) notSafari.hidden = false;
  const copyBtn = $("#copy-game-link");
  if (copyBtn) copyBtn.addEventListener("click", async () => {
    const link = new URL("jouer/", location.href).href;
    try { await navigator.clipboard.writeText(link); copyBtn.textContent = "Lien copié ✓"; }
    catch { prompt("Copie ce lien, puis colle-le dans Safari :", link); }
  });

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const day = (iso) => new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });

  // ---------- Version du jeu (celle que les applis reçoivent) ----------
  fetch("version.json", { cache: "no-store" })
    .then((r) => r.json())
    .then((v) => v.version && document.querySelectorAll("[data-version]").forEach((el) => (el.textContent = v.version)))
    .catch(() => {});

  // ---------- Classement mondial ----------
  async function loadBoard() {
    const board = $("#board");
    if (!board) return; // page sans classement
    try {
      const [info] = await rpc("event_info").catch(() => [null]);
      if (info) {
        document.querySelectorAll("[data-players]").forEach((el) => (el.textContent = info.players));
        let text;
        if (info.season > 0) {
          text = `Saison ${info.season}` + (info.season_end ? ` : jusqu'au ${day(info.season_end)}.` : ".") + " Le classement repart de zéro chaque mois.";
        } else if (info.event_start) {
          text = `L'événement commence le ${day(info.event_start)} : le classement repartira de zéro pour la saison 1.`;
        } else {
          const left = Math.max(0, info.players_needed - info.players);
          text = `Pré-saison : l'événement mensuel démarre 7 jours après le ${info.players_needed}e joueur. Encore ${left} joueur${left > 1 ? "s" : ""} !`;
        }
        $("#season-text").textContent = text;
      }
      const rows = await rpc("get_overall", { p_season: null, p_limit: 10 });
      if (!rows.length) {
        board.innerHTML = '<p class="empty">Personne n\'a encore marqué de points. La première place est libre !</p>';
        return;
      }
      board.innerHTML = rows.map((r) => `
        <div class="row">
          <span class="rank">#${r.rank}</span>
          <span class="name">${esc(r.name)}<small>${r.games ?? r.modes} partie${(r.games ?? r.modes) > 1 ? "s" : ""}</small></span>
          <span class="total">${Number(r.total).toLocaleString("fr-FR")}</span>
        </div>`).join("");
    } catch {
      $("#season-text").textContent = "Le classement n'a pas pu être chargé. Réessaie dans un moment.";
      board.innerHTML = "";
    }
  }
  loadBoard();

  // ---------- Carrousel des captures ----------
  const shots = $("#shots");
  if (shots) {
    const figs = [...shots.querySelectorAll("figure")];
    const dots = $("#shot-dots");
    const prev = $(".arrow.prev"), next = $(".arrow.next");
    let current = 0;
    figs.forEach((f, i) => {
      const d = document.createElement("button");
      d.type = "button";
      d.setAttribute("role", "tab");
      d.setAttribute("aria-label", f.querySelector("figcaption").textContent);
      d.addEventListener("click", () => go(i));
      dots.appendChild(d);
      f.addEventListener("click", () => i !== current && go(i));
    });
    let moving = 0;
    function show(i) {
      current = i;
      figs.forEach((f, k) => f.classList.toggle("active", k === i));
      [...dots.children].forEach((d, k) => d.setAttribute("aria-selected", String(k === i)));
      prev.disabled = i === 0;
      next.disabled = i === figs.length - 1;
    }
    // Flèche, point ou clic sur une capture : elle devient la grande tout de suite, puis glisse au centre.
    function go(i) {
      i = Math.max(0, Math.min(figs.length - 1, i));
      show(i);
      moving = Date.now();
      const f = figs[i];
      shots.scrollTo({ left: f.offsetLeft - (shots.clientWidth - f.offsetWidth) / 2, behavior: "smooth" });
    }
    // Glissé au doigt : la capture la plus proche du centre devient la grande.
    function nearest() {
      const center = shots.scrollLeft + shots.clientWidth / 2;
      let best = 0, dist = Infinity;
      figs.forEach((f, i) => {
        const d = Math.abs(f.offsetLeft + f.offsetWidth / 2 - center);
        if (d < dist) { dist = d; best = i; }
      });
      return best;
    }
    prev.addEventListener("click", () => go(current - 1));
    next.addEventListener("click", () => go(current + 1));
    shots.addEventListener("scroll", () => {
      if (Date.now() - moving < 700) return; // défilement lancé par une flèche : déjà à jour
      requestAnimationFrame(() => show(nearest()));
    }, { passive: true });
    addEventListener("resize", () => go(current));
    show(0);
  }

  // ---------- Démo jouable ----------
  const grid = $("#demo-grid"), overlay = $("#demo-overlay");
  if (!grid) return; // page sans démo
  const cells = [];
  for (let i = 0; i < 12; i++) {
    const b = document.createElement("button");
    b.className = "cell";
    b.type = "button";
    b.setAttribute("aria-label", "Case " + (i + 1));
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); tap(i); });
    grid.appendChild(b);
    cells.push({ el: b, kind: null, until: 0 });
  }

  let playing = false, score = 0, lives = 3, bpm = 70, timer = 0, beats = 0, attract = 0;

  function setCell(c, kind, ms) {
    c.kind = kind;
    c.until = performance.now() + ms;
    c.el.className = "cell" + (kind ? " " + kind : "");
  }
  function flash(c, cls) {
    c.el.className = "cell " + cls;
    setTimeout(() => { if (!c.kind) c.el.className = "cell"; }, 160);
  }
  function hud() {
    $("#demo-score").textContent = score;
    $("#demo-lives").textContent = lives;
    $("#demo-bpm").textContent = Math.round(bpm);
  }

  // Un temps de musique : les cases expirées partent, de nouvelles tombent.
  function beat() {
    const now = performance.now(), period = 60000 / bpm;
    for (const c of cells) {
      if (c.kind && now >= c.until) {
        if (playing && c.kind === "green") { lives--; flash(c, "miss"); c.kind = null; }
        else setCell(c, null, 0);
      }
    }
    const free = cells.filter((c) => !c.kind);
    const count = Math.min(free.length, 1 + (Math.random() < Math.min(.6, (bpm - 70) / 120) ? 1 : 0));
    for (let k = 0; k < count; k++) {
      const c = free.splice(Math.floor(Math.random() * free.length), 1)[0];
      setCell(c, Math.random() < .3 ? "red" : "green", period * 2.2);
    }
    if (playing) {
      beats++;
      if (beats % 4 === 0) bpm = Math.min(220, bpm * 1.06); // ça accélère, comme dans le vrai jeu
      hud();
      if (lives <= 0) return end("Plus de vies");
      timer = setTimeout(beat, 60000 / bpm);
    }
  }

  function tap(i) {
    if (!playing) return;
    const c = cells[i];
    if (c.kind === "green") { score++; setCell(c, null, 0); flash(c, "hit"); hud(); }
    else if (c.kind === "red") { flash(c, "miss"); end("Touché un rouge"); }
  }

  function start() {
    clearInterval(attract);
    cells.forEach((c) => setCell(c, null, 0));
    playing = true; score = 0; lives = 3; bpm = 70; beats = 0;
    hud();
    overlay.hidden = true;
    timer = setTimeout(beat, 400);
  }

  function end(reason) {
    playing = false;
    clearTimeout(timer);
    $("#demo-title").textContent = `${reason} · score ${score}`;
    $("#demo-text").innerHTML = `Tu as tenu jusqu'à <b>${Math.round(bpm)} BPM</b>. Dans le vrai jeu, la musique accélère sans fin, et les cases mentent.`;
    $("#demo-start").textContent = "Rejouer";
    overlay.hidden = false;
    idle();
  }

  // En attendant qu'on joue : des cases s'allument toutes seules derrière le message.
  function idle() {
    clearInterval(attract);
    attract = setInterval(() => !playing && beat(), 650);
  }

  $("#demo-start").addEventListener("click", start);
  idle();
})();
