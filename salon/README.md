# Salon

Interface plein écran pour un petit PC Ubuntu : **films, chaînes TV, jeux rétro et infos du PC**, pilotés au clavier, à la manette, au doigt (écran tactile) ou depuis le téléphone.

Elle est faite pour les machines faibles (Celeron, 2 à 4 Go de mémoire) :
- un seul fichier Python, `salon.py`, qui n'utilise que pygame ;
- l'écran n'est redessiné que quand quelque chose change, donc le processeur est presque à 0 % dans les menus ;
- la vidéo est confiée à **mpv** (décodage matériel) et les jeux à **RetroArch**, lancés seulement quand on en a besoin ;
- la session « Salon » démarre l'interface **sans le bureau GNOME**, ce qui laisse plusieurs centaines de Mo de mémoire en plus aux jeux et aux films.

## Installer

```sh
git clone -b ccr-d0963a6c-u8wcle https://github.com/scalariapp-byte/RedLess- ~/RedLess-
bash ~/RedLess-/salon/installer.sh --session
```

| Option | Effet |
|---|---|
| *(aucune)* | ajoute l'appli « Salon » au menu d'Ubuntu |
| `--session` | ajoute aussi la session « Salon » (sans bureau) à l'écran de connexion |
| `--demarrage-auto` | le PC s'allume directement sur Salon, sans mot de passe |

Pour annuler le démarrage automatique : `sudo cp /etc/gdm3/custom.conf.avant-salon /etc/gdm3/custom.conf`.

## Utiliser

| | Clavier | Manette | Téléphone |
|---|---|---|---|
| Se déplacer | flèches | croix ou stick gauche | ▲ ▼ ◀ ▶ |
| Valider | Entrée | A | OK |
| Revenir | Échap | B | Retour |
| Accueil | Début | Select ou bouton central | Accueil |
| Page suivante / précédente | Page ↓ / Page ↑ | RB / LB | ⏩ / ⏪ |
| Volume | + / − | | Vol + / Vol − |

Pendant un **film** : OK pour pause, ◀ ▶ pour reculer de 10 s ou avancer de 30 s, ▲ ▼ pour le volume, Retour pour quitter. mpv reprend là où tu t'étais arrêté.
Pendant la **TV** : ▲ ▼ pour changer de chaîne, ◀ ▶ pour le volume.
Pendant un **jeu** : la manette appartient au jeu. **Select + Start** ensemble quittent le jeu, ou bien « Stop » sur le téléphone.

**Téléphone** : ouvre l'adresse affichée en bas de l'écran (`http://<adresse du PC>:8765`) dans le navigateur, puis « Ajouter à l'écran d'accueil ». Le téléphone doit être sur le même Wi-Fi, ou relié par Tailscale. N'importe qui sur ton réseau peut ouvrir cette page : c'est un choix assumé pour un réseau de maison, pas pour un Wi-Fi public.

**Mode tente** (convertible retourné) : Options → « Retourner l'écran ».

## Où mettre quoi

- **Films** : `~/Vidéos`, avec autant de sous-dossiers que tu veux.
- **Jeux** : `~/ROMs/<console>`, où `<console>` vaut `nes`, `snes`, `megadrive`, `mastersystem`, `gb`, `gbc`, `gba`, `pcengine`, `psx` ou `n64`. Seulement des copies de jeux que tu possèdes, ou des homebrews libres. Les jeux PS1 ont besoin du BIOS de ta console, à placer dans `~/.config/retroarch/system`.
- **Chaînes** : par défaut, la liste des chaînes françaises en accès libre d'iptv-org, téléchargée à l'ouverture et gardée en cache. Une chaîne qui ne répond plus est sautée.

## Réglages

`~/.config/salon/config.json` (créé au premier lancement) :

```json
{
  "films": ["/home/moi/Vidéos", "/media/moi/DisqueUSB/Films"],
  "chaines": "https://iptv-org.github.io/iptv/countries/fr.m3u",
  "roms": "/home/moi/ROMs",
  "retroarch": "retroarch",
  "cores_dir": "",
  "mpv": ["mpv", "--fs", "--hwdec=auto-safe", "--really-quiet"],
  "port_telecommande": 8765,
  "ecran_retourne": false
}
```

`chaines` accepte une adresse web ou un fichier `.m3u` local (celui de ta box, par exemple).

## Vérifier

```sh
python3 salon/test_salon.py            # parcourt tous les écrans sans affichage, doit finir par OK
python3 salon/test_salon.py captures/  # en plus, une capture PNG de chaque écran
salon --fenetre                        # lance Salon dans une fenêtre 1280 × 720 au lieu du plein écran
```
