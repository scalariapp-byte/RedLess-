#!/usr/bin/env python3
"""Salon : films, chaînes TV, jeux rétro et infos du PC, en plein écran.

Pilotable au clavier, à la manette, au tactile et depuis un téléphone
(page web servie sur le port 8765). Conçu pour les petits PC : rien n'est
redessiné tant que rien ne change, la vidéo passe par mpv et les jeux par
RetroArch, lancés seulement quand on en a besoin.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from glob import glob
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# La manette doit rester lue quand mpv est devant (pause, volume, quitter).
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
# pygame charge d'office numpy, le son et d'autres modules dont Salon ne se sert pas :
# les bloquer économise environ 18 Mo de mémoire (pygame les remplace par des modules vides).
for _module in ("numpy", "pygame.mixer", "pygame.mixer_music", "pygame.sndarray", "pygame.surfarray",
                "pygame.freetype", "pygame.ftfont", "pygame.midi", "pygame.camera", "pygame.scrap",
                "pygame.fastevent"):
    sys.modules.setdefault(_module, None)
import pygame  # noqa: E402

VERSION = "1.0"
ACCUEIL_DIR = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or ACCUEIL_DIR / ".config") / "salon"
CONFIG_FICHIER = CONFIG_DIR / "config.json"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
MPV_SOCKET = RUNTIME / "salon-mpv.sock"
PLAYLIST_TV = RUNTIME / "salon-chaines.m3u"


def dossier_videos():
    """Dossier « Vidéos » de l'utilisateur (son nom dépend de la langue)."""
    try:
        for ligne in (ACCUEIL_DIR / ".config/user-dirs.dirs").read_text().splitlines():
            if ligne.startswith("XDG_VIDEOS_DIR="):
                return ligne.split("=", 1)[1].strip('"').replace("$HOME", str(ACCUEIL_DIR))
    except OSError:
        pass
    return str(ACCUEIL_DIR / "Vidéos")


DEFAUTS = {
    "films": [dossier_videos()],
    # Chaînes gratuites et diffusées légalement en clair, recensées par iptv-org.
    "chaines": "https://iptv-org.github.io/iptv/countries/fr.m3u",
    "roms": str(ACCUEIL_DIR / "ROMs"),
    "retroarch": "retroarch",
    "cores_dir": "",
    # Décodage par la puce graphique, petit tampon réseau (150 Mo par défaut dans mpv).
    "mpv": ["mpv", "--fs", "--hwdec=auto-safe", "--really-quiet", "--ytdl=no",
            "--demuxer-max-bytes=32MiB", "--demuxer-max-back-bytes=8MiB"],
    "port_telecommande": 8765,
    "ecran_retourne": False,
}
ANCIEN_MPV = ["mpv", "--fs", "--hwdec=auto-safe", "--really-quiet"]

# Réglages de RetroArch pour un petit processeur, ajoutés par-dessus les siens à chaque lancement.
RETROARCH_LEGER = """\
video_threaded = "true"
video_shader_enable = "false"
video_smooth = "false"
video_fullscreen = "true"
menu_driver = "rgui"
rewind_enable = "false"
run_ahead_enabled = "false"
audio_latency = "64"
savestate_auto_save = "true"
savestate_auto_load = "true"
"""

# dossier dans ~/ROMs, nom affiché, émulateurs RetroArch (les plus légers d'abord), extensions
SYSTEMES = [
    ("nes", "NES", ["fceumm_libretro", "nestopia_libretro", "mesen_libretro"], ".nes .fds .unf .zip .7z"),
    ("snes", "Super Nintendo", ["snes9x_libretro", "snes9x2010_libretro", "bsnes_libretro"], ".sfc .smc .zip .7z"),
    ("megadrive", "Mega Drive", ["picodrive_libretro", "genesis_plus_gx_libretro"], ".md .gen .smd .bin .zip .7z"),
    ("mastersystem", "Master System", ["picodrive_libretro", "genesis_plus_gx_libretro"], ".sms .zip .7z"),
    ("gb", "Game Boy", ["gambatte_libretro", "sameboy_libretro", "mgba_libretro"], ".gb .zip .7z"),
    ("gbc", "Game Boy Color", ["gambatte_libretro", "sameboy_libretro", "mgba_libretro"], ".gbc .zip .7z"),
    ("gba", "Game Boy Advance", ["gpsp_libretro", "mgba_libretro", "vba_next_libretro"], ".gba .zip .7z"),
    ("pcengine", "PC Engine", ["mednafen_pce_fast_libretro"], ".pce .cue .chd .zip"),
    ("psx", "PlayStation", ["pcsx_rearmed_libretro", "swanstation_libretro", "mednafen_psx_libretro"], ".cue .chd .pbp .m3u"),
    ("n64", "Nintendo 64", ["mupen64plus_next_libretro", "parallel_n64_libretro"], ".n64 .z64 .v64 .zip"),
]

EXT_VIDEO = set(".mkv .mp4 .avi .mov .webm .m4v .mpg .mpeg .ts .wmv .flv .ogv".split())

ACTIONS = {"haut", "bas", "gauche", "droite", "ok", "retour", "accueil",
           "pause", "avance", "recul", "vol+", "vol-", "stop"}

# Couleurs
FOND = (14, 16, 22)
PANNEAU = (28, 32, 42)
PANNEAU_SEL = (46, 53, 70)
TEXTE = (236, 239, 244)
TEXTE_DIM = (138, 146, 163)
VERT = (72, 187, 120)
ORANGE = (237, 137, 54)
ROUGE = (229, 72, 77)
BLEU = (66, 153, 225)
VIOLET = (159, 122, 234)

EV_TELE = pygame.USEREVENT + 1     # action venue du téléphone
EV_REVEIL = pygame.USEREVENT + 2   # une tâche de fond a fini : redessiner


# ---------------------------------------------------------------- configuration

def charger_config():
    cfg = dict(DEFAUTS)
    try:
        cfg.update(json.loads(CONFIG_FICHIER.read_text()))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"salon : {CONFIG_FICHIER} illisible ({e}), réglages par défaut", file=sys.stderr)
    if cfg.get("mpv") == ANCIEN_MPV:  # fichier écrit par la 1re version : on reprend les nouveaux réglages
        cfg["mpv"] = DEFAUTS["mpv"]
    return cfg


