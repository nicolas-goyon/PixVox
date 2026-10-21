"""Ligne de commande pixvox — pour les humains, les agents et les logiciels (pixvox <commande> --help).

  review   fichier.py [autre.py…] [--out DOSSIER] [--only NOM] [--fail-on never|warn|err]
  view     fichier.py --yaw 135 --pitch 20 [--persp 2] [--size 700] [--shading gui|world|night|flat] [--tick T]
  anim     fichier.py [--only NOM] [--out DOSSIER]                 images d'une animation + GIF
  ascii    fichier.py [--only NOM] [--face up|down|north|south|west|east]
  export   fichier.py [autre.py…] [--pack DOSSIER] [--ns pixvox] [--zip FICHIER.zip] [--replace nom=minecraft:stone]
           [--mc 1.21.4+|1.21.1]
  mod      fichier.py [autre.py…] --modid mon_mod [--loader fabric|neoforge] [--build] [--java-home JDK25]
  compare  fichier.py [autre.py…] [--out FICHIER.png] [--size 300]
  render-model DOSSIER_PACK ns:block/nom [--out FICHIER.png] [--yaw 225] [--pitch 30] [--tick T]
  new      nom [--kind block|model|multiblock|item|animated] [--dir .]   crée un fichier d'asset de départ
  doctor   [--java-home JDK25]                                       vérifie l'installation (+ export test)
  summary  résultat.json [--format markdown|text]                    résumé lisible d'un résultat --json

--json (toutes les commandes) : un seul document JSON sur la sortie standard, le journal lisible part sur
la sortie d'erreur. Codes de sortie : 0 réussi ; 1 vérification échouée (écart de rendu, asset refusé,
compilation ratée, seuil --fail-on atteint) ; 2 erreur d'utilisation ou d'environnement (fichier absent,
asset qui plante, JDK absent) ; 3 erreur interne de pixvox. Contrat détaillé : docs/cli.md.

Un fichier d'asset définit build() -> asset | liste d'assets (Block, Model, MultiBlock, Item).
Noms d'assets : minuscules, chiffres et _ (identifiants Minecraft).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import runpy
import sys
import time
import traceback
from collections import Counter
from contextlib import nullcontext, redirect_stdout
from pathlib import Path

from . import __version__
from ._io import OutputDirError, say

SCHEMA = "pixvox.result/2"          # /2 : export indique la version de Minecraft visée (champ mc)
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERNAL = 0, 1, 2, 3
KINDS = ("block", "model", "multiblock", "item", "animated")
MC_TARGETS = ("1.21.4+", "1.21.1")  # = pixvox.export.TARGETS (sans importer numpy pour --help)
FACE_ALIASES = {"top": "up", "bottom": "down", "haut": "up", "dessus": "up", "bas": "down", "dessous": "down",
                "nord": "north", "sud": "south", "ouest": "west", "est": "east"}


class CliError(Exception):
    """Erreur rapportée proprement (message + code de sortie), en texte ou dans le JSON."""

    def __init__(self, message: str, *, type: str = "input", code: int = EXIT_USAGE, **where):
        super().__init__(message)
        self.type, self.code, self.where = type, code, where

    def as_dict(self) -> dict:
        return {"type": self.type, "message": str(self), **{k: v for k, v in self.where.items() if v is not None}}


class _Parser(argparse.ArgumentParser):
    """argparse qui lève CliError au lieu de quitter, pour pouvoir répondre en JSON."""

    def error(self, message):
        err = CliError(message, type="usage")
        err.parser = self
        raise err


# ============================================================================ outils
def asset_kind(asset) -> str:
    """'block' | 'model' | 'multiblock' | 'item' (identifiants stables, pour les logiciels)."""
    from .assets import Block, Item, Model, MultiBlock
    for cls, name in ((MultiBlock, "multiblock"), (Block, "block"), (Model, "model"), (Item, "item")):
        if isinstance(asset, cls):
            return name
    return type(asset).__name__.lower()


def _is_animated(asset) -> bool:
    return any(n > 1 for _, n in getattr(asset, "anims", []))


def _jsonable(x):
    """Convertit récursivement en types JSON (chemins en / , tableaux numpy, tuples, ensembles)."""
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(_jsonable(v) for v in x)
    if isinstance(x, Path):
        return x.as_posix()
    if hasattr(x, "tolist"):                       # numpy : scalaires et tableaux
        return x.tolist()
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def load_assets(path: str) -> list:
    """Exécute un fichier d'asset et renvoie ses assets (build() ou variables globales)."""
    from .assets import Asset
    p = Path(path)
    if not p.is_file():
        raise CliError(f"fichier introuvable : {path}", file=path)
    sys.path.insert(0, str(p.resolve().parent))
    try:
        ns = runpy.run_path(str(p), run_name="__pixvox_asset__")
        if "build" in ns and callable(ns["build"]):
            res = ns["build"]()
            out = list(res) if isinstance(res, (list, tuple)) else [res]
        else:
            out = [v for v in ns.values() if isinstance(v, Asset)]
    except CliError:
        raise
    except (Exception, SystemExit) as e:  # noqa: BLE001 - le code de l'asset peut lever n'importe quoi
        traceback.print_exc(file=sys.stderr)
        raise CliError(f"{path} : {type(e).__name__}: {e}", type="asset_code", file=path) from e
    finally:
        if sys.path and sys.path[0] == str(p.resolve().parent):
            sys.path.pop(0)
    bad = [type(a).__name__ for a in out if not isinstance(a, Asset)]
    if bad:
        raise CliError(f"{path} : build() doit renvoyer des Block / Model / MultiBlock / Item "
                       f"(reçu : {', '.join(bad)})", file=path)
    if not out:
        raise CliError(f"{path} : aucun asset (définir build() qui renvoie un asset ou une liste d'assets)", file=path)
    return out


