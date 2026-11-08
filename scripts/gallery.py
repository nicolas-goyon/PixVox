"""Galerie des exemples (#29) : page statique, publiée sur GitHub Pages par le workflow « Galerie ».

    python scripts/gallery.py --out site/                       # toute la galerie, à relire avant publication
    python scripts/gallery.py --out site/ examples/brazier.py   # quelques fichiers seulement

Pour chaque asset de `examples/` : vignette (vue d'inventaire), vue « en jeu », planche de revue, GIF s'il
est animé, lien vers le fichier source, commandes pour le reproduire, et résultat de la vérification de
l'export pour les deux cibles (1.21.4+ et 1.21.1), relu du disque comme le jeu le lit. La page n'a besoin
d'aucun serveur : un dossier de fichiers (index.html, images, results.json), liens relatifs.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pixvox import __version__  # noqa: E402
from pixvox.cli import asset_kind, load_assets  # noqa: E402
from pixvox.export import export_assets, verified  # noqa: E402
from pixvox.review import anim_gif, review_data, view  # noqa: E402

REPO = "https://github.com/nicolas-goyon/PixVox"
TARGETS = ("1.21.4+", "1.21.1")
KIND_FR = {"block": "bloc", "model": "modèle", "multiblock": "objet multibloc", "multipart": "bloc multipart",
           "variant": "variante", "item": "item"}


def _doc(path: Path) -> tuple[str, list]:
    """(titre, blocs) tirés de la docstring du fichier d'exemple : blocs = [("p", texte) | ("ul", [éléments])],
    les exemples de code (lignes indentées) en moins."""
    import ast
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or path.stem
    first, _, rest = doc.partition("\n")
    blocks = []
    for para in rest.strip().split("\n\n"):
        lines = [ln for ln in para.splitlines() if ln.strip() and not ln.startswith("    ")]
        if not lines:
            continue
        if lines[0].lstrip().startswith("- "):
            items, cur = [], []
            for ln in lines:
                if ln.lstrip().startswith("- ") and cur:
                    items.append(" ".join(cur))
                    cur = []
                cur.append(ln.strip().removeprefix("- "))
            items.append(" ".join(cur))
            blocks.append(("ul", items))
        else:
            blocks.append(("p", " ".join(ln.strip() for ln in lines)))
    return first.strip().rstrip("."), blocks


def _blocks_html(blocks: list) -> str:
    out = []
    for kind, val in blocks:
        if kind == "ul":
            out.append("<ul>" + "".join(f"<li>{_e(i)}</li>" for i in val) + "</ul>")
        else:
            out.append(f"<p>{_e(val)}</p>")
    return f'<div class="desc">{"".join(out)}</div>' if out else ""


def _verify(path: Path, tmp: Path) -> dict:
    """{nom d'asset: {cible: {"verified", "diff_px"}}} : export du fichier pour chaque cible."""
    out: dict = {}
    assets = load_assets(str(path))
    for mc in TARGETS:
        res = export_assets(assets, tmp / f"{path.stem}_{mc.replace('+', 'p').replace('.', '_')}", mc=mc, log=None)
        for info in res["infos"]:
            out.setdefault(info["name"], {})[mc] = {"verified": verified(info), "diff_px": info["verify"]["diff_px"]}
        for r in res["refused"]:
            out.setdefault(r["name"], {})[mc] = {"verified": False, "refused": r.get("reason", "refusé")}
    return out


def build(out: Path, files: list) -> dict:
    """Construit la galerie dans `out` (remplacé). Renvoie le résumé (aussi écrit dans results.json)."""
    t0 = time.time()
    if out.exists():
        shutil.rmtree(out)
    img = out / "img"
    img.mkdir(parents=True)
    groups = []
    with tempfile.TemporaryDirectory(prefix="pixvox_gallery_") as td:
        tmp = Path(td)
        for path in files:
            path = Path(path)
            rel = path.resolve().relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else path.name
            title, desc = _doc(path)
            checks = _verify(path, tmp)
            entries = []
            for a in load_assets(str(path)):
                r = review_data(a, tmp / "rev")
                files_out = {"sheet": _copy(r["sheet"], img, f"{a.name}.review.png")}
                files_out["thumb"] = _copy(view(a, 225, 30, 360, "gui", out_dir=tmp / "v"), img, f"{a.name}.thumb.png")
                if asset_kind(a) != "item":
                    files_out["world"] = _copy(view(a, 135, 22, 520, "world", out_dir=tmp / "w"), img,
                                               f"{a.name}.world.png")
                if r["anim"]:                                    # GIF d'une vue, cadré comme la vignette
                    files_out["gif"] = anim_gif(a, img / f"{a.name}.gif", 360).relative_to(out).as_posix()
                counts = {lv: sum(f.level == lv for f in r["findings"]) for lv in ("OK", "INFO", "WARN", "ERR")}
                entries.append({"name": a.name, "kind": asset_kind(a), "files": files_out, "counts": counts,
                                "checks": checks.get(a.name, {})})
            groups.append({"file": rel, "title": title, "description": desc, "assets": entries})
    total = [e for g in groups for e in g["assets"]]
    summary = {"pixvox": __version__, "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "assets": len(total), "files": len(groups), "targets": list(TARGETS),
               "all_verified": all(c.get("verified") for e in total for c in e["checks"].values())
               and all(len(e["checks"]) == len(TARGETS) for e in total),
               "seconds": round(time.time() - t0, 1), "groups": groups}
    (out / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "index.html").write_text(_page(summary), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")         # Pages : servir les fichiers tels quels
    return summary


def _copy(src, folder: Path, name: str) -> str:
    shutil.copyfile(src, folder / name)
    return f"img/{name}"


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _badge(mc: str, c: dict) -> str:
    if c.get("verified"):
        return f'<span class="ok" title="relu du disque et comparé : {c["diff_px"]} px d\'écart">✓ {_e(mc)}</span>'
    why = c.get("refused") or f'{c.get("diff_px", "?")} px d\'écart'
    return f'<span class="ko" title="{_e(why)}">✗ {_e(mc)}</span>'


def _card(g: dict, e: dict) -> str:
    f = e["files"]
    checks = "".join(_badge(mc, e["checks"][mc]) for mc in TARGETS if mc in e["checks"]) or '<span class="ko">non vérifié</span>'
    warn = e["counts"]["WARN"] + e["counts"]["ERR"]
    alerts = f" · {warn} alerte(s) d'analyse" if warn else ""      # pas de \ dans une f-string (Python 3.10)
    media = f'<img class="thumb" src="{_e(f["thumb"])}" alt="{_e(e["name"])}, vue d\'inventaire" loading="lazy">'
    if "gif" in f:
        media = f'<img class="thumb" src="{_e(f["gif"])}" alt="{_e(e["name"])}, animation" loading="lazy">'
    links = [f'<a href="{_e(f["sheet"])}">planche de revue</a>']
    if "world" in f:
        links.append(f'<a href="{_e(f["world"])}">en jeu</a>')
    if "gif" in f:
        links.append(f'<a href="{_e(f["thumb"])}">image fixe</a>')
    links.append(f'<a href="{REPO}/blob/main/{_e(g["file"])}">source</a>')
    cmd = (f'pixvox review {g["file"]} --only {e["name"]}\npixvox export {g["file"]}\n'
           f'pixvox export {g["file"]} --mc 1.21.1')
    return f'''<article class="card" id="{_e(e["name"])}">
  <a class="frame" href="{_e(f["sheet"])}">{media}</a>
  <div class="meta">
    <h3>{_e(e["name"])}</h3>
    <p class="kind">{_e(KIND_FR.get(e["kind"], e["kind"]))}{alerts}</p>
    <p class="checks">{checks}</p>
    <p class="links">{" · ".join(links)}</p>
    <details><summary>reproduire</summary><pre><code>{_e(cmd)}</code></pre></details>
  </div>
</article>'''


def _page(s: dict) -> str:
    sections = []
    for g in s["groups"]:
        cards = "\n".join(_card(g, e) for e in g["assets"])
        sections.append(f'''<section>
  <header class="group"><h2><a href="{REPO}/blob/main/{_e(g["file"])}">{_e(g["file"])}</a></h2>
  <p class="title">{_e(g["title"])}</p>{_blocks_html(g["description"])}</header>
  <div class="grid">{cards}</div>
</section>''')
    state = ("toutes vérifiées" if s["all_verified"] else "certaines non vérifiées")
    return f'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galerie pixvox</title>
<meta name="description" content="Les exemples de pixvox tels que Minecraft les affiche : planches de revue, animations, vérification de l'export.">
<style>
:root {{ --bg:#16181d; --panel:#21242c; --line:#2e323c; --text:#e3e6ec; --muted:#9aa1ad; --ok:#6fd38a; --ko:#ff8b7a; --accent:#e8b25c; }}
@media (prefers-color-scheme: light) {{ :root {{ --bg:#f4f2ee; --panel:#ffffff; --line:#dedad2; --text:#1d1f24; --muted:#5f6570; --ok:#1f7a3a; --ko:#b3261e; --accent:#9a5b00; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
a {{ color:var(--accent); }}
.top {{ max-width:1200px; margin:0 auto; padding:32px 16px 8px; }}
.top h1 {{ margin:0 0 6px; font-size:28px; letter-spacing:.2px; }}
.top p {{ margin:4px 0; color:var(--muted); max-width:780px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 0; padding:0; list-style:none; }}
.stats li {{ background:var(--panel); border:1px solid var(--line); border-radius:999px; padding:3px 12px; font-size:13px; }}
main {{ max-width:1200px; margin:0 auto; padding:8px 16px 48px; }}
section {{ margin-top:28px; }}
.group h2 {{ margin:0; font:600 15px ui-monospace, SFMono-Regular, Menlo, monospace; }}
.group h2 a {{ color:var(--text); text-decoration:none; }}
.group .title {{ margin:2px 0 0; font-size:17px; }}
.group .desc {{ margin:4px 0 0; color:var(--muted); font-size:14px; max-width:900px; }}
.group .desc p {{ margin:4px 0 0; }}
.group .desc ul {{ margin:4px 0 0; padding-left:20px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:14px; margin-top:12px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }}
.frame {{ display:block; background:#2a2d36; aspect-ratio:1; }}
.thumb {{ width:100%; height:100%; object-fit:contain; image-rendering:pixelated; display:block; }}
.meta {{ padding:10px 12px 12px; }}
.meta h3 {{ margin:0; font:600 14px ui-monospace, SFMono-Regular, Menlo, monospace; word-break:break-all; }}
.meta p {{ margin:4px 0 0; font-size:13px; }}
.kind {{ color:var(--muted); }}
.checks span {{ display:inline-block; margin-right:6px; font-weight:600; }}
.ok {{ color:var(--ok); }} .ko {{ color:var(--ko); }}
details {{ margin-top:6px; font-size:13px; }}
summary {{ cursor:pointer; color:var(--muted); }}
pre {{ margin:6px 0 0; padding:8px; background:var(--bg); border-radius:6px; overflow-x:auto; font-size:12px; }}
footer {{ max-width:1200px; margin:0 auto; padding:0 16px 32px; color:var(--muted); font-size:13px; }}
</style>
</head>
<body>
<div class="top">
  <h1>Galerie pixvox</h1>
  <p>Chaque exemple du dépôt tel que Minecraft l'affiche, rendu par pixvox. Cliquer une vignette ouvre la
  planche de revue (vues, patron, analyse). La coche indique que l'export a été relu du disque et comparé au
  pixel près, pour chaque version de Minecraft visée.</p>
  <ul class="stats"><li>{s["assets"]} assets</li><li>{s["files"]} fichiers d'exemple</li>
  <li>exports {state} ({" et ".join(_e(t) for t in s["targets"])})</li><li>pixvox {_e(s["pixvox"])}</li></ul>
</div>
<main>
{chr(10).join(sections)}
</main>
<footer>Générée le {_e(s["generated"])} par <code>scripts/gallery.py</code> ·
<a href="{REPO}">dépôt</a> · <a href="results.json">résultats (JSON)</a></footer>
</body>
</html>
'''


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="galerie statique des exemples de pixvox")
    ap.add_argument("files", nargs="*", help="fichiers d'exemple (défaut : examples/*.py)")
    ap.add_argument("--out", default="site", help="dossier de sortie (remplacé ; défaut : site)")
    args = ap.parse_args(argv)
    files = [Path(f) for f in args.files] or sorted((ROOT / "examples").glob("*.py"))
    s = build(Path(args.out), files)
    print(f"{args.out}/index.html : {s['assets']} assets, {s['files']} fichiers, "
          f"{'tous vérifiés' if s['all_verified'] else 'CERTAINS NON VÉRIFIÉS'} ({s['seconds']} s)")
    return 0 if s["all_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
