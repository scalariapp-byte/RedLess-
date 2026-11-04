#!/usr/bin/env bash
# Récupère la dernière version du dépôt (branche main) et redémarre le serveur si son code a changé.
# Lancé toutes les 10 minutes par redless-maj.timer (voir pi/installer.sh). Argument : le compte propriétaire du dépôt.
set -euo pipefail
U="${1:?compte}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
as_user() { runuser -u "$U" -- "$@"; }

before=$(as_user git -C "$DIR" rev-parse HEAD)
# --ff-only : une modification faite à la main sur le Pi bloque la mise à jour au lieu d'être écrasée.
as_user git -C "$DIR" pull --ff-only --quiet origin main || { echo "Mise à jour impossible (modification locale ?) : git -C $DIR status"; exit 1; }
after=$(as_user git -C "$DIR" rev-parse HEAD)
[ "$before" = "$after" ] && exit 0
echo "Redlok : $before -> $after"
# Le site et le jeu sont lus sur le disque à chaque demande : seul le code du serveur demande un redémarrage.
if ! as_user git -C "$DIR" diff --quiet "$before" "$after" -- pi/serveur.mjs pi/courriel.mjs; then
  systemctl restart redless
  echo "Serveur redémarré."
fi
