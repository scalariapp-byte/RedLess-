#!/usr/bin/env bash
# Installe le serveur Redless sur le Raspberry Pi : site, jeu, classement, comptes, sauvegardes.
# Depuis le dossier du dépôt, SUR le Pi :  sudo bash pi/installer.sh
# Relançable sans risque : garde les données (/var/lib/redless) et les réglages (/etc/redless/redless.env).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lance avec sudo : sudo bash pi/installer.sh"; exit 1; }
U="${SUDO_USER:?Lance avec sudo depuis ton compte (pas directement en root)}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8787
DATA=/var/lib/redless
CONF=/etc/redless/redless.env
ADRESSE=redless.taild80a87.ts.net
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

echo "== 1. Node.js"
command -v node >/dev/null || { apt-get update -q && apt-get install -yq nodejs git curl; }
NODE_MAJ=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJ" -ge 18 ] || { echo "Node.js $NODE_MAJ trop ancien (18 ou plus requis). Mets à jour Raspberry Pi OS (Bookworm)."; exit 1; }
echo "Node.js $(node -v)"

echo "== 2. Données et réglages"
install -d -o "$U" -g "$U" -m 700 "$DATA"
install -d -o root -g "$U" -m 750 /etc/redless
if [ ! -f "$CONF" ]; then
  cat > "$CONF" <<'EOF'
# Réglages du serveur Redless. Après une modification : sudo systemctl restart redless
PORT=8787
DATA_DIR=/var/lib/redless
# Compte administrateur du jeu (peut bannir) et adresse qui reçoit les alertes d'installation.
ADMIN_EMAIL=scalariapp@gmail.com
NOTIFY_EMAIL=scalariapp@gmail.com

# ----- E-mails (codes de connexion des comptes protégés) -----
# Sans ces lignes, le jeu marche, mais « Protéger mon compte » et « Retrouver » répondent
# « Le serveur n'a pas pu envoyer l'e-mail ».
# Gmail : compte Google -> Sécurité -> Validation en deux étapes (activée) -> Mots de passe des applications.
#SMTP_HOST=smtp.gmail.com
#SMTP_PORT=465
#SMTP_USER=scalariapp@gmail.com
#SMTP_PASS=xxxxxxxxxxxxxxxx
#MAIL_FROM=Redless <scalariapp@gmail.com>
EOF
fi
chown root:"$U" "$CONF"; chmod 640 "$CONF"

echo "== 3. Service redless"
cat > /etc/systemd/system/redless.service <<EOF
[Unit]
Description=Redless (site, jeu, classement en ligne)
After=network-online.target
Wants=network-online.target

[Service]
User=$U
WorkingDirectory=$DIR
EnvironmentFile=$CONF
Environment=REDLESS_ROOT=$DIR
ExecStart=$(command -v node) $DIR/pi/serveur.mjs
Restart=always
RestartSec=5
MemoryMax=400M
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes

[Install]
WantedBy=multi-user.target
EOF

echo "== 4. Mise à jour automatique depuis GitHub (toutes les 10 minutes)"
cat > /etc/systemd/system/redless-maj.service <<EOF
[Unit]
Description=Redless : récupère la dernière version sur GitHub
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash $DIR/pi/mettre-a-jour.sh $U
EOF
cat > /etc/systemd/system/redless-maj.timer <<'EOF'
[Unit]
Description=Redless : mise à jour toutes les 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now redless.service redless-maj.timer
systemctl restart redless.service

echo "== 5. Vérification locale"
ok=""
for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/sante" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || { echo "Le serveur ne répond pas. Journal :"; journalctl -u redless -n 30 --no-pager; exit 1; }
curl -fsS "http://127.0.0.1:$PORT/sante"; echo

echo "== 6. Accès public (Tailscale Funnel)"
if ! command -v tailscale >/dev/null; then
  echo "Tailscale absent : installe-le (curl -fsSL https://tailscale.com/install.sh | sh), connecte-le (sudo tailscale up), puis relance ce script."
  exit 0
fi
NOM=$(tailscale status --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{console.log(JSON.parse(s).Self.DNSName.replace(/\.$/,""))}catch{console.log("")}})')
if [ "$NOM" = "$ADRESSE" ]; then
  # Le Pi s'appelle déjà « redless » : Funnel du Tailscale principal.
  ACTUEL=$(tailscale funnel status 2>/dev/null || true)
  if echo "$ACTUEL" | grep -q "127.0.0.1:$PORT"; then
    echo "Funnel déjà réglé vers le serveur Redless."
  else
    if echo "$ACTUEL" | grep -q "proxy\|path\|http"; then
      echo "Funnel sert déjà autre chose :"; echo "$ACTUEL"
      read -r -p "Le remplacer par le serveur Redless ? [o/N] " r
      [ "$r" = o ] || [ "$r" = O ] || { echo "Funnel laissé tel quel."; exit 0; }
      tailscale funnel reset || true
    fi
    tailscale funnel --bg "$PORT" || { echo "Active Funnel avec le lien ci-dessus, puis relance : sudo bash pi/installer.sh"; exit 1; }
  fi
  tailscale funnel status || true
else
  # Le Pi a un autre nom (et publie peut-être déjà autre chose) : 2e identité Tailscale « redless »,
  # sans toucher au Tailscale principal.
  echo "Ce Pi s'appelle « ${NOM:-inconnu} » sur Tailscale : Redless aura sa propre identité « redless »."
  PORT="$PORT" bash "$DIR/pi/tailscale-redless.sh"
fi

echo
echo "Installé."
echo "  Site    : https://$ADRESSE/"
echo "  Jeu     : https://$ADRESSE/jouer/"
echo "  Santé   : https://$ADRESSE/sante"
echo "  Journal : journalctl -u redless -f"
echo "  Réglages (e-mails) : sudo nano $CONF   puis   sudo systemctl restart redless"
