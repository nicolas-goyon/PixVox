"""pixvox watch : passages à chaque sauvegarde (fichier et modules importés), erreurs sans arrêt, page HTML,
une ligne JSON par passage. Relevé des dates de modification : même comportement sur les trois systèmes."""
import json
import os
import time
import urllib.request

from testkit import tmpdir

ASSET = '''from couleurs import BASE
from pixvox import Block, Volume, ramp
def build():
    v = Volume(16)
    v.noise(ramp(BASE, 4), cells=4, seed=1)
    return Block("essai", v)
'''


def _touch(p, text):
    """Écrit puis avance la date de modification : un relevé rapide ne doit pas manquer la sauvegarde."""
    p.write_text(text, encoding="utf-8")
    t = time.time() + 2 + _touch.n
    _touch.n += 2
    os.utime(p, (t, t))


_touch.n = 0


def test_local_deps_follow_imports():
    from pixvox.watch import local_deps
    with tmpdir() as tmp:
        (tmp / "a.py").write_text("import b\nfrom c import X\nimport numpy\nfrom . import d\n", encoding="utf-8")
        (tmp / "b.py").write_text("import c\n", encoding="utf-8")
        (tmp / "c.py").write_text("X = 1\n", encoding="utf-8")
        (tmp / "cassé.py").write_text("def (:\n", encoding="utf-8")
        assert [p.name for p in local_deps(tmp / "a.py")] == ["a.py", "b.py", "c.py"]
        assert [p.name for p in local_deps(tmp / "cassé.py")] == ["cassé.py"]


def test_watch_reruns_on_save_and_survives_errors():
    from pixvox.watch import watch
    with tmpdir() as tmp:
        colors, asset = tmp / "couleurs.py", tmp / "bloc.py"
        colors.write_text('BASE = "#7a7a7a"\n', encoding="utf-8")
        asset.write_text(ASSET, encoding="utf-8")
        sheets = []

        def step(res):
            n = res["pass"]
            if res["ok"]:
                sheets.append((tmp / "out" / "essai.review.png").read_bytes())
            if n == 1:
                _touch(colors, 'BASE = "#aa5533"\n')                       # module importé modifié
            elif n == 2:
                _touch(asset, "def build(): raise ValueError('oups')\n")    # fichier cassé
            elif n == 3:
                _touch(asset, ASSET)                                         # réparé
        res = watch(asset, tmp / "out", interval=0.05, passes=4, html_port=0, on_pass=step, log=lambda *_: None)
        assert [r["ok"] for r in res] == [True, True, False, True]
        assert res[0]["watched"] == ["bloc.py", "couleurs.py"]
        assert sheets[0] != sheets[1], "la nouvelle couleur du module importé doit changer la planche"
        assert "ValueError: oups" in res[2]["errors"][0]["message"]
        state = json.loads((tmp / "out" / "watch_state.json").read_text(encoding="utf-8"))
        assert state["pass"] == 4 and state["images"] == ["essai.review.png"] and not state["error"]
        assert "pixvox watch" in (tmp / "out" / "index.html").read_text(encoding="utf-8")


def test_watch_html_page_is_served():
    from pixvox.watch import _serve
    with tmpdir() as tmp:
        (tmp / "watch_state.json").write_text('{"pass": 1}', encoding="utf-8")
        srv = _serve(tmp, 0, "essai")
        old = {k: os.environ.get(k) for k in ("no_proxy", "NO_PROXY")}
        os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}/"
            with urllib.request.urlopen(base, timeout=5) as r:                  # noqa: S310 - serveur local
                assert b"watch_state.json" in r.read()
            with urllib.request.urlopen(base + "watch_state.json", timeout=5) as r:  # noqa: S310
                assert json.loads(r.read())["pass"] == 1
        finally:
            srv.shutdown()
            srv.server_close()
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_watch_command_line():
    import subprocess
    import sys

    from test_cli import _cli
    from testkit import ROOT
    with tmpdir() as tmp:
        (tmp / "couleurs.py").write_text('BASE = "#7a7a7a"\n', encoding="utf-8")
        (tmp / "bloc.py").write_text(ASSET, encoding="utf-8")
        rc, data = _cli("watch", "bloc.py", "--passes", "1", cwd=tmp)        # --json : refusé (code 2)
        assert rc == 2 and "--json-lines" in data["errors"][0]["message"]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
        r = subprocess.run([sys.executable, "-m", "pixvox", "watch", "bloc.py", "--passes", "1", "--json-lines",
                            "--view", "135,20"], cwd=tmp, capture_output=True, text=True, encoding="utf-8", env=env,
                           timeout=120)
        assert r.returncode == 0, r.stderr[-800:]
        lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
        assert len(lines) == 1 and lines[0]["ok"] and lines[0]["assets"][0]["image"].endswith("essai.view_135_20.png")
        assert (tmp / "out" / "essai.view_135_20.png").exists()