def _load_many(files, only: str | None = None) -> list:
    """[(fichier, asset)] de tous les fichiers ; --only garde un seul nom (erreur s'il n'existe nulle part)."""
    pairs = [(f, a) for f in files for a in load_assets(f)]
    names = [a.name for _, a in pairs]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise CliError(f"noms d'assets en double : {', '.join(dup)}")
    if only:
        pairs = [(f, a) for f, a in pairs if a.name == only]
        if not pairs:
            raise CliError(f"aucun asset nommé {only!r} (disponibles : {', '.join(names)})")
    return pairs


def _check_outputs(files, *dirs) -> None:
    """Refuse un dossier de sortie (recréé à chaque fois) qui contient un fichier d'entrée."""
    for d in dirs:
        if d is None:
            continue
        target = Path(d).resolve()
        for f in files:
            if target == Path(f).resolve() or target in Path(f).resolve().parents:
                raise CliError(f"le dossier de sortie {d} contient le fichier d'entrée {f} : il serait effacé",
                               type="output_dir")


def _positive(text: str) -> int:
    v = int(text)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"entier strictement positif attendu (reçu {text})")
    return v


def _entry(f, a) -> dict:
    return {"name": a.name, "kind": asset_kind(a), "file": Path(f).as_posix(), "animated": _is_animated(a)}


# ============================================================================ commandes
def cmd_review(args, out) -> int:
    from .review import review_data
    entries = []
    for f, a in _load_many(args.files, args.only):
        r = review_data(a, args.out)
        say(r["report"])
        say(f"planche : {r['sheet']}")
        if r["anim"]:
            say(f"animation : {r['anim'][0]} (images) | {r['anim'][1]} (GIF)")
        say()
        counts = Counter(x.level for x in r["findings"])
        entries.append({**_entry(f, a), "sheet": r["sheet"], "report_file": r["report_file"],
                        "anim_sheet": r["anim"][0] if r["anim"] else None,
                        "anim_gif": r["anim"][1] if r["anim"] else None,
                        "counts": {k: counts.get(k, 0) for k in ("OK", "INFO", "WARN", "ERR")},
                        "findings": [{"level": x.level, "topic": x.topic, "message": x.msg} for x in r["findings"]]})
    out["assets"] = entries
    levels = {"never": (), "warn": ("WARN", "ERR"), "err": ("ERR",)}[args.fail_on]
    flagged = [e["name"] for e in entries if any(e["counts"][lv] for lv in levels)]
    if flagged:
        out["errors"].append({"type": "quality", "message": f"alertes {'/'.join(levels)} (--fail-on {args.fail_on}) "
                                                            f"sur : {', '.join(flagged)}"})
        return EXIT_FAILED
    return EXIT_OK


