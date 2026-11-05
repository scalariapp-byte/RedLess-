# Salon

Interface plein écran pour un petit PC Ubuntu : **films, chaînes TV, jeux rétro et infos du PC**, pilotés au clavier, à la manette, au doigt (écran tactile) ou depuis le téléphone.

Elle est faite pour les machines faibles (Celeron, 2 à 4 Go de mémoire).

## Ce qui a été optimisé (mesuré)

| Mesure | Avant | Après | Comment |
|---|---|---|---|
| Mémoire de Salon | 58 Mo | **38 Mo** | modules inutiles de pygame bloqués (numpy, son…), mini-serveur HTTP fait main, téléchargement des chaînes chargé seulement à l'usage |
| Processeur au repos | 3 % | **0,4 %** | boucle qui dort entre deux vérifications : l'attente de SDL se réveille 1 000 fois par seconde dès qu'une manette est branchée |
| Une image à l'écran | 2,3 ms | 2,3 ms | rien n'est redessiné tant que rien ne change |

Le reste :
- **mpv** décode la vidéo avec la puce graphique et garde 32 Mo d'avance sur le réseau, au lieu de 150 Mo par défaut ;
- **RetroArch** reçoit à chaque lancement des réglages légers (`~/.config/salon/retroarch-leger.cfg`) : rendu dans un fil séparé, ni shaders, ni retour arrière, ni run-ahead, menu RGUI. Il sauvegarde aussi automatiquement : un jeu reprend là où tu l'avais quitté ;
- les **émulateurs les plus légers** sont choisis d'abord : FCEUmm (NES), PicoDrive (Mega Drive), gpSP (GBA), PCSX ReARMed (PS1) ;
- la **session « Salon »** démarre l'interface sans le bureau GNOME, soit environ 1 Go de mémoire en moins (estimation) ;
- **`optimiser.sh`** allège Ubuntu lui-même (voir plus bas).

## Alléger Ubuntu

```sh
bash ~/RedLess-/salon/optimiser.sh            # applique
bash ~/RedLess-/salon/optimiser.sh --annuler  # remet comme avant
```

1. **Mémoire compressée (zram)** : la mémoire peu utilisée est compressée au lieu d'être écrite sur le disque. C'est le plus gros gain sur un PC à 2 Go.
2. **Pilotes de décodage vidéo** Intel (VA-API) : sans eux, un film 1080p saccade sur un Celeron.
3. **Services arrêtés** : impression (CUPS), modem 3G, rapports de plantage, indexation des fichiers de GNOME. Si tu imprimes depuis ce PC, relance l'impression avec `sudo systemctl enable --now cups`.

Rien n'est désinstallé. Snap n'est pas touché, parce que Firefox en dépend sur Ubuntu.

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
