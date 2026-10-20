"""Extrait la section d'une version de CHANGELOG.md (notes de la release GitHub).

    python scripts/release_notes.py v0.1.0 > notes.md
Sans section pour cette version : message par défaut (les notes générées par GitHub s'y ajoutent).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def notes(version: str, changelog: Path) -> str:
    v = version.lstrip("v")
    text = changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
    m = re.search(rf"^## \[?{re.escape(v)}\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    body = m.group(1).strip() if m else f"Version {v}."
    return body + ("\n\nInstallation : `pip install \"pixvox @ git+https://github.com/nicolas-goyon/PixVox@v"
                   f"{v}\"` ou la wheel ci-dessous ; skill Claude : `pixvox_skill.zip` ; mods de démo : "
                   "`pixvox_demo-*.jar` ; action : `uses: nicolas-goyon/PixVox@v" f"{v}`.\n")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.stdout.write(notes(sys.argv[1] if len(sys.argv) > 1 else "", root / "CHANGELOG.md"))
