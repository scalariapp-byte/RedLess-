#!/usr/bin/env bash
# Durcit le Raspberry Pi qui sert Redless. À lancer SUR le Pi : sudo bash pi/securiser.sh
# Sans risque de perdre l'accès : SSH reste ouvert sur le réseau local et via Tailscale,
# et les mots de passe SSH ne sont coupés que si une clé SSH est déjà installée.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lance avec sudo."; exit 1; }
U="${SUDO_USER:-pi}"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

echo "== 1. Mises à jour (et automatiques ensuite)"
apt-get update -q && apt-get -yq full-upgrade
apt-get install -yq unattended-upgrades fail2ban ufw
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== 2. Pare-feu : tout fermé en entrée, sauf SSH local et Tailscale"
LAN=$(ip -o -f inet addr show scope global | awk '$2!="tailscale0"{print $4; exit}')
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
[ -n "$LAN" ] && ufw allow from "$(python3 -c "import ipaddress,sys;print(ipaddress.ip_interface(sys.argv[1]).network)" "$LAN")" to any port 22 proto tcp
ufw --force enable
# Tailscale Funnel passe par une connexion sortante : aucun port de la box à ouvrir.

echo "== 3. SSH"
F=/etc/ssh/sshd_config.d/99-redless.conf
{
  echo "PermitRootLogin no"
  echo "MaxAuthTries 3"
  echo "X11Forwarding no"
  if [ -s "/home/$U/.ssh/authorized_keys" ]; then
    echo "PasswordAuthentication no"
    echo "KbdInteractiveAuthentication no"
  else
    echo "# Pas de clé SSH pour $U : mots de passe laissés actifs." >&2
  fi
} > "$F"
sshd -t && systemctl reload ssh

echo "== 4. fail2ban (bannit après 5 échecs SSH)"
printf '[sshd]\nenabled = true\nmaxretry = 5\nbantime = 1h\n' > /etc/fail2ban/jail.d/redless.conf
systemctl enable --now fail2ban && systemctl restart fail2ban

echo "== 5. À vérifier"
tailscale funnel status 2>/dev/null || echo "tailscale funnel status : indisponible"
echo "Ports ouverts :"; ss -tlnp | awk 'NR>1{print "  "$4, $6}'
echo "Fini. Garde cette session SSH ouverte et teste une NOUVELLE connexion avant de fermer."