def sauver_config(cfg):
    """N'écrit que ce qui diffère des valeurs par défaut, pour profiter des améliorations futures."""
    perso = {k: v for k, v in cfg.items() if DEFAUTS.get(k) != v}
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FICHIER.write_text(json.dumps(perso, indent=2, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"salon : impossible d'écrire {CONFIG_FICHIER} ({e})", file=sys.stderr)


# ---------------------------------------------------------------- utilitaires

def lire(chemin, defaut=""):
    try:
        return Path(chemin).read_text().strip()
    except OSError:
        return defaut


def tri_naturel(texte):
    return [int(m) if m.isdigit() else m.casefold() for m in re.split(r"(\d+)", texte)]


def nom_de_jeu(fichier):
    """« Sonic (Europe) [!].md » devient « Sonic »."""
    nom = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", Path(fichier).stem).strip()
    return nom or Path(fichier).stem


def taille_lisible(octets):
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024 or unite == "Go":
            return f"{octets:.0f} {unite}" if unite in ("o", "Ko") else f"{octets:.1f} {unite}".replace(".", ",")
        octets /= 1024


def lire_m3u(texte):
    """Liste de (nom, groupe, url) à partir d'une playlist M3U."""
    chaines, nom, groupe = [], None, ""
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("#EXTINF"):
            # Le nom suit la première virgule hors des attributs entre guillemets.
            m = re.match(r'#EXTINF:[^,"]*(?:"[^"]*"[^,"]*)*,(.*)', ligne)
            nom = m.group(1).strip() if m else None
            m = re.search(r'group-title="([^"]*)"', ligne)
            groupe = m.group(1) if m else ""
        elif ligne and not ligne.startswith("#"):
            chaines.append((nom or ligne, groupe, ligne))
            nom, groupe = None, ""
    return chaines


def adresse_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))  # aucun paquet n'est envoyé : sert à choisir l'interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def volume_systeme(delta):
    signe = "+" if delta > 0 else "-"
    if shutil.which("wpctl"):
        cmd = ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(delta)}%{signe}"]
    elif shutil.which("pactl"):
        cmd = ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{signe}{abs(delta)}%"]
    elif shutil.which("amixer"):
        cmd = ["amixer", "-q", "set", "Master", f"{abs(delta)}%{signe}"]
    else:
        return
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# ---------------------------------------------------------------- infos du PC

