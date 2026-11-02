#!/usr/bin/env bash
# Installe le bot Redless sur le Raspberry Pi comme service (redémarre seul, démarre avec le Pi).
# À lancer depuis le dossier du jeu : sudo bash bot/installer.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lance avec sudo."; exit 1; }
U="${SUDO_USER:?Lance avec sudo depuis ton compte, pas en root direct}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

echo "== 1. Node.js et Chromium"
apt-get update -q
apt-get install -yq nodejs npm chromium
node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' || { echo "Node 18 ou plus requis."; exit 1; }

echo "== 2. Playwright (pilote de Chromium, sans télécharger d'autre navigateur)"
sudo -u "$U" bash -c "cd '$DIR' && npm install --no-save --no-package-lock --no-audit --no-fund playwright-core@1.56.1"

echo "== 3. Notifications sur le téléphone (ntfy)"
CONF="$DIR/bot/donnees/config.env"
sudo -u "$U" mkdir -p "$DIR/bot/donnees"
if [ ! -f "$CONF" ]; then
  TOPIC="redless-bot-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  printf 'NTFY_TOPIC=%s\nBOT_MODE=classic\n' "$TOPIC" | sudo -u "$U" tee "$CONF" >/dev/null
  chmod 600 "$CONF"
fi
TOPIC=$(grep -oP '^NTFY_TOPIC=\K.*' "$CONF")

echo "== 4. Service systemd"
cat > /etc/systemd/system/redless-bot.service <<EOF
[Unit]
Description=Bot Redless (apprend a jouer, signale les bugs)
After=network-online.target
Wants=network-online.target

[Service]
User=$U
WorkingDirectory=$DIR
EnvironmentFile=$CONF
ExecStart=$(command -v node) bot/bot.mjs
Restart=always
RestartSec=30
# Ne gêne pas le serveur du jeu : priorité basse, 2 cœurs et 1,5 Go au plus.
Nice=15
CPUQuota=200%
MemoryMax=1500M
# Sécurité : pas d'élévation de droits, système en lecture seule.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now redless-bot
sleep 5
systemctl --no-pager --lines=5 status redless-bot || true

cat <<EOF

Installé. Pour recevoir les alertes sur ton téléphone :
  1. Installe l'appli « ntfy » (Android / iPhone).
  2. Touche +, puis abonne-toi au sujet :  $TOPIC
     (garde-le secret : quiconque le connaît peut lire les alertes)

Commandes utiles :
  journalctl -u redless-bot -f        voir le bot jouer en direct
  sudo systemctl stop redless-bot     l'arrêter
  sudo systemctl start redless-bot    le relancer
  cat bot/donnees/etat.json           ses réglages appris, son record, les bugs trouvés
EOF
