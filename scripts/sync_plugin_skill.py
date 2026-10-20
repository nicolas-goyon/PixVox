"""Génère le skill du plugin Claude Code à partir de SKILL.md (source unique) :

    python scripts/sync_plugin_skill.py          # écrit claude-plugin/skills/pixvox/SKILL.md
    python scripts/sync_plugin_skill.py --check  # code 1 si la copie n'est pas à jour (CI)

Seule différence : la mise en route installe pixvox avec pip (le plugin ne contient pas le code).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "SKILL.md"
TARGET = ROOT / "claude-plugin" / "skills" / "pixvox" / "SKILL.md"
SETUP = """## Mise en route (une fois par machine)

```bash
python -m pip install "pixvox @ git+https://github.com/nicolas-goyon/PixVox"
python -m pixvox doctor          # auto-test d'export ; dit si les mods sont compilables (JDK 25 + Maven)
```
Installé ainsi avec pip, `pixvox` et `python -m pixvox` sont équivalents (avec pipx ou `uv tool`, seule la
commande `pixvox` marche). Les fichiers d'assets et les sorties (`out/`) vont dans le projet courant.
Sources, exemples, CI : https://github.com/nicolas-goyon/PixVox (consignes : AGENTS.md).

"""
NOTE = ("<!-- Fichier généré par scripts/sync_plugin_skill.py depuis SKILL.md : modifier SKILL.md, "
        "puis relancer le script. -->\n")


def render() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    new, n = re.subn(r"^## Mise en route.*?(?=^## )", lambda _: SETUP, text, count=1, flags=re.S | re.M)
    if n != 1:
        sys.exit("section « ## Mise en route » introuvable dans SKILL.md")
    head, sep, body = new.partition("\n---\n")             # après le front matter YAML
    return head + sep + NOTE + body


def main(argv) -> int:
    want = render()
    if "--check" in argv:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != want:
            print(f"{TARGET.relative_to(ROOT)} n'est pas à jour : python scripts/sync_plugin_skill.py")
            return 1
        print("skill du plugin à jour")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(want, encoding="utf-8")
    print(f"écrit : {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