def cmd_view(args, out) -> int:
    from .review import view
    entries = []
    for f, a in _load_many([args.file], args.only):
        path = view(a, args.yaw, args.pitch, args.size, args.shading, out_dir=args.out, persp=args.persp,
                    tick=args.tick)
        say(path)
        entries.append({**_entry(f, a), "image": path})
    out["assets"] = entries
    return EXIT_OK


def cmd_anim(args, out) -> int:
    from .review import anim_sheet
    entries = []
    for f, a in _load_many(args.files, args.only):
        if _is_animated(a):
            png, gif = anim_sheet(a, args.out)
            say(f"{a.name} : {png} | {gif}")
            entries.append({**_entry(f, a), "sheet": png, "gif": gif})
        else:
            say(f"{a.name} : pas animé")
            entries.append(_entry(f, a))
    out["assets"] = entries
    if not any(e["animated"] for e in entries):
        raise CliError("aucun asset animé (liste de volumes, Anim ou plans animés attendus)")
    return EXIT_OK


def cmd_ascii(args, out) -> int:
    from .assets import Block, Item
    from .volume import FACES
    face = None
    if args.face:
        face = FACE_ALIASES.get(args.face.lower(), args.face.lower())
        if face not in FACES:
            raise CliError(f"face inconnue {args.face!r} : {', '.join(FACES)} (alias : top, bottom)")
    entries = []
    for f, a in _load_many([args.file], args.only):
        say(f"=== {a.name}")
        e = _entry(f, a)
        if isinstance(a, Item):
            e["ascii"] = a.sprite.to_ascii()
            say(e["ascii"])
        elif isinstance(a, Block):
            faces = a.faces()
            e["faces"] = {}
            for fc in ([face] if face else list(faces)):
                e["faces"][fc] = faces[fc].to_ascii()
                say(f"--- face {fc} (x = colonne du PNG, y = ligne)")
                say(e["faces"][fc])
        else:
            e["slices"] = a.volume.to_slices_ascii()
            say(e["slices"])
        entries.append(e)
    out["assets"] = entries
    return EXIT_OK


def _replacements(items) -> dict:
    repl = {}
    for s in items:
        if "=" not in s:
            raise CliError(f"--replace attend nom=minecraft:bloc (reçu {s!r})")
        k, val = s.split("=", 1)
        repl[k] = val
    return repl


def _export_entries(pairs, infos) -> list:
    from .export import KINDS_EN, verified
    files = {a.name: f for f, a in pairs}
    skip = {"name", "kind", "model", "verify", "warnings"}
    return [{"name": i["name"], "kind": KINDS_EN.get(i["kind"], i["kind"]), "file": Path(files[i["name"]]).as_posix(),
             "model": i["model"], "verified": verified(i), "verify": i["verify"], "warnings": i.get("warnings", []),
             "details": {k: v for k, v in i.items() if k not in skip}} for i in infos]


def _verification_errors(entries) -> list:
    errs = []
    for e in entries:
        if not e["verified"]:
            v = e["verify"]
            msg = f"{e['name']} : le re-rendu de l'export diffère de l'asset ({v['diff_px']} px)"
            if v.get("missing"):
                msg += f", textures manquantes : {', '.join(v['missing'])}"
            errs.append({"type": "verification", "asset": e["name"], "file": e["file"], "message": msg})
    return errs