class InfosPC:
    def __init__(self):
        self._stat = self._lire_stat()
        vendeur = lire("/sys/class/dmi/id/sys_vendor")
        version = lire("/sys/class/dmi/id/product_version")
        produit = lire("/sys/class/dmi/id/product_name")
        nom = version if version and not re.search(r"none|filled|default|^\d*$", version, re.I) else produit
        self.modele = " ".join(p for p in (vendeur, nom) if p) or "Inconnu"
        self.processeur = "Inconnu"
        for ligne in lire("/proc/cpuinfo").splitlines():
            if ligne.startswith("model name"):
                brut = ligne.split(":", 1)[1]
                self.processeur = re.sub(r"\((R|TM|tm|r)\)|\bCPU\b", "", brut)
                self.processeur = re.sub(r"\s+", " ", self.processeur).strip()
                break
        self.coeurs = os.cpu_count() or 1
        systeme = "Linux"
        for ligne in lire("/etc/os-release").splitlines():
            if ligne.startswith("PRETTY_NAME="):
                systeme = ligne.split("=", 1)[1].strip('"')
        self.systeme = systeme
        self.noyau = os.uname().release
        self.ip = adresse_ip()
        self._ip_lue = time.time()

    @staticmethod
    def _lire_stat():
        try:
            valeurs = [int(v) for v in lire("/proc/stat").splitlines()[0].split()[1:]]
            return valeurs[3] + (valeurs[4] if len(valeurs) > 4 else 0), sum(valeurs)
        except (IndexError, ValueError):
            return 0, 0

    def cpu(self):
        repos, total = self._lire_stat()
        d_repos, d_total = repos - self._stat[0], total - self._stat[1]
        self._stat = (repos, total)
        return 0.0 if d_total <= 0 else max(0.0, min(100.0, 100 * (1 - d_repos / d_total)))

    @staticmethod
    def frequence():
        valeurs = [int(lire(f, "0")) for f in glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")]
        valeurs = [v for v in valeurs if v > 0]
        return sum(valeurs) / len(valeurs) / 1000 if valeurs else None

    @staticmethod
    def temperature():
        for hw in glob("/sys/class/hwmon/hwmon*"):
            if lire(f"{hw}/name") in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                t = lire(f"{hw}/temp1_input")
                if t.isdigit():
                    return int(t) / 1000
        meilleure = None
        for zone in glob("/sys/class/thermal/thermal_zone*"):
            t = lire(f"{zone}/temp")
            if t.lstrip("-").isdigit() and 0 < int(t) / 1000 < 150:
                meilleure = max(meilleure or 0, int(t) / 1000)
        return meilleure

    @staticmethod
    def memoire():
        infos = {}
        for ligne in lire("/proc/meminfo").splitlines():
            cle, _, reste = ligne.partition(":")
            if reste.split():
                infos[cle] = int(reste.split()[0]) * 1024
        total = infos.get("MemTotal", 0)
        return total - infos.get("MemAvailable", total), total

    @staticmethod
    def batterie():
        for bat in sorted(glob("/sys/class/power_supply/BAT*")):
            niveau = lire(f"{bat}/capacity")
            if niveau.isdigit():
                etat = {"Charging": "en charge", "Discharging": "sur batterie", "Full": "pleine",
                        "Not charging": "branchée"}.get(lire(f"{bat}/status"), "")
                return int(niveau), etat
        return None

    @staticmethod
    def allume_depuis():
        try:
            s = int(float(lire("/proc/uptime").split()[0]))
        except (IndexError, ValueError):
            return "?"
        j, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        return (f"{j} j " if j else "") + f"{h} h {s // 60:02d}"

    def adresse(self):
        if time.time() - self._ip_lue > 30:  # le Wi-Fi peut changer
            self.ip, self._ip_lue = adresse_ip(), time.time()
        return self.ip


# ---------------------------------------------------------------- écrans

class Ecran:
    titre = ""

    def __init__(self, app):
        self.app = app

    def action(self, a):
        pass

    def tick(self):
        """Appelé chaque seconde ; True s'il faut redessiner."""
        return False

    def clic(self, x, y):
        pass

    def glisser(self, dy):
        pass

    def dessiner(self, s):
        pass


class Liste(Ecran):
    """Liste verticale : (texte, détail, fonction appelée sur OK)."""

    def __init__(self, app, titre, elements=None, vide="Rien ici."):
        super().__init__(app)
        self.titre = titre
        self.elements = elements or []
        self.vide = vide
        self.sel = 0
        self.haut = 0
        self._glisse = 0.0

    def _geometrie(self):
        u = self.app.u
        y0, y1 = 15 * u, self.app.H - 10 * u
        h = 9 * u
        return y0, h, max(1, int((y1 - y0) // h))

    def _visible(self):
        _, _, n = self._geometrie()
        self.sel = max(0, min(self.sel, len(self.elements) - 1))
        if self.sel < self.haut:
            self.haut = self.sel
        elif self.sel >= self.haut + n:
            self.haut = self.sel - n + 1
        self.haut = max(0, min(self.haut, max(0, len(self.elements) - n)))

    def action(self, a):
        if not self.elements:
            return
        _, _, n = self._geometrie()
        if a == "haut":
            self.sel = (self.sel - 1) % len(self.elements)
        elif a == "bas":
            self.sel = (self.sel + 1) % len(self.elements)
        elif a in ("recul", "gauche"):
            self.sel = max(0, self.sel - n)
        elif a in ("avance", "droite"):
            self.sel = min(len(self.elements) - 1, self.sel + n)
        elif a == "ok":
            self.elements[self.sel][2]()
        self._visible()

    def clic(self, x, y):
        y0, h, n = self._geometrie()
        i = self.haut + int((y - y0) // h)
        if y >= y0 and 0 <= i < min(len(self.elements), self.haut + n):
            self.sel = i
            self.elements[i][2]()

    def glisser(self, dy):
        _, h, n = self._geometrie()
        self._glisse += dy
        pas = int(self._glisse / h)
        if pas:
            self._glisse -= pas * h
            self.haut = max(0, min(self.haut - pas, max(0, len(self.elements) - n)))
            self.sel = max(self.haut, min(self.sel, self.haut + n - 1))

    def dessiner(self, s):
        app, u = self.app, self.app.u
        if not self.elements:
            app.texte(s, self.vide, 5 * u, (app.W // 2, app.H // 2), TEXTE_DIM, centre=True, largeur=app.W - 16 * u)
            return
        self._visible()
        y0, h, n = self._geometrie()
        x, larg = 6 * u, app.W - 12 * u
        police, police_d = app.police(int(4.6 * u)), app.police(int(3.4 * u))
        for i in range(self.haut, min(len(self.elements), self.haut + n)):
            nom, detail, _ = self.elements[i]
            y = y0 + (i - self.haut) * h
            rect = pygame.Rect(x, y + 0.6 * u, larg, h - 1.2 * u)
            if i == self.sel:
                pygame.draw.rect(s, PANNEAU_SEL, rect, border_radius=int(1.5 * u))
                pygame.draw.rect(s, app.accent, (x, rect.y + u, int(0.8 * u), rect.h - 2 * u), border_radius=int(0.4 * u))
            larg_d = 0
            if detail:
                img = police_d.render(app.ajuster(police_d, detail, larg * 0.35), True, TEXTE_DIM)
                larg_d = img.get_width() + 4 * u
                s.blit(img, (x + larg - img.get_width() - 3 * u, rect.centery - img.get_height() // 2))
            img = police.render(app.ajuster(police, nom, larg - 6 * u - larg_d), True, TEXTE)
            s.blit(img, (x + 3 * u, rect.centery - img.get_height() // 2))
        if len(self.elements) > n:  # ascenseur
            zone = n * h
            hb = max(4 * u, zone * n / len(self.elements))
            yb = y0 + (zone - hb) * self.haut / max(1, len(self.elements) - n)
            pygame.draw.rect(s, PANNEAU_SEL, (app.W - 3.5 * u, yb, 0.8 * u, hb), border_radius=int(0.4 * u))
        app.texte(s, f"{self.sel + 1} / {len(self.elements)}", int(3 * u), (app.W - 6 * u, app.H - 6 * u), TEXTE_DIM, droite=True)


class Accueil(Ecran):
    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.tuiles = [
            ("Films", ROUGE, "films", app.ouvrir_films),
            ("Chaînes TV", BLEU, "tv", app.ouvrir_tv),
            ("Jeux", VERT, "jeux", app.ouvrir_jeux),
            ("Système", ORANGE, "systeme", app.ouvrir_systeme),
            ("Options", VIOLET, "options", app.ouvrir_options),
        ]
        self.resume = ""
        self._compteur = 0

    def _rects(self):
        app, u = self.app, self.app.u
        n, ecart = len(self.tuiles), 3 * u
        larg = min((app.W - 12 * u - (n - 1) * ecart) / n, 40 * u)
        haut = larg * 1.15
        x0 = (app.W - (n * larg + (n - 1) * ecart)) / 2
        y0 = (app.H - haut) / 2
        return [pygame.Rect(x0 + i * (larg + ecart), y0, larg, haut) for i in range(n)]

    def action(self, a):
        if a in ("gauche", "haut"):
            self.sel = (self.sel - 1) % len(self.tuiles)
        elif a in ("droite", "bas"):
            self.sel = (self.sel + 1) % len(self.tuiles)
        elif a == "ok":
            self.tuiles[self.sel][3]()

    def clic(self, x, y):
        for i, r in enumerate(self._rects()):
            if r.collidepoint(x, y):
                self.sel = i
                self.tuiles[i][3]()

    def tick(self):
        self._compteur += 1
        if self._compteur % 2 and self.resume:
            return False
        pc = self.app.pc
        morceaux = [f"Processeur {pc.cpu():.0f} %"]
        utilise, total = pc.memoire()
        if total:
            morceaux.append(f"Mémoire {utilise / 2**30:.1f} / {total / 2**30:.1f} Go".replace(".", ","))
        t = pc.temperature()
        if t:
            morceaux.append(f"{t:.0f} °C")
        b = pc.batterie()
        if b:
            morceaux.append(f"Batterie {b[0]} %")
        self.resume = "   ·   ".join(morceaux)
        return True

    def dessiner(self, s):
        app, u = self.app, self.app.u
        for i, (nom, couleur, icone, _) in enumerate(self.tuiles):
            r = self._rects()[i]
            choisi = i == self.sel
            if choisi:
                r = r.inflate(2 * u, 2 * u)
                fond = tuple(int(c * 0.30 + p * 0.70) for c, p in zip(couleur, PANNEAU))
                pygame.draw.rect(s, fond, r, border_radius=int(3 * u))
                pygame.draw.rect(s, couleur, r, width=max(2, int(0.6 * u)), border_radius=int(3 * u))
            else:
                pygame.draw.rect(s, PANNEAU, r, border_radius=int(3 * u))
            dessiner_icone(s, icone, (r.centerx, r.y + r.h * 0.42), r.w * 0.28, TEXTE if choisi else couleur)
            app.texte(s, nom, int(4.6 * u), (r.centerx, r.y + r.h * 0.80), TEXTE if choisi else TEXTE_DIM,
                      centre=True, gras=choisi, largeur=r.w - 2 * u)
        if self.resume:
            app.texte(s, self.resume, int(3.4 * u), (app.W // 2, app.H - 15 * u), TEXTE_DIM, centre=True)


class EcranSysteme(Ecran):
    titre = "Système"

    def __init__(self, app):
        super().__init__(app)
        self.mesures = {}
        self.tick()

    def tick(self):
        pc = self.app.pc
        utilise, total = pc.memoire()
        try:
            disque = shutil.disk_usage("/")
        except OSError:
            disque = None
        self.mesures = {
            "cpu": pc.cpu(), "freq": pc.frequence(), "temp": pc.temperature(),
            "mem": (utilise, total), "disque": disque, "bat": pc.batterie(),
            "depuis": pc.allume_depuis(), "ip": pc.adresse(),
        }
        return True

    def jauge(self, s, x, y, larg, nom, valeur, texte):
        app, u = self.app, self.app.u
        app.texte(s, nom, int(3.4 * u), (x, y), TEXTE_DIM)
        app.texte(s, texte, int(3.4 * u), (x + larg, y), TEXTE, droite=True)
        barre = pygame.Rect(x, y + 5.2 * u, larg, 1.8 * u)
        pygame.draw.rect(s, PANNEAU, barre, border_radius=int(0.9 * u))
        if valeur is not None:
            v = max(0.0, min(1.0, valeur))
            couleur = VERT if v < 0.6 else ORANGE if v < 0.85 else ROUGE
            pygame.draw.rect(s, couleur, (barre.x, barre.y, max(barre.h, barre.w * v), barre.h), border_radius=int(0.9 * u))

    def dessiner(self, s):
        app, u, pc, m = self.app, self.app.u, self.app.pc, self.mesures
        col = (app.W - 18 * u) / 2
        xg, xd, y0 = 6 * u, 12 * u + col, 16 * u
        lignes = [
            ("Modèle", pc.modele), ("Processeur", pc.processeur), ("Cœurs", str(pc.coeurs)),
            ("Système", pc.systeme), ("Noyau", pc.noyau), ("Écran", f"{app.W} × {app.H}"),
            ("Allumé depuis", m["depuis"]), ("Adresse", m["ip"]),
            ("Télécommande", f"http://{m['ip']}:{app.port}"),
        ]
        pas = (app.H - y0 - 12 * u) / len(lignes)
        for i, (nom, val) in enumerate(lignes):
            y = y0 + i * pas
            app.texte(s, nom, int(3.4 * u), (xg, y), TEXTE_DIM)
            app.texte(s, val, int(3.8 * u), (xg + col * 0.36, y - 0.2 * u), TEXTE, largeur=col * 0.64)

        jauges = []
        jauges.append(("Processeur", m["cpu"] / 100, f"{m['cpu']:.0f} %"))
        if m["freq"]:
            jauges.append(("Fréquence", None, f"{m['freq']:.0f} MHz"))
        if m["temp"]:
            jauges.append(("Température", (m["temp"] - 30) / 65, f"{m['temp']:.0f} °C"))
        utilise, total = m["mem"]
        if total:
            jauges.append(("Mémoire", utilise / total,
                           f"{taille_lisible(utilise)} / {taille_lisible(total)}"))
        if m["disque"]:
            d = m["disque"]
            jauges.append(("Stockage", d.used / d.total, f"{taille_lisible(d.free)} libres sur {taille_lisible(d.total)}"))
        if m["bat"]:
            niveau, etat = m["bat"]
            jauges.append(("Batterie", 1 - niveau / 100, f"{niveau} %  {etat}".strip()))
        pas = (app.H - y0 - 12 * u) / max(len(jauges), 1)
        for i, (nom, val, texte) in enumerate(jauges):
            self.jauge(s, xd, y0 + i * pas, col, nom, val, texte)


def dessiner_icone(s, nom, centre, r, couleur):
    cx, cy = centre
    e = max(2, int(r * 0.12))
    if nom == "films":
        pygame.draw.circle(s, couleur, (cx, cy), r, e)
        pygame.draw.polygon(s, couleur, [(cx - r * 0.3, cy - r * 0.45), (cx - r * 0.3, cy + r * 0.45), (cx + r * 0.5, cy)])
    elif nom == "tv":
        ecran = pygame.Rect(0, 0, r * 2, r * 1.3)
        ecran.center = (cx, cy + r * 0.15)
        pygame.draw.rect(s, couleur, ecran, e, border_radius=int(r * 0.15))
        pygame.draw.line(s, couleur, (cx, ecran.y), (cx - r * 0.45, ecran.y - r * 0.5), e)
        pygame.draw.line(s, couleur, (cx, ecran.y), (cx + r * 0.45, ecran.y - r * 0.5), e)
    elif nom == "jeux":
        corps = pygame.Rect(0, 0, r * 2.2, r * 1.2)
        corps.center = (cx, cy)
        pygame.draw.rect(s, couleur, corps, e, border_radius=int(r * 0.5))
        gx = cx - r * 0.55
        pygame.draw.line(s, couleur, (gx - r * 0.28, cy), (gx + r * 0.28, cy), e)
        pygame.draw.line(s, couleur, (gx, cy - r * 0.28), (gx, cy + r * 0.28), e)
        pygame.draw.circle(s, couleur, (cx + r * 0.45, cy + r * 0.12), r * 0.13)
        pygame.draw.circle(s, couleur, (cx + r * 0.72, cy - r * 0.15), r * 0.13)
    elif nom == "systeme":
        for i, h in enumerate((0.6, 1.2, 0.9, 1.6)):
            x = cx - r * 0.9 + i * r * 0.55
            pygame.draw.rect(s, couleur, (x, cy + r * 0.8 - r * h, r * 0.35, r * h), border_radius=int(r * 0.06))
    elif nom == "options":
        rect = pygame.Rect(0, 0, r * 1.8, r * 1.8)
        rect.center = (cx, cy)
        for k in range(e):  # un arc épais de pygame laisse des trous : on en empile des fins
            pygame.draw.arc(s, couleur, rect.inflate(-2 * k, -2 * k), 2.2, 7.2, 2)
        pygame.draw.line(s, couleur, (cx, cy - r * 1.05), (cx, cy - r * 0.15), e)


# ---------------------------------------------------------------- application

class App:
    def __init__(self, fenetre=None):
        self.cfg = charger_config()
        self.port = int(self.cfg.get("port_telecommande", 8765))
        pygame.display.init()
        pygame.font.init()
        pygame.joystick.init()
        pygame.display.set_caption("Salon")
        if fenetre:
            self.ecran = pygame.display.set_mode(fenetre)
        else:
            self.ecran = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        self.W, self.H = self.ecran.get_size()
        self.u = self.H / 100
        self.toile = pygame.Surface((self.W, self.H)) if self.cfg.get("ecran_retourne") else self.ecran
        pygame.key.set_repeat(300, 60)
        pygame.event.set_blocked([pygame.ACTIVEEVENT, pygame.TEXTINPUT, pygame.TEXTEDITING])

        self.pc = InfosPC()
        self._polices = {}
        self.accent = BLEU
        self.pile = [Accueil(self)]
        self.pile[0].tick()
        self.sale = True
        self.actif = True
        self.enfant = None
        self.genre_enfant = None
        self.toast = None
        self.minute = None
        self.dernier_tick = 0.0
        self.appui = None
        self.dir_tenue = None
        self.manettes = {}     # instance_id -> objet (gardé ouvert)
        self.controleurs = set()  # instance_id gérés par l'API « manette standard »
        self.boutons = {}      # instance_id -> boutons enfoncés
        self.axes = {}
        self.sdlctl = None
        try:
            from pygame._sdl2 import controller
            controller.init()
            self.sdlctl = controller
        except Exception:
            pass
        self.serveur = None
        self.demarrer_telecommande()

    # ------------------------------------------------ dessin

    def police(self, taille, gras=False):
        cle = (taille, gras)
        if cle not in self._polices:
            # Chemin direct : évite que pygame lance fc-list (lent au premier appel sur un petit PC).
            fichier = f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if gras else ''}.ttf"
            if os.path.exists(fichier):
                self._polices[cle] = pygame.font.Font(fichier, taille)
            else:
                self._polices[cle] = pygame.font.SysFont("dejavusans,notosans,ubuntu,freesans", taille, bold=gras)
        return self._polices[cle]

    @staticmethod
    def ajuster(police, texte, largeur):
        if police.size(texte)[0] <= largeur:
            return texte
        while texte and police.size(texte + "…")[0] > largeur:
            texte = texte[:-1]
        return texte + "…"

    def texte(self, s, texte, taille, pos, couleur, centre=False, droite=False, gras=False, largeur=None):
        police = self.police(taille, gras)
        if largeur:
            texte = self.ajuster(police, texte, largeur)
        img = police.render(texte, True, couleur)
        x, y = pos
        if centre:
            x, y = x - img.get_width() // 2, y - img.get_height() // 2
        elif droite:
            x -= img.get_width()
        s.blit(img, (x, y))
        return img.get_rect(topleft=(x, y))

    def dessiner(self):
        s, u = self.toile, self.u
        s.fill(FOND)
        courant = self.pile[-1]
        if len(self.pile) > 1:
            self.texte(s, "‹", int(8 * u), (4 * u, 1.5 * u), TEXTE_DIM)
            self.texte(s, courant.titre, int(6 * u), (10 * u, 3 * u), TEXTE, gras=True, largeur=self.W * 0.6)
        else:
            self.texte(s, "Salon", int(6 * u), (6 * u, 3 * u), TEXTE, gras=True)
        self.texte(s, time.strftime("%H:%M"), int(5 * u), (self.W - 6 * u, 3.4 * u), TEXTE_DIM, droite=True)
        courant.dessiner(s)
        aide = f"Téléphone : http://{self.pc.adresse()}:{self.port}" if self.serveur else ""
        self.texte(s, aide, int(2.8 * u), (self.W // 2, self.H - 4 * u), TEXTE_DIM, centre=True)
        if self.toast:
            police = self.police(int(3.8 * u))
            img = police.render(self.ajuster(police, self.toast[0], self.W - 16 * u), True, TEXTE)
            r = img.get_rect(center=(self.W // 2, self.H - 12 * u)).inflate(5 * u, 3 * u)
            pygame.draw.rect(s, PANNEAU_SEL, r, border_radius=int(1.5 * u))
            s.blit(img, img.get_rect(center=r.center))
        if s is not self.ecran:
            self.ecran.blit(pygame.transform.flip(s, True, True), (0, 0))
        pygame.display.flip()

    def notifier(self, texte, duree=4):
        self.toast = (texte, time.time() + duree)
        self.sale = True

    # ------------------------------------------------ navigation

    def ouvrir(self, ecran, accent=None):
        if accent:
            self.accent = accent
        self.pile.append(ecran)
        self.sale = True

    def retour(self):
        if len(self.pile) > 1:
            self.pile.pop()
        self.sale = True

    def confirmer(self, question, fonction):
        def oui():
            self.retour()
            fonction()
        self.ouvrir(Liste(self, question, [("Oui", "", oui), ("Non", "", self.retour)]))
        self.pile[-1].sel = 1

    # Films
    def ouvrir_films(self):
        racines = [Path(p).expanduser() for p in self.cfg.get("films", [])]
        racines = [p for p in racines if p.is_dir()]
        if len(racines) == 1:
            self.ouvrir_dossier(racines[0], "Films")
            return
        elements = [(p.name or str(p), str(p.parent), lambda p=p: self.ouvrir_dossier(p)) for p in racines]
        self.ouvrir(Liste(self, "Films", elements,
                          "Aucun dossier de films trouvé. Mets tes vidéos dans ~/Vidéos, "
                          "ou indique leurs dossiers dans ~/.config/salon/config.json."), ROUGE)

    def ouvrir_dossier(self, dossier, titre=None):
        dossiers, fichiers = [], []
        try:
            for e in os.scandir(dossier):
                if e.name.startswith("."):
                    continue
                if e.is_dir():
                    dossiers.append(e)
                elif Path(e.name).suffix.lower() in EXT_VIDEO:
                    fichiers.append(e)
        except OSError as err:
            self.notifier(f"Dossier illisible : {err.strerror}")
            return
        elements = [(d.name, "Dossier", lambda p=d.path: self.ouvrir_dossier(Path(p)))
                    for d in sorted(dossiers, key=lambda e: tri_naturel(e.name))]
        for f in sorted(fichiers, key=lambda e: tri_naturel(e.name)):
            try:
                taille = taille_lisible(f.stat().st_size)
            except OSError:
                taille = ""
            elements.append((Path(f.name).stem, taille, lambda p=f.path: self.lire_video(p)))
        self.ouvrir(Liste(self, titre or Path(dossier).name, elements, "Aucune vidéo dans ce dossier."), ROUGE)

    def lire_video(self, chemin):
        self.lancer_mpv(["--save-position-on-quit", chemin])

    # Chaînes TV
    def ouvrir_tv(self):
        ecran = Liste(self, "Chaînes TV", [], "Chargement des chaînes…")
        self.ouvrir(ecran, BLEU)

        def charger():
            source = str(self.cfg.get("chaines", ""))
            cache = CONFIG_DIR / "chaines-cache.m3u"
            texte = ""
            try:
                if source.startswith(("http://", "https://")):
                    import urllib.request  # chargé seulement ici : 6 Mo évités tant qu'on ne regarde pas la TV
                    try:
                        with urllib.request.urlopen(source, timeout=15) as r:
                            texte = r.read().decode("utf-8", "replace")
                        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                        cache.write_text(texte)
                    except OSError:
                        texte = cache.read_text() if cache.exists() else ""
                elif source:
                    texte = Path(source).expanduser().read_text(errors="replace")
            except OSError:
                texte = ""
            chaines = lire_m3u(texte)
            ecran.elements = [(nom, groupe, lambda i=i: self.regarder(chaines, i))
                              for i, (nom, groupe, _) in enumerate(chaines)]
            ecran.vide = ("Aucune chaîne. Vérifie la connexion, ou mets une liste M3U "
                          "dans « chaines » de ~/.config/salon/config.json.")
            pygame.event.post(pygame.event.Event(EV_REVEIL))

        threading.Thread(target=charger, daemon=True).start()

    def regarder(self, chaines, index):
        lignes = ["#EXTM3U"]
        for nom, _, url in chaines:
            lignes += [f"#EXTINF:-1,{nom}", url]
        try:
            PLAYLIST_TV.write_text("\n".join(lignes) + "\n")
        except OSError as e:
            self.notifier(f"Impossible de préparer la liste : {e.strerror}")
            return
        self.lancer_mpv([f"--playlist={PLAYLIST_TV}", f"--playlist-start={index}",
                         "--osd-playing-msg=${media-title}", "--osd-duration=2500"], tv=True)

    # Jeux
    def dossiers_cores(self):
        candidats = [self.cfg.get("cores_dir") or "",
                     ACCUEIL_DIR / ".config/retroarch/cores",
                     ACCUEIL_DIR / ".var/app/org.libretro.RetroArch/config/retroarch/cores",
                     "/usr/lib/x86_64-linux-gnu/libretro", "/usr/lib/i386-linux-gnu/libretro",
                     "/usr/lib/aarch64-linux-gnu/libretro", "/usr/lib/libretro", "/usr/lib64/libretro"]
        return [Path(c) for c in candidats if c and Path(c).is_dir()]

    def trouver_core(self, noms):
        dossiers = self.dossiers_cores()
        for nom in noms:
            for d in dossiers:
                if (d / f"{nom}.so").exists():
                    return d / f"{nom}.so"
        return None

    def commande_retroarch(self):
        c = self.cfg.get("retroarch") or "retroarch"
        if isinstance(c, list):
            return c
        if shutil.which(c):
            return [c]
        for base in ("/var/lib/flatpak", ACCUEIL_DIR / ".local/share/flatpak"):
            if (Path(base) / "app/org.libretro.RetroArch").is_dir():
                return ["flatpak", "run", "org.libretro.RetroArch"]
        return None

    def ouvrir_jeux(self):
        racine = Path(self.cfg.get("roms", "~/ROMs")).expanduser()
        elements = []
        for dossier, nom, cores, ext in SYSTEMES:
            jeux = self.lister_jeux(racine / dossier, ext)
            if jeux:
                detail = f"{len(jeux)} jeu{'x' if len(jeux) > 1 else ''}"
                if not self.trouver_core(cores):
                    detail += " · émulateur manquant"
                elements.append((nom, detail, lambda d=dossier, n=nom, c=cores, j=jeux: self.ouvrir_console(n, c, j)))
        self.ouvrir(Liste(self, "Jeux", elements,
                          f"Aucun jeu trouvé. Range-les dans {racine}/<console> "
                          "(nes, snes, megadrive, gb, gba, psx, n64…)."), VERT)

    @staticmethod
    def lister_jeux(dossier, extensions):
        ext = set(extensions.split())
        try:
            return sorted((e.path for e in os.scandir(dossier)
                           if e.is_file() and Path(e.name).suffix.lower() in ext),
                          key=lambda p: tri_naturel(Path(p).name))
        except OSError:
            return []

    def ouvrir_console(self, nom, cores, jeux):
        elements = [(nom_de_jeu(j), "", lambda j=j: self.jouer(j, nom, cores)) for j in jeux]
        self.ouvrir(Liste(self, nom, elements))

    def jouer(self, rom, nom, cores):
        cmd = self.commande_retroarch()
        if not cmd:
            self.notifier("RetroArch n'est pas installé (voir salon/README.md).")
            return
        core = self.trouver_core(cores)
        if not core:
            self.notifier(f"Aucun émulateur {nom} : installe « {cores[0].replace('_libretro', '')} » dans RetroArch.")
            return
        options = []
        try:
            leger = CONFIG_DIR / "retroarch-leger.cfg"
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            leger.write_text(RETROARCH_LEGER)
            options = [f"--appendconfig={leger}"]
        except OSError:
            pass
        self.lancer(cmd + options + ["-f", "-L", str(core), rom], "retroarch")

    # Système et options
    def ouvrir_systeme(self):
        self.ouvrir(EcranSysteme(self), ORANGE)

    def ouvrir_options(self):
        retourne = "oui" if self.cfg.get("ecran_retourne") else "non"
        elements = [
            ("Retourner l'écran (mode tente)", retourne, self.retourner_ecran),
            ("Mettre en veille", "", lambda: self.systemctl("suspend")),
            ("Redémarrer", "", lambda: self.confirmer("Redémarrer le PC ?", lambda: self.systemctl("reboot"))),
            ("Éteindre", "", lambda: self.confirmer("Éteindre le PC ?", lambda: self.systemctl("poweroff"))),
            ("Quitter Salon", "", self.quitter),
        ]
        self.ouvrir(Liste(self, "Options", elements), VIOLET)

    def retourner_ecran(self):
        self.cfg["ecran_retourne"] = not self.cfg.get("ecran_retourne")
        sauver_config(self.cfg)
        self.toile = pygame.Surface((self.W, self.H)) if self.cfg["ecran_retourne"] else self.ecran
        self.retour()
        self.ouvrir_options()
        self.pile[-1].sel = 0

    def systemctl(self, verbe):
        subprocess.Popen(["systemctl", verbe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def quitter(self):
        self.actif = False

    # ------------------------------------------------ programmes externes

    def lancer(self, cmd, genre):
        try:
            self.enfant = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
            self.genre_enfant = genre
        except OSError as e:
            self.notifier(f"Impossible de lancer {cmd[0]} : {e.strerror}")

    def lancer_mpv(self, args, tv=False):
        mpv = list(self.cfg.get("mpv") or DEFAUTS["mpv"])
        if not shutil.which(mpv[0]):
            self.notifier("mpv n'est pas installé : sudo apt install mpv")
            return
        try:
            MPV_SOCKET.unlink()
        except OSError:
            pass
        self.lancer(mpv + [f"--input-ipc-server={MPV_SOCKET}"] + args, "tv" if tv else "mpv")

    def mpv(self, *commande):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(str(MPV_SOCKET))
                s.sendall((json.dumps({"command": list(commande)}) + "\n").encode())
        except OSError:
            pass

    def fin_enfant(self):
        self.enfant = None
        self.genre_enfant = None
        self.dir_tenue = None
        self.sale = True

    def arreter_enfant(self):
        if self.enfant and self.enfant.poll() is None:
            self.enfant.terminate()

    # ------------------------------------------------ commandes

    def commande(self, a, source="local"):
        if self.enfant:
            g = self.genre_enfant
            if g in ("mpv", "tv"):
                table = {
                    "ok": ("cycle", "pause"), "pause": ("cycle", "pause"),
                    "vol+": ("add", "volume", 5), "vol-": ("add", "volume", -5),
                    "retour": ("quit",), "accueil": ("quit",), "stop": ("quit",),
                }
                if g == "tv":
                    table.update({"haut": ("playlist-prev",), "bas": ("playlist-next",),
                                  "gauche": ("add", "volume", -5), "droite": ("add", "volume", 5),
                                  "recul": ("playlist-prev",), "avance": ("playlist-next",)})
                else:
                    table.update({"gauche": ("seek", -10), "droite": ("seek", 30),
                                  "recul": ("seek", -60), "avance": ("seek", 60),
                                  "haut": ("add", "volume", 5), "bas": ("add", "volume", -5)})
                if a in table:
                    self.mpv(*table[a])
            elif source == "telephone":
                if a in ("stop", "accueil"):
                    self.arreter_enfant()
                elif a in ("vol+", "vol-"):
                    volume_systeme(5 if a == "vol+" else -5)
            return
        if a in ("vol+", "vol-"):
            volume_systeme(5 if a == "vol+" else -5)
            return
        if a == "accueil":
            del self.pile[1:]
        elif a == "retour":
            self.retour()
        elif a != "stop":
            self.pile[-1].action(a)
        self.sale = True

    def coordonnees(self, pos):
        x, y = pos
        if self.cfg.get("ecran_retourne"):
            x, y = self.W - x, self.H - y
        return x, y

    def traiter(self, e):
        t = e.type
        if t == pygame.QUIT:
            self.actif = False
        elif t == EV_TELE:
            self.commande(e.action, "telephone")
        elif t == EV_REVEIL:
            self.sale = True
        elif t == pygame.KEYDOWN:
            touches = {
                pygame.K_UP: "haut", pygame.K_DOWN: "bas", pygame.K_LEFT: "gauche", pygame.K_RIGHT: "droite",
                pygame.K_RETURN: "ok", pygame.K_KP_ENTER: "ok", pygame.K_SPACE: "ok",
                pygame.K_ESCAPE: "retour", pygame.K_BACKSPACE: "retour", pygame.K_HOME: "accueil",
                pygame.K_PAGEUP: "recul", pygame.K_PAGEDOWN: "avance",
                pygame.K_PLUS: "vol+", pygame.K_KP_PLUS: "vol+", pygame.K_MINUS: "vol-", pygame.K_KP_MINUS: "vol-",
            }
            if e.key in touches:
                self.commande(touches[e.key])
        elif t == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.appui = [self.coordonnees(e.pos), 0.0]
        elif t == pygame.MOUSEMOTION and self.appui and e.buttons[0]:
            dy = -e.rel[1] if self.cfg.get("ecran_retourne") else e.rel[1]
            self.appui[1] += abs(dy)
            if self.appui[1] > 2 * self.u:
                self.pile[-1].glisser(dy)
                self.sale = True
        elif t == pygame.MOUSEBUTTONUP and e.button == 1 and self.appui:
            (x, y), parcouru = self.appui
            self.appui = None
            if parcouru <= 2 * self.u and not self.enfant:
                if len(self.pile) > 1 and x < 12 * self.u and y < 12 * self.u:
                    self.retour()
                else:
                    self.pile[-1].clic(x, y)
                self.sale = True
        elif t == pygame.MOUSEWHEEL:
            self.commande("haut" if e.y > 0 else "bas")
        else:
            self.traiter_manette(e)

    # ------------------------------------------------ manettes

    def traiter_manette(self, e):
        t = e.type
        sdl = self.sdlctl
        if sdl and t == getattr(pygame, "CONTROLLERDEVICEADDED", -1):
            try:
                c = sdl.Controller(e.device_index)
                iid = c.as_joystick().get_instance_id()
                self.manettes[iid] = c
                self.controleurs.add(iid)
            except Exception:
                pass
            return
        if t == pygame.JOYDEVICEADDED:
            if sdl and sdl.is_controller(e.device_index):
                return  # reçu aussi en CONTROLLERDEVICEADDED
            j = pygame.joystick.Joystick(e.device_index)
            self.manettes[j.get_instance_id()] = j
            return
        if t in (pygame.JOYDEVICEREMOVED, getattr(pygame, "CONTROLLERDEVICEREMOVED", -1)):
            self.manettes.pop(e.instance_id, None)
            self.controleurs.discard(e.instance_id)
            self.dir_tenue = None
            return

        if sdl and t in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            noms = {
                pygame.CONTROLLER_BUTTON_A: "ok", pygame.CONTROLLER_BUTTON_B: "retour",
                pygame.CONTROLLER_BUTTON_X: "pause", pygame.CONTROLLER_BUTTON_Y: "pause",
                pygame.CONTROLLER_BUTTON_BACK: "select", pygame.CONTROLLER_BUTTON_START: "start",
                pygame.CONTROLLER_BUTTON_GUIDE: "accueil",
                pygame.CONTROLLER_BUTTON_LEFTSHOULDER: "recul", pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: "avance",
                pygame.CONTROLLER_BUTTON_DPAD_UP: "haut", pygame.CONTROLLER_BUTTON_DPAD_DOWN: "bas",
                pygame.CONTROLLER_BUTTON_DPAD_LEFT: "gauche", pygame.CONTROLLER_BUTTON_DPAD_RIGHT: "droite",
            }
            self.bouton(e.instance_id, noms.get(e.button), t == pygame.CONTROLLERBUTTONDOWN)
        elif sdl and t == pygame.CONTROLLERAXISMOTION:
            if e.axis in (pygame.CONTROLLER_AXIS_LEFTX, pygame.CONTROLLER_AXIS_LEFTY):
                self.stick(e.instance_id, "x" if e.axis == pygame.CONTROLLER_AXIS_LEFTX else "y", e.value / 32767)
        elif t in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) and e.instance_id not in self.controleurs:
            # Manette non reconnue par SDL : disposition la plus courante (type Xbox).
            noms = {0: "ok", 1: "retour", 2: "pause", 3: "pause", 4: "recul", 5: "avance",
                    6: "select", 7: "start", 8: "accueil"}
            self.bouton(e.instance_id, noms.get(e.button), t == pygame.JOYBUTTONDOWN)
        elif t == pygame.JOYHATMOTION and e.instance_id not in self.controleurs:
            hx, hy = e.value
            direction = "gauche" if hx < 0 else "droite" if hx > 0 else "haut" if hy > 0 else "bas" if hy < 0 else None
            if direction:
                self.tenir(direction)
            else:
                self.dir_tenue = None
        elif t == pygame.JOYAXISMOTION and e.instance_id not in self.controleurs and e.axis in (0, 1):
            self.stick(e.instance_id, "x" if e.axis == 0 else "y", e.value)

    def bouton(self, iid, nom, enfonce):
        if not nom:
            return
        tenus = self.boutons.setdefault(iid, set())
        if not enfonce:
            tenus.discard(nom)
            if self.dir_tenue and self.dir_tenue[0] == nom:
                self.dir_tenue = None
            return
        tenus.add(nom)
        if {"select", "start"} <= tenus:   # Select + Start : quitter le jeu ou la vidéo
            if self.enfant:
                self.arreter_enfant()
            return
        if self.genre_enfant == "retroarch":
            return  # la manette appartient au jeu
        nom = {"select": "accueil", "start": "pause"}.get(nom, nom)
        if nom in ("haut", "bas", "gauche", "droite"):
            self.tenir(nom)
        else:
            self.commande(nom)

    def stick(self, iid, axe, valeur):
        axes = self.axes.setdefault(iid, {"x": 0.0, "y": 0.0})
        axes[axe] = valeur
        x, y = axes["x"], axes["y"]
        if max(abs(x), abs(y)) < 0.5:
            if self.dir_tenue and self.dir_tenue[2] == "stick":
                self.dir_tenue = None
            return
        direction = ("droite" if x > 0 else "gauche") if abs(x) > abs(y) else ("bas" if y > 0 else "haut")
        if not self.dir_tenue or self.dir_tenue[0] != direction:
            if self.genre_enfant != "retroarch":
                self.tenir(direction, "stick")

    def tenir(self, direction, source="croix"):
        if self.genre_enfant == "retroarch":
            return
        self.commande(direction)
        self.dir_tenue = [direction, time.time() + 0.35, source]

    def repeter(self):
        if self.dir_tenue and time.time() >= self.dir_tenue[1]:
            self.commande(self.dir_tenue[0])
            self.dir_tenue[1] = time.time() + 0.09

    # ------------------------------------------------ télécommande (téléphone)

    def demarrer_telecommande(self):
        # Mini-serveur fait main : le module http.server de Python coûterait 5 Mo de plus.
        try:
            self.serveur = socket.create_server(("0.0.0.0", self.port))
        except OSError as e:
            print(f"salon : télécommande indisponible sur le port {self.port} ({e.strerror})", file=sys.stderr)
            self.serveur = None
            return
        threading.Thread(target=self.servir, daemon=True).start()

    def servir(self):
        while True:
            try:
                client, _ = self.serveur.accept()
            except OSError:
                return  # serveur fermé
            with client:
                try:
                    client.settimeout(2)
                    requete = b""
                    while b"\r\n\r\n" not in requete and len(requete) < 8192:
                        morceau = client.recv(2048)
                        if not morceau:
                            break
                        requete += morceau
                    methode, chemin = requete.split(b"\r\n", 1)[0].decode("latin-1").split()[:2]
                    statut, genre, corps = self.repondre(methode, chemin)
                    client.sendall(
                        (f"HTTP/1.1 {statut}\r\nContent-Type: {genre}\r\nContent-Length: {len(corps)}\r\n"
                         "Cache-Control: no-store\r\nConnection: close\r\n\r\n").encode() + corps)
                except (OSError, ValueError):
                    pass

    def repondre(self, methode, chemin):
        url = urlparse(chemin)
        if methode == "GET" and url.path in ("/", "/index.html"):
            return "200 OK", "text/html; charset=utf-8", PAGE_TELECOMMANDE.encode()
        if methode == "GET" and url.path == "/etat":
            etat = {"ecran": self.pile[-1].titre or "Accueil", "lecture": self.genre_enfant}
            return "200 OK", "application/json", json.dumps(etat).encode()
        if methode == "POST" and url.path == "/action":
            action = parse_qs(url.query).get("a", [""])[0]
            if action in ACTIONS:
                pygame.event.post(pygame.event.Event(EV_TELE, action=action))
                return "204 No Content", "text/plain", b""
            return "400 Bad Request", "text/plain", b"action inconnue"
        return "404 Not Found", "text/plain", b"introuvable"

    def fermer_telecommande(self):
        if self.serveur:
            try:
                self.serveur.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.serveur.close()
            self.serveur = None

    # ------------------------------------------------ boucle

    def boucle(self):
        # Pas de pygame.event.wait : dès qu'une manette est branchée, SDL y vérifie les événements
        # toutes les millisecondes (11 fois plus de processeur, mesuré). On dort entre deux tours :
        # 16 ms juste après une action (fluide), 50 ms au repos, 100 ms pendant un film ou un jeu.
        derniere_action = 0.0
        while self.actif:
            evenements = pygame.event.get()
            for e in evenements:
                self.traiter(e)
            if evenements:
                derniere_action = time.time()
            self.repeter()
            if self.enfant and self.enfant.poll() is not None:
                self.fin_enfant()
            maintenant = time.time()
            if maintenant - self.dernier_tick >= 1:
                self.dernier_tick = maintenant
                if not self.enfant and self.pile[-1].tick():
                    self.sale = True
                minute = time.strftime("%H:%M")
                if minute != self.minute:
                    self.minute, self.sale = minute, True
                if self.toast and maintenant > self.toast[1]:
                    self.toast, self.sale = None, True
            if self.sale and not self.enfant:
                self.sale = False
                self.dessiner()
            if self.enfant:
                time.sleep(0.1)
            elif self.dir_tenue or time.time() - derniere_action < 2:
                time.sleep(0.016)
            else:
                time.sleep(0.05)
        self.arreter_enfant()
        self.fermer_telecommande()
        pygame.quit()


PAGE_TELECOMMANDE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0e1016">
<title>Salon</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0e1016;color:#eceff4;font:16px system-ui,sans-serif;
 min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;padding:16px;
 user-select:none;-webkit-user-select:none;touch-action:manipulation}
#etat{color:#8a92a3;min-height:1.2em;text-align:center}
.croix{display:grid;grid-template-columns:repeat(3,84px);grid-template-rows:repeat(3,84px);gap:10px}
.ligne{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;max-width:300px}
button{border:0;border-radius:18px;background:#1c202a;color:#eceff4;font:600 18px system-ui,sans-serif;
 min-width:84px;height:64px;padding:0 12px}
.croix button{height:84px;font-size:28px}
button:active{background:#2e3546}
.ok{background:#4299e1;border-radius:50%}
.ok:active{background:#2b6cb0}
.stop{color:#e5484d}
</style></head><body>
<div id="etat">Salon</div>
<div class="croix">
 <span></span><button data-a="haut" data-repete>▲</button><span></span>
 <button data-a="gauche" data-repete>◀</button><button class="ok" data-a="ok">OK</button><button data-a="droite" data-repete>▶</button>
 <span></span><button data-a="bas" data-repete>▼</button><span></span>
</div>
<div class="ligne">
 <button data-a="retour">Retour</button><button data-a="accueil">Accueil</button><button data-a="pause">⏯</button>
 <button data-a="recul">⏪</button><button data-a="avance">⏩</button><button class="stop" data-a="stop">■ Stop</button>
 <button data-a="vol-">Vol −</button><button data-a="vol+">Vol +</button>
</div>
<script>
const envoyer = a => { fetch('/action?a=' + a, {method: 'POST'}).catch(() => {}); if (navigator.vibrate) navigator.vibrate(12); };
document.querySelectorAll('button').forEach(b => {
  let t1, t2;
  const fin = () => { clearTimeout(t1); clearInterval(t2); };
  b.addEventListener('pointerdown', e => {
    e.preventDefault(); envoyer(b.dataset.a);
    if (b.hasAttribute('data-repete')) t1 = setTimeout(() => { t2 = setInterval(() => envoyer(b.dataset.a), 110); }, 380);
  });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(n => b.addEventListener(n, fin));
});
const etat = document.getElementById('etat');
const noms = {mpv: 'Vidéo en cours', tv: 'TV en cours (▲▼ change de chaîne)', retroarch: 'Jeu en cours'};
setInterval(() => fetch('/etat').then(r => r.json()).then(e => {
  etat.textContent = e.lecture ? noms[e.lecture] : e.ecran;
}).catch(() => { etat.textContent = 'PC injoignable'; }), 2000);
</script></body></html>
"""


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(f"Salon {VERSION}")
        return 0
    if pygame.version.vernum[0] < 2:
        print("Salon a besoin de pygame 2 (Ubuntu 22.04 ou plus récent).", file=sys.stderr)
        return 1
    fenetre = None
    if "--fenetre" in args:
        fenetre = (1280, 720)
    app = App(fenetre)
    try:
        app.boucle()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
