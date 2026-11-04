# Serveur Redless sur le Raspberry Pi

Un seul programme (`pi/serveur.mjs`, Node.js, sans dépendance) sert tout ce que le jeu appelle sur `https://redless.taild80a87.ts.net` :

| Adresse | Contenu |
|---|---|
| `/` | le site (`site/`) |
| `/jouer/` | le jeu (racine du dépôt : `index.html`, `js/`, `css/`, `audio/`…) |
| `/version.json` | la version du jeu, lue dans `js/game.js` (bouton « Mettre à jour ») |
| `/redless.apk` | redirige vers l'APK signé de la release GitHub (voir plus bas) |
| `/auth/v1/…`, `/rest/v1/rpc/…` | l'API en ligne, aux mêmes adresses que Supabase : comptes anonymes, comptes protégés par e-mail, classement, sauvegardes, bannissements, installations |
| `/sante` | état du serveur (pour vérifier qu'il tourne) |

Le serveur écoute seulement sur la machine elle-même (`127.0.0.1:8787`). C'est Tailscale Funnel qui l'ouvre au public en HTTPS : aucun port de la box à ouvrir.

## Installer (une fois)
Sur le Pi, en SSH :
```sh
git clone https://github.com/scalariapp-byte/RedLess- ~/RedLess-
cd ~/RedLess-
sudo bash pi/securiser.sh     # pare-feu, SSH, fail2ban, mises à jour automatiques (garde ta session SSH ouverte)
sudo bash pi/installer.sh     # le serveur, sa mise à jour automatique, Funnel
```
Si Tailscale affiche un lien pour autoriser Funnel : ouvre-le, accepte, puis relance `sudo bash pi/installer.sh`.
Si le Pi porte un autre nom dans Tailscale (par exemple « maison », qui publie déjà Cercle), l'installateur ne touche pas à son Tailscale : il lance `pi/tailscale-redless.sh`, qui donne au Pi une 2e identité Tailscale nommée **redless** (un second `tailscaled`, en mode userspace). Ouvre le lien de connexion qu'il affiche et connecte-toi avec ton compte Tailscale habituel. La console Tailscale montre alors une machine de plus, « redless ».

## E-mails (codes « Protéger mon compte » et « Retrouver »)
Sans réglage, tout marche sauf ces deux boutons. Avec Gmail :
1. Compte Google → Sécurité → active la **Validation en deux étapes**.
2. Puis **Mots de passe des applications** → crée-en un nommé « Redless » → copie les 16 lettres.
3. Sur le Pi : `sudo nano /etc/redless/redless.env`, enlève les `#` devant les lignes `SMTP_…` et `MAIL_FROM`, colle le mot de passe dans `SMTP_PASS`.
4. `sudo systemctl restart redless`, puis `curl -s http://127.0.0.1:8787/sante` : la ligne `email` doit afficher `SMTP smtp.gmail.com:465`.

Limite de Gmail : environ 500 e-mails par jour. Le serveur en envoie au plus 200 par heure, et un code par minute et par adresse.

## Mises à jour
Toutes les 10 minutes, le Pi récupère `main` sur GitHub (`pi/mettre-a-jour.sh`). Le site et le jeu changent tout de suite ; le serveur redémarre seul si `pi/serveur.mjs` ou `pi/courriel.mjs` a changé.
Si `pi/installer.sh` change, relance-le à la main.

## Au quotidien
```sh
journalctl -u redless -f                 # journal en direct
node ~/RedLess-/pi/stats.mjs             # installations, joueurs, parties par jour
sudo systemctl restart redless           # redémarrer
```

## Données
Tout est dans `/var/lib/redless` :
- `base.json` : comptes, pseudos, points par saison, installations (écrit de façon atomique, au plus toutes les 0,5 s) ;
- `saves/` : une sauvegarde de progression par compte protégé ;
- `journal.jsonl` : une ligne par événement (compte créé, points, installation), pour les statistiques ;
- `sauvegardes/` : une copie de `base.json` par jour, 14 jours gardés.

Copie de sécurité hors du Pi (une carte SD finit par lâcher), depuis ton PC :
```sh
scp -r ton-compte@redless:/var/lib/redless ./redless-donnees-$(date +%F)
```

## L'APK
`/redless.apk` redirige vers `https://github.com/anonyme5575/redless/releases/download/latest/redless.apk`, l'APK signé avec ta clé personnelle : c'est le seul qui s'installe par-dessus l'appli des joueurs. `dist/redless.apk` du dépôt est signé avec la clé de debug, il n'est donc pas servi. Pour changer d'adresse : `APK_URL=...` dans `/etc/redless/redless.env`.

## Règles du classement (identiques à `supabase/schema.sql`)
- Un compte anonyme par appareil ; le pseudo (2 à 14 caractères, unique sans tenir compte des majuscules) est enregistré avec les premiers points.
- Le téléphone envoie la somme des points de ses parties classées (`add_points`). Refusé si plus de ~40 points par seconde de jeu, ou moins de 5 s après l'envoi précédent (le téléphone garde alors les points pour plus tard).
- Pré-saison (saison 0) jusqu'à 7 jours après le 30e joueur classé, puis une saison par mois : le classement repart de zéro.
- L'administrateur (`ADMIN_EMAIL`, compte protégé avec cette adresse) peut bannir un pseudo : il disparaît du classement et ne peut plus envoyer de points.

## Tests
`node tests/serveur.test.mjs` : l'API, les fichiers, l'envoi SMTP (serveur simulé) et le vrai code du jeu dans Chromium branché sur le serveur.
