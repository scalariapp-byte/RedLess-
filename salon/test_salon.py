#!/usr/bin/env python3
"""Test de Salon sans écran : python3 salon/test_salon.py [dossier_captures]

Fabrique un faux dossier personnel (ROMs), parcourt tous les écrans, vérifie
la télécommande HTTP et l'envoi de jeux depuis le téléphone, et enregistre une
capture de chaque écran si un dossier est donné.
"""

import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

maison = Path(tempfile.mkdtemp(prefix="salon-test-"))
os.environ.update(HOME=str(maison), XDG_CONFIG_HOME=str(maison / ".config"),
                  XDG_RUNTIME_DIR=str(maison), SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
captures = Path(sys.argv[1]) if len(sys.argv) > 1 else None

for console, jeux in {"snes": ["Super Jeu (Europe).sfc", "Autre Jeu [!].smc"], "gba": ["Aventure (France).gba"],
                      "psx": ["Disque (Europe).cue", "Disque (Europe).bin"]}.items():
    (maison / "ROMs" / console).mkdir(parents=True)
    for j in jeux:
        (maison / "ROMs" / console / j).write_bytes(b"x")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
(maison / ".config/salon").mkdir(parents=True)
(maison / ".config/salon/config.json").write_text(json.dumps({"port_telecommande": port}))

sys.path.insert(0, str(Path(__file__).parent))
import salon  # noqa: E402  (avant pygame : Salon bloque les modules inutiles de pygame)
import pygame  # noqa: E402

erreurs = []


def verifier(condition, message):
    if not condition:
        erreurs.append(message)
        print("ÉCHEC :", message)


# Fonctions pures
verifier(salon.nom_de_jeu("Sonic (Europe) [!].md") == "Sonic", "nom_de_jeu enlève les étiquettes")
verifier(salon.nom_de_jeu("(Prototype).md") == "(Prototype)", "nom_de_jeu garde un nom vide d'origine")
verifier(sorted(["Episode 10", "Episode 2"], key=salon.tri_naturel) == ["Episode 2", "Episode 10"], "tri naturel")
verifier(salon.deviner_console("Zelda.sfc") == "snes", "console devinée : .sfc")
verifier(salon.deviner_console("Jeu.zip") is None, "console non devinée : .zip")
verifier(salon.deviner_console("Disque.bin") is None, "console non devinée : .bin (Mega Drive ou PS1)")

app = salon.App((1366, 768))
n = 0


def capture(nom):
    global n
    app.sale = True
    if app.toast and time.time() > app.toast[1]:
        app.toast = None
    for _ in range(40):  # laisser finir les animations
        app.dessiner()
    if captures:
        captures.mkdir(parents=True, exist_ok=True)
        n += 1
        pygame.image.save(app.ecran, str(captures / f"{n:02d}-{nom}.png"))


def titre():
    return app.pile[-1].titre


def evenements():
    time.sleep(0.1)
    for e in pygame.event.get():
        app.traiter(e)


verifier([t[0] for t in app.pile[0].tuiles] == ["Jeux", "Netflix", "Système", "Options"], "tuiles de l'accueil")
verifier(app.pile[0].details[0] == "4 jeux", f"nombre de jeux sur l'accueil : {app.pile[0].details[0]}")
capture("accueil")

app.commande("ok")  # Jeux
consoles = [e[0] for e in app.pile[-1].elements]
verifier(consoles == ["Super Nintendo", "Game Boy Advance", "PlayStation"], f"consoles : {consoles}")
verifier("émulateur manquant" in app.pile[-1].elements[0][1], "émulateur absent signalé")
capture("jeux")
app.commande("ok")
verifier([e[0] for e in app.pile[-1].elements] == ["Autre Jeu", "Super Jeu"], "jeux Super Nintendo")
app.commande("ok")  # pas de RetroArch ici : un message, pas de plantage
verifier(app.toast is not None and app.enfant is None, "message quand RetroArch manque")
capture("jeux-snes")
app.commande("retour")
app.commande("bas")
app.commande("bas")
app.commande("ok")
verifier([e[0] for e in app.pile[-1].elements] == ["Disque"], "PS1 : seulement le .cue")
app.commande("accueil")
verifier(len(app.pile) == 1, "Accueil vide la pile")

app.commande("droite")
app.cfg["navigateur"] = "navigateur-absent"
app.commande("ok")  # Netflix sans navigateur : un message, pas de plantage
verifier(app.enfant is None and app.toast and "Chrome" in app.toast[0], "Netflix sans navigateur")

app.commande("droite")
app.commande("ok")  # Système
verifier(titre() == "Système", "Système")
time.sleep(0.3)
app.pile[-1].tick()
capture("systeme")
app.commande("accueil")

app.commande("droite")
app.commande("ok")  # Options
capture("options")
app.commande("bas")
app.commande("bas")
app.commande("bas")
app.commande("ok")  # Éteindre → confirmation, « Non » choisi par défaut
verifier(titre() == "Éteindre le PC ?" and app.pile[-1].sel == 1, "confirmation avant d'éteindre")
capture("confirmation")
app.commande("ok")
verifier(titre() == "Options", "« Non » revient aux options")
app.pile[-1].sel = 0
app.commande("ok")  # écran retourné
verifier(app.cfg["ecran_retourne"] and app.toile is not app.ecran, "retournement de l'écran")
capture("options-retourne")
app.commande("ok")
verifier(not app.cfg["ecran_retourne"], "retournement annulé")
enregistre = json.loads((maison / ".config/salon/config.json").read_text())
verifier("navigateur" in enregistre and enregistre["port_telecommande"] == port and "roms" not in enregistre,
         f"seuls les réglages personnels sont enregistrés : {enregistre}")
verifier("numpy" not in sys.modules or sys.modules["numpy"] is None, "numpy n'est pas chargé")

# Tactile : appui sur la tuile « Système »
app.commande("accueil")
r = app.pile[0]._rects()[2]
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=r.center))
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=r.center))
verifier(titre() == "Système", "tactile : tuile Système")
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(20, 20)))
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(20, 20)))
verifier(len(app.pile) == 1, "tactile : bouton retour")

