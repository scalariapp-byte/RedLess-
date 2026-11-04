// Visual layer: chamfered holographic frames, rain, particle bursts, and the shareable score card.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const app = $("#app");
  const cssVar = (n) => getComputedStyle(app).getPropertyValue(n).trim();
  const dpr = () => Math.min(window.devicePixelRatio || 1, 2);

  // ---------- frames: SVG outlines sized to their element ([data-frame]) ----------
  const SVGNS = "http://www.w3.org/2000/svg";
  function framePaths(type, w, h) {
    if (type === "hex") {
      const c = Math.min(22, w * 0.09);
      return { outline: `M${c} 0H${w - c}L${w} ${h / 2}L${w - c} ${h}H${c}L0 ${h / 2}Z`,
               ticks: `M${c + 8} 0H${c + 40}M${w - c - 40} ${h}H${w - c - 8}` };
    }
    const c = type === "board" ? 18 : 9;
    const outline = `M${c} 0H${w - c}L${w} ${c}V${h - c}L${w - c} ${h}H${c}L0 ${h - c}V${c}Z`;
    if (type !== "board") return { outline, ticks: `M${c + 4} 0H${c + 22}` };
    const m = h / 2;
    return { outline,
      ticks: `M0 ${c + 6}V${c + 40}M${w} ${h - c - 40}V${h - c - 6}M${c + 6} ${h}H${c + 50}M${w - c - 50} 0H${w - c - 6}`,
      extra: `M-7 ${m - 26}L-14 ${m}L-7 ${m + 26}M${w + 7} ${m - 26}L${w + 14} ${m}L${w + 7} ${m + 26}` };
  }
  function drawFrame(el) {
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    let svg = el.querySelector(":scope > .frame-svg");
    if (!svg) {
      svg = document.createElementNS(SVGNS, "svg"); svg.setAttribute("class", "frame-svg"); svg.setAttribute("aria-hidden", "true");
      svg.innerHTML = '<path class="fill"/><path class="line" pathLength="1"/><path class="tick"/><path class="line extra"/>';
      el.prepend(svg);
    }
    const p = framePaths(el.dataset.frame, w, h);
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    const [fill, line, tick, extra] = svg.children;
    fill.setAttribute("d", el.dataset.frame === "board" ? "" : p.outline);
    line.setAttribute("d", p.outline); tick.setAttribute("d", p.ticks); extra.setAttribute("d", p.extra || "");
  }
  const observer = "ResizeObserver" in window ? new ResizeObserver((es) => es.forEach((e) => drawFrame(e.target))) : null;
  function initFrames(root = document) {
    root.querySelectorAll("[data-frame]").forEach((el) => {
      if (el.dataset.framed) return;
      el.dataset.framed = "1";
      observer ? observer.observe(el) : drawFrame(el);
    });
  }
  function redrawFrames(root) { root.querySelectorAll("[data-frame]").forEach(drawFrame); }

  // ---------- canvases ----------
  const fxCv = $("#fx"), fxCtx = fxCv.getContext("2d");
  const rainCv = $("#rain"), rainCtx = rainCv.getContext("2d");
  let drops = [], rainColor = "#36c9ff", parts = [], dirty = false;
  // Background animation (shop « Fonds »): pluie, neige, etoiles, bulles, grille, matrice, aucun.
  let bgStyle = "pluie", gridOffset = 0;
  const BG_COUNT = { pluie: 4, neige: 5, etoiles: 3, bulles: 14, matrice: 14, grille: 0, aucun: 0 }; // px per item
  const GLYPHS = "01アイウエオカキクケコサシスセソタチツテト";
  function sizeCanvases() {
    const r = app.getBoundingClientRect(), d = dpr();
    for (const [cv, cx] of [[fxCv, fxCtx], [rainCv, rainCtx]]) {
      cv.width = r.width * d; cv.height = r.height * d; cx.setTransform(d, 0, 0, d, 0, 0);
    }
    const per = BG_COUNT[bgStyle] || 0;
    drops = per ? Array.from({ length: Math.round(r.width / per) }, (_, i) => newDrop(r.width, r.height, true, i)) : [];
  }
  window.addEventListener("resize", sizeCanvases);
  function setBgStyle(s) { if (s === bgStyle) return; bgStyle = BG_COUNT[s] === undefined ? "pluie" : s; sizeCanvases(); }
  function newDrop(w, h, anywhere, i = 0) {
    const z = Math.random();
    switch (bgStyle) {
      case "neige": return { x: Math.random() * w, y: anywhere ? Math.random() * h : -10, r: 0.8 + z * 2, v: 0.4 + z * 1.1, a: 0.15 + z * 0.45, ph: Math.random() * 6 };
      case "etoiles": return { x: Math.random() * w, y: Math.random() * h, r: 0.5 + z * 1.4, a: 0.15 + z * 0.55, ph: Math.random() * 6 };
      case "bulles": return { x: Math.random() * w, y: anywhere ? Math.random() * h : h + 20, r: 2 + z * 7, v: 0.3 + z * 0.9, a: 0.08 + z * 0.22, ph: Math.random() * 6 };
      case "matrice": return { x: i * 14 + 4, y: anywhere ? Math.random() * h : -20 - Math.random() * h, v: 1.5 + z * 3.5, a: 0.06 + z * 0.22, len: 5 + Math.floor(z * 10), ch: [] };
      default: return { x: Math.random() * (w + 60), y: anywhere ? Math.random() * h : -20, len: 8 + z * 22, v: 7 + z * 11, a: 0.05 + z * 0.22 };
    }
  }
  function drawRain(dt, speed) {
    const w = rainCv.width / dpr(), h = rainCv.height / dpr(), k = speed * dt / 16.7, c = rainCtx;
    c.clearRect(0, 0, w, h);
    c.strokeStyle = c.fillStyle = rainColor; c.lineWidth = 1;
    if (bgStyle === "grille") {
      gridOffset = (gridOffset + k * 0.6) % 32;
      c.globalAlpha = 0.07; c.beginPath();
      for (let x = 0; x <= w; x += 32) { c.moveTo(x, 0); c.lineTo(x, h); }
      for (let y = gridOffset - 32; y <= h; y += 32) { c.moveTo(0, y); c.lineTo(w, y); }
      c.stroke(); c.globalAlpha = 1; return;
    }
    if (bgStyle === "matrice") c.font = "12px monospace";
    for (const d of drops) {
      switch (bgStyle) {
        case "neige":
          d.y += d.v * k; d.ph += 0.02 * k; d.x += Math.sin(d.ph) * 0.3 * k;
          if (d.y > h + 10) Object.assign(d, newDrop(w, h, false));
          c.globalAlpha = d.a; c.beginPath(); c.arc(d.x, d.y, d.r, 0, Math.PI * 2); c.fill(); break;
        case "etoiles":
          d.ph += 0.03 * k;
          c.globalAlpha = d.a * (0.55 + 0.45 * Math.sin(d.ph)); c.fillRect(d.x, d.y, d.r, d.r); break;
        case "bulles":
          d.y -= d.v * k; d.ph += 0.02 * k; d.x += Math.sin(d.ph) * 0.25 * k;
          if (d.y < -20) Object.assign(d, newDrop(w, h, false));
          c.globalAlpha = d.a; c.beginPath(); c.arc(d.x, d.y, d.r, 0, Math.PI * 2); c.stroke(); break;
        case "matrice":
          d.y += d.v * k;
          if (d.y - d.len * 14 > h) Object.assign(d, newDrop(w, h, false, Math.round((d.x - 4) / 14)));
          for (let i = 0; i < d.len; i++) {
            if (!d.ch[i] || Math.random() < 0.02) d.ch[i] = GLYPHS[(Math.random() * GLYPHS.length) | 0];
            c.globalAlpha = d.a * (1 - i / d.len) * (i === 0 ? 2.5 : 1);
            c.fillText(d.ch[i], d.x, d.y - i * 14);
          }
          break;
        default:
          d.y += d.v * k; d.x -= d.v * k * 0.12;
          if (d.y > h + 20) Object.assign(d, newDrop(w, h, false));
          c.globalAlpha = d.a;
          c.beginPath(); c.moveTo(d.x, d.y); c.lineTo(d.x + d.len * 0.12, d.y - d.len); c.stroke();
      }
    }
    c.globalAlpha = 1;
  }

  // ---------- particles ----------
  function burst(x, y, color, kind, big = false) {
    const n = big ? 26 : 14;
    parts.push({ type: "hexring", x, y, r: 8, life: 1, color });
    if (kind === "onde") { parts.push({ type: "ring", x, y, r: 6, life: 1, color }); parts.push({ type: "ring", x, y, r: 2, life: 1.25, color }); return; }
    if (kind === "eclair") {
      for (let i = 0; i < 6; i++) parts.push({ type: "bolt", x, y, a: (i / 6) * Math.PI * 2 + Math.random() * 0.5, len: 30 + Math.random() * 40, life: 1, color });
      return;
    }
    if (kind === "spirale") {
      for (let i = 0; i < (big ? 24 : 16); i++) parts.push({ type: "spiral", cx: x, cy: y, a: (i / 8) * Math.PI, r: 2 + i * 1.2, va: 0.16, vr: 1.6 + Math.random(), life: 1, size: 2.5, color: i % 2 ? color : cssVar("--holo") });
      return;
    }
    if (kind === "flammes") {
      const fire = ["#ffe066", "#ffa03a", "#ff4d2e"];
      for (let i = 0; i < (big ? 26 : 16); i++) parts.push({ type: "flame", x: x + (Math.random() - 0.5) * 22, y, vx: (Math.random() - 0.5) * 1.2, vy: -1.5 - Math.random() * 3, life: 1, size: 4 + Math.random() * 5, color: fire[i % 3] });
      return;
    }
    if (kind === "glitch") {
      parts.push({ type: "slice", x: x - 40, y: y - 3, w: 80, h: 6, life: 0.8, color: cssVar("--red") });
      for (let i = 0; i < (big ? 14 : 9); i++) parts.push({ type: "slice", x: x + (Math.random() - 0.5) * 70, y: y + (Math.random() - 0.5) * 50, w: 10 + Math.random() * 50, h: 2 + Math.random() * 6, life: 0.6 + Math.random() * 0.4, color: i % 3 ? color : cssVar("--holo") });
      return;
    }
    if (kind === "bulles") {
      for (let i = 0; i < (big ? 16 : 10); i++) parts.push({ type: "bubble", x: x + (Math.random() - 0.5) * 30, y, vx: (Math.random() - 0.5) * 0.8, vy: -0.8 - Math.random() * 2, r: 3 + Math.random() * 6, life: 1, color: i % 3 ? color : cssVar("--holo") });
      return;
    }
    if (kind === "neige") {
      for (let i = 0; i < (big ? 22 : 14); i++) { const a = Math.random() * Math.PI * 2, sp = 1 + Math.random() * 3; parts.push({ type: "flake", x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 1, r: 1.5 + Math.random() * 2.5, life: 1, color: "#ffffff" }); }
      return;
    }
    if (kind === "coeurs") {
      for (let i = 0; i < (big ? 12 : 7); i++) parts.push({ type: "heart", x: x + (Math.random() - 0.5) * 24, y, vx: (Math.random() - 0.5) * 2, vy: -1.5 - Math.random() * 2.5, size: 5 + Math.random() * 5, life: 1, color: i % 2 ? "#ff5c8a" : color });
      return;
    }
    if (kind === "anneaux") {
      for (let i = 0; i < 3; i++) parts.push({ type: "ring", x, y, r: 3, life: 1, delay: i * 5, color: i === 1 ? cssVar("--holo") : color });
      return;
    }
    if (kind === "laser") {
      parts.push({ type: "beam", x, y, dir: "h", life: 1, color }); parts.push({ type: "beam", x, y, dir: "v", life: 1, color: cssVar("--holo") });
      parts.push({ type: "hexring", x, y, r: 4, life: 1, color });
      return;
    }
    if (kind === "artifice") {
      const cols = [cssVar("--gold"), color, cssVar("--holo"), "#ff5c8a", "#ffffff"];
      for (let i = 0; i < (big ? 40 : 26); i++) { const a = (i / (big ? 40 : 26)) * Math.PI * 2, sp = 3 + Math.random() * 3; parts.push({ type: "spark", x, y, px: x, py: y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, color: cols[i % cols.length] }); }
      return;
    }
    if (kind === "nova") {
      parts.push({ type: "flash", x, y, r: 6, life: 1, color });
      parts.push({ type: "ring", x, y, r: 4, life: 1.3, color: cssVar("--gold") });
    }
    const palette = kind === "confetti" ? [cssVar("--green"), cssVar("--gold"), cssVar("--holo"), cssVar("--red")]
      : kind === "etoiles" ? [cssVar("--gold"), color, "#ffffff"] : kind === "nova" ? [cssVar("--gold"), color] : [color];
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, sp = 2 + Math.random() * (big ? 6 : 4);
      parts.push({
        type: kind === "pixels" ? "px" : kind === "confetti" ? "conf" : kind === "etoiles" ? "star" : "shard",
        x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - (kind === "confetti" ? 2 : 0),
        rot: Math.random() * 6, life: 1, size: kind === "pixels" ? 5 + Math.random() * 4 : 2 + Math.random() * 3,
        color: palette[i % palette.length],
      });
    }
  }
  function hexPath(c, x, y, r) {
    c.beginPath();
    for (let i = 0; i < 6; i++) { const a = Math.PI / 6 + (i * Math.PI) / 3; c[i ? "lineTo" : "moveTo"](x + Math.cos(a) * r, y + Math.sin(a) * r); }
    c.closePath();
  }
  function drawFx(dt) {
    if (!parts.length && !dirty) return;
    dirty = parts.length > 0;
    fxCtx.clearRect(0, 0, fxCv.width, fxCv.height);
    const k = dt / 16.7;
    parts = parts.filter((p) => (p.life -= 0.03 * k) > 0);
    for (const p of parts) {
      fxCtx.globalAlpha = Math.min(1, p.life);
      fxCtx.fillStyle = fxCtx.strokeStyle = p.color;
      if (p.delay > 0) { p.delay -= k; p.life += 0.03 * k; continue; } // staggered rings wait their turn
      if (p.type === "bubble") {
        p.x += p.vx * k; p.y += p.vy * k; fxCtx.lineWidth = 1.5;
        fxCtx.beginPath(); fxCtx.arc(p.x, p.y, p.r * (1.2 - p.life * 0.2), 0, Math.PI * 2); fxCtx.stroke();
      } else if (p.type === "flake") {
        p.x += p.vx * k; p.y += p.vy * k; p.vx *= 0.96; p.vy = p.vy * 0.96 + 0.05 * k;
        fxCtx.beginPath(); fxCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2); fxCtx.fill();
      } else if (p.type === "heart") {
        p.x += p.vx * k; p.y += p.vy * k; p.vy *= 0.98;
        const s = p.size; fxCtx.beginPath();
        fxCtx.moveTo(p.x, p.y + s * 0.9);
        fxCtx.bezierCurveTo(p.x - s * 1.4, p.y - s * 0.2, p.x - s * 0.6, p.y - s * 1.3, p.x, p.y - s * 0.4);
        fxCtx.bezierCurveTo(p.x + s * 0.6, p.y - s * 1.3, p.x + s * 1.4, p.y - s * 0.2, p.x, p.y + s * 0.9);
        fxCtx.fill();
      } else if (p.type === "beam") {
        const w = fxCv.width / dpr(), h = fxCv.height / dpr(); fxCtx.lineWidth = 3 * p.life;
        fxCtx.beginPath();
        if (p.dir === "h") { fxCtx.moveTo(0, p.y); fxCtx.lineTo(w, p.y); } else { fxCtx.moveTo(p.x, 0); fxCtx.lineTo(p.x, h); }
        fxCtx.stroke(); p.life -= 0.02 * k;
      } else if (p.type === "spark") {
        p.px = p.x; p.py = p.y; p.x += p.vx * k; p.y += p.vy * k; p.vx *= 0.96; p.vy = p.vy * 0.96 + 0.08 * k;
        fxCtx.lineWidth = 2; fxCtx.beginPath(); fxCtx.moveTo(p.px - p.vx * 2, p.py - p.vy * 2); fxCtx.lineTo(p.x, p.y); fxCtx.stroke();
      } else if (p.type === "ring" || p.type === "hexring") {
        p.r += (p.type === "ring" ? 3.2 : 2.4) * k; fxCtx.lineWidth = 3 * p.life;
        if (p.type === "ring") { fxCtx.beginPath(); fxCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2); } else hexPath(fxCtx, p.x, p.y, p.r);
        fxCtx.stroke();
      } else if (p.type === "bolt") {
        const d = p.len * (1.2 - p.life); fxCtx.lineWidth = 3;
        fxCtx.beginPath(); fxCtx.moveTo(p.x + Math.cos(p.a) * d * 0.4, p.y + Math.sin(p.a) * d * 0.4);
        fxCtx.lineTo(p.x + Math.cos(p.a + 0.3) * d * 0.7, p.y + Math.sin(p.a + 0.3) * d * 0.7);
        fxCtx.lineTo(p.x + Math.cos(p.a) * d, p.y + Math.sin(p.a) * d); fxCtx.stroke();
      } else if (p.type === "spiral") {
        p.a += p.va * k; p.r += p.vr * k;
        fxCtx.beginPath(); fxCtx.arc(p.cx + Math.cos(p.a) * p.r, p.cy + Math.sin(p.a) * p.r, p.size, 0, Math.PI * 2); fxCtx.fill();
      } else if (p.type === "flame") {
        p.x += p.vx * k; p.y += p.vy * k; p.vy *= 0.985;
        fxCtx.beginPath(); fxCtx.arc(p.x, p.y, Math.max(0.5, p.size * p.life), 0, Math.PI * 2); fxCtx.fill();
      } else if (p.type === "slice") {
        p.life -= 0.02 * k; // glitch lines vanish faster
        fxCtx.fillRect(p.x + (Math.random() - 0.5) * 8, p.y, p.w, p.h);
      } else if (p.type === "flash") {
        p.r += 5 * k; fxCtx.globalAlpha = Math.max(0, p.life * 0.45);
        fxCtx.beginPath(); fxCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2); fxCtx.fill();
      } else {
        p.x += p.vx * k; p.y += p.vy * k; p.vy += (p.type === "conf" ? 0.12 : 0.16) * k; p.vx *= 0.98; p.rot += 0.2 * k;
        if (p.type === "px") fxCtx.fillRect(Math.round(p.x / 4) * 4, Math.round(p.y / 4) * 4, p.size, p.size);
        else if (p.type === "conf") { fxCtx.save(); fxCtx.translate(p.x, p.y); fxCtx.rotate(p.rot); fxCtx.fillRect(-4, -2, 8, 4); fxCtx.restore(); }
        else if (p.type === "star") {
          fxCtx.save(); fxCtx.translate(p.x, p.y); fxCtx.rotate(p.rot); fxCtx.beginPath();
          for (let i = 0; i < 10; i++) { const r = i % 2 ? p.size : p.size * 2.4, a = (i * Math.PI) / 5; fxCtx[i ? "lineTo" : "moveTo"](Math.cos(a) * r, Math.sin(a) * r); }
          fxCtx.closePath(); fxCtx.fill(); fxCtx.restore();
        }
        else {
          fxCtx.save(); fxCtx.translate(p.x, p.y); fxCtx.rotate(p.rot);
          fxCtx.beginPath(); fxCtx.moveTo(0, -p.size * 2); fxCtx.lineTo(p.size, p.size); fxCtx.lineTo(-p.size, p.size); fxCtx.fill(); fxCtx.restore();
        }
      }
    }
    fxCtx.globalAlpha = 1;
  }

  // ---------- share card (1080×1350 PNG) ----------
  let cityImg = null;
  function loadCity() {
    if (cityImg) return Promise.resolve(cityImg);
    return new Promise((res) => {
      const im = new Image();
      im.onload = () => { cityImg = im; res(im); };
      im.onerror = () => res(null);
      im.src = "assets/city.jpg";
    });
  }
  function chamfer(c, x, y, w, h, k) {
    c.beginPath();
    c.moveTo(x + k, y); c.lineTo(x + w - k, y); c.lineTo(x + w, y + k); c.lineTo(x + w, y + h - k);
    c.lineTo(x + w - k, y + h); c.lineTo(x + k, y + h); c.lineTo(x, y + h - k); c.lineTo(x, y + k); c.closePath();
  }
  // d: { score, mode, bpm, level, combo, rank, date, code }
  async function shareCard(d) {
    const W = 1080, H = 1350, cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const c = cv.getContext("2d");
    try { await Promise.all([document.fonts.load("800 100px Oxanium"), document.fonts.load("700 40px 'Chakra Petch'")]); } catch {}
    const col = { bg: cssVar("--bg"), holo: cssVar("--holo"), green: cssVar("--green"), red: cssVar("--red"), ink: cssVar("--ink"), muted: cssVar("--muted"), gold: cssVar("--gold") };
    c.fillStyle = col.bg; c.fillRect(0, 0, W, H);
    const img = await loadCity();
    if (img) {
      c.globalAlpha = 0.45;
      const s = Math.max(W / img.width, H / img.height);
      c.drawImage(img, (W - img.width * s) / 2, (H - img.height * s) / 2, img.width * s, img.height * s);
      c.globalAlpha = 1;
    }
    const g = c.createRadialGradient(W / 2, H / 2, H * 0.2, W / 2, H / 2, H * 0.75);
    g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,.7)");
    c.fillStyle = g; c.fillRect(0, 0, W, H);
    c.fillStyle = "rgba(255,255,255,.035)";
    for (let y = 0; y < H; y += 4) c.fillRect(0, y, W, 1);

    c.shadowColor = col.holo; c.shadowBlur = 18;
    c.strokeStyle = col.holo; c.lineWidth = 4;
    chamfer(c, 60, 60, W - 120, H - 120, 46); c.stroke();
    c.shadowBlur = 0;

    c.textAlign = "center"; c.fillStyle = col.ink;
    // "REDLOK" with "RED" in red, centred as one word.
    c.font = "800 150px Oxanium, sans-serif";
    const wRed = c.measureText("RED").width, wLess = c.measureText("LOK").width, xt = (W - wRed - wLess) / 2;
    c.textAlign = "left";
    c.fillStyle = col.red; c.shadowColor = col.red; c.shadowBlur = 26; c.fillText("RED", xt, 290);
    c.fillStyle = col.ink; c.shadowColor = col.holo; c.shadowBlur = 18; c.fillText("LOK", xt + wRed, 290);
    c.shadowBlur = 0; c.textAlign = "center";
    c.fillStyle = col.muted; c.font = "600 34px 'Chakra Petch', sans-serif";
    c.fillText("TOUCHE LE VERT · JAMAIS LE ROUGE", W / 2, 360);

    c.fillStyle = col.holo; c.font = "700 40px 'Chakra Petch', sans-serif";
    c.fillText(d.mode.toUpperCase() + (d.code ? ` · CODE ${d.code}` : ""), W / 2, 450);
    c.fillStyle = col.ink; c.shadowColor = col.holo; c.shadowBlur = 30;
    c.font = "800 300px Oxanium, sans-serif"; c.fillText(String(d.score), W / 2, 760);
    c.shadowBlur = 0;
    c.fillStyle = col.muted; c.font = "600 40px 'Chakra Petch', sans-serif";
    c.fillText(`${d.bpm} BPM  ·  NIVEAU ${d.level}  ·  COMBO ${d.combo}`, W / 2, 850);

    // a row of tiles as signature
    const tiles = [col.green, col.green, col.red, col.green, col.gold, col.green];
    const tw = 110, gap = 22, x0 = (W - (tiles.length * tw + (tiles.length - 1) * gap)) / 2;
    tiles.forEach((t, i) => { c.fillStyle = t; chamfer(c, x0 + i * (tw + gap), 920, tw, tw, 16); c.fill(); });

    c.fillStyle = col.gold; c.font = "700 44px 'Chakra Petch', sans-serif";
    c.fillText(`RANG : ${d.rank.toUpperCase()}`, W / 2, 1140);
    c.fillStyle = col.muted; c.font = "600 34px 'Chakra Petch', sans-serif";
    c.fillText(d.date, W / 2, 1200);
    return cv;
  }

  NT.fx = {
    initFrames, redrawFrames, sizeCanvases, drawRain, burst, drawFx, shareCard,
    setRainColor(c) { rainColor = c; }, setBgStyle, cssVar,
  };
})();
