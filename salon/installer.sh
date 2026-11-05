#!/usr/bin/env bash
# Installe Salon sur Ubuntu.
#   bash salon/installer.sh                    : appli « Salon » dans le menu
#   bash salon/installer.sh --session          : + session « Salon » à l'écran de connexion (sans bureau)
#   bash salon/installer.sh --demarrage-auto   : + le PC démarre directement sur Salon
#   bash salon/installer.sh --netflix          : + Google Chrome, pour la tuile Netflix
set -euo pipefail

ici="$(cd "$(dirname "$0")" && pwd)"
session=0
auto=0
netflix=0
for option in "$@"; do
  case "$option" in
    --session) session=1 ;;
    --demarrage-auto) session=1; auto=1 ;;
    --netflix) netflix=1 ;;
    *) echo "Option inconnue : $option"; exit 1 ;;
  esac
done
if [ "$(id -u)" -eq 0 ]; then
  echo "Lance ce script sans sudo : il demandera ton mot de passe quand il en aura besoin."
  exit 1
fi
utilisateur="$(id -un)"

echo "== 1/4 Paquets"
sudo apt-get update -qq
sudo apt-get install -y python3-pygame x11-xserver-utils fonts-inter xdotool
if ! sudo apt-get install -y retroarch; then
  echo "   RetroArch absent d'apt : installe-le avec « flatpak install flathub org.libretro.RetroArch »."
fi
# Émulateurs (« cores ») packagés par Ubuntu. Ceux qui manquent s'installent depuis RetroArch :
# Menu principal → Mise à jour en ligne → Télécharger des cœurs.
for core in nestopia snes9x genesisplusgx gambatte mgba beetle-psx beetle-pce-fast; do
  if sudo apt-get install -y -qq "libretro-$core" >/dev/null 2>&1; then
    echo "   émulateur $core : installé"
  else
    echo "   émulateur $core : pas dans apt, à prendre dans RetroArch"
  fi
done

if [ "$netflix" = 1 ] && ! command -v google-chrome-stable >/dev/null; then
  # Netflix exige un navigateur qui lit les vidéos protégées : Chromium d'Ubuntu ne le fait pas.
  echo "   Google Chrome (pour Netflix)"
  deb="$(mktemp -d)/chrome.deb"
  wget -q -O "$deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y "$deb"
fi

echo "== 2/4 Programme"
sudo install -Dm644 "$ici/salon.py" /opt/salon/salon.py
sudo python3 -m compileall -q /opt/salon   # version précompilée : démarrage plus rapide
sudo rm -f /usr/local/bin/salon
printf '#!/bin/sh\nexec python3 -c "import sys; sys.path.insert(0, \\"/opt/salon\\"); import salon; sys.exit(salon.main())" "$@"\n' \
  | sudo tee /usr/local/bin/salon >/dev/null
sudo chmod 755 /usr/local/bin/salon
sudo install -Dm755 "$ici/salon-session" /usr/local/bin/salon-session
install -Dm644 "$ici/salon.desktop" "$HOME/.local/share/applications/salon.desktop"

echo "== 3/4 Dossiers et réseau"
for console in nes snes megadrive mastersystem gb gbc gba pcengine psx n64; do
  mkdir -p "$HOME/ROMs/$console"
done
if command -v ufw >/dev/null; then
  sudo ufw allow 8765/tcp comment "Salon : télécommande" >/dev/null 2>&1 || true
fi

if [ "$session" = 1 ]; then
  echo "== Session « Salon »"
  sudo install -Dm644 "$ici/salon-xsession.desktop" /usr/share/xsessions/salon.desktop
fi
if [ "$auto" = 1 ]; then
  echo "== Démarrage automatique sur Salon"
  gdm=/etc/gdm3/custom.conf
  if [ -f "$gdm" ]; then
    sudo cp -n "$gdm" "$gdm.avant-salon"
    sudo sed -i '/^#\?\s*AutomaticLogin/d' "$gdm"
    sudo sed -i "/^\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=$utilisateur" "$gdm"
  else
    echo "   $gdm introuvable (pas GDM ?) : connexion automatique non réglée."
  fi
  compte="/var/lib/AccountsService/users/$utilisateur"
  if [ -f "$compte" ]; then
    sudo sed -i '/^X\?Session=/d' "$compte"
    sudo sed -i '/^\[User\]/a Session=salon\nXSession=salon' "$compte"
  else
    printf '[User]\nSession=salon\nXSession=salon\n' | sudo tee "$compte" >/dev/null
  fi
fi

echo "== 4/4 Terminé"
echo "   Pour alléger aussi Ubuntu (mémoire compressée, services inutiles) : bash $ici/optimiser.sh"
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "   Lancer : « salon » dans le menu des applications (ou la commande salon)."
[ "$session" = 1 ] && echo "   Sans bureau : déconnecte-toi, clique sur ton nom, puis sur ⚙ en bas à droite → « Salon »."
[ "$auto" = 1 ] && echo "   Au prochain démarrage, le PC ouvre Salon directement."
echo "   Téléphone (même Wi-Fi) : http://${ip:-ADRESSE-DU-PC}:8765"
echo "   Jeux : envoie-les depuis la page du téléphone, ou range-les dans ~/ROMs/<console>."
