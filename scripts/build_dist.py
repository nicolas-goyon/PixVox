"""Construit les livrables d'une version dans dist/ (utilisé par la CI et par le workflow de release).

    python scripts/build_dist.py [--out dist] [--check] [--no-python] [--no-pack]

Produit :
  - pixvox-<version>-py3-none-any.whl et pixvox-<version>.tar.gz   (pip install …)
  - pixvox_skill.zip            skill pour Claude : SKILL.md + paquet + exemples + tests, autonome
  - pixvox_demo_pack.zip        tous les exemples exportés et vérifiés (resource pack Java)
  - pixvox_demo_pack_datapack.zip   placement des objets multiblocs sans mod
--check contrôle la licence de la wheel, puis décompresse le skill dans un dossier temporaire et y lance
`python -m pixvox doctor` SANS installation (c'est ainsi que Claude l'utilise) et toute la suite de
tests (`tests/run.py`).
Les .jar des mods de démo sont produits par le job « mods » (JDK 25 requis).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # pixvox importable même sans installation
SKILL_FILES = ["SKILL.md", "README.md", "LICENSE", "CHANGELOG.md", "docs/cli.md"]
SKILL_DIRS = ["pixvox", "examples", "tests"]


def _skip(p: Path) -> bool:
    return "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo") or p.name == ".DS_Store"


def build_skill(out: Path) -> Path:
    """Zip du skill : un dossier pixvox/ dont SKILL.md est à la racine (format attendu par claude.ai)."""
    z = out / "pixvox_skill.zip"
    n = 0
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in SKILL_FILES:
            if (ROOT / rel).is_file():
                zf.write(ROOT / rel, f"pixvox/{rel}")
                n += 1
        for d in SKILL_DIRS:
            for p in sorted((ROOT / d).rglob("*")):
                if p.is_file() and not _skip(p.relative_to(ROOT)):
                    info = zipfile.ZipInfo(f"pixvox/{p.relative_to(ROOT).as_posix()}")
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (0o755 if p.name == "gradlew" else 0o644) << 16
                    zf.writestr(info, p.read_bytes())
                    n += 1
    print(f"skill : {z} ({n} fichiers, {z.stat().st_size // 1024} Ko)")
    return z


def build_python(out: Path) -> None:
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(out), str(ROOT)], check=True)


def build_pack(out: Path) -> None:
    from pixvox.cli import run
    examples = sorted(str(p) for p in (ROOT / "examples").glob("*.py"))
    with tempfile.TemporaryDirectory(prefix="pixvox_dist_", ignore_cleanup_errors=True) as tmp:
        code, res = run(["export", *examples, "--pack", str(Path(tmp) / "pixvox_demo_pack"),
                         "--zip", str(out / "pixvox_demo_pack.zip"), "--json"])
    if code != 0:
        sys.exit(f"export des exemples en échec (code {code}) : {res['errors']}")
    print(f"pack de démo : {len(res['assets'])} assets vérifiés -> {out / 'pixvox_demo_pack.zip'}")


def check_wheel(out: Path) -> None:
    """La wheel déclare sa licence (PEP 639 : License-Expression) et embarque le fichier LICENSE."""
    wheel = next(out.glob("pixvox-*.whl"))
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        meta = zf.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode("utf-8")
    assert "License-Expression: MIT" in meta.splitlines(), "licence absente des métadonnées de la wheel"
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names), "LICENSE absent de la wheel"
    print(f"wheel : licence MIT déclarée, LICENSE inclus ({wheel.name})")


def check_skill(z: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="pixvox_skill_", ignore_cleanup_errors=True) as tmp:
        zipfile.ZipFile(z).extractall(tmp)
        skill = Path(tmp) / "pixvox"
        assert (skill / "SKILL.md").is_file(), "SKILL.md absent de la racine du skill"
        env = dict(os.environ, PYTHONPATH="")                       # pas le dépôt : le skill seul
        for cmd in ([sys.executable, "-m", "pixvox", "doctor"], [sys.executable, "tests/run.py"]):
            subprocess.run(cmd, cwd=skill, env=env, check=True)
    print("skill autonome : OK (doctor + toute la suite de tests depuis le zip décompressé)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="dist")
    ap.add_argument("--check", action="store_true", help="vérifier le skill décompressé")
    ap.add_argument("--no-python", action="store_true", help="ne pas construire wheel et sdist")
    ap.add_argument("--no-pack", action="store_true", help="ne pas exporter le pack de démo")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if not a.no_python:
        build_python(out)
    z = build_skill(out)
    if not a.no_pack:
        build_pack(out)
    if a.check:
        if not a.no_python:
            check_wheel(out)
        check_skill(z)
    for p in sorted(out.iterdir()):
        print(f"  {p.name:45s} {p.stat().st_size // 1024:6d} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