# Netflix : un faux navigateur ; « Stop » ferme tout son groupe de processus
faux = maison / "faux-navigateur"
faux.write_text("#!/bin/sh\nsleep 30 &\nwait\n")
faux.chmod(0o755)
app.cfg["navigateur"] = str(faux)
app.dessiner()
avant = sum(len(c) for c in app.pinceau.caches.values())
app.ouvrir_netflix()
verifier(app.genre_enfant == "web", "Netflix lancé")
verifier(avant > 0 and not any(app.pinceau.caches.values()) and not app._textes, "mémoire rendue pendant Netflix")
groupe = app.enfant.pid
app.commande("stop", "telephone")
time.sleep(0.3)
verifier(app.enfant.poll() is not None, "Stop ferme le navigateur")
vivants = []  # processus du groupe encore en vie (les zombies sont déjà morts, en attente de nettoyage)
for stat in Path("/proc").glob("[0-9]*/stat"):
    try:
        champs = stat.read_text().rsplit(")", 1)[1].split()
    except OSError:
        continue
    if int(champs[2]) == groupe and champs[0] != "Z":
        vivants.append(stat.parent.name)
verifier(not vivants, f"les processus enfants du navigateur sont fermés aussi ({vivants})")
app.fin_enfant()
app.dessiner()  # tout se redessine après le retour

# Télécommande
base = f"http://127.0.0.1:{port}"
page = urllib.request.urlopen(base + "/", timeout=3).read().decode()
verifier('data-a="ok"' in page and '<option value="snes">Super Nintendo</option>' in page,
         "page de télécommande servie, avec la liste des consoles")
urllib.request.urlopen(urllib.request.Request(base + "/action?a=bas", method="POST"), timeout=3)
avant = app.pile[0].sel
evenements()
verifier(app.pile[0].sel == (avant + 1) % 4, "action reçue du téléphone")
for adresse, code in (("/action?a=rm", 400), ("/inconnu", 404)):
    try:
        methode = "POST" if adresse.startswith("/action") else "GET"
        urllib.request.urlopen(urllib.request.Request(base + adresse, method=methode), timeout=3)
        verifier(False, f"{adresse} : {code} attendu")
    except urllib.error.HTTPError as e:
        verifier(e.code == code, f"{adresse} : {code} attendu, {e.code} reçu")
etat = json.loads(urllib.request.urlopen(base + "/etat", timeout=3).read())
verifier(etat == {"ecran": "Accueil", "lecture": None}, f"état : {etat}")


# Envoi de jeux depuis le téléphone
def envoyer(nom, contenu, console="auto"):
    url = f"{base}/envoyer?console={console}&nom={urllib.parse.quote(nom)}"
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=contenu, method="POST"), timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def zip_avec(nom):
    import io
    import zipfile
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr(nom, b"jeu")
    return tampon.getvalue()


def cue_de(*pistes):
    return "".join(f'FILE "{p}" BINARY\n  TRACK {i + 1:02d} MODE2/2352\n    INDEX 01 00:00:00\n'
                   for i, p in enumerate(pistes))


