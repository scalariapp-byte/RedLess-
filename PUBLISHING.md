# Publier sur le Play Store

## iPhone

- **Aujourd'hui, sans frais** : la version web sur Vercel, installée depuis Safari (Partager → « Sur l'écran d'accueil »). Elle fonctionne hors ligne et en plein écran.
- **App Store** (plus tard) : il faut un compte Apple Developer (99 $ par an) et un Mac, ou un service de build macOS dans le cloud (GitHub Actions macOS, Codemagic). Le jeu se range alors dans une coque native, le même principe que `android/` (WKWebView ou Capacitor). Apple refuse parfois les applis qui ne sont qu'un site web emballé : les fonctions natives (vibrations, partage, Game Center) aident à passer la revue.

## 1. Avant tout
- **Droits de la musique.** « Sync or Die », « Every Scar A Shield » et « The Velvet Hour » sont signées MyBlackWhite, mais leurs fichiers d'origine indiquent « Created by Google Generative AI » (manifeste C2PA + filigrane SynthID). Deux conséquences : 1) relis les conditions de l'outil Google utilisé, qui fixent ce que tu as le droit de faire avec ses créations (usage commercial compris) ; 2) en droit français, une œuvre n'est protégée par le droit d'auteur que si elle porte l'empreinte d'une création humaine : un morceau généré par une IA à partir d'une simple consigne risque de ne pas l'être, donc d'autres pourraient le réutiliser. Garde les preuves de ta part créative (paroles, consignes, retouches, montage). Pour publier sans ces morceaux : `NO_LICENSED_MUSIC=1` (piste Synthé).
- **Tests sur téléphone** : voir `TESTS.md`.

## 2. Clé de publication (une seule fois, sur ton ordinateur)
```sh
android/release-key.sh            # crée ~/redless-release.jks
```
Sauvegarde le fichier `.jks` et ses mots de passe à deux endroits, **jamais dans ce dépôt**. Sans eux, plus aucune mise à jour possible.
Sur la Play Console, active **Play App Signing** : Google garde la clé de signature finale, ta clé `.jks` sert de clé d'importation (récupérable auprès de Google si elle est perdue).

## 3. Construire le fichier à envoyer
```sh
export RELEASE_KEYSTORE=~/redless-release.jks RELEASE_KEY_ALIAS=redless
read -rs RELEASE_STORE_PASSWORD && export RELEASE_STORE_PASSWORD
VERSION_CODE=8 VERSION_NAME=2.5 NO_LICENSED_MUSIC=1 android/build.sh aab
# -> dist/redless.aab
```
Chaque nouvelle version envoyée doit avoir un `VERSION_CODE` plus grand.

## 4. Play Console
1. Créer un compte développeur (25 $ une fois) et une application « Redlok », langue par défaut français, type Jeu, gratuit.
2. **Fiche du Store** : textes dans `store/fr-FR/`, icône `store/icon-512.png`, bannière `store/feature-graphic.png`, captures `store/screenshots/` (6 × 1080×1920).
3. **Règles de confidentialité** : URL de `PRIVACY.md` sur GitHub (dépôt public) ou toute page web qui en reprend le texte.
4. **Sécurité des données** : données collectées = **Identifiants de l'appareil ou autres** (ID anonyme), **Activité dans l'appli** (scores, parties), **Autres infos** (pseudo). Usage : fonctionnalités de l'appli. Non partagées, chiffrées en transit (HTTPS), suppression sur demande.
5. **Classification du contenu** : questionnaire, jeu sans violence ni achat ni interaction entre joueurs → PEGI 3 attendu.
6. **Public cible** : 13 ans et plus (en dessous, le programme Familles impose des contraintes supplémentaires).
7. **Publicités** : non.
8. **Test fermé** : les nouveaux comptes personnels doivent faire tester l'appli par au moins 12 testeurs pendant 14 jours avant la production (règle Google en vigueur depuis fin 2023 ; vérifier l'état actuel dans la Play Console).
9. Envoyer `dist/redless.aab` dans la piste de test, puis en production.
