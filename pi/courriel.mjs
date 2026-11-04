// Envoi d'e-mails pour le serveur Redlok : codes de connexion, alertes d'installation.
// Sans dépendance. Trois façons d'envoyer, choisies par les variables d'environnement :
//   SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS  (Gmail : smtp.gmail.com, 465, mot de passe d'application)
//   RESEND_API_KEY                                 (Resend : sans domaine vérifié, n'envoie qu'à l'adresse du compte)
//   MAIL_OUTBOX=dossier                            (tests : chaque e-mail est écrit dans un fichier)
import net from "node:net";
import tls from "node:tls";
import os from "node:os";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

const b64 = (s) => Buffer.from(s, "utf8").toString("base64");
const wrap = (s) => s.replace(/.{1,76}/g, "$&\r\n");
const encodeHeader = (s) => (/^[\x20-\x7e]*$/.test(s) ? s : `=?UTF-8?B?${b64(s)}?=`);
// « Redlok <a@b.fr> » -> a@b.fr
const bareAddress = (s) => ((/<([^>]+)>/.exec(s) || [])[1] || s).trim();

function buildMessage({ from, to, subject, text }) {
  const domain = bareAddress(from).split("@")[1] || "redless.local";
  const name = /^(.*?)\s*</.exec(from);
  const fromHeader = name && name[1] ? `${encodeHeader(name[1].replace(/"/g, ""))} <${bareAddress(from)}>` : bareAddress(from);
  return [
    `From: ${fromHeader}`,
    `To: ${to}`,
    `Subject: ${encodeHeader(subject)}`,
    `Date: ${new Date().toUTCString().replace("GMT", "+0000")}`,
    `Message-ID: <${randomUUID()}@${domain}>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: base64",
    "",
    wrap(b64(text)),
  ].join("\r\n");
}

// Petit client SMTP : TLS direct (port 465), STARTTLS (587), ou texte clair vers la machine elle-même (tests).
function smtpSend(cfg, mail) {
  return new Promise((resolve, reject) => {
    const port = +cfg.port || 465;
    const implicit = port === 465;
    const plainLocal = cfg.secure === "0" && /^(127\.0\.0\.1|localhost|::1)$/.test(cfg.host);
    let sock = implicit
      ? tls.connect({ host: cfg.host, port, servername: cfg.host })
      : net.connect({ host: cfg.host, port });
    let buf = "", waiting = null, done = false;
    const timer = setTimeout(() => fail(new Error("SMTP : délai dépassé")), 20000);
    function fail(e) { if (done) return; done = true; clearTimeout(timer); sock.destroy(); reject(e); }
    function onData(d) {
      buf += d.toString("utf8");
      if (!waiting) return;
      // A reply is complete when a line has the form « 250 ... » (code then space).
      const lines = buf.split("\r\n");
      for (let i = 0; i < lines.length - 1; i++) {
        if (/^\d{3} /.test(lines[i])) {
          buf = lines.slice(i + 1).join("\r\n");
          const w = waiting; waiting = null;
          w(lines.slice(0, i + 1));
          return;
        }
      }
    }
    const read = () => new Promise((ok) => { waiting = ok; onData(""); });
    async function cmd(line, expect) {
      if (line !== null) sock.write(line + "\r\n");
      const reply = await read();
      const code = +reply[reply.length - 1].slice(0, 3);
      if (!expect.includes(code)) throw new Error(`SMTP : ${reply.join(" | ").replace(/AUTH PLAIN \S+/, "AUTH PLAIN ***")}`);
      return reply;
    }
    const attach = (s) => { s.on("data", onData); s.on("error", fail); };
    attach(sock);
    (async () => {
      const host = os.hostname() || "redless";
      await cmd(null, [220]);
      let ehlo = await cmd(`EHLO ${host}`, [250]);
      if (!implicit && !plainLocal) {
        if (!ehlo.some((l) => /STARTTLS/i.test(l))) throw new Error("SMTP : le serveur ne propose pas STARTTLS");
        await cmd("STARTTLS", [220]);
        sock.removeAllListeners("data");
        sock = tls.connect({ socket: sock, servername: cfg.host });
        attach(sock);
        await new Promise((ok, ko) => { sock.once("secureConnect", ok); sock.once("error", ko); });
        ehlo = await cmd(`EHLO ${host}`, [250]);
      }
      if (cfg.user) await cmd(`AUTH PLAIN ${b64(`\0${cfg.user}\0${cfg.pass || ""}`)}`, [235]);
      await cmd(`MAIL FROM:<${bareAddress(mail.from)}>`, [250]);
      await cmd(`RCPT TO:<${bareAddress(mail.to)}>`, [250, 251]);
      await cmd("DATA", [354]);
      // Base64 body: no line starts with a dot, no dot-stuffing needed.
      await cmd(buildMessage(mail) + "\r\n.", [250]);
      sock.write("QUIT\r\n");
      done = true; clearTimeout(timer); sock.end(); resolve();
    })().catch(fail);
  });
}

export function createMailer(env = process.env) {
  const from = (env.MAIL_FROM || env.SMTP_USER || "").trim();
  if (env.MAIL_OUTBOX) {
    let n = 0;
    return {
      configured: true, how: "dossier " + env.MAIL_OUTBOX,
      async send(mail) {
        await mkdir(env.MAIL_OUTBOX, { recursive: true });
        await writeFile(join(env.MAIL_OUTBOX, `${Date.now()}-${++n}.json`), JSON.stringify({ from: from || "redless@localhost", ...mail }));
      },
    };
  }
  if (env.SMTP_HOST) {
    const cfg = { host: env.SMTP_HOST, port: env.SMTP_PORT, user: env.SMTP_USER, pass: env.SMTP_PASS, secure: env.SMTP_SECURE };
    return {
      configured: true, how: `SMTP ${cfg.host}:${cfg.port || 465}`,
      send: (mail) => smtpSend(cfg, { from: from || "redless@localhost", ...mail }),
    };
  }
  if (env.RESEND_API_KEY) {
    return {
      configured: true, how: "Resend",
      async send({ to, subject, text }) {
        const res = await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: { Authorization: "Bearer " + env.RESEND_API_KEY, "Content-Type": "application/json" },
          body: JSON.stringify({ from: from || "Redlok <onboarding@resend.dev>", to: [to], subject, text }),
        });
        if (!res.ok) throw new Error(`Resend : ${res.status} ${await res.text()}`);
      },
    };
  }
  return { configured: false, how: "aucun", async send() { throw new Error("e-mail non configuré"); } };
}
