#!/usr/bin/env python3
"""Test de Salon sans écran : python3 salon/test_salon.py [dossier_captures]

Fabrique un faux dossier personnel (films, ROMs, liste de chaînes), parcourt
tous les écrans, vérifie la télécommande HTTP, et enregistre une capture de
chaque écran si un dossier est donné.
"""

import json
import os
import socket
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

maison = Path(tempfile.mkdtemp(prefix="salon-test-"))
os.environ.update(HOME=str(maison), XDG_CONFIG_HOME=str(maison / ".config"),
                  XDG_RUNTIME_DIR=str(maison), SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
captures = Path(sys.argv[1]) if len(sys.argv) > 1 else None

(maison / "Vidéos/Séries/Saison 1").mkdir(parents=True)
for f in ("Le Grand Film.mkv", "Vacances 2024.mp4", "notes.txt"):
    (maison / "Vidéos" / f).write_bytes(b"x" * 2048)
for i in (1, 2, 10):
    (maison / f"Vidéos/Séries/Saison 1/Episode {i}.mkv").write_bytes(b"x")
for console, jeux in {"snes": ["Super Jeu (Europe).sfc", "Autre Jeu [!].smc"], "gba": ["Aventure (France).gba"],
                      "psx": ["Disque (Europe).cue", "Disque (Europe).bin"]}.items():
    (maison / "ROMs" / console).mkdir(parents=True)
    for j in jeux:
        (maison / "ROMs" / console / j).write_bytes(b"x")
(maison / "chaines.m3u").write_text(
    '#EXTM3U\n#EXTINF:-1 group-title="Info",France Info\nhttps://exemple.invalid/a.m3u8\n'
    '#EXTINF:-1 tvg-logo="x.png" group-title="Général",Chaîne Test, édition HD\nhttps://exemple.invalid/b.m3u8\n'
    'https://exemple.invalid/sans-nom.m3u8\n')
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
(maison / ".config/salon").mkdir(parents=True)
(maison / ".config/salon/config.json").write_text(json.dumps({
    "chaines": str(maison / "chaines.m3u"), "port_telecommande": port}))

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
m3u = salon.lire_m3u((maison / "chaines.m3u").read_text())
verifier([c[0] for c in m3u] == ["France Info", "Chaîne Test, édition HD", "https://exemple.invalid/sans-nom.m3u8"],
         f"lire_m3u : {m3u}")
verifier(m3u[0][1] == "Info", "lire_m3u lit le groupe")
verifier(sorted(["Episode 10", "Episode 2"], key=salon.tri_naturel) == ["Episode 2", "Episode 10"], "tri naturel")

app = salon.App((1366, 768))
n = 0


def capture(nom):
    global n
    app.sale = True
    if app.toast and time.time() > app.toast[1]:
        app.toast = None
    app.dessiner()
    if captures:
        captures.mkdir(parents=True, exist_ok=True)
        n += 1
        pygame.image.save(app.ecran, str(captures / f"{n:02d}-{nom}.png"))


def titre():
    return app.pile[-1].titre


capture("accueil")

app.commande("ok")  # Films
verifier(titre() == "Films", f"Films ouvert directement sur ~/Vidéos ({titre()})")
noms = [e[0] for e in app.pile[-1].elements]
verifier(noms == ["Séries", "Le Grand Film", "Vacances 2024"], f"contenu de Films : {noms}")
capture("films")
app.commande("ok")
app.commande("ok")
verifier([e[0] for e in app.pile[-1].elements] == ["Episode 1", "Episode 2", "Episode 10"], "sous-dossiers")
app.commande("accueil")
verifier(len(app.pile) == 1, "Accueil vide la pile")

app.commande("droite")
app.commande("ok")  # Chaînes
for _ in range(50):
    for e in pygame.event.get():
        app.traiter(e)
    if app.pile[-1].elements:
        break
    time.sleep(0.05)
verifier(len(app.pile[-1].elements) == 3, "chaînes chargées")
capture("chaines")
app.commande("accueil")

app.commande("droite")
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
verifier("mpv" not in enregistre and enregistre["port_telecommande"] == port,
         f"seuls les réglages personnels sont enregistrés : {enregistre}")
verifier("numpy" not in sys.modules or sys.modules["numpy"] is None, "numpy n'est pas chargé")

# Tactile : appui sur la tuile « Jeux »
app.commande("accueil")
r = app.pile[0]._rects()[2]
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=r.center))
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=r.center))
verifier(titre() == "Jeux", "tactile : tuile Jeux")
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(20, 20)))
app.traiter(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(20, 20)))
verifier(len(app.pile) == 1, "tactile : bouton retour")

# Télécommande
base = f"http://127.0.0.1:{port}"
page = urllib.request.urlopen(base + "/", timeout=3).read().decode()
verifier('data-a="ok"' in page, "page de télécommande servie")
urllib.request.urlopen(urllib.request.Request(base + "/action?a=bas", method="POST"), timeout=3)
avant = app.pile[0].sel
time.sleep(0.1)
for e in pygame.event.get():
    app.traiter(e)
verifier(app.pile[0].sel == (avant + 1) % 5, "action reçue du téléphone")
try:
    urllib.request.urlopen(urllib.request.Request(base + "/action?a=rm", method="POST"), timeout=3)
    verifier(False, "action inconnue refusée")
except urllib.error.HTTPError as e:
    verifier(e.code == 400, "action inconnue refusée")
try:
    urllib.request.urlopen(base + "/inconnu", timeout=3)
    verifier(False, "adresse inconnue : 404")
except urllib.error.HTTPError as e:
    verifier(e.code == 404, "adresse inconnue : 404")
etat = json.loads(urllib.request.urlopen(base + "/etat", timeout=3).read())
verifier(etat == {"ecran": "Accueil", "lecture": None}, f"état : {etat}")

app.fermer_telecommande()
pygame.quit()
print("OK" if not erreurs else f"{len(erreurs)} échec(s)")
sys.exit(1 if erreurs else 0)