gros = os.urandom(3 * 2**20 + 123)  # plusieurs morceaux réseau
code, rep = envoyer("Mario Kart (Europe).sfc", gros)
verifier(code == 200 and rep["console"] == "Super Nintendo", f"envoi deviné : {code} {rep}")
recu = maison / "ROMs/snes/Mario Kart (Europe).sfc"
verifier(recu.exists() and recu.read_bytes() == gros, "fichier reçu intact")
verifier(not list((maison / "ROMs/snes").glob("*.part")), "pas de fichier partiel qui traîne")
evenements()
verifier(app.toast and "Mario Kart" in app.toast[0] and app.pile[0].details[0] == "5 jeux",
         "le PC affiche le jeu reçu et le compte")
code, rep = envoyer("Jeu.zip", b"x")
verifier(code == 400 and "Choisis la console" in rep["erreur"] and not (maison / "ROMs/Jeu.zip").exists(),
         f".zip illisible sans console : {code} {rep}")
code, rep = envoyer("Jeu.zip", b"x", "gba")
verifier(code == 200 and (maison / "ROMs/gba/Jeu.zip").exists(), ".zip avec console choisie")
code, rep = envoyer("Disque 2.bin", b"x", "psx")
verifier(code == 200, ".bin accepté pour la PS1")
code, rep = envoyer("virus.sh", b"x", "snes")
verifier(code == 400 and "Pas un jeu" in rep["erreur"], f"extension refusée : {code} {rep}")
code, rep = envoyer("../../.bashrc", b"x", "snes")
verifier(code == 400 and not (maison / ".bashrc").exists(), "impossible d'écrire hors du dossier des jeux")
code, rep = envoyer("../evasion.sfc", b"x")
verifier(code == 200 and (maison / "ROMs/snes/evasion.sfc").exists() and not (maison / "ROMs/evasion.sfc").exists(),
         "chemin ramené au nom du fichier")

code, rep = envoyer("Pack GBA.zip", zip_avec("Metroid.gba"))
verifier(code == 200 and rep["console"] == "Game Boy Advance" and (maison / "ROMs/gba/Pack GBA.zip").exists(),
         f".zip examiné à l'envoi : {code} {rep}")
code, rep = envoyer("Piste (Track 2).bin", b"x")  # piste envoyée AVANT son .cue : prise pour de la Mega Drive…
code, rep = envoyer("Crash.cue", cue_de("Crash (Track 1).bin", "Piste (Track 2).bin").encode())
verifier(code == 200 and rep["console"] == "PlayStation", f".cue envoyé : {code} {rep}")
verifier((maison / "ROMs/psx/Piste (Track 2).bin").exists() and not (maison / "ROMs/megadrive/Piste (Track 2).bin").exists(),
         "… puis rattachée à son .cue quand il arrive")
code, rep = envoyer("Archive.7z", b"x")
verifier(code == 400 and "Choisis la console" in rep["erreur"], f".7z sans console : {code} {rep}")

# Jeux posés en vrac dans ~/ROMs : rangés par console
roms = maison / "ROMs"
(roms / "Sonic (Europe).md").write_bytes(b"x")
(roms / "Tekken.cue").write_text(cue_de("Tekken (Track 1).bin"))
(roms / "Tekken (Track 1).bin").write_bytes(b"x")
(roms / "Streets.bin").write_bytes(b"x" * 1000)
(roms / "Pokemon.zip").write_bytes(zip_avec("Pokemon Rouge.gb"))
(roms / "Gros disque.bin").write_bytes(b"\0")
os.truncate(roms / "Gros disque.bin", 20 * 2**20)  # fichier creux : 20 Mo sans les écrire
(roms / "Mystere.7z").write_bytes(b"x")
app.toast = None
app.pile[0].compter()
for chemin, attendu in (("megadrive/Sonic (Europe).md", True), ("psx/Tekken.cue", True),
                        ("psx/Tekken (Track 1).bin", True), ("megadrive/Streets.bin", True),
                        ("gb/Pokemon.zip", True), ("psx/Gros disque.bin", True), ("Mystere.7z", True),
                        ("Sonic (Europe).md", False)):
    verifier((roms / chemin).exists() == attendu, f"rangement : {chemin} {'absent' if attendu else 'présent'}")
verifier(app.toast and "rangés" in app.toast[0], f"message de rangement : {app.toast}")
app.toast = None
app.pile[0].compter()
verifier(app.toast and "Mystere.7z" in app.toast[0], f"console inconnue signalée : {app.toast}")
app.toast = None
app.pile[0].compter()
verifier(app.toast is None, "console inconnue signalée une seule fois")

app.fermer_telecommande()
pygame.quit()
print("OK" if not erreurs else f"{len(erreurs)} échec(s)")
sys.exit(1 if erreurs else 0)
