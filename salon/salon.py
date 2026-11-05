#!/usr/bin/env python3
"""Salon : jeux rétro, Netflix et infos du PC, en plein écran.

Pilotable au clavier, à la manette, au tactile et depuis un téléphone (page web
sur le port 8765, qui sert aussi à envoyer des jeux). Conçu pour les petits PC :
rien n'est redessiné tant que rien ne change, et pendant un jeu ou Netflix Salon
rend au système presque toute sa mémoire.
"""

import json
import math
import os
import re
import gc
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from glob import glob
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# La manette doit rester lue quand le jeu ou Netflix est devant (Select + Start pour quitter).
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


DEFAUTS = {
    "roms": str(ACCUEIL_DIR / "ROMs"),
    "retroarch": "retroarch",
    "cores_dir": "",
    "port_telecommande": 8765,
    "ecran_retourne": False,
    "netflix": "https://www.netflix.com/browse",
    # Navigateurs capables de lire les vidéos protégées (DRM), essayés dans l'ordre.
    "navigateur": "",
}
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

NOMS = {d: n for d, n, _, _ in SYSTEMES}
# Fichiers acceptés à l'envoi depuis le téléphone (les .bin des jeux PS1 accompagnent leur .cue).
EXT_ENVOI = {d: set(ext.split()) | ({".bin"} if d == "psx" else set()) for d, _, _, ext in SYSTEMES}

ACTIONS = {"haut", "bas", "gauche", "droite", "ok", "retour", "accueil",
           "pause", "avance", "recul", "vol+", "vol-", "stop"}

# Couleurs
FOND_HAUT = (16, 20, 33)
FOND_BAS = (7, 9, 15)
PANNEAU = (21, 26, 40)
PANNEAU_HAUT = (29, 35, 53)
PANNEAU_SEL = (38, 45, 66)
BORD = (48, 56, 80)
PISTE = (40, 47, 68)
TEXTE = (242, 244, 249)
TEXTE_DIM = (132, 142, 166)
VERT = (52, 205, 125)
ORANGE = (255, 154, 60)
ROUGE = (255, 84, 98)
BLEU = (64, 156, 255)
VIOLET = (158, 118, 255)
ROSE = (240, 80, 150)

EV_TELE = pygame.USEREVENT + 1     # action venue du téléphone
EV_REVEIL = pygame.USEREVENT + 2   # une tâche de fond a fini : redessiner
EV_JEU = pygame.USEREVENT + 3      # un jeu vient d'arriver depuis le téléphone


# ---------------------------------------------------------------- configuration

def charger_config():
    cfg = dict(DEFAUTS)
    try:
        cfg.update(json.loads(CONFIG_FICHIER.read_text()))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"salon : {CONFIG_FICHIER} illisible ({e}), réglages par défaut", file=sys.stderr)
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


