# Bot Redless

Joue à Redless en boucle dans un Chromium invisible, apprend à mieux jouer et t'envoie une notification sur le téléphone quand il trouve un bug.

## Installer sur le Raspberry Pi
```sh
cd ~/RedLess-          # le dossier du jeu (git clone https://github.com/scalariapp-byte/RedLess-)
git pull
sudo bash bot/installer.sh
```
Puis installe l'appli **ntfy** et abonne-toi au sujet affiché à la fin.

## Comment il apprend
Il joue comme un humain rapide : il voit les cases à l'écran, réagit après un délai (150 à 450 ms) et n'a qu'un doigt (au plus ~9 touches par seconde). Il ne lit jamais le code du jeu pour tricher.
Il a 8 réglages : temps de réaction, temps d'attente avant de toucher une case qui change de couleur, priorités (dorées, cases anciennes, bleues, violettes), et s'il touche les bleues, violettes et noires.
Toutes les 3 parties, il essaie un réglage modifié au hasard et le garde s'il fait mieux en moyenne (stratégie d'évolution). Sa mémoire est dans `bot/donnees/etat.json`, l'historique dans `bot/donnees/parties.csv`.

## Ce qu'il signale
- erreurs JavaScript et `console.error` ;
- valeurs impossibles (score, vies ou tempo non numériques ou négatifs) ;
- plus de cases que d'emplacements ;
- partie figée (rien ne bouge pendant 20 s) ;
- plantage de la page.

Chaque bug différent n'est signalé qu'une fois, avec une capture dans `bot/donnees/bugs/`. Il prévient aussi à chaque nouveau record.
Le bot ne contacte jamais le serveur du jeu : il ne pollue pas le classement.

## Réglages (`bot/donnees/config.env`)
| Variable | Défaut | Rôle |
|---|---|---|
| `BOT_MODE` | `classic` | mode joué (`classic`, `chrono`, `chaos`…) |
| `BOT_PARTIES` | `3` | parties pour juger un réglage |
| `BOT_MAX_MIN` | `15` | durée max d'une partie (minutes) |
| `NTFY_TOPIC` | aléatoire | sujet ntfy des notifications |

Après modification : `sudo systemctl restart redless-bot`.
Tester les notifications : `BOT_TEST_BUG=1 BOT_MAX_PARTIES=1 node bot/bot.mjs` (avec `NTFY_TOPIC=...` devant).
