"""Publie (ou met à jour) le commentaire « Aperçu pixvox » d'une PR — utilisé par .github/workflows/preview.yml.

Variables d'environnement : GH_TOKEN, GITHUB_REPOSITORY, PR, REVIEW_MD, EXPORT_MD (chemins des résumés
Markdown), REVIEW_URL, PACK_URL (liens d'artefacts), RUN_URL. N'utilise que l'API REST via `gh`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MARKER = "<!-- pixvox-apercu -->"
BOT = "github-actions[bot]"                       # auteur des commentaires faits avec GITHUB_TOKEN
LIMIT = 60000                                     # un commentaire GitHub est limité à 65 536 caractères


def _read(var: str) -> str:
    p = os.environ.get(var, "")
    return Path(p).read_text(encoding="utf-8") if p and Path(p).is_file() else "_(résumé indisponible)_\n"


def _gh(*args: str, body: str | None = None) -> str:
    cmd = ["gh", "api", *args]
    if body is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps({"body": body}) if body is not None else None,
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return r.stdout


def main() -> int:
    repo, pr = os.environ["GITHUB_REPOSITORY"], os.environ["PR"]
    links = []
    if os.environ.get("REVIEW_URL"):
        links.append(f"[planches de revue et GIF]({os.environ['REVIEW_URL']})")
    if os.environ.get("PACK_URL"):
        links.append(f"[resource pack de test]({os.environ['PACK_URL']})")
    if os.environ.get("RUN_URL"):
        links.append(f"[exécution]({os.environ['RUN_URL']})")
    body = "\n".join([MARKER, "## Aperçu pixvox", "",
                      "Téléchargements : " + " · ".join(links) if links else "", "",
                      _read("REVIEW_MD"), _read("EXPORT_MD"),
                      "<sub>Mis à jour automatiquement à chaque poussée (workflow « Aperçu des assets »).</sub>"])
    if len(body) > LIMIT:
        body = body[:LIMIT] + "\n\n… (tronqué : voir le résumé de l'exécution)"
    pages = _gh("--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments?per_page=100") or "[]"
    comments = [c for page in json.loads(pages) for c in page]
    mine = [c for c in comments if c.get("body", "").startswith(MARKER)
            and (c.get("user") or {}).get("login") == BOT]          # jamais le commentaire de quelqu'un d'autre
    if mine:
        _gh("-X", "PATCH", f"repos/{repo}/issues/comments/{mine[0]['id']}", body=body)
    else:
        _gh("-X", "POST", f"repos/{repo}/issues/{pr}/comments", body=body)
    print(f"commentaire {'mis à jour' if mine else 'publié'} sur la PR #{pr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
