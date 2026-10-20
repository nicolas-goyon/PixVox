"""Entrées / sorties sûres : journal qui ne plante jamais, dossiers de sortie qu'on ne vide pas par erreur."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

MARKER = ".pixvox"                    # présent dans chaque dossier créé (et donc effaçable) par pixvox
_MARKER_TEXT = "Dossier généré par pixvox : il est effacé et recréé à chaque export.\n"


class OutputDirError(ValueError):
    """Dossier de sortie refusé : il contient autre chose qu'une sortie de pixvox."""


def say(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
    """print() tolérant : caractères non représentables remplacés (console Windows redirigée en cp1252),
    lecteur fermé (`| head`) ignoré au lieu d'une trace d'erreur."""
    stream = file if file is not None else sys.stdout
    text = sep.join(str(a) for a in args) + end
    try:
        try:
            stream.write(text)
        except UnicodeEncodeError:
            enc = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(enc, "replace").decode(enc, "replace"))
        if flush:
            stream.flush()
    except BrokenPipeError:
        try:                                       # plus personne ne lit : la suite part dans le néant
            os.dup2(os.open(os.devnull, os.O_WRONLY), stream.fileno())
        except (OSError, ValueError, AttributeError):
            pass


def prepare_output_dir(path, what: str = "dossier de sortie") -> Path:
    """Vide `path` pour le recréer, mais SEULEMENT s'il est vide ou a été créé par pixvox (fichier .pixvox).

    Évite d'effacer un dossier de travail (`--pack .`, `--out examples`…) : lève OutputDirError sinon.
    """
    p = Path(path)
    if p.exists():
        if not p.is_dir():
            raise OutputDirError(f"{what} {p} : c'est un fichier, pas un dossier")
        if any(p.iterdir()) and not (p / MARKER).is_file():
            raise OutputDirError(f"{what} {p} : dossier non vide qui n'a pas été créé par pixvox — pixvox le "
                                 "viderait ; choisir un autre dossier (ex. out/pack) ou le vider soi-même")
        shutil.rmtree(p)
    return p


def mark_output_dir(path) -> None:
    """Signe un dossier de sortie : le prochain export pourra le vider sans risque."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    (p / MARKER).write_text(_MARKER_TEXT, encoding="utf-8")
