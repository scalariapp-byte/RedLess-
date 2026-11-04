# Redlok

Jeu mobile en portrait, jouable à un doigt, avec une interface de cockpit holographique. Touche les cases vertes, jamais les rouges. Les cases tombent sur les temps de la musique, et la musique accélère sans arrêt.

HTML/CSS/JS sans dépendance, emballé en application Android (APK pour installer directement, AAB pour le Play Store).

## Jouer

- **Android** : installer `[dist/redlok.apk](https://redlok.taild80a87.ts.net/redlok.apk)` (ou l'artefact du workflow « APK » dans l'onglet Actions).
- **iPhone / iPad** : ouvrir le site (déployé sur Vercel) dans **Safari**, puis **Partager → Sur l'écran d'accueil**. Redlok s'installe comme une appli : plein écran, icône, fonctionne hors ligne (`sw.js`), le son joue même en mode silencieux (iOS 16.4+). Seule limite : Safari ne donne pas accès au vibreur.
- **Navigateur** : `python3 -m [http.server 8000](https://redlok.taild80a87.ts.net/redlok.apk)` puis http://localhost:8000. Sur Android, Chrome propose aussi « Installer ».

## Serveur

Le site, le jeu et le classement en ligne sont servis par un Raspberry Pi (`pi/serveur.mjs`) : installation et réglages dans [`pi/README.md`](pi/README.md).

## Règles

- **Vert** (rond) : à toucher. **Doré** (étoile) : +5 crédits. **Rouge** (croix) : défaite.
- **Fintes** (score double) : vert → rouge (touche vite), rouge → vert (attends), clignotante (vise le vert).
- **Spéciales** (dès le niveau 3) : bleue = tempo ralenti 3 s ; violette = efface les rouges ; noire = garder le doigt appuyé. Rater une bleue ou une violette ne coûte rien ; rater une noire coûte une vie, comme une verte.
- **Boss** tous les 5 niveaux (Classique, Mort subite, Fintes, Défi, Duel) : 15 s de fintes et de cases en plus ; y survivre rapporte +50 points et +20 crédits.
- **Combo** : x2 à 10, x3 à 25, x4 à 50 (jauge Bouclier).
- **Tempo** : départ lent (60 BPM en Classique Normal ; Facile −12, Difficile +12, Hardcore +24, Impossible +40), puis croissance **exponentielle sans plafond** : le tempo double toutes les 2 min 30 en Normal (÷0,7 en Facile, ÷1,7 en Impossible ; 45 s en Chrono), et chaque palier ajoute +3 %. La musique est l'horloge et suit jusqu'à 2× sa vitesse (hauteur conservée) ; au-delà, elle reste à 2× et les cases tombent aussi entre les temps (croches, doubles croches…), donc la cadence continue de monter.

## Modes

| Mode | Vies | Départ | Particularité |
|---|---|---|---|
| Classique | 3 | 60 BPM | palier tous les 8 verts, fintes dès le niveau 2 |
| Chrono | – | 66 BPM | 60 s, rouge = −5 s |
| Mort subite | 1 | 76 BPM | une erreur et c'est fini |
| Fintes | 3 | 60 BPM | plus de la moitié des cases sont des fintes |
| Expansion | 3 | 60 BPM | la grille passe de 2×3 à 7×9 |
| Rythme | 3 | 64 BPM | toucher quand l'anneau se referme : Parfait (±70 ms), Bien (±150 ms) |
| Miroir | 3 | 62 BPM | la couleur à toucher s'inverse tous les 16 temps |
| Chaos | 3 | 60 BPM | Plateau qui tourne (de plus en plus vite), se retourne (recto verso) tous les 16 temps, zoome, change de taille à chaque palier, plus un événement surprise toutes les quelques mesures : Séisme, Tornade, Mélange (les cases changent de place), Dérive, Gelée, Brouillard, Microscope, Géant, Déluge, Retourne-veste. Tous les 3 paliers : téléportation à la ferme, 10 s de mini-jeu où la poule saute par-dessus les arbres (arbre = −1 vie, grain = +2, survie = +15 points et +5 crédits) |
| Défi du jour | 3 | 60 BPM | même suite de cases pour tous, un essai officiel par jour |
| Duel | 3 | 60 BPM | un code de 5 caractères = la même partie pour les deux joueurs |