def cmd_export(args, out) -> int:
    from .export import NAMESPACE_RE, export_assets
    if not NAMESPACE_RE.fullmatch(args.ns):
        raise CliError(f"--ns {args.ns!r} invalide : minuscules, chiffres, _ . - (Minecraft refuse le reste)",
                       type="usage")
    pack = Path(args.pack)
    _check_outputs(args.files, pack, pack.parent / f"{pack.name}_datapack")
    pairs = _load_many(args.files)
    res = export_assets([a for _, a in pairs], args.pack, args.ns, args.zip, _replacements(args.replace), mc=args.mc)
    out.update({"pack": res["pack"], "zip": res["zip"], "datapack": res["datapack"],
                "datapack_zip": res["datapack_zip"], "namespace": args.ns, "mc": res["mc"]})
    out["assets"] = _export_entries(pairs, res["infos"])
    files = {a.name: f for f, a in pairs}
    out["refused"] = [{"name": n, "file": Path(files[n]).as_posix(), "message": m} for n, m in res["refused"]]
    out["errors"] += [{"type": "refused", "asset": r["name"], "file": r["file"], "message": r["message"]}
                      for r in out["refused"]]
    out["errors"] += _verification_errors(out["assets"])
    out["warnings"] += [f"{e['name']} : {w}" for e in out["assets"] for w in e["warnings"]]
    if out["errors"]:
        say(f"[export] ÉCHEC : {len(out['errors'])} problème(s) — voir ci-dessus")
        return EXIT_FAILED
    return EXIT_OK


def _junit_results(project: Path) -> dict | None:
    """Résultats des tests JUnit d'un projet Gradle (build/test-results/test/*.xml)."""
    import xml.etree.ElementTree as ET
    files = sorted((project / "build" / "test-results" / "test").glob("*.xml"))
    if not files:
        return None
    tot = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for p in files:
        root = ET.parse(p).getroot()
        for k in tot:
            tot[k] += int(root.get(k, 0))
    tot["passed"] = tot["tests"] > 0 and tot["failures"] == 0 and tot["errors"] == 0
    return tot


def cmd_mod(args, out) -> int:
    from .export import ExportError
    from .mod import FABRIC, build_mod, export_mod, find_java, java_version
    project = Path(args.out or f"out/mod_{args.modid}_{args.loader}")
    _check_outputs(args.files, project)
    pairs = _load_many(args.files)
    try:
        res = export_mod([a for _, a in pairs], project, args.modid, args.name, loader=args.loader,
                         version=args.version, authors=tuple(args.author) or ("pixvox",), zip_path=args.zip,
                         build=False, java_home=args.java_home)
    except OutputDirError as e:
        raise CliError(str(e), type="output_dir") from e
    except ExportError as e:                       # (sous-classe de ValueError : à tester en premier)
        raise CliError(f"REFUSÉ — {e} (aucun fichier modifié)", type="refused", code=EXIT_FAILED) from e
    except ValueError as e:
        raise CliError(f"REFUSÉ — {e} (aucun fichier modifié)", type="usage") from e
    out.update({"project": res["project"], "loader": args.loader, "modid": args.modid, "zip": res.get("zip"),
                "jar": None, "build": None})
    out["assets"] = _export_entries(pairs, res["assets"])
    out["errors"] += _verification_errors(out["assets"])
    out["warnings"] += [f"{e['name']} : {w}" for e in out["assets"] for w in e["warnings"]]
    code = EXIT_FAILED if out["errors"] else EXIT_OK
    if args.build:
        jh = find_java(args.java_home)
        build = {"java_home": jh, "java_version": java_version(jh), "log": project / "build_log.txt"}
        out["build"] = build
        if jh is None or (build["java_version"] or FABRIC["java"]) < FABRIC["java"]:
            raise CliError(f"JDK {FABRIC['java']} requis pour --build (trouvé : {build['java_version'] or 'aucun'}) ; "
                           "--java-home ou JAVA_HOME", type="environment")
        try:
            out["jar"] = build_mod(project, jh)
            build["ok"] = True
        except RuntimeError as e:
            build["ok"] = False
            out["errors"].append({"type": "build", "message": str(e), "log": build["log"]})
            say(f"[mod] ÉCHEC de la compilation — journal : {build['log']}")
            code = EXIT_FAILED
        build["tests"] = _junit_results(project)
    return code


