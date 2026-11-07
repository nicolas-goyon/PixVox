"""pixvox.watch — planche de revue régénérée à chaque sauvegarde (#25).

    pixvox watch examples/ma_lanterne.py [--only NOM] [--view 135,20] [--shading night] [--html]

Surveille le fichier d'asset ET les modules locaux qu'il importe (fichiers .py du même dossier, de proche
en proche), par simple relevé des dates de modification : aucune dépendance, même comportement sous Linux,
macOS et Windows. À chaque changement, la revue est refaite et la planche réécrite au même chemin
(`out/<nom>.review.png`) : une visionneuse qui recharge l'image suit d'elle-même. Une erreur dans le fichier
(exception de build(), faute de frappe) est affichée et la surveillance continue : la sauvegarde suivante
relance la revue.

`--html` sert une page locale (http://127.0.0.1:8765/) qui se recharge seule quand la planche change.
`--json-lines` écrit un résultat JSON par passage sur la sortie standard, pour un éditeur ou un agent.
`--passes N` s'arrête après N passages (scripts, tests) ; sinon Ctrl+C.
"""
from __future__ import annotations

import ast
import json
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

__all__ = ["local_deps", "watch"]


def local_deps(path) -> list:
    """Le fichier et les modules locaux qu'il importe (même dossier, récursivement), triés."""
    path = Path(path).resolve()
    root = path.parent
    seen: set = set()
    todo = [path]
    while todo:
        p = todo.pop()
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue                                   # fichier cassé : surveillé, ses imports le seront après
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            for n in names:
                cand = root / (n.split(".")[0] + ".py")
                if cand.is_file():
                    todo.append(cand.resolve())
    return sorted(seen)


def _stamp(files) -> tuple:
    out = []
    for f in files:
        try:
            st = Path(f).stat()
            out.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(f), None, None))           # supprimé (sauvegarde par renommage) : attendre
    return tuple(out)


_PAGE = """<!doctype html><meta charset="utf-8"><title>pixvox watch — {name}</title>
<style>body{{margin:0;background:#1b1d23;color:#c8ccd4;font:14px system-ui}}
header{{padding:8px 14px}}img{{max-width:100%;display:block}}.err{{color:#ff8b7a;white-space:pre-wrap;padding:8px 14px}}</style>
<header>pixvox watch — <b id=n></b> · passage <span id=p></span> · <span id=t></span></header>
<div class=err id=e></div><div id=imgs></div>
<script>
let last = null;
async function poll() {{
  try {{
    const s = await (await fetch("watch_state.json?" + Date.now())).json();
    if (s.pass !== last) {{
      last = s.pass;
      document.getElementById("n").textContent = s.file;
      document.getElementById("p").textContent = s.pass;
      document.getElementById("t").textContent = s.seconds + " s";
      document.getElementById("e").textContent = s.error || "";
      document.getElementById("imgs").innerHTML = (s.images || []).map(i => `<img src="${{i}}?${{s.pass}}">`).join("");
    }}
  }} catch (e) {{}}
  setTimeout(poll, 700);
}}
poll();
</script>
"""


def _serve(out_dir: Path, port: int, name: str):
    (out_dir / "index.html").write_text(_PAGE.format(name=name), encoding="utf-8")
    srv = ThreadingHTTPServer(("127.0.0.1", port), partial(_Quiet, directory=str(out_dir)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _forget_local_modules(path: Path) -> None:
    """Oublie les modules importés depuis le dossier de l'asset : sinon Python garderait leur ancienne version
    (sys.modules) et la planche serait refaite avec l'ancienne palette d'un `from couleurs import …`."""
    root = path.resolve().parent
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and Path(f).resolve().parent == root:
            del sys.modules[name]


def _one_pass(path: Path, out_dir: Path, only, view, shading, n: int) -> dict:
    """Une revue complète du fichier ; ne lève jamais (l'erreur va dans le résultat)."""
    from .cli import CliError, _entry, load_assets
    from .review import review_data
    from .review import view as render_view
    t0 = time.time()
    res = {"pass": n, "file": path.as_posix(), "ok": True, "assets": [], "errors": []}
    _forget_local_modules(path)
    try:
        assets = load_assets(str(path))
        if only:
            assets = [a for a in assets if a.name == only]
            if not assets:
                raise CliError(f"aucun asset nommé {only!r} dans {path.name}")
        for a in assets:
            r = review_data(a, out_dir)
            e = {**_entry(str(path), a), "sheet": Path(r["sheet"]).as_posix(),
                 "counts": {lv: sum(f.level == lv for f in r["findings"]) for lv in ("OK", "INFO", "WARN", "ERR")}}
            if view is not None or shading:
                yaw, pitch = view if view is not None else (225.0, 30.0)
                e["image"] = Path(render_view(a, yaw, pitch, 700, shading or "gui", out_dir=out_dir)).as_posix()
            res["assets"].append(e)
    except CliError as e:
        res["ok"] = False
        res["errors"].append({"type": getattr(e, "type", "input"), "message": str(e)})
    except Exception as e:  # noqa: BLE001 - un asset en cours d'écriture peut lever n'importe quoi
        res["ok"] = False
        res["errors"].append({"type": "asset_code", "message": f"{type(e).__name__}: {e}"})
    res["seconds"] = round(time.time() - t0, 2)
    return res


def watch(path, out_dir="out", *, only: str | None = None, view=None, shading: str | None = None,
          interval: float = 0.4, passes: int | None = None, html_port: int | None = None, on_pass=None,
          log=print) -> list:
    """Relance la revue de `path` à chaque modification du fichier ou d'un module local importé.
    on_pass(résultat) est appelé après chaque passage ; passes=N arrête après N passages. Renvoie les
    résultats (le dernier passage d'abord en cas d'arrêt par Ctrl+C)."""
    path = Path(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        raise FileNotFoundError(f"fichier introuvable : {path}")
    srv = _serve(out, html_port, path.stem) if html_port is not None else None      # 0 : port libre
    if srv:
        log(f"[watch] page : http://127.0.0.1:{srv.server_address[1]}/")
    results = []
    files = local_deps(path)
    last = None
    try:
        while passes is None or len(results) < passes:
            stamp = _stamp(files)
            if stamp != last:
                time.sleep(interval / 2)                      # sauvegarde en plusieurs écritures : attendre
                stamp2 = _stamp(files)
                if stamp2 != stamp:
                    continue
                last = stamp
                res = _one_pass(path, out, only, view, shading, len(results) + 1)
                files = local_deps(path)                      # un import a pu apparaître
                last = _stamp(files)
                res["watched"] = [Path(f).name for f in files]
                results.append(res)
                if srv:
                    images = [Path(a.get("image") or a["sheet"]).name for a in res["assets"]]
                    state = {"pass": res["pass"], "file": res["file"], "seconds": res["seconds"], "images": images,
                             "error": "\n".join(e["message"] for e in res["errors"])}
                    (out / "watch_state.json").write_text(json.dumps(state), encoding="utf-8")
                if res["ok"]:
                    log(f"[watch] passage {res['pass']} : " + ", ".join(
                        f"{a['name']} → {a.get('image') or a['sheet']}" for a in res["assets"]) + f" ({res['seconds']} s)")
                else:
                    log(f"[watch] passage {res['pass']} : ERREUR {res['errors'][0]['message']} — surveillance "
                        "maintenue, corriger puis sauvegarder")
                if on_pass:
                    on_pass(res)
                continue
            time.sleep(interval)
    except KeyboardInterrupt:
        log("[watch] arrêt")
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
    return results
