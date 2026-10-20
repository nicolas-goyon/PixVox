"""Publication d'une version : contrôle préalable et notes de la release (workflow « Release »).

    python scripts/release.py check          # 1re étape du workflow (lit GITHUB_EVENT_NAME, GITHUB_EVENT_PATH…)
    python scripts/release.py notes v0.2.0   # notes : section de CHANGELOG.md + installation

check décide, d'après l'événement GitHub :
  - release publiée (page Releases du site, `gh release create`) : son tag doit valoir v + __version__
    de pixvox/__init__.py, sinon refus avant de construire quoi que ce soit ;
  - lancement manuel (Actions → Release → Run workflow) : publication seulement si « publish » est
    coché, depuis la branche par défaut et si le tag v<version> n'existe pas encore ; sans « publish »,
    construction de contrôle : rien n'est publié.
Version de test au sens PEP 440 (0.2.0rc1…) ou release cochée « pre-release » : prerelease=true.
Sorties : version, tag, prerelease, publish dans $GITHUB_OUTPUT ; résumé dans $GITHUB_STEP_SUMMARY.
Code 0 : la suite peut continuer ; 1 : refus, message ::error:: qui dit quoi corriger ; 2 : usage.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEP440 = re.compile(r"\d+\.\d+\.\d+(?:(?P<pre>a|b|rc)\d+)?(?:\.post\d+)?(?P<dev>\.dev\d+)?")


class ReleaseError(Exception):
    """Publication refusée ; le message dit quoi corriger."""


def package_version(root: Path = ROOT) -> str:
    """__version__ lu dans pixvox/__init__.py, sans importer pixvox (ni numpy, ni Pillow)."""
    text = (root / "pixvox" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.M)
    if not m:
        raise ReleaseError("__version__ introuvable dans pixvox/__init__.py")
    return m.group(1)


def is_prerelease(version: str) -> bool:
    m = PEP440.fullmatch(version)
    if not m:
        raise ReleaseError(f"__version__ = {version!r} : format attendu X.Y.Z, X.Y.ZrcN, X.Y.ZbN… (PEP 440)")
    return bool(m["pre"] or m["dev"])


def decide(event: str, payload: dict, ref: str, version: str, tag_exists) -> dict:
    """Que faire de cette exécution ? Lève ReleaseError si la publication demandée est impossible.

    tag_exists(tag) -> bool n'est appelé que pour un lancement manuel qui publie."""
    tag = f"v{version}"
    pre = is_prerelease(version)
    if event == "release":
        release = payload.get("release") or {}
        got = release.get("tag_name") or "?"
        if got != tag:
            raise ReleaseError(
                f"la release {got} ne correspond pas à pixvox/__init__.py ({version}) : supprimer cette release "
                f"et son tag, mettre __version__ et CHANGELOG.md à jour sur la branche par défaut, puis republier")
        return {"version": version, "tag": tag, "prerelease": pre or bool(release.get("prerelease")),
                "publish": True}
    inputs = payload.get("inputs") or {}
    publish = event == "workflow_dispatch" and str(inputs.get("publish", "")).lower() == "true"
    if publish:
        default = (payload.get("repository") or {}).get("default_branch") or "main"
        if ref != f"refs/heads/{default}":
            raise ReleaseError(f"publication depuis la branche {default} uniquement "
                               f"(choisie : {ref.removeprefix('refs/heads/') or '?'})")
        if tag_exists(tag):
            raise ReleaseError(f"{tag} existe déjà : augmenter __version__ (et CHANGELOG.md) sur {default}")
    return {"version": version, "tag": tag, "prerelease": pre, "publish": publish}


def section(version: str, changelog: str) -> str | None:
    """Corps de la section « ## [X.Y.Z] » de CHANGELOG.md, None si absente ([X.Y.Zrc1] n'est pas X.Y.Z)."""
    m = re.search(rf"^## \[?{re.escape(version)}(?:\]|[ \t]|$)[^\n]*(?:\n|\Z)(.*?)(?=^## |\Z)",
                  changelog, re.S | re.M)
    return m.group(1).strip() if m else None


def notes(tag: str, changelog: str) -> str:
    """Notes de la release : section du CHANGELOG (ou une ligne par défaut) puis l'installation."""
    v = tag.removeprefix("v")
    body = section(v, changelog) or f"Version {v}."
    return body + ("\n\nInstallation : `pip install \"pixvox @ git+https://github.com/nicolas-goyon/PixVox@v"
                   f"{v}\"` ou la wheel ci-dessous ; skill Claude : `pixvox_skill.zip` ; mods de démo : "
                   "`pixvox_demo-*.jar` ; action : `uses: nicolas-goyon/PixVox@v" f"{v}`.\n")


def remote_tag_exists(tag: str) -> bool:
    r = subprocess.run(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode not in (0, 2):                  # 2 : aucun tag de ce nom
        raise ReleaseError(f"tags du dépôt illisibles (git ls-remote) : {r.stderr.strip() or r.returncode}")
    return r.returncode == 0


def _changelog() -> str:
    p = ROOT / "CHANGELOG.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _append(var: str, text: str) -> None:
    """Ajoute au fichier désigné par la variable GitHub ($GITHUB_OUTPUT…) ; rien hors d'Actions."""
    if os.environ.get(var):
        with open(os.environ[var], "a", encoding="utf-8") as f:
            f.write(text)


def check() -> int:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    payload = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
    try:
        res = decide(os.environ.get("GITHUB_EVENT_NAME", ""), payload, os.environ.get("GITHUB_REF", ""),
                     package_version(), remote_tag_exists)
    except ReleaseError as e:
        print(f"::error title=Publication refusée::{e}")
        _append("GITHUB_STEP_SUMMARY", f"### Publication refusée\n\n{e}\n")
        return 1
    if section(res["version"], _changelog()) is None:
        print(f"::warning title=CHANGELOG.md::pas de section [{res['version']}] : "
              "les notes de la release se limiteront à la liste des PR")
    out = "".join(f"{k}={str(v).lower() if isinstance(v, bool) else v}\n" for k, v in res.items())
    _append("GITHUB_OUTPUT", out)
    sys.stdout.write(out)
    publish = "oui" if res["publish"] else "non (construction de contrôle)"
    _append("GITHUB_STEP_SUMMARY", f"### Release {res['tag']}\n\n| version | pré-version | publication |\n"
            f"|---|---|---|\n| {res['version']} | {'oui' if res['prerelease'] else 'non'} | {publish} |\n")
    return 0


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if argv == ["check"]:
        return check()
    if len(argv) == 2 and argv[0] == "notes":
        sys.stdout.write(notes(argv[1], _changelog()))
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