def cmd_compare(args, out) -> int:
    from .review import compare_sheet
    pairs = _load_many(args.files)
    path = compare_sheet([a for _, a in pairs], args.out, args.size)
    say(path)
    out["image"] = path
    out["assets"] = [_entry(f, a) for f, a in pairs]
    return EXIT_OK


def cmd_render_model(args, out) -> int:
    from PIL import Image

    from .mcmodel import ModelLoader
    from .render import fit_camera, render
    if not (Path(args.pack) / "assets").is_dir():
        raise CliError(f"{args.pack} : pas un resource pack (dossier assets/ absent)", file=args.pack)
    loader = ModelLoader([args.pack], tick=args.tick)
    try:
        q = loader.quads(args.model)
    except (FileNotFoundError, KeyError, ValueError) as e:
        raise CliError(f"modèle {args.model!r} illisible : {e}") from e
    if not q:
        raise CliError(f"modèle {args.model!r} introuvable ou vide dans {args.pack}")
    bg = (10, 12, 20, 255) if args.shading == "night" else (24, 26, 32, 255)
    img = render(q, fit_camera(q, (args.yaw, args.pitch), args.size, args.size, persp=args.persp),
                 shading=args.shading, bg=bg)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).convert("RGB").save(args.out)
    missing = sorted(set(loader.missing))
    say(f"{len(q)} quads, textures manquantes : {missing or 'aucune'} -> {args.out}")
    out.update({"image": Path(args.out), "quads": len(q), "missing": missing})
    if missing:
        out["errors"].append({"type": "missing_texture", "message": f"textures manquantes : {', '.join(missing)}"})
        return EXIT_FAILED
    return EXIT_OK


def _title(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def cmd_new(args, out) -> int:
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", args.name):
        raise CliError(f"nom {args.name!r} invalide : minuscules, chiffres et _, commence par une lettre")
    target = Path(args.dir) / f"{args.name}.py"
    if target.exists() and not args.force:
        raise CliError(f"{target} existe déjà (--force pour l'écraser)", file=str(target))
    tpl = (Path(__file__).parent / "templates" / f"{args.kind}.py").read_text(encoding="utf-8")
    text = (tpl.replace("__NAME__", args.name).replace("__TITLE__", _title(args.name))
            .replace("__FILE__", target.as_posix()))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    nxt = [f"pixvox review {target.as_posix()}", f"pixvox export {target.as_posix()}"]
    say(f"{target} créé ({args.kind}). Ensuite :\n  " + "\n  ".join(nxt))
    out.update({"file": target, "kind": args.kind, "name": args.name, "next": nxt})
    return EXIT_OK


def _selftest() -> dict:
    """Export d'un bloc et d'un modèle dans un dossier temporaire, vérifiés par re-rendu."""
    import tempfile

    from . import Block, Model, Volume, ramp
    from .export import export_assets, verified
    t0 = time.time()
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 4), cells=4, seed=1)
    m = Volume(6, 4, 6)
    m.set(m.m_ellipsoid((3, 2, 3), (2.8, 1.9, 2.8)), "#888888")
    with tempfile.TemporaryDirectory(prefix="pixvox_doctor_", ignore_cleanup_errors=True) as d:
        res = export_assets([Block("doctor_block", v), Model("doctor_model", m)], Path(d) / "pack", log=None)
    ok = not res["refused"] and all(verified(i) for i in res["infos"])
    return {"ok": ok, "diff_px": sum(i["verify"]["diff_px"] for i in res["infos"]),
            "seconds": round(time.time() - t0, 2)}