def deviner_console(nom):
    """Console d'après l'extension, quand une seule console l'utilise (.sfc → snes ; .zip → ?)."""
    ext = Path(nom).suffix.lower()
    possibles = [d for d, e in EXT_ENVOI.items() if ext in e]
    return possibles[0] if len(possibles) == 1 else None


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
        maxi = lire("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
        self.freq_max = int(maxi) / 1000 if maxi.isdigit() else None
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


# ---------------------------------------------------------------- dessin

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
POIDS = {"r": "Regular", "m": "Medium", "sb": "SemiBold", "b": "Bold"}


def melange(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def niveau_couleur(v, inverse=False):
    """Vert, orange ou rouge selon la charge (inverse : pour la batterie, plein = vert)."""
    if inverse:
        return VERT if v > 0.3 else ORANGE if v > 0.15 else ROUGE
    return VERT if v < 0.6 else ORANGE if v < 0.85 else ROUGE


def arc_plein(s, couleur, centre, r_ext, r_int, debut, fin, bouts_ronds=True):
    """Arc épais sans trous (angles en radians, 0 = droite, sens des aiguilles d'une montre)."""
    cx, cy = centre
    n = max(6, int(abs(fin - debut) * r_ext / 3))
    ext = [(cx + r_ext * math.cos(debut + (fin - debut) * k / n), cy + r_ext * math.sin(debut + (fin - debut) * k / n))
           for k in range(n + 1)]
    inte = [(cx + r_int * math.cos(debut + (fin - debut) * k / n), cy + r_int * math.sin(debut + (fin - debut) * k / n))
            for k in range(n, -1, -1)]
    pygame.draw.polygon(s, couleur, ext + inte)
    if bouts_ronds:
        rm, e = (r_ext + r_int) / 2, (r_ext - r_int) / 2
        for a in (debut, fin):
            pygame.draw.circle(s, couleur, (cx + rm * math.cos(a), cy + rm * math.sin(a)), e)


def dessiner_icone(s, nom, centre, r, couleur):
    """Icônes géométriques ; dessinées en grand puis réduites par Pinceau.icone (lissage)."""
    cx, cy = centre
    e = max(2, r * 0.14)
    ligne = lambda a, b: pygame.draw.line(s, couleur, a, b, int(e))  # noqa: E731
    point = lambda p, rr: pygame.draw.circle(s, couleur, p, rr)  # noqa: E731
    vide = (*couleur[:3], 0)
    if nom == "video":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.72, 2 * r, 1.44 * r), int(e), border_radius=int(r * 0.22))
        pygame.draw.polygon(s, couleur, [(cx - r * 0.25, cy - r * 0.36), (cx - r * 0.25, cy + r * 0.36), (cx + r * 0.38, cy)])
    elif nom in ("jeux", "jeu"):
        pygame.draw.rect(s, couleur, (cx - r * 1.1, cy - r * 0.62, 2.2 * r, 1.24 * r), int(e), border_radius=int(r * 0.6))
        gx = cx - r * 0.52
        ligne((gx - r * 0.27, cy), (gx + r * 0.27, cy))
        ligne((gx, cy - r * 0.27), (gx, cy + r * 0.27))
        point((cx + r * 0.42, cy + r * 0.12), r * 0.13)
        point((cx + r * 0.68, cy - r * 0.14), r * 0.13)
    elif nom == "systeme":
        for i, h in enumerate((0.7, 1.25, 0.95, 1.7)):
            pygame.draw.rect(s, couleur, (cx - r * 0.95 + i * r * 0.52, cy + r * 0.85 - r * h, r * 0.34, r * h),
                             border_radius=int(r * 0.12))
    elif nom == "options":
        for i, pos in enumerate((0.35, -0.35, 0.15)):
            y = cy + (i - 1) * r * 0.62
            ligne((cx - r, y), (cx + r, y))
            point((cx + pos * r * 1.6, y), r * 0.26)
    elif nom == "eteindre":
        arc_plein(s, couleur, (cx, cy + r * 0.1), r * 0.9, r * 0.9 - e, -math.pi / 2 + 0.75, 3 * math.pi / 2 - 0.75)
        ligne((cx, cy - r * 0.95), (cx, cy - r * 0.05))
    elif nom == "redemarrer":
        arc_plein(s, couleur, (cx, cy), r * 0.85, r * 0.85 - e, -math.pi / 2 + 0.5, 3 * math.pi / 2 - 0.1)
        pygame.draw.polygon(s, couleur, [(cx + r * 0.05, cy - r * 1.2), (cx + r * 0.55, cy - r * 0.83), (cx + r * 0.05, cy - r * 0.45)])
    elif nom == "lune":
        point((cx, cy), r * 0.88)
        pygame.draw.circle(s, vide, (cx + r * 0.5, cy - r * 0.38), r * 0.72)
    elif nom == "retourner":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.65, 2 * r, 1.3 * r), int(e), border_radius=int(r * 0.2))
        pygame.draw.polygon(s, couleur, [(cx - r * 0.4, cy - r * 0.2), (cx + r * 0.4, cy - r * 0.2), (cx, cy + r * 0.35)])
    elif nom == "quitter":
        pygame.draw.lines(s, couleur, False, [(cx + r * 0.1, cy - r), (cx - r * 0.9, cy - r), (cx - r * 0.9, cy + r),
                                               (cx + r * 0.1, cy + r)], int(e))
        ligne((cx - r * 0.3, cy), (cx + r, cy))
        pygame.draw.polygon(s, couleur, [(cx + r * 1.05, cy), (cx + r * 0.6, cy - r * 0.42), (cx + r * 0.6, cy + r * 0.42)])
    elif nom == "oui":
        pygame.draw.lines(s, couleur, False, [(cx - r * 0.8, cy), (cx - r * 0.2, cy + r * 0.6), (cx + r * 0.85, cy - r * 0.6)],
                          int(e * 1.2))
    elif nom == "non":
        ligne((cx - r * 0.7, cy - r * 0.7), (cx + r * 0.7, cy + r * 0.7))
        ligne((cx - r * 0.7, cy + r * 0.7), (cx + r * 0.7, cy - r * 0.7))
    elif nom == "dossier":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.8, r * 0.95, r * 0.5), border_radius=int(r * 0.15))
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.55, 2 * r, r * 1.4), border_radius=int(r * 0.18))
    elif nom == "chevron":
        pygame.draw.lines(s, couleur, False, [(cx + r * 0.3, cy - r * 0.7), (cx - r * 0.4, cy), (cx + r * 0.3, cy + r * 0.7)],
                          int(e * 1.3))
    elif nom == "telephone":
        pygame.draw.rect(s, couleur, (cx - r * 0.58, cy - r, r * 1.16, r * 2), int(e), border_radius=int(r * 0.25))
        point((cx, cy + r * 0.62), r * 0.13)
    elif nom == "cpu":
        pygame.draw.rect(s, couleur, (cx - r * 0.65, cy - r * 0.65, r * 1.3, r * 1.3), int(e), border_radius=int(r * 0.15))
        pygame.draw.rect(s, couleur, (cx - r * 0.25, cy - r * 0.25, r * 0.5, r * 0.5))
        for k in (-0.3, 0.3):
            ligne((cx + k * r, cy - r), (cx + k * r, cy - r * 0.65))
            ligne((cx + k * r, cy + r * 0.65), (cx + k * r, cy + r))
            ligne((cx - r, cy + k * r), (cx - r * 0.65, cy + k * r))
            ligne((cx + r * 0.65, cy + k * r), (cx + r, cy + k * r))
    elif nom == "memoire":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.5, 2 * r, r), int(e), border_radius=int(r * 0.12))
        for k in (-0.5, 0, 0.5):
            pygame.draw.rect(s, couleur, (cx + k * r - r * 0.14, cy - r * 0.22, r * 0.28, r * 0.44))
        for k in (-0.6, -0.2, 0.2, 0.6):
            ligne((cx + k * r, cy + r * 0.5), (cx + k * r, cy + r * 0.8))
    elif nom == "temperature":
        pygame.draw.rect(s, couleur, (cx - r * 0.25, cy - r, r * 0.5, r * 1.4), int(e), border_radius=int(r * 0.25))
        point((cx, cy + r * 0.6), r * 0.42)
        ligne((cx, cy - r * 0.4), (cx, cy + r * 0.5))
    elif nom == "disque":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.6, 2 * r, r * 1.2), int(e), border_radius=int(r * 0.3))
        point((cx + r * 0.55, cy), r * 0.15)
        ligne((cx - r * 0.6, cy), (cx + r * 0.15, cy))
    elif nom == "batterie":
        pygame.draw.rect(s, couleur, (cx - r, cy - r * 0.5, r * 1.8, r), int(e), border_radius=int(r * 0.18))
        pygame.draw.rect(s, couleur, (cx + r * 0.8, cy - r * 0.22, r * 0.25, r * 0.44), border_radius=int(r * 0.08))
        pygame.draw.rect(s, couleur, (cx - r * 0.75, cy - r * 0.27, r * 1.0, r * 0.54), border_radius=int(r * 0.08))
    elif nom == "frequence":
        pygame.draw.polygon(s, couleur, [(cx + r * 0.2, cy - r), (cx - r * 0.6, cy + r * 0.15), (cx - r * 0.02, cy + r * 0.15),
                                         (cx - r * 0.2, cy + r), (cx + r * 0.6, cy - r * 0.15), (cx + r * 0.02, cy - r * 0.15)])
    elif nom == "info":
        arc_plein(s, couleur, (cx, cy), r, r - e, 0, 2 * math.pi, False)
        point((cx, cy - r * 0.42), r * 0.12)
        ligne((cx, cy - r * 0.12), (cx, cy + r * 0.5))


