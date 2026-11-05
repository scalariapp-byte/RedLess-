#!/usr/bin/env bash
# Allège Ubuntu pour un petit PC (2 à 4 Go de mémoire, processeur Celeron).
#   bash salon/optimiser.sh            : applique tout
#   bash salon/optimiser.sh --annuler  : remet tout comme avant
# Chaque réglage est indépendant et réversible ; rien n'est désinstallé.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Lance ce script sans sudo : il demandera ton mot de passe quand il en aura besoin."
  exit 1
fi

etat=/etc/salon
# Services système inutiles sur un PC de salon (impression, modem 3G, rapports de plantage).
services="cups.service cups-browsed.service ModemManager.service whoopsie.service kerneloops.service apport.service"
# Indexation des fichiers de GNOME : gourmande, et inutile pour Salon (n'agit que dans le bureau GNOME).
services_utilisateur="tracker-miner-fs-3.service tracker-extract-3.service"

if [ "${1:-}" = "--annuler" ]; then
  if [ -f "$etat/services-desactives" ]; then
    while read -r s; do sudo systemctl enable --now "$s" 2>/dev/null || true; done < "$etat/services-desactives"
  fi
  for s in $services_utilisateur; do systemctl --user unmask "$s" 2>/dev/null || true; done
  sudo systemctl disable --now zramswap.service 2>/dev/null || true
  sudo rm -f /etc/sysctl.d/99-salon.conf /etc/systemd/zram-generator.conf "$etat/services-desactives"
  sudo sysctl --system >/dev/null
  echo "Annulé. Redémarre le PC pour retirer la mémoire compressée (zram)."
  exit 0
fi

memoire_mo=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
echo "Mémoire du PC : $memoire_mo Mo"

echo "== 1/4 Mémoire compressée (zram)"
# Les pages peu utilisées sont compressées en mémoire (2 à 3 fois plus petites) au lieu d'aller sur le
# disque, très lent sur un eMMC. C'est le plus gros gain sur un PC à 2 ou 4 Go.
if sudo apt-get install -y -qq systemd-zram-generator >/dev/null 2>&1; then
  printf '[zram0]\nzram-size = ram\ncompression-algorithm = zstd\n' | sudo tee /etc/systemd/zram-generator.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl restart systemd-zram-setup@zram0.service 2>/dev/null || true
  echo "   zram : activé (zstd, taille = mémoire du PC)"
elif sudo apt-get install -y -qq zram-tools >/dev/null 2>&1; then
  printf 'ALGO=zstd\nPERCENT=100\n' | sudo tee /etc/default/zramswap >/dev/null
  sudo systemctl restart zramswap.service || true
  echo "   zram : activé avec zram-tools"
else
  echo "   zram : aucun paquet disponible, étape sautée"
fi
# Avec zram, mieux vaut compresser tôt que vider le cache des fichiers (réglages recommandés pour zram).
printf 'vm.swappiness = 150\nvm.page-cluster = 0\nvm.watermark_scale_factor = 125\n' \
  | sudo tee /etc/sysctl.d/99-salon.conf >/dev/null
sudo sysctl --system >/dev/null 2>&1 || true

echo "== 2/4 Décodage vidéo par la puce graphique"
# Sans ces pilotes, le processeur décode la vidéo seul : un film 1080p saccade sur un Celeron.
for paquet in i965-va-driver intel-media-va-driver mesa-va-drivers vainfo; do
  sudo apt-get install -y -qq "$paquet" >/dev/null 2>&1 && echo "   $paquet : ok" || echo "   $paquet : indisponible"
done

echo "== 3/4 Services inutiles"
sudo mkdir -p "$etat"
for s in $services; do
  if systemctl is-enabled "$s" >/dev/null 2>&1; then
    sudo systemctl disable --now "$s" >/dev/null 2>&1 && echo "$s" | sudo tee -a "$etat/services-desactives" >/dev/null
    echo "   $s : arrêté"
  fi
done
for s in $services_utilisateur; do
  systemctl --user mask --now "$s" >/dev/null 2>&1 && echo "   $s : arrêté (recherche de fichiers de GNOME)"
done

echo "== 4/4 Bilan"
swapon --show 2>/dev/null || true
free -h
if command -v vainfo >/dev/null; then
  if vainfo 2>/dev/null | grep -q VAProfileH264; then
    echo "   Décodage matériel H.264 : disponible"
  else
    echo "   Décodage matériel : non détecté (vérifie avec « vainfo » une fois connecté à l'écran)"
  fi
fi
echo "Redémarre le PC pour que tout soit pris en compte. Pour revenir en arrière : bash salon/optimiser.sh --annuler"