def cmd_doctor(args, out) -> int:
    import numpy
    import PIL

    from .mod import FABRIC, find_java, java_version
    jh = find_java(args.java_home)
    jv = java_version(jh)
    need = FABRIC["java"]
    java_ok = jv is not None and jv >= need
    out["python"] = {"version": platform.python_version(), "executable": sys.executable,
                     "ok": sys.version_info >= (3, 10), "required": ">=3.10"}
    out["packages"] = {"pixvox": __version__, "numpy": numpy.__version__, "pillow": PIL.__version__}
    out["platform"] = {"system": platform.system(), "machine": platform.machine()}
    out["java"] = {"home": jh, "version": jv, "required": need, "ok": java_ok}
    out["mod_build"] = {"possible": java_ok,
                        "reason": "JDK trouvé" if java_ok else
                        (f"JDK {jv} trop ancien" if jv else "aucun JDK (--java-home, JAVA_HOME ou java dans le PATH)")
                        + ("" if java_ok else f" : `pixvox mod --build` exige un JDK {need} et l'accès réseau à "
                                               "Maven (Fabric, NeoForge, Maven Central)")}
    out["selftest"] = _selftest()
    say(f"pixvox {__version__} — Python {platform.python_version()} ({platform.system()}), numpy "
          f"{numpy.__version__}, Pillow {PIL.__version__}")
    say(f"auto-test d'export : {'OK' if out['selftest']['ok'] else 'ÉCHEC'} ({out['selftest']['seconds']} s)")
    say(f"mods (--build) : {'possible' if java_ok else 'impossible'} — {out['mod_build']['reason']}")
    if not out["selftest"]["ok"]:
        out["errors"].append({"type": "selftest", "message": "l'export de test ne se vérifie pas (0 px attendu)"})
        return EXIT_FAILED
    return EXIT_OK


def cmd_summary(args, out) -> int:
    from .summary import to_markdown, to_text
    try:
        raw = sys.stdin.read() if args.result == "-" else Path(args.result).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as e:
        raise CliError(f"résultat JSON illisible ({args.result}) : {e}", file=args.result) from e
    if not isinstance(data, dict):
        raise CliError(f"{args.result} : un objet JSON produit par --json est attendu", file=args.result)
    text = to_markdown(data) if args.format == "markdown" else to_text(data)
    say(text)
    out["text"] = text
    return EXIT_OK


HANDLERS = {"review": cmd_review, "view": cmd_view, "anim": cmd_anim, "ascii": cmd_ascii, "export": cmd_export,
            "mod": cmd_mod, "compare": cmd_compare, "render-model": cmd_render_model, "new": cmd_new,
            "doctor": cmd_doctor, "summary": cmd_summary}


