# Salon

Interface plein écran pour un petit PC Ubuntu : **jeux rétro, Netflix et infos du PC**, pilotée au clavier, à la manette, au doigt (écran tactile) ou depuis le téléphone, qui sert aussi à **envoyer des jeux**.

Elle est faite pour les machines faibles (Celeron, 2 à 4 Go de mémoire).

![Accueil](captures/accueil.png)
![Système](captures/systeme.png)
![Liste](captures/liste.png)

## Installer

```sh
git clone -b ccr-d0963a6c-u8wcle https://github.com/scalariapp-byte/RedLess- ~/RedLess-
bash ~/RedLess-/salon/installer.sh --session --netflix
bash ~/RedLess-/salon/optimiser.sh
```

| Option de `installer.sh` | Effet |
|---|---|
| *(aucune)* | ajoute l'appli « Salon » au menu d'Ubuntu |
| `--session` | ajoute la session « Salon » (sans bureau) à l'écran de connexion |
| `--demarrage-auto` | le PC s'allume directement sur Salon, sans mot de passe |
| `--netflix` | installe Google Chrome pour la tuile Netflix |

Pour annuler le démarrage automatique : `sudo cp /etc/gdm3/custom.conf.avant-salon /etc/gdm3/custom.conf`.

## Envoyer des jeux depuis le téléphone

1. Sur le téléphone, connecté au même Wi-Fi, ouvre l'adresse affichée en bas à droite de l'écran (`http://<adresse du PC>:8765`).
2. En bas de la page, dans « Ajouter des jeux », appuie sur **Choisir des jeux** et sélectionne un ou plusieurs fichiers.
3. La console est devinée d'après l'extension (`.sfc` → Super Nintendo, `.gba` → Game Boy Advance…). Pour les `.zip`, `.7z`, `.bin`, `.cue` et `.chd`, qui servent à plusieurs consoles, choisis la console dans la liste avant d'envoyer.
4. Une barre montre l'avancement ; le PC affiche « Jeu reçu » et le compte de jeux se met à jour.

Pour un jeu PS1, envoie le `.cue` **et** son ou ses `.bin`, avec « PlayStation » choisi. Le BIOS de la console reste à copier à la main dans `~/.config/retroarch/system/`.

Seules les extensions de jeux sont acceptées, et les fichiers vont uniquement dans `~/ROMs/<console>`. N'importe qui sur ton Wi-Fi peut ouvrir cette page : c'est un choix assumé pour un réseau de maison, pas pour un Wi-Fi public.

Sans téléphone : copie les fichiers dans `~/ROMs/<console>`, où `<console>` vaut `nes`, `snes`, `megadrive`, `mastersystem`, `gb`, `gbc`, `gba`, `pcengine`, `psx` ou `n64`. Seulement des copies de jeux que tu possèdes, ou des homebrews libres.

## Utiliser

| | Clavier | Manette | Téléphone |
|---|---|---|---|
| Se déplacer | flèches | croix ou stick gauche | ▲ ▼ ◀ ▶ |
| Valider | Entrée | A | OK |
| Revenir | Échap | B | Retour |
| Accueil | Début | Select ou bouton central | Accueil |
| Page suivante / précédente | Page ↓ / Page ↑ | RB / LB | ⏩ / ⏪ |
| Volume | + / − | | Vol + / Vol − |

Pendant un **jeu** : la manette appartient au jeu. **Select + Start** ensemble quittent le jeu, ou bien « Stop » sur le téléphone. RetroArch sauvegarde tout seul : le jeu reprend là où tu l'avais quitté.

Pendant **Netflix** : le site officiel s'ouvre dans Chrome en plein écran. Choisis un programme au doigt (écran tactile) ou à la souris ; ensuite OK met en pause, ◀ ▶ reculent ou avancent de 10 s, ▲ ▼ règlent le volume, Retour revient à la page précédente, **Stop** (téléphone) ou **Select + Start** (manette) ferment Netflix. Sur Linux, Netflix limite l'image à 720p.

**Mode tente** (convertible retourné) : Options → « Retourner l'écran ».

## Ce qui est optimisé (mesuré)

| | Valeur | Comment |
|---|---|---|
| Mémoire de Salon pendant un jeu ou Netflix | **34 Mo** | au lancement, Salon vide ses caches (images, fonds, textes, polices) et rend la mémoire au système (`malloc_trim`) ; le jeu ou Chrome en profitent |
| Mémoire de Salon dans les menus | 58 Mo | numpy et les modules audio de pygame bloqués ; mini-serveur HTTP fait main ; caches plafonnés : fonds au quart de la résolution, halos en demi-résolution, couleurs d'animation limitées à deux états |
| Processeur au repos | **0,4 %** | boucle qui dort entre deux vérifications (l'attente de SDL se réveille 1 000 fois par seconde dès qu'une manette est branchée) |
| Un pas sur l'accueil / une image d'animation | 9 ms / 4 ms | formes lissées calculées une fois puis gardées au format de l'écran ; rien n'est redessiné tant que rien ne change |

Le reste :
- **RetroArch** reçoit à chaque lancement des réglages légers (`~/.config/salon/retroarch-leger.cfg`) : rendu dans un fil séparé, ni shaders, ni retour arrière, ni run-ahead, menu RGUI ;
- les **émulateurs les plus légers** sont choisis d'abord : FCEUmm (NES), PicoDrive (Mega Drive), gpSP (GBA), PCSX ReARMed (PS1) ;
- **Chrome** démarre sans extensions ni synchronisation, avec au plus 2 processus d'affichage, et en mode « petit appareil » si le PC a moins de 3 Go ;
- la **session « Salon »** démarre l'interface sans le bureau GNOME, soit environ 1 Go de mémoire en moins (estimation) ;
- **`optimiser.sh`** allège Ubuntu lui-même (voir plus bas).

## Alléger Ubuntu

```sh
bash ~/RedLess-/salon/optimiser.sh            # applique
bash ~/RedLess-/salon/optimiser.sh --annuler  # remet comme avant
```

1. **Mémoire compressée (zram)** : la mémoire peu utilisée est compressée au lieu d'être écrite sur le disque. C'est le plus gros gain sur un PC à 2 Go.
2. **Services arrêtés** : impression (CUPS), modem 3G, rapports de plantage, indexation des fichiers de GNOME. Si tu imprimes depuis ce PC, relance l'impression avec `sudo systemctl enable --now cups`.

Rien n'est désinstallé. Snap n'est pas touché, parce que Firefox en dépend sur Ubuntu.

## Réglages

`~/.config/salon/config.json` ne contient que ce que tu changes :

```json
{
  "roms": "/home/moi/ROMs",
  "retroarch": "retroarch",
  "cores_dir": "",
  "navigateur": "google-chrome-stable",
  "netflix": "https://www.netflix.com/browse",
  "port_telecommande": 8765,
  "ecran_retourne": false
}
```

## Vérifier

```sh
python3 salon/test_salon.py            # parcourt tous les écrans et teste l'envoi de jeux, doit finir par OK
python3 salon/test_salon.py captures/  # en plus, une capture PNG de chaque écran
salon --fenetre                        # lance Salon dans une fenêtre 1280 × 720 au lieu du plein écran
```
