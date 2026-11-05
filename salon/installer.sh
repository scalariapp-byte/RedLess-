#!/usr/bin/env bash
# Installe Salon sur Ubuntu.
#   bash salon/installer.sh                    : appli « Salon » dans le menu
#   bash salon/installer.sh --session          : + session « Salon » à l'écran de connexion (sans bureau)
#   bash salon/installer.sh --demarrage-auto   : + le PC démarre directement sur Salon
set -euo pipefail

ici="$(cd "$(dirname "$0")" && pwd)"
session=0
auto=0
for option in "$@"; do
  case "$option" in
    --session) session=1 ;;
    --demarrage-auto) session=1; auto=1 ;;
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
sudo apt-get install -y python3-pygame mpv x11-xserver-utils
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

echo "== 2/4 Programme"
sudo install -Dm755 "$ici/salon.py" /opt/salon/salon.py
sudo ln -sf /opt/salon/salon.py /usr/local/bin/salon
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
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "   Lancer : « salon » dans le menu des applications (ou la commande salon)."
[ "$session" = 1 ] && echo "   Sans bureau : déconnecte-toi, clique sur ton nom, puis sur ⚙ en bas à droite → « Salon »."
[ "$auto" = 1 ] && echo "   Au prochain démarrage, le PC ouvre Salon directement."
echo "   Téléphone (même Wi-Fi) : http://${ip:-ADRESSE-DU-PC}:8765"
echo "   Jeux : range-les dans ~/ROMs/<console>. Films : ~/Vidéos."