# ============================================================================ analyse des arguments
def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="pixvox", description=__doc__.split("\n")[0], epilog=__doc__, allow_abbrev=False,
                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"pixvox {__version__}")
    p.add_argument("--json", action="store_true", help="résultat JSON sur la sortie standard (journal sur stderr)")
    common = _Parser(add_help=False, allow_abbrev=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="résultat JSON sur la sortie standard (journal sur stderr)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="commande", parser_class=_Parser)
    only_help = "ne traiter que l'asset portant ce nom"

    def add(name, help_):
        return sub.add_parser(name, help=help_, description=help_, parents=[common], allow_abbrev=False)

    r = add("review", "planche de revue PNG + rapport texte (+ planche d'animation et GIF)")
    r.add_argument("files", nargs="+", help="fichiers d'assets (.py)")
    r.add_argument("--out", default="out", help="DOSSIER de sortie (défaut : out)")
    r.add_argument("--only", help=only_help)
    r.add_argument("--fail-on", default="never", choices=("never", "warn", "err"),
                   help="code de sortie 1 si l'analyse signale des alertes de ce niveau (défaut : never)")
    v = add("view", "rendu à un angle libre (blocs, modèles, items extrudés)")
    v.add_argument("file")
    v.add_argument("--yaw", type=float, default=225, help="rotation autour de y en degrés (225 = inventaire)")
    v.add_argument("--pitch", type=float, default=30, help="inclinaison en degrés (négatif = par dessous)")
    v.add_argument("--size", type=_positive, default=700, help="taille de l'image en pixels")
    v.add_argument("--shading", default="gui", choices=("gui", "world", "night", "flat"),
                   help="gui = icône d'inventaire, world = ombrage en jeu, night = la nuit (seules les faces "
                        "light_emission restent claires), flat = couleurs brutes")
    v.add_argument("--tick", type=float, default=0, help="instant d'une animation (20 ticks = 1 s)")
    v.add_argument("--persp", type=float, default=0.0,
                   help="perspective : 0 = orthographique ; 1.5–3 = distance de l'œil en diagonales de l'objet")
    v.add_argument("--only", help=only_help)
    v.add_argument("--out", default="out", help="DOSSIER de sortie ; fichier <nom>.view_<yaw>_<pitch>.png")
    an = add("anim", "animation : planche des images (vues inventaire / en jeu / nuit) + GIF")
    an.add_argument("files", nargs="+")
    an.add_argument("--only", help=only_help)
    an.add_argument("--out", default="out", help="DOSSIER de sortie")
    a = add("ascii", "pixels exacts en texte (faces d'un bloc, sprite, tranches d'un modèle)")
    a.add_argument("file")
    a.add_argument("--only", help=only_help)
    a.add_argument("--face", help="up, down, north, south, west, east (alias : top, bottom)")
    e = add("export", "resource pack Java vérifié par re-rendu")
    e.add_argument("files", nargs="+")
    e.add_argument("--pack", default="out/pack", help="DOSSIER du pack (recréé à chaque export)")
    e.add_argument("--ns", default="pixvox", help="namespace des ressources (défaut : pixvox)")
    e.add_argument("--zip", help="FICHIER .zip à produire en plus")
    e.add_argument("--replace", action="append", default=[], metavar="NOM=minecraft:BLOC",
                   help="remplace l'apparence d'un bloc/item vanilla sans propriétés (répétable)")
    e.add_argument("--mc", default=MC_TARGETS[0], choices=MC_TARGETS,
                   help="version de Minecraft visée : 1.21.4+ (défaut, 1.21.4 → 26.3) ou 1.21.1 (NeoForge 21.1 : "
                        "models/item, neoforge_data, render_type)")
    md = add("mod", "projet de mod Fabric ou NeoForge 26.3 (vrais blocs) ; --build compile le .jar")
    md.add_argument("files", nargs="+")
    md.add_argument("--modid", default="pixvox_mod", help="identifiant du mod (minuscules, chiffres, _)")
    md.add_argument("--loader", default="fabric", choices=("fabric", "neoforge"), help="chargeur de mods")
    md.add_argument("--name", help="nom affiché du mod")
    md.add_argument("--out", help="DOSSIER du projet (défaut : out/mod_<modid>_<loader>)")
    md.add_argument("--version", default="1.0.0", help="version du mod")
    md.add_argument("--author", action="append", default=[], help="auteur (répétable)")
    md.add_argument("--zip", help="FICHIER .zip des sources du projet")
    md.add_argument("--build", action="store_true", help="compiler avec Gradle (JDK 25 + réseau Maven requis)")
    md.add_argument("--java-home", help="dossier du JDK 25 (sinon JAVA_HOME ou java du PATH)")
    c = add("compare", "variantes côte à côte")
    c.add_argument("files", nargs="+")
    c.add_argument("--out", default="out/compare.png", help="FICHIER image produit")
    c.add_argument("--size", type=_positive, default=300, help="taille de chaque vue en pixels")
    m = add("render-model", "prévisualiser un modèle JSON d'un resource pack (fait main, Blockbench…)")
    m.add_argument("pack", help="dossier du pack (contenant assets/)")
    m.add_argument("model", help="identifiant du modèle, ex. pixvox:block/nom")
    m.add_argument("--out", default="out/model_preview.png", help="FICHIER image produit")
    m.add_argument("--yaw", type=float, default=225)
    m.add_argument("--pitch", type=float, default=30)
    m.add_argument("--shading", default="gui", choices=("gui", "world", "night", "flat"))
    m.add_argument("--tick", type=float, default=0, help="instant des textures animées (lu dans les .mcmeta)")
    m.add_argument("--persp", type=float, default=0.0)
    m.add_argument("--size", type=_positive, default=600, help="taille de l'image en pixels")
    n = add("new", "crée un fichier d'asset de départ, prêt à modifier")
    n.add_argument("name", help="nom de l'asset (minuscules, chiffres, _)")
    n.add_argument("--kind", default="block", choices=KINDS, help="type d'asset (défaut : block)")
    n.add_argument("--dir", default=".", help="DOSSIER où écrire <nom>.py (défaut : dossier courant)")
    n.add_argument("--force", action="store_true", help="écraser le fichier s'il existe")
    d = add("doctor", "vérifie l'installation : Python, dépendances, JDK pour les mods, export de test")
    d.add_argument("--java-home", help="dossier d'un JDK à tester")
    s = add("summary", "résumé Markdown (ou texte) d'un résultat --json, pour une CI ou une PR")
    s.add_argument("result", help="fichier JSON produit par --json, ou - pour l'entrée standard")
    s.add_argument("--format", default="markdown", choices=("markdown", "text"))
    return p


# ============================================================================ point d'entrée
def _utf8_streams() -> None:
    """Sorties en UTF-8 (sinon une console Windows redirigée plante sur « é » ou « → »)."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def run(argv=None) -> tuple[int, dict]:
    """Exécute une commande et renvoie (code de sortie, résultat) sans rien imprimer sur stdout en mode
    JSON (le journal lisible part sur stderr). Utilisable depuis Python : pixvox.cli.run(["export", …])."""
    argv = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in argv
    out = {"schema": SCHEMA, "pixvox": __version__, "command": next((a for a in argv if a in HANDLERS), None),
           "ok": False, "exit_code": EXIT_USAGE, "errors": [], "warnings": []}
    try:
        args = build_parser().parse_args(argv)
    except CliError as e:
        if not want_json:
            getattr(e, "parser", build_parser()).print_usage(sys.stderr)
        out["errors"].append(e.as_dict())
        out["seconds"] = 0.0
        return EXIT_USAGE, out
    out["command"] = args.cmd
    t0 = time.time()
    try:
        with redirect_stdout(sys.stderr) if args.json else nullcontext():
            code = HANDLERS[args.cmd](args, out)
    except CliError as e:
        out["errors"].append(e.as_dict())
        code = e.code
    except OutputDirError as e:
        out["errors"].append({"type": "output_dir", "message": str(e)})
        code = EXIT_USAGE
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001 - bogue (ou sys.exit) : rapporté dans le JSON, trace sur stderr
        traceback.print_exc(file=sys.stderr)
        out["errors"].append({"type": "internal", "message": f"{type(e).__name__}: {e}"})
        code = EXIT_INTERNAL
    out["ok"] = code == EXIT_OK
    out["exit_code"] = code
    out["seconds"] = round(time.time() - t0, 2)
    return code, _jsonable(out)


def main(argv=None) -> int:
    _utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    code, out = run(argv)
    if "--json" in argv:
        try:
            say(json.dumps(out, ensure_ascii=False, indent=2))
            sys.stdout.flush()
        except BrokenPipeError:                    # lecteur fermé (| head…) : pas de trace inutile
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    else:
        for e in out["errors"]:
            prefix = f"pixvox {out['command']}" if out["command"] else "pixvox"
            say(f"{prefix} : {e['message']}", file=sys.stderr)
    if os.environ.get("PIXVOX_NO_EXIT"):          # pratique pour un débogueur ou un notebook
        return code
    sys.exit(code)


if __name__ == "__main__":
    main()
