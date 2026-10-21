"""Étape principale de l'action GitHub (action.yml), en Python pour marcher partout (Linux, macOS avec
bash 3.2, Windows) : motifs glob -> fichiers, arguments découpés comme un shell, `pixvox … --json`,
résultat + résumé dans out/, sorties de l'étape (GITHUB_OUTPUT).

Variables lues : PIXVOX_CMD, PIXVOX_FILES, PIXVOX_ARGS, PIXVOX_UPLOAD_PATH, PIXVOX_ARTIFACT_NAME,
PIXVOX_JOB_SUMMARY, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY, GITHUB_JOB. Le code de pixvox est exposé en sortie ; l'étape elle-même réussit
(une étape suivante de l'action échoue si `fail` est vrai).
"""
from __future__ import annotations

import glob
import json
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path


def expand(patterns: str) -> list[str]:
    """Motifs séparés par des espaces ou des retours à la ligne ; `**` descend dans les sous-dossiers.
    Un motif sans correspondance est passé tel quel (pixvox répond alors « fichier introuvable »)."""
    out: list[str] = []
    for p in patterns.split():
        matches = sorted(glob.glob(p, recursive=True))
        out += [m.replace(os.sep, "/") for m in matches] if matches else [p]
    return out


def outputs(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    lines = []
    for k, v in values.items():
        v = str(v)
        if "\n" in v:
            lines += [f"{k}<<PIXVOX_EOF", v, "PIXVOX_EOF"]
        else:
            lines.append(f"{k}={v}")
    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def upload_paths(cmd: str, custom: str) -> str:
    """Chemins absolus (upload-artifact part de la racine du dépôt, pas de working-directory)."""
    def absolute(line: str) -> str:
        neg = line.startswith("!")
        return ("!" if neg else "") + os.path.abspath(line[1:] if neg else line).replace(os.sep, "/")
    if custom.strip():
        lines = [ln.strip() for ln in custom.split("\n") if ln.strip()] + [f"out/pixvox-{cmd}.json"]
    else:
        lines = ["out", "!out/**/.gradle", "!out/**/build/tmp", "!out/**/build/classes",
                 "!out/**/build/resources", "!out/**/*.tmp_pixvox"]
    return "\n".join(absolute(ln) for ln in lines)


def main() -> int:
    cmd = os.environ.get("PIXVOX_CMD", "export").strip()
    files = expand(os.environ.get("PIXVOX_FILES", ""))
    out = Path("out")
    result, summary = out / f"pixvox-{cmd}.json", out / f"pixvox-{cmd}.md"
    try:
        extra = shlex.split(os.environ.get("PIXVOX_ARGS", ""))
    except ValueError as e:                        # guillemet non fermé…
        code, doc = 2, {"schema": "pixvox.result/2", "command": cmd, "ok": False, "exit_code": 2,
                        "errors": [{"type": "usage", "message": f"entrée args illisible : {e}"}], "warnings": []}
        print(f"::error title=pixvox::entrée args illisible ({e})")
    else:
        argv = [sys.executable, "-m", "pixvox", cmd, *files, *extra, "--json"]
        print("pixvox " + " ".join(shlex.quote(a) for a in argv[3:]), flush=True)
        r = subprocess.run(argv, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        code = r.returncode
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            doc = {"schema": "pixvox.result/2", "command": cmd, "ok": False, "exit_code": code,
                   "errors": [{"type": "internal", "message": "sortie non JSON : " + r.stdout[-500:]}], "warnings": []}
    out.mkdir(parents=True, exist_ok=True)         # après pixvox : `--pack out` ne l'efface pas
    result.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from pixvox.summary import to_markdown
        summary.write_text(to_markdown(doc), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - le résumé ne doit jamais masquer le résultat
        summary.write_text(f"pixvox {cmd} : code {code} (résumé indisponible : {e})\n", encoding="utf-8")
    job_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if job_summary and os.environ.get("PIXVOX_JOB_SUMMARY", "true") == "true":
        with open(job_summary, "a", encoding="utf-8") as fh:
            fh.write(summary.read_text(encoding="utf-8") + "\n")
    name = os.environ.get("PIXVOX_ARTIFACT_NAME", "").strip() or \
        f"pixvox-{cmd}-{os.environ.get('GITHUB_JOB', 'job')}-{secrets.token_hex(3)}"
    outputs({"exit-code": code, "ok": "true" if code == 0 else "false", "result": result.resolve(),
             "summary": summary.resolve(), "artifact-name": name,
             "upload-path": upload_paths(cmd, os.environ.get("PIXVOX_UPLOAD_PATH", ""))})
    print(f"pixvox {cmd} : code de sortie {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
