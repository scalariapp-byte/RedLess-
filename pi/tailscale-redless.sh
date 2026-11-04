#!/usr/bin/env bash
# Donne au Pi une 2e identité Tailscale nommée « redless », pour que https://redless.taild80a87.ts.net
# mène au serveur Redlok, sans toucher au Tailscale principal du Pi ni à ce qu'il publie déjà
# (par exemple Cercle sur https://maison.taild80a87.ts.net).
# Un second tailscaled tourne en mode « userspace » (pas d'interface réseau), avec son propre état.
# SUR le Pi : sudo bash pi/tailscale-redless.sh      (appelé aussi par pi/installer.sh)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lance avec sudo."; exit 1; }
PORT="${PORT:-8787}"
NOM=redless
SOCK=/run/tailscale-redless/tailscaled.sock
TS() { tailscale --socket="$SOCK" "$@"; }
TAILSCALED=$(command -v tailscaled || echo /usr/sbin/tailscaled)
[ -x "$TAILSCALED" ] || { echo "tailscaled introuvable : installe Tailscale d'abord."; exit 1; }

echo "-- Service tailscaled-redless (2e identité Tailscale, séparée de la principale)"
cat > /etc/systemd/system/tailscaled-redless.service <<EOF
[Unit]
Description=Tailscale : identité « $NOM » pour le serveur Redlok
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$TAILSCALED --tun=userspace-networking --statedir=/var/lib/tailscale-redless --socket=$SOCK --port=41642
RuntimeDirectory=tailscale-redless
StateDirectory=tailscale-redless
StateDirectoryMode=0700
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tailscaled-redless
for i in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done

etat() { TS status --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{try{const j=JSON.parse(s);console.log(j.BackendState+" "+(j.Self&&j.Self.DNSName||"").replace(/\.$/,""))}catch{console.log("? ")}})'; }
read -r BACKEND DNS <<<"$(etat)"
if [ "$BACKEND" != "Running" ]; then
  echo
  echo "-- Connexion : ouvre le lien qui va s'afficher et connecte-toi avec le MÊME compte Tailscale que d'habitude."
  TS up --hostname="$NOM"
  read -r BACKEND DNS <<<"$(etat)"
fi
echo "Identité : ${DNS:-?} ($BACKEND)"
case "$DNS" in
  "$NOM".*) ;;
  *) echo "Attention : le nom obtenu est « $DNS » et non « $NOM.… »."
     echo "Une autre machine s'appelle sans doute déjà « $NOM » dans la console Tailscale (Machines) : supprime-la ou renomme-la,"
     echo "puis renomme celle-ci « $NOM » (… -> Edit machine name), et relance : sudo bash pi/tailscale-redless.sh" ;;
esac

echo "-- Funnel : https://$DNS -> serveur Redlok (127.0.0.1:$PORT)"
if ! TS funnel status 2>/dev/null | grep -q "127.0.0.1:$PORT"; then
  TS funnel --bg "$PORT" || { echo "Si un lien s'affiche pour autoriser Funnel : ouvre-le, accepte, puis relance ce script."; exit 1; }
fi
TS funnel status || true
echo
echo "Le Tailscale principal (et ce qu'il publie) n'a pas été modifié :"
tailscale funnel status 2>/dev/null | sed -n '1,6p' || true
