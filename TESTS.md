# Test sur téléphone — à faire avant toute publication

But : trouver ce qui ne marche pas sur de vrais appareils (latence du toucher, son décalé, cases trop petites, règles pas comprises).
Prévoir 3 à 4 testeurs, 10 minutes chacun, si possible sur des téléphones différents (dont un d'entrée de gamme).

## Préparation
1. Installer `dist/redless.apk` (ou l'APK de l'onglet Actions de GitHub).
2. Ne rien expliquer au testeur : le tutoriel doit suffire.
3. Noter le modèle de téléphone et la version d'Android.

## Pendant le test (observer, ne pas aider)
| # | Vérifier | OK ? | Remarque |
|---|---|---|---|
| 1 | Le tutoriel se lance au premier « Jouer » et le testeur le termine seul | | |
| 2 | Il comprend les fintes sans qu'on les lui explique | | |
| 3 | La musique démarre après « 3, 2, 1 » | | |
| 4 | Les cases tombent en même temps que les temps de la musique | | |
| 5 | Le toucher répond tout de suite (pas de case touchée « pour rien ») | | |
| 6 | Le téléphone vibre (vert, rouge, palier) | | |
| 7 | Bouton Retour : met en pause, puis quitte la partie | | |
| 8 | Sortir de l'appli pendant une partie la met en pause | | |
| 9 | Expansion : les cases restent assez grandes pour le doigt jusqu'à 5×6 | | |
| 10 | Rythme : on obtient des « Parfait » en tapant sur le temps | | |
| 11 | Calibrage (Réglages → Calibrer) : la valeur mesurée est stable si on le refait | | |
| 12 | Partager : le menu de partage Android s'ouvre avec l'image | | |
| 13 | Rien ne rame (pluie, particules) sur le téléphone le plus lent | | |

## iPhone (version web installée)
| # | Vérifier | OK ? | Remarque |
|---|---|---|---|
| 14 | Safari → Partager → « Sur l'écran d'accueil » : l'icône Redlok apparaît | | |
| 15 | L'appli s'ouvre en plein écran, rien n'est caché par l'encoche ni la barre du bas | | |
| 16 | La musique démarre, y compris interrupteur silencieux activé | | |
| 17 | Case noire : garder le doigt appuyé n'ouvre aucun menu ni loupe | | |
| 18 | Mode avion : l'appli s'ouvre et se joue (après une première partie en ligne) | | |
| 19 | Partager : la feuille de partage iOS s'ouvre avec l'image | | |

## Après le test, demander
- Qu'est-ce qui t'a paru injuste ?
- À quel moment as-tu eu envie d'arrêter ?
- Tu y rejouerais demain ? Pourquoi ?

## Critères pour passer à la suite
- Points 1 à 8 OK sur tous les téléphones.
- Personne ne dit « ça ne répond pas » ou « la musique est décalée » (sinon : calibrage, puis retester).
- Au moins la moitié des testeurs relancent une partie sans qu'on le leur demande.