## Niveaux (campagne)

**200 niveaux** en 20 mondes de 10 (`js/levels.js`), chacun avec **son propre thème de couleurs**, un mode, une difficulté qui monte, et **3 quêtes** : la première (score) réussit le niveau et ouvre le suivant, les deux autres sont des bonus. Chaque quête rapporte des crédits la première fois ; les 3 quêtes débloquent le thème du niveau dans la boutique (onglet Niveaux).

## Musiques

4 musiques d'origine (« Sync or Die », « Synthé », « Every Scar A Shield », « The Velvet Hour ») et **17 musiques libres CC0** d'OpenGameArt, à acheter dans la boutique (onglet Musique). Auteurs et sources : [`audio/CREDITS.md`](audio/CREDITS.md). La musique choisie joue partout (menus et parties) ; dans les Réglages, une liste déroulante.

## Difficulté

Dans **Modes de jeu** : Facile, Normal, Difficile, Hardcore, Impossible (tempo, fintes, durée des cases, vies, crédits ×0,5 à ×3). Facile n'est pas classé au mondial ; le Défi du jour et le Duel restent en Normal.

## Progression

- **Crédits** = score ÷ 5 + bonus. Boutique : 6 thèmes, 5 effets, 5 formes, à essayer avant d'acheter.
- **Missions** : 3 par jour (tirées d'une liste de 14), crédits à la clé.
- **Rangs** selon les points de carrière (somme des scores) : Recrue, Cadet, Pilote, Vétéran, Élite, Spectre, Légende.
- **Partage** du score en image (1080×1350). Le classement est uniquement mondial (voir plus bas).

## Classement mondial et événement

Via Supabase (offre gratuite) : un pseudo, un identifiant anonyme par téléphone, des scores contrôlés côté serveur. En option, le joueur **protège son compte** avec son e-mail (code reçu par e-mail, sans mot de passe) : sa progression est sauvegardée en ligne et il la retrouve sur un autre téléphone.
L'**événement** démarre **7 jours après le 30e joueur**, puis le classement **repart de zéro chaque mois** (saison 1, 2, 3…). Le classement est général : une ligne par joueur, avec le total de ses meilleurs scores de la saison dans tous les modes ; toucher un joueur ouvre son profil (ses scores mode par mode). Sans pseudo, le jeu en donne un automatiquement (« Pilote-1234 »), modifiable dans Réglages. Avant l'événement : pré-saison.

**Connexion** : au lancement, tant que le joueur n'a pas de compte, l'écran « Connexion » s'affiche : créer un compte (pseudo + e-mail, code reçu par e-mail, pas de mot de passe), se connecter à un compte existant (la progression en ligne remplace celle du téléphone), ou jouer sans compte. Dans tous les cas, le jeu se connecte tout seul au serveur au démarrage (compte anonyme) ; l'adresse du serveur n'est plus modifiable dans le jeu.

**Déconnexion** : Réglages → Compte → « Se déconnecter » (deux touches). La progression est d'abord sauvegardée en ligne ; si c'est impossible (hors ligne), rien ne se passe. Ensuite le téléphone repart de zéro (réglages de son et calibrage gardés) et l'écran Connexion revient.

Le pseudo est vérifié dès la création du compte (fonction `name_available` : relancer `supabase/schema.sql`). Sans compte, l'écran Connexion revient au plus une fois par semaine.

**Compteur** : le menu affiche « N joueurs sont venus » (fonction `visitor_count` : nombre de comptes, un par appareil lancé en ligne depuis la v3.5 ; relancer `supabase/schema.sql`).

**Statistiques** : `supabase/stats.sql` (installations, joueurs actifs, rétention J1/S1/M1, modes joués), à coller requête par requête dans le SQL Editor. Aucune donnée nouvelle collectée.

**Tests** : `node tests/login.test.mjs`, `node tests/chaos.test.mjs` et `node tests/tempo.test.mjs` (Chromium + Playwright, Supabase simulé) ; lancés par GitHub Actions à chaque push.
Mise en place : **[`supabase/README.md`](supabase/README.md)** (SQL à coller : `supabase/schema.sql`, puis URL et clé publique dans `js/online-config.js`).

## Mises à jour

À chaque déploiement, le site publie `version.json` (tiré de `VERSION` dans `js/game.js`). Si le jeu installé est plus ancien, une barre **« Mettre à jour »** apparaît : l'appli web se recharge, l'appli Android télécharge le nouvel APK publié par GitHub (release « latest »). Pour sortir une version : changer `VERSION` (game.js), `CACHE` (sw.js), `app-version` (index.html) et `VERSION_CODE/NAME` (android/build.sh).

## Confort

- **Tutoriel** interactif en 8 étapes au premier lancement (revoir dans Réglages).
- **Calibrage** du décalage audio : on tape sur 16 temps, le jeu mesure le retard du son et le compense.
- **Écran de fin** qui explique la défaite (finte, piège, mauvaise cible…).
- Volumes séparés, vibrations désactivables, **mode daltonien renforcé** (motifs sur les cases), choix de la piste (« Sync or Die » ou Synthé).

## Android

```sh
android/build.sh            # APK  -> dist/redlok.apk
android/build.sh aab        # AAB  -> dist/redlok.aab (Play Store)
android/release-key.sh      # crée ta clé de publication (une seule fois)
```
Il faut seulement un JDK 17+, `curl`, `unzip` et `zip` : `android/fetch-tools.sh` télécharge android.jar (API 34), aapt2, d8, uber-apk-signer et bundletool. Pas besoin d'Android Studio.
Sans clé, l'APK est signé en debug et l'AAB n'est pas signé. `NO_LICENSED_MUSIC=1` retire la musique sous droits (le jeu passe sur la piste Synthé).
Le wrapper (`android/src/.../MainActivity.java`) fournit le plein écran, le bouton Retour, la pause en arrière-plan, les vibrations et le partage natif.

Publication : voir **`PUBLISHING.md`**. Tests sur téléphone : **`TESTS.md`**. Confidentialité : **`PRIVACY.md`**. Fiche du Store : **`store/`**.

## Droits

Redlok © 2026 MyBlackWhite, tous droits réservés. Les musiques « Sync or Die », « Every Scar A Shield » et « The Velvet Hour » ont été créées par MyBlackWhite avec un outil d'IA générative de Google : aucune réutilisation sans autorisation écrite. Détails dans [`COPYRIGHT.md`](COPYRIGHT.md).

## Structure

```
index.html                  écrans
css/style.css               HUD, cases, animations
js/config.js                modes, boutique, missions, rangs, pistes
js/audio.js                 musique (horloge du jeu), synthé, vibrations
js/visuals.js               cadres, pluie, particules, carte de partage
js/game.js                  moteur, tutoriel, calibrage, écrans
js/minigame.js              mini-jeu de la poule (mode Chaos)
audio/ fonts/ assets/       musique (jeu : sync-or-die.mp3, every-scar-a-shield.mp3, the-velvet-hour.mp3 ; menu : sync-or-die-original.mp3, fichier d'origine non modifié), polices, images
android/                    wrapper WebView et scripts de build
store/                      textes, icône, bannière, captures du Play Store
```

Réglages de difficulté : objet `MODES` dans `js/config.js`, puis `lifetimeMs()`, `redChance()`, `feintChance()`, `spawnsThisBeat()` dans `js/game.js`.
Ajouter une musique : une entrée dans `TRACKS` (`js/config.js`) avec son tempo et la position de son premier temps.