class Pinceau:
    """Formes lissées (dessinées en double taille puis réduites), gardées en cache :
    chacune n'est calculée qu'une fois, ensuite c'est une simple copie de pixels."""

    def __init__(self):
        self.caches = {}

    def _garder(self, genre, cle, fabrique, limite=80):
        cache = self.caches.setdefault(genre, {})
        surf = cache.get(cle)
        if surf is None:
            if len(cache) >= limite:
                cache.clear()
            surf = fabrique()
            try:
                surf = surf.convert_alpha()  # même format que l'écran : copies 2 à 3 fois plus rapides
            except pygame.error:
                pass
            cache[cle] = surf
        return surf

    def carte(self, w, h, r, couleur, alpha=255, haut=None, bord=None):
        """Rectangle arrondi ; dégradé vertical si `haut` (couleur du haut) ; liseré clair si `bord`."""
        w, h, r = max(2, int(w)), max(2, int(h)), int(r)

        def fabrique():
            masque = pygame.Surface((w * 2, h * 2), pygame.SRCALPHA)
            pygame.draw.rect(masque, (255, 255, 255, alpha), masque.get_rect(), border_radius=r * 2)
            masque = pygame.transform.smoothscale(masque, (w, h))
            if haut:
                fond = pygame.Surface((1, 4), pygame.SRCALPHA)
                for i in range(4):
                    fond.set_at((0, i), (*melange(haut, couleur, i / 3), 255))
                fond = pygame.transform.smoothscale(fond, (w, h))
            else:
                fond = pygame.Surface((w, h), pygame.SRCALPHA)
                fond.fill((*couleur, 255))
            if bord:
                trait = pygame.Surface((w * 2, h * 2), pygame.SRCALPHA)
                pygame.draw.rect(trait, (*bord, 255), trait.get_rect(), width=3, border_radius=r * 2)
                fond.blit(pygame.transform.smoothscale(trait, (w, h)), (0, 0))
            fond.blit(masque, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            return fond
        return self._garder("carte", (w, h, r, couleur, alpha, haut, bord), fabrique)

    def halo(self, w, h, r, couleur, force=150):
        """Lueur floue autour d'un rectangle ; renvoie (surface, marge). Gardée en demi-résolution
        (4 fois moins de mémoire) puis agrandie à l'affichage : invisible sur un flou."""
        w, h = int(w), int(h)
        marge = int(min(w, h) * 0.35)

        def fabrique():
            k = 6
            pw, ph = (w + 2 * marge) // k + 2, (h + 2 * marge) // k + 2
            petit = pygame.Surface((pw, ph), pygame.SRCALPHA)
            petit.fill((*couleur, 0))
            pygame.draw.rect(petit, (*couleur, force), (marge // k + 1, marge // k + 1, w // k, h // k),
                             border_radius=max(1, int(r) // k))
            for _ in range(3):  # flou : réduire puis agrandir
                petit = pygame.transform.smoothscale(petit, (max(1, pw // 3), max(1, ph // 3)))
                petit = pygame.transform.smoothscale(petit, (pw, ph))
            return pygame.transform.smoothscale(petit, ((w + 2 * marge) // 2, (h + 2 * marge) // 2))
        demi = self._garder("halo", (w, h, int(r), couleur, force), fabrique, 4)
        return pygame.transform.scale(demi, (w + 2 * marge, h + 2 * marge)), marge

    def disque(self, rayon, couleur, alpha=255):
        t = max(2, int(rayon * 2))

        def fabrique():
            s = pygame.Surface((t * 2, t * 2), pygame.SRCALPHA)
            s.fill((*couleur, 0))
            pygame.draw.circle(s, (*couleur, alpha), (t, t), t)
            return pygame.transform.smoothscale(s, (t, t))
        return self._garder("disque", (t, couleur, alpha), fabrique)

    def icone(self, nom, taille, couleur):
        t = max(4, int(taille))

        def fabrique():
            s = pygame.Surface((t * 2, t * 2), pygame.SRCALPHA)
            s.fill((*couleur, 0))
            dessiner_icone(s, nom, (t, t), t * 0.78, couleur)
            return pygame.transform.smoothscale(s, (t, t))
        return self._garder("icone", (nom, t, couleur), fabrique, 120)

    def anneau(self, taille, valeur, couleur, epaisseur):
        t = max(8, int(taille))
        v = None if valeur is None else round(max(0.0, min(1.0, valeur)) * 200) / 200

        def fabrique():
            s = pygame.Surface((t * 2, t * 2), pygame.SRCALPHA)
            s.fill((*couleur, 0))
            r_ext = t - 2
            r_int = r_ext - epaisseur * 2
            arc_plein(s, (*PISTE, 255), (t, t), r_ext, r_int, 0, 2 * math.pi, False)
            if v:
                debut = -math.pi / 2
                arc_plein(s, (*couleur, 255), (t, t), r_ext, r_int, debut, debut + 2 * math.pi * v)
            return pygame.transform.smoothscale(s, (t, t))
        return self._garder("anneau", (t, v, couleur, int(epaisseur)), fabrique, 40)


# ---------------------------------------------------------------- écrans

class Ecran:
    titre = ""
    icone = "info"

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
    """Liste verticale : (texte, détail, fonction appelée sur OK[, icône])."""

    def __init__(self, app, titre, elements=None, vide="Rien ici.", icone="dossier", compteur=True):
        super().__init__(app)
        self.compteur = compteur
        self.titre = titre
        self.elements = elements or []
        self.vide = vide
        self.icone = icone
        self.sel = 0
        self.haut = 0
        self._glisse = 0.0

    def _geometrie(self):
        u = self.app.u
        y0, y1 = 17 * u, self.app.H - 11 * u
        h = 10 * u
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
        app, u, p = self.app, self.app.u, self.app.pinceau
        if not self.elements:
            badge = 9 * u
            s.blit(p.disque(badge, app.accent, 40), (app.W / 2 - badge, app.H * 0.42 - badge))
            ic = p.icone(self.icone, badge * 0.9, app.accent)
            s.blit(ic, ic.get_rect(center=(app.W / 2, app.H * 0.42)))
            y = app.H * 0.42 + badge + 4 * u
            for ligne in app.lignes(self.vide, int(3.6 * u), app.W * 0.6, "m"):
                app.texte(s, ligne, int(3.6 * u), (app.W / 2, y), TEXTE_DIM, centre=True, poids="m")
                y += 5 * u
            return
        self._visible()
        y0, h, n = self._geometrie()
        x, larg = 5 * u, app.W - 10 * u
        rayon = 2 * u
        # Surlignage qui glisse jusqu'à l'élément choisi
        cible = y0 + (self.sel - self.haut) * h
        y_sel = app.animer(("liste", id(self)), cible, seuil=0.5)
        surligne = p.carte(larg, h - 1.2 * u, rayon, melange(app.accent, PANNEAU, 0.78),
                           haut=melange(app.accent, PANNEAU, 0.62), bord=melange(app.accent, PANNEAU, 0.35))
        s.blit(surligne, (x, y_sel + 0.6 * u))
        for i in range(self.haut, min(len(self.elements), self.haut + n)):
            nom, detail, _ = self.elements[i][:3]
            icone = self.elements[i][3] if len(self.elements[i]) > 3 else self.icone
            y = y0 + (i - self.haut) * h
            cy = y + h / 2
            choisi = i == self.sel
            badge = 2.9 * u
            bx = x + 2.4 * u
            s.blit(p.disque(badge, app.accent if choisi else TEXTE_DIM, 70 if choisi else 28), (bx, cy - badge))
            ic = p.icone(icone, badge * 1.3, TEXTE if choisi else melange(TEXTE_DIM, TEXTE, 0.3))
            s.blit(ic, ic.get_rect(center=(bx + badge, cy)))
            tx = bx + 2 * badge + 2.4 * u
            larg_d = 0
            if detail:
                police_d = app.police(int(2.9 * u), "m")
                d = app.rendu(app.ajuster(police_d, detail, larg * 0.32), int(2.9 * u),
                              melange(TEXTE_DIM, TEXTE, 0.4) if choisi else TEXTE_DIM, "m")
                larg_d = d.get_width() + 4 * u
                s.blit(d, (x + larg - d.get_width() - 3 * u, cy - d.get_height() / 2))
            police = app.police(int(4 * u), "sb" if choisi else "m")
            t = app.rendu(app.ajuster(police, nom, x + larg - tx - 3 * u - larg_d), int(4 * u),
                          TEXTE if choisi else melange(TEXTE_DIM, TEXTE, 0.65), "sb" if choisi else "m")
            s.blit(t, (tx, cy - t.get_height() / 2))
        if len(self.elements) > n:  # ascenseur
            zone = n * h
            hb = max(4 * u, zone * n / len(self.elements))
            yb = y0 + (zone - hb) * self.haut / max(1, len(self.elements) - n)
            s.blit(p.carte(0.6 * u, hb, 0.3 * u, PISTE), (app.W - 3 * u, yb))
            s.blit(p.carte(0.6 * u, hb, 0.3 * u, app.accent, 160), (app.W - 3 * u, yb))


class Accueil(Ecran):
    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.tuiles = [
            ("Jeux", VERT, "jeux", app.ouvrir_jeux),
            ("Netflix", ROSE, "video", app.ouvrir_netflix),
            ("Système", ORANGE, "systeme", app.ouvrir_systeme),
            ("Options", VIOLET, "options", app.ouvrir_options),
        ]
        self.details = ["", "Dans Chrome", "", "Écran, veille, arrêt"]
        self.puces = []
        self._compteur = 0

    def couleur(self):
        return self.tuiles[self.sel][1]

    def _rects(self):
        app, u = self.app, self.app.u
        n, ecart = len(self.tuiles), 2.6 * u
        larg = min((app.W - 10 * u - (n - 1) * ecart) / n, 42 * u)
        haut = larg * 1.22
        x0 = (app.W - (n * larg + (n - 1) * ecart)) / 2
        y0 = app.H * 0.55 - haut / 2
        return [pygame.Rect(x0 + i * (larg + ecart), y0, larg, haut) for i in range(n)]

    def action(self, a):
        if a in ("gauche", "haut"):
            self.sel = (self.sel - 1) % len(self.tuiles)
        elif a in ("droite", "bas"):
            self.sel = (self.sel + 1) % len(self.tuiles)
        elif a == "ok":
            self.tuiles[self.sel][3]()
        self.app.accent = self.couleur()

    def clic(self, x, y):
        for i, r in enumerate(self._rects()):
            if r.collidepoint(x, y):
                self.sel = i
                self.app.accent = self.couleur()
                self.tuiles[i][3]()

    def compter(self):
        racine = Path(self.app.cfg.get("roms", "~/ROMs")).expanduser()
        jeux = sum(len(App.lister_jeux(racine / d, ext)) for d, _, _, ext in SYSTEMES)
        self.details[0] = f"{jeux} jeu{'x' if jeux > 1 else ''}" if jeux else "Aucun jeu"

    def tick(self):
        self._compteur += 1
        if self._compteur % 30 == 1:
            self.compter()
        if self._compteur % 2 == 0 and self.puces:
            return False
        pc = self.app.pc
        cpu = pc.cpu()
        puces = [("cpu", f"{cpu:.0f} %")]
        t = pc.temperature()
        if t:
            puces.append(("temperature", f"{t:.0f} °C"))
        utilise, total = pc.memoire()
        if total:
            puces.append(("memoire", f"{utilise / 2**30:.1f} Go".replace(".", ",")))
        b = pc.batterie()
        if b:
            puces.append(("batterie", f"{b[0]} %"))
        self.puces = puces
        self.details[2] = f"Processeur {cpu:.0f} %" + (f" · {t:.0f} °C" if t else "")
        return True

    def dessiner(self, s):
        app, u, p = self.app, self.app.u, self.app.pinceau
        rects = self._rects()
        rayon = 3.2 * u
        for i, (nom, couleur, icone, _) in enumerate(self.tuiles):
            r = rects[i]
            levee = app.animer(("tuile", i), 1.0 if i == self.sel else 0.0, seuil=0.01)
            dy = -1.8 * u * levee
            if levee > 0.02:
                halo, marge = p.halo(r.w, r.h, rayon, couleur)
                halo.set_alpha(int(255 * levee))
                s.blit(halo, (r.x - marge, r.y - marge + dy))
            s.blit(p.carte(r.w, r.h, rayon, PANNEAU, haut=PANNEAU_HAUT, bord=BORD), (r.x, r.y + dy))
            if levee > 0.02:
                vive = p.carte(r.w, r.h, rayon, melange(couleur, FOND_BAS, 0.55), haut=melange(couleur, FOND_BAS, 0.15),
                               bord=melange(couleur, TEXTE, 0.35))
                vive.set_alpha(int(255 * levee))
                s.blit(vive, (r.x, r.y + dy))
            cx, cy = r.centerx, r.y + r.h * 0.38 + dy
            badge = r.w * 0.2
            s.blit(p.disque(badge, couleur, 55), (cx - badge, cy - badge))
            if levee > 0.02:
                blanc = p.disque(badge, TEXTE, 60)
                blanc.set_alpha(int(255 * levee))
                s.blit(blanc, (cx - badge, cy - badge))
            vif = levee > 0.5  # deux états seulement : pas une nouvelle teinte en cache à chaque image
            ic = p.icone(icone, badge * 1.1, TEXTE if vif else couleur)
            s.blit(ic, ic.get_rect(center=(cx, cy)))
            couleur_txt = TEXTE if vif else melange(TEXTE_DIM, TEXTE, 0.6)
            app.texte(s, nom, int(4.2 * u), (cx, r.y + r.h * 0.72 + dy), couleur_txt, centre=True, poids="sb",
                      largeur=r.w - 2 * u)
            if self.details[i]:
                app.texte(s, self.details[i], int(2.7 * u), (cx, r.y + r.h * 0.84 + dy),
                          melange(TEXTE_DIM, TEXTE, 0.35) if vif else TEXTE_DIM, centre=True, poids="m", largeur=r.w - 2.4 * u)
        # Points sous les tuiles
        n = len(self.tuiles)
        y = rects[0].bottom + 5 * u
        for i in range(n):
            x = app.W / 2 + (i - (n - 1) / 2) * 2.6 * u
            if i == self.sel:
                s.blit(p.carte(3 * u, 0.9 * u, 0.45 * u, self.couleur()), (x - 1.5 * u, y - 0.45 * u))
            else:
                s.blit(p.disque(0.45 * u, PISTE), (x - 0.45 * u, y - 0.45 * u))


class EcranSysteme(Ecran):
    titre = "Système"
    icone = "systeme"

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

    def jauges(self):
        m, pc = self.mesures, self.app.pc
        j = [("cpu", "Processeur", m["cpu"] / 100, f"{m['cpu']:.0f} %", f"{pc.coeurs} cœurs", None)]
        utilise, total = m["mem"]
        if total:
            j.append(("memoire", "Mémoire", utilise / total, f"{100 * utilise / total:.0f} %",
                      f"{taille_lisible(utilise)} / {taille_lisible(total)}", None))
        if m["temp"]:
            j.append(("temperature", "Température", (m["temp"] - 30) / 65, f"{m['temp']:.0f}°", "Processeur", None))
        if m["disque"]:
            d = m["disque"]
            j.append(("disque", "Stockage", d.used / d.total, f"{100 * d.used / d.total:.0f} %",
                      f"{taille_lisible(d.free)} libres", None))
        if m["bat"]:
            niveau, etat = m["bat"]
            j.append(("batterie", "Batterie", niveau / 100, f"{niveau} %", etat.capitalize(), True))
        if m["freq"]:
            maxi = pc.freq_max
            j.append(("frequence", "Fréquence", m["freq"] / maxi if maxi else None,
                      f"{m['freq'] / 1000:.1f}".replace(".", ","), "GHz", "bleu"))
        return j[:6]

    def dessiner(self, s):
        app, u, p, pc, m = self.app, self.app.u, self.app.pinceau, self.app.pc, self.mesures
        y0, y1 = 17 * u, app.H - 11 * u
        x0, x1 = 5 * u, app.W - 5 * u
        ecart = 2 * u
        gauche = (x1 - x0) * 0.36
        rayon = 2.6 * u
        # Fiche du PC
        s.blit(p.carte(gauche, y1 - y0, rayon, PANNEAU, haut=PANNEAU_HAUT, bord=BORD), (x0, y0))
        x, y, lw = x0 + 3 * u, y0 + 3 * u, gauche - 6 * u
        app.texte(s, "CE PC", int(2.4 * u), (x, y), app.accent, poids="b")
        y += 3.6 * u
        for ligne in app.lignes(pc.modele, int(4.4 * u), lw, "sb")[:2]:
            app.texte(s, ligne, int(4.4 * u), (x, y), TEXTE, poids="sb")
            y += 5.4 * u
        app.texte(s, pc.processeur, int(2.8 * u), (x, y), TEXTE_DIM, poids="m", largeur=lw)
        y += 5.6 * u
        lignes = [("Système", pc.systeme), ("Noyau", pc.noyau), ("Écran", f"{app.W} × {app.H}"),
                  ("Allumé depuis", m["depuis"]), ("Adresse", m["ip"]), ("Télécommande", f"{m['ip']}:{app.port}")]
        pas = min(6 * u, (y1 - 2 * u - y) / len(lignes))
        for nom, val in lignes:
            s.blit(p.carte(lw, 1, 0, BORD), (x, y))
            app.texte(s, nom, int(2.7 * u), (x, y + 1.4 * u), TEXTE_DIM, poids="m")
            police = app.police(int(2.9 * u), "sb")
            larg_nom = app.police(int(2.7 * u), "m").size(nom)[0] + 2 * u
            app.texte(s, app.ajuster(police, val, lw - larg_nom), int(2.9 * u), (x + lw, y + 1.3 * u), TEXTE,
                      droite=True, poids="sb")
            y += pas
        # Jauges en anneaux
        gx = x0 + gauche + ecart
        jauges = self.jauges()
        rangees = 2  # 6 jauges sur un portable (batterie, température…) ; même grille sinon
        cw = (x1 - gx - 2 * ecart) / 3
        ch = (y1 - y0 - (rangees - 1) * ecart) / rangees
        for k, (icone, nom, val, grand, petit, mode) in enumerate(jauges):
            cx0 = gx + (k % 3) * (cw + ecart)
            cy0 = y0 + (k // 3) * (ch + ecart)
            s.blit(p.carte(cw, ch, rayon, PANNEAU, haut=PANNEAU_HAUT, bord=BORD), (cx0, cy0))
            if mode == "bleu":
                couleur = BLEU
            else:
                couleur = niveau_couleur(val or 0, inverse=bool(mode))
            taille = min(cw * 0.58, ch * 0.56, 26 * u)
            centre = (cx0 + cw / 2, cy0 + ch * 0.46 - 4 * u)
            anneau = p.anneau(taille, val, couleur, taille * 0.085)
            s.blit(anneau, anneau.get_rect(center=centre))
            app.texte(s, grand, int(taille * 0.24), centre, TEXTE, centre=True, poids="sb")
            ic = p.icone(icone, 3.4 * u, couleur)
            s.blit(ic, (cx0 + 1.8 * u, cy0 + 1.8 * u))
            bas = centre[1] + taille / 2
            app.texte(s, nom, int(2.9 * u), (cx0 + cw / 2, bas + 4.4 * u), TEXTE, centre=True, poids="sb",
                      largeur=cw - 2 * u)
            app.texte(s, petit, int(2.4 * u), (cx0 + cw / 2, bas + 8 * u), TEXTE_DIM, centre=True, poids="m",
                      largeur=cw - 2 * u)


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
        self.pinceau = Pinceau()
        self._polices = {}
        self._textes = {}
        self._fond = (None, None)
        self._fonds = {}
        self._anims = {}
        self.anime = False
        self.accent = VERT
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

    def police(self, taille, poids="r"):
        cle = (taille, poids)
        if cle not in self._polices:
            # Chemins directs : évite que pygame lance fc-list (lent au premier appel sur un petit PC).
            gras = poids in ("sb", "b")
            for fichier in (f"/usr/share/fonts/opentype/inter/Inter-{POIDS[poids]}.otf",
                            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if gras else ''}.ttf"):
                if os.path.exists(fichier):
                    self._polices[cle] = pygame.font.Font(fichier, taille)
                    break
            else:
                self._polices[cle] = pygame.font.SysFont("inter,dejavusans,notosans,ubuntu,freesans", taille, bold=gras)
        return self._polices[cle]

    def rendu(self, texte, taille, couleur, poids="r"):
        """Texte rendu une fois puis gardé : le rendu des polices est ce qui coûte le plus."""
        cle = (texte, taille, couleur, poids)
        img = self._textes.get(cle)
        if img is None:
            if len(self._textes) > 150:
                self._textes.clear()
            img = self._textes[cle] = self.police(taille, poids).render(texte, True, couleur)
        return img

    @staticmethod
    def ajuster(police, texte, largeur):
        if police.size(texte)[0] <= largeur:
            return texte
        while texte and police.size(texte + "…")[0] > largeur:
            texte = texte[:-1]
        return texte + "…"

    def lignes(self, texte, taille, largeur, poids="r"):
        police, lignes, courante = self.police(taille, poids), [], ""
        for mot in texte.split():
            essai = f"{courante} {mot}".strip()
            if police.size(essai)[0] <= largeur or not courante:
                courante = essai
            else:
                lignes.append(courante)
                courante = mot
        return lignes + ([courante] if courante else [])

    def texte(self, s, texte, taille, pos, couleur, centre=False, droite=False, poids="r", largeur=None):
        if largeur:
            texte = self.ajuster(self.police(taille, poids), texte, largeur)
        img = self.rendu(texte, taille, couleur, poids)
        x, y = pos
        if centre:
            x, y = x - img.get_width() / 2, y - img.get_height() / 2
        elif droite:
            x -= img.get_width()
        s.blit(img, (x, y))
        return img.get_rect(topleft=(x, y))

    def animer(self, cle, cible, seuil=0.01, vitesse=0.3):
        """Valeur qui rejoint `cible` en quelques images ; tant qu'elle bouge, on redessine."""
        v = self._anims.get(cle, cible)
        if abs(cible - v) <= seuil:
            v = cible
        else:
            v += (cible - v) * vitesse
            self.anime = True
        self._anims[cle] = v
        return v

    def fond_ecran(self):
        """Dégradé sombre éclairé par la couleur de la section. Chaque couleur est gardée au quart
        de la résolution (0,25 Mo) ; seul le fond affiché existe en pleine taille."""
        if self._fond[0] != self.accent:
            quart = self._fonds.get(self.accent)
            if quart is None:
                quart = self._fabriquer_fond()
                try:
                    quart = quart.convert()  # au format de l'écran dès le départ : aucune conversion ensuite
                except pygame.error:
                    pass
                self._fonds[self.accent] = quart
            # Lissage jusqu'à mi-taille puis doublement : 3 fois plus rapide qu'un lissage plein écran,
            # et sans différence visible sur un dégradé.
            moitie = pygame.transform.smoothscale(quart, (self.W // 2, self.H // 2))
            fond = pygame.transform.scale2x(moitie)
            if fond.get_size() != (self.W, self.H):  # dimensions impaires
                fond = pygame.transform.scale(fond, (self.W, self.H))
            self._fond = (self.accent, fond)
        return self._fond[1]

    def _fabriquer_fond(self):
        pw, ph = 32, 18
        petit = pygame.Surface((pw, ph))
        for y in range(ph):
            for x in range(pw):
                c = melange(FOND_HAUT, FOND_BAS, y / (ph - 1))
                lueur = max(0.0, 1 - ((x - 3) / 17) ** 2 - ((y - 1) / 10) ** 2) ** 2
                c = melange(c, self.accent, 0.28 * lueur)
                lueur2 = max(0.0, 1 - ((x - pw) / 15) ** 2 - ((y - ph) / 9) ** 2) ** 2
                c = melange(c, melange(self.accent, BLEU, 0.5), 0.10 * lueur2)
                petit.set_at((x, y), c)
        return pygame.transform.smoothscale(petit, (self.W // 4, self.H // 4))  # flou : le quart suffit

    def puce(self, s, x, y, icone, texte, couleur=TEXTE_DIM):
        """Petite étiquette arrondie avec icône ; renvoie sa largeur."""
        u = self.u
        img = self.rendu(texte, int(2.6 * u), TEXTE, "sb")
        h = 5 * u
        w = img.get_width() + (6.6 * u if icone else 3.4 * u)
        s.blit(self.pinceau.carte(w, h, h / 2, PANNEAU, 210, bord=BORD), (x, y))
        tx = x + 1.7 * u
        if icone:
            ic = self.pinceau.icone(icone, 3 * u, couleur)
            s.blit(ic, ic.get_rect(midleft=(x + 1.6 * u, y + h / 2)))
            tx = x + 4.8 * u
        s.blit(img, (tx, y + h / 2 - img.get_height() / 2))
        return w

    def entete(self, s):
        u, p = self.u, self.pinceau
        maintenant = time.localtime()
        courant = self.pile[-1]
        if len(self.pile) == 1:
            salut = "Bonsoir" if maintenant.tm_hour >= 18 or maintenant.tm_hour < 5 else "Bonjour"
            self.texte(s, salut, int(6.4 * u), (5 * u, 3.6 * u), TEXTE, poids="b")
            x = 5 * u
            for icone, texte in courant.puces:
                x += self.puce(s, x, 12.6 * u, icone, texte) + 1.2 * u
        else:
            r = 3 * u
            s.blit(p.disque(r, PANNEAU, 230), (5 * u, 5.4 * u))
            ic = p.icone("chevron", 3.6 * u, TEXTE)
            s.blit(ic, ic.get_rect(center=(5 * u + r, 5.4 * u + r)))
            titre = self.texte(s, courant.titre, int(5.6 * u), (13 * u, 4.4 * u), TEXTE, poids="b", largeur=self.W * 0.55)
            if isinstance(courant, Liste) and courant.compteur and courant.elements:
                self.puce(s, titre.right + 2 * u, 5.8 * u, None, str(len(courant.elements)))
            s.blit(p.carte(9 * u, 0.6 * u, 0.3 * u, self.accent), (13 * u, 12.6 * u))
        self.texte(s, time.strftime("%H:%M"), int(6.4 * u), (self.W - 5 * u, 3.6 * u), TEXTE, droite=True, poids="sb")
        date = f"{JOURS[maintenant.tm_wday]} {maintenant.tm_mday} {MOIS[maintenant.tm_mon - 1]}"
        self.texte(s, date.capitalize(), int(2.8 * u), (self.W - 5 * u, 12 * u), TEXTE_DIM, droite=True, poids="m")

    def pied(self, s):
        u, p = self.u, self.pinceau
        y = self.H - 5.2 * u
        x = 5 * u
        for lettre, couleur, texte in (("A", VERT, "Ouvrir"), ("B", ROUGE, "Retour")):
            r = 1.7 * u
            s.blit(p.disque(r, couleur, 230), (x, y - r))
            self.texte(s, lettre, int(2.2 * u), (x + r, y), FOND_BAS, centre=True, poids="b")
            x += 2 * r + 1.2 * u
            x = self.texte(s, texte, int(2.6 * u), (x, y - 1.5 * u), TEXTE_DIM, poids="m").right + 3 * u
        if self.serveur:
            adresse = f"{self.pc.adresse()}:{self.port}"
            r = self.texte(s, adresse, int(2.6 * u), (self.W - 5 * u, y - 1.5 * u), TEXTE_DIM, droite=True, poids="m")
            ic = p.icone("telephone", 3.2 * u, TEXTE_DIM)
            s.blit(ic, ic.get_rect(midright=(r.x - 0.8 * u, y)))

    def dessiner(self):
        s, u = self.toile, self.u
        self.anime = False
        courant = self.pile[-1]
        if isinstance(courant, Accueil):
            self.accent = courant.couleur()
        s.blit(self.fond_ecran(), (0, 0))
        self.entete(s)
        courant.dessiner(s)
        self.pied(s)
        if self.toast:
            police = self.police(int(3.2 * u), "m")
            img = self.rendu(self.ajuster(police, self.toast[0], self.W - 24 * u), int(3.2 * u), TEXTE, "m")
            w, h = img.get_width() + 10 * u, 7.4 * u
            x, y = (self.W - w) / 2, self.H - 19 * u
            s.blit(self.pinceau.carte(w, h, h / 2, PANNEAU_SEL, 245, bord=BORD), (x, y))
            ic = self.pinceau.icone("info", 3 * u, self.accent)
            s.blit(ic, ic.get_rect(center=(x + 4 * u, y + h / 2)))
            s.blit(img, (x + 7 * u, y + h / 2 - img.get_height() / 2))
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
        self.ouvrir(Liste(self, question, [("Oui", "", oui, "oui"), ("Non", "", self.retour, "non")],
                          compteur=False))
        self.pile[-1].sel = 1

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

    # Netflix
    def navigateur(self):
        choix = self.cfg.get("navigateur")
        candidats = [choix] if choix else ["google-chrome-stable", "google-chrome", "firefox"]
        for nom in candidats:
            if nom and shutil.which(nom):
                return nom
        return None

    def ouvrir_netflix(self):
        nav = self.navigateur()
        if not nav:
            self.notifier("Netflix a besoin de Google Chrome : bash salon/installer.sh --netflix")
            return
        url = self.cfg.get("netflix") or DEFAUTS["netflix"]
        if "firefox" in nav:
            cmd = [nav, "--kiosk", url]
        else:
            # Profil à part : la connexion à Netflix est gardée d'une fois sur l'autre.
            cmd = [nav, "--kiosk", "--no-first-run", "--no-default-browser-check", "--disable-translate",
                   "--disable-features=Translate,MediaRouter,OptimizationHints", "--password-store=basic",
                   "--disable-extensions", "--disable-sync", "--renderer-process-limit=2",
                   f"--user-data-dir={CONFIG_DIR / 'navigateur'}"]
            if self.pc.memoire()[1] < 3 * 2**30:  # moins de 3 Go : mode « petit appareil » de Chrome
                cmd.append("--enable-low-end-device-mode")
            cmd.append(url)
        self.lancer(cmd, "web")
        if not shutil.which("xdotool"):
            self.notifier("Installe xdotool pour piloter Netflix au téléphone : sudo apt install xdotool")

    @staticmethod
    def touche(touche):
        """Envoie une touche à la fenêtre au premier plan (le navigateur)."""
        if shutil.which("xdotool"):
            subprocess.Popen(["xdotool", "key", "--clearmodifiers", touche],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
                          "(nes, snes, megadrive, gb, gba, psx, n64…).", "jeux"), VERT)

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
        self.ouvrir(Liste(self, nom, elements, icone="jeu"))

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
            ("Retourner l'écran (mode tente)", retourne, self.retourner_ecran, "retourner"),
            ("Mettre en veille", "", lambda: self.systemctl("suspend"), "lune"),
            ("Redémarrer", "", lambda: self.confirmer("Redémarrer le PC ?", lambda: self.systemctl("reboot")), "redemarrer"),
            ("Éteindre", "", lambda: self.confirmer("Éteindre le PC ?", lambda: self.systemctl("poweroff")), "eteindre"),
            ("Quitter Salon", "", self.quitter, "quitter"),
        ]
        self.ouvrir(Liste(self, "Options", elements, icone="options", compteur=False), VIOLET)

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
            return
        self.liberer_memoire()

    def liberer_memoire(self):
        """Pendant un jeu ou Netflix, Salon est caché : il rend au système images, fonds et polices
        gardés en cache (recalculés en quelques millisecondes au retour)."""
        self.pinceau.caches.clear()
        self._textes.clear()
        self._fonds.clear()
        self._fond = (None, None)
        self._polices.clear()
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)  # rend vraiment la mémoire libérée au système
        except (OSError, AttributeError):
            pass

    def fin_enfant(self):
        self.enfant = None
        self.genre_enfant = None
        self.dir_tenue = None
        self.sale = True

    def arreter_enfant(self):
        if self.enfant and self.enfant.poll() is None:
            try:  # tout le groupe : Chrome lance de nombreux processus
                os.killpg(self.enfant.pid, signal.SIGTERM)
            except OSError:
                self.enfant.terminate()

    # ------------------------------------------------ commandes

    def commande(self, a, source="local"):
        if self.enfant:
            g = self.genre_enfant
            if g == "web":
                # Raccourcis du lecteur Netflix : espace = pause, flèches = avancer/reculer/volume.
                touches = {"ok": "space", "pause": "space", "gauche": "Left", "droite": "Right",
                           "haut": "Up", "bas": "Down", "recul": "Left", "avance": "Right",
                           "retour": "alt+Left"}
                if a in touches:
                    self.touche(touches[a])
                elif a in ("stop", "accueil"):
                    self.arreter_enfant()
                elif a in ("vol+", "vol-"):
                    volume_systeme(5 if a == "vol+" else -5)
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
        elif t == EV_JEU:
            self.pile[0].compter()
            self.notifier(f"Jeu reçu : {e.nom} ({e.console})")
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
            # Un fil par connexion : un envoi de jeu ne bloque pas les boutons de la télécommande.
            threading.Thread(target=self.client, args=(client,), daemon=True).start()

    def client(self, client):
        with client:
            try:
                client.settimeout(10)
                requete = b""
                while b"\r\n\r\n" not in requete:
                    morceau = client.recv(4096)
                    if not morceau or len(requete) > 16384:
                        return
                    requete += morceau
                tete, debut = requete.split(b"\r\n\r\n", 1)
                lignes = tete.decode("latin-1").split("\r\n")
                methode, chemin = lignes[0].split()[:2]
                entetes = {}
                for ligne in lignes[1:]:
                    cle, _, valeur = ligne.partition(":")
                    entetes[cle.strip().lower()] = valeur.strip()
                url = urlparse(chemin)
                if methode == "POST" and url.path == "/envoyer":
                    statut, genre, corps = self.recevoir_jeu(client, url, entetes, debut)
                else:
                    statut, genre, corps = self.repondre(methode, chemin)
                client.sendall(
                    (f"HTTP/1.1 {statut}\r\nContent-Type: {genre}\r\nContent-Length: {len(corps)}\r\n"
                     "Cache-Control: no-store\r\nConnection: close\r\n\r\n").encode() + corps)
            except (OSError, ValueError):
                pass

    def recevoir_jeu(self, client, url, entetes, debut):
        """Écrit le fichier envoyé par le téléphone dans ~/ROMs/<console>, morceau par morceau."""
        def reponse(statut, **donnees):
            return statut, "application/json", json.dumps(donnees).encode()

        q = parse_qs(url.query)
        nom = os.path.basename(q.get("nom", [""])[0]).strip()
        console = q.get("console", ["auto"])[0]
        if not nom or nom.startswith("."):
            return reponse("400 Bad Request", erreur="Nom de fichier invalide.")
        if console not in EXT_ENVOI:
            console = deviner_console(nom)
            if not console:
                return reponse("400 Bad Request", erreur=f"Choisis la console : impossible de la deviner pour « {nom} ».")
        if Path(nom).suffix.lower() not in EXT_ENVOI[console]:
            acceptes = ", ".join(sorted(EXT_ENVOI[console]))
            return reponse("400 Bad Request", erreur=f"Pas un jeu {NOMS[console]} (fichiers acceptés : {acceptes}).")
        try:
            taille = int(entetes.get("content-length", ""))
        except ValueError:
            return reponse("411 Length Required", erreur="Taille du fichier inconnue.")
        dossier = Path(self.cfg.get("roms", "~/ROMs")).expanduser() / console
        try:
            dossier.mkdir(parents=True, exist_ok=True)
            if taille > shutil.disk_usage(dossier).free - 100 * 2**20:
                return reponse("507 Insufficient Storage", erreur="Plus assez de place sur le PC.")
        except OSError as e:
            return reponse("500 Internal Server Error", erreur=f"Dossier inaccessible : {e.strerror}")
        if entetes.get("expect", "").lower() == "100-continue":
            client.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        partiel = dossier / (nom + ".part")  # extension inconnue : invisible dans Salon pendant l'envoi
        recu = 0
        try:
            client.settimeout(30)
            with open(partiel, "wb") as f:
                morceau = debut[:taille]
                while True:
                    f.write(morceau)
                    recu += len(morceau)
                    if recu >= taille:
                        break
                    morceau = client.recv(min(256 * 1024, taille - recu))
                    if not morceau:
                        raise OSError("connexion coupée")
            os.replace(partiel, dossier / nom)
        except OSError:
            try:
                partiel.unlink()
            except OSError:
                pass
            return reponse("500 Internal Server Error", erreur="Envoi interrompu.")
        pygame.event.post(pygame.event.Event(EV_JEU, nom=nom_de_jeu(nom), console=NOMS[console]))
        return reponse("200 OK", ok=True, console=NOMS[console])

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
        # 16 ms juste après une action (fluide), 50 ms au repos, 100 ms pendant un jeu ou Netflix.
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
                self.sale = self.anime  # animation en cours : image suivante au prochain tour
            if self.enfant:
                time.sleep(0.1)
            elif self.anime or self.dir_tenue or time.time() - derniere_action < 2:
                time.sleep(0.016)
            else:
                time.sleep(0.05)
        self.arreter_enfant()
        self.fermer_telecommande()
        pygame.quit()


PAGE_TELECOMMANDE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0b0e17">
<title>Salon</title>
<style>
:root{color-scheme:dark;--fond:#0b0e17;--carte:#161b2b;--appui:#262e45;--texte:#f2f4f9;--dim:#848ea6;
 --vert:#34cd7d;--rouge:#ff5462;--bleu:#409cff}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--fond);color:var(--texte);font:16px system-ui,sans-serif;min-height:100vh;
 display:flex;flex-direction:column;align-items:center;gap:20px;padding:20px 16px 32px;
 user-select:none;-webkit-user-select:none;touch-action:manipulation}
#etat{color:var(--dim);min-height:1.2em;text-align:center;font-size:15px}
.croix{display:grid;grid-template-columns:repeat(3,84px);grid-template-rows:repeat(3,84px);gap:10px}
.ligne{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;max-width:300px}
button,.bouton{border:0;border-radius:18px;background:var(--carte);color:var(--texte);font:600 17px system-ui,sans-serif;
 min-width:84px;height:60px;padding:0 14px;display:inline-flex;align-items:center;justify-content:center}
.croix button{height:84px;font-size:26px}
button:active,.bouton:active{background:var(--appui)}
.ok{background:var(--vert);color:#06210f;border-radius:50%}
.stop{color:var(--rouge)}
.envoi{width:100%;max-width:340px;background:var(--carte);border-radius:22px;padding:18px;display:flex;flex-direction:column;gap:12px}
h2{margin:0;font-size:17px}
select{width:100%;height:48px;border-radius:14px;border:0;background:var(--fond);color:var(--texte);font:16px system-ui;padding:0 12px}
.bouton{width:100%;background:var(--bleu);color:#fff}
#envois{display:flex;flex-direction:column;gap:14px}
.envoi-ligne{display:flex;flex-direction:column;gap:6px;font-size:14px;word-break:break-all}
progress{width:100%;height:8px;accent-color:var(--bleu)}
.reussi{color:var(--vert)} .rate{color:var(--rouge)}
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
<section class="envoi">
 <h2>Ajouter des jeux</h2>
 <select id="console"><option value="auto">Console : automatique</option>{{CONSOLES}}</select>
 <label class="bouton">Choisir des jeux<input id="fichiers" type="file" multiple hidden></label>
 <div id="envois"></div>
</section>
<script>
const envoyer = a => { fetch('/action?a=' + a, {method: 'POST'}).catch(() => {}); if (navigator.vibrate) navigator.vibrate(12); };
document.querySelectorAll('button[data-a]').forEach(b => {
  let t1, t2;
  const fin = () => { clearTimeout(t1); clearInterval(t2); };
  b.addEventListener('pointerdown', e => {
    e.preventDefault(); envoyer(b.dataset.a);
    if (b.hasAttribute('data-repete')) t1 = setTimeout(() => { t2 = setInterval(() => envoyer(b.dataset.a), 110); }, 380);
  });
  ['pointerup', 'pointerleave', 'pointercancel'].forEach(n => b.addEventListener(n, fin));
});
const etat = document.getElementById('etat');
const noms = {retroarch: 'Jeu en cours (Stop = quitter)', web: 'Netflix (OK = pause, ◀ ▶ = reculer/avancer, Stop = fermer)'};
setInterval(() => fetch('/etat').then(r => r.json()).then(e => {
  etat.textContent = e.lecture ? noms[e.lecture] : e.ecran;
}).catch(() => { etat.textContent = 'PC injoignable'; }), 2000);

const choix = document.getElementById('console'), envois = document.getElementById('envois');
document.getElementById('fichiers').addEventListener('change', async e => {
  for (const f of [...e.target.files]) await envoyerJeu(f);
  e.target.value = '';
});
function envoyerJeu(f) {
  return new Promise(fini => {
    const ligne = document.createElement('div'), nom = document.createElement('span'), barre = document.createElement('progress');
    ligne.className = 'envoi-ligne'; nom.textContent = f.name; barre.max = 100; barre.value = 0;
    ligne.append(nom, barre); envois.prepend(ligne);
    const fin = (reussi, texte) => {
      barre.remove(); const m = document.createElement('small');
      m.className = reussi ? 'reussi' : 'rate'; m.textContent = (reussi ? '✓ ' : '✗ ') + texte; ligne.append(m); fini();
    };
    const x = new XMLHttpRequest();
    x.open('POST', '/envoyer?console=' + encodeURIComponent(choix.value) + '&nom=' + encodeURIComponent(f.name));
    x.upload.onprogress = ev => { if (ev.lengthComputable) barre.value = 100 * ev.loaded / ev.total; };
    x.onload = () => {
      let r = {}; try { r = JSON.parse(x.responseText); } catch (_) {}
      if (x.status === 200) fin(true, 'Ajouté à ' + r.console); else fin(false, r.erreur || 'Erreur ' + x.status);
    };
    x.onerror = () => fin(false, 'PC injoignable');
    x.send(f);
  });
}
</script></body></html>
""".replace("{{CONSOLES}}", "".join(f'<option value="{d}">{n}</option>' for d, n, _, _ in SYSTEMES))


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
