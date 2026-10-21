"""Ligne de commande : chaque commande, le contrat JSON (docs/cli.md) et les codes de sortie 0/1/2."""
import json
import os
import subprocess
import sys

from pixvox.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, KINDS, SCHEMA, run
from testkit import ROOT, tmpdir

ASSETS = """from pixvox import *
def build():
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 4), cells=4, seed=1)
    m = Volume(6, 4, 6)
    m.set(m.m_ellipsoid((3, 2, 3), (2.8, 1.9, 2.8)), "#888888")
    s = Sprite(16)
    s.ellipse(8, 8, 5, 5, "#55aa55").outline("#102010")
    return [Block("blk", v), Model("peb", m, inventory_scale=1.5, inventory_center=True), Item("itm", s)]
"""


def _write(tmp, name, text):
    p = tmp / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _cli(*args, cwd=ROOT):
    """Vraie ligne de commande (python -m pixvox), sortie JSON décodée."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
    r = subprocess.run([sys.executable, "-m", "pixvox", *args, "--json"], cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", env=env)
    try:
        data = json.loads(r.stdout)
    except ValueError as e:
        raise AssertionError(f"stdout n'est pas du JSON : {r.stdout[:300]!r} / stderr {r.stderr[-800:]}") from e
    assert data["exit_code"] == r.returncode, (data["exit_code"], r.returncode)
    return r.returncode, data


def test_every_command_runs():
    with tmpdir() as tmp:
        f = _write(tmp, "a.py", ASSETS)
        out = str(tmp / "out")
        code, d = run(["review", f, "--out", out])
        assert code == EXIT_OK and {a["name"] for a in d["assets"]} == {"blk", "peb", "itm"}
        assert run(["compare", f, "--out", str(tmp / "cmp.png")])[0] == EXIT_OK
        code, d = run(["view", f, "--yaw", "135", "--pitch", "20", "--out", out])
        assert code == EXIT_OK and all((tmp / "out" / f"{n}.view_135_20.png").exists() for n in ("blk", "peb", "itm"))
        code, d = run(["ascii", f, "--only", "blk", "--face", "top"])
        assert code == EXIT_OK and len(d["assets"][0]["faces"]["up"].splitlines()) >= 16
        code, d = run(["export", f, "--pack", str(tmp / "pack"), "--zip", str(tmp / "p.zip")])
        assert code == EXIT_OK and all(a["verified"] for a in d["assets"]), d["errors"]
        model = json.loads((tmp / "pack/assets/pixvox/models/block/peb.json").read_text(encoding="utf-8"))
        assert model["display"]["gui"]["scale"][0] > 0.625
        code, d = run(["render-model", str(tmp / "pack"), "pixvox:block/peb", "--out", str(tmp / "rm.png")])
        assert code == EXIT_OK and d["quads"] > 0 and d["missing"] == []
        assert run(["anim", f])[0] == EXIT_USAGE                       # rien d'animé dans ce fichier


def test_json_contract_and_exit_codes():
    with tmpdir() as tmp:
        good = _write(tmp, "good.py", ASSETS)
        code, d = _cli("export", good, "--pack", str(tmp / "pack"), cwd=tmp)
        assert code == EXIT_OK and d["ok"] and d["schema"] == SCHEMA and d["command"] == "export"
        assert d["mc"] == "1.21.4+" and (tmp / "pack/assets/pixvox/items/blk.json").exists()
        a = {x["name"]: x for x in d["assets"]}
        assert a["blk"]["kind"] == "block" and a["peb"]["kind"] == "model" and a["itm"]["kind"] == "item"
        assert a["blk"]["verify"]["diff_px"] == 0 and a["blk"]["model"] == "pixvox:block/blk"
        assert d["pack"].endswith("pack") and d["refused"] == [] and d["errors"] == []
        # cible 1.21.1 : même contrat, champ mc, fichiers relus et vérifiés comme 1.21.1
        code, d = _cli("export", good, "--pack", str(tmp / "p121"), "--mc", "1.21.1", cwd=tmp)
        assert code == EXIT_OK and d["mc"] == "1.21.1" and all(x["verified"] for x in d["assets"]), d["errors"]
        assert not (tmp / "p121/assets/pixvox/items").exists()
        assert (tmp / "p121/assets/pixvox/models/item/blk.json").exists()
        code, d = _cli("export", good, "--mc", "1.20.1", cwd=tmp)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "usage" and "1.21.1" in d["errors"][0]["message"]
        # modèle refusé par le jeu (48 unités de haut > 32) : code 1, les autres sont exportés
        tall = _write(tmp, "tall.py", "from pixvox import *\ndef build():\n"
                                      "    return [Model('tall', Volume(6, 48, 6, fill='#888888')), "
                                      "Block('ok_block', Volume(16, fill='#777777'))]\n")
        code, d = _cli("export", tall, "--pack", str(tmp / "p2"), cwd=tmp)
        assert code == EXIT_FAILED and not d["ok"]
        assert [r["name"] for r in d["refused"]] == ["tall"] and d["errors"][0]["type"] == "refused"
        assert [x["name"] for x in d["assets"]] == ["ok_block"]
        # erreurs d'utilisation : code 2, toujours un JSON valide
        assert _cli("export", str(tmp / "absent.py"), cwd=tmp)[1]["errors"][0]["type"] == "input"
        boom = _write(tmp, "boom.py", "def build():\n    raise RuntimeError('oups')\n")
        code, d = _cli("review", boom, cwd=tmp)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "asset_code" and "oups" in d["errors"][0]["message"]
        code, d = _cli("export", cwd=tmp)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "usage"
        code, d = _cli("review", good, "--only", "nope", cwd=tmp)
        assert code == EXIT_USAGE and "blk" in d["errors"][0]["message"]


def test_review_fail_on_threshold():
    grad = ("from pixvox import Block, Volume\ndef build():\n    v = Volume(16)\n    for x in range(16):\n"
            "        v.set(v.m_box(x, 0, 0, x, 15, 15), (40 + 12 * x, 40 + 12 * x, 50 + 12 * x))\n"
            "    return Block('grad_block', v)\n")
    with tmpdir() as tmp:
        f = _write(tmp, "grad.py", grad)
        code, d = run(["review", f, "--out", str(tmp / "rv"), "--json"])
        assert code == EXIT_OK and d["assets"][0]["counts"]["WARN"] >= 1     # par défaut : on signale seulement
        code, d = run(["review", f, "--out", str(tmp / "rv"), "--fail-on", "warn", "--json"])
        assert code == EXIT_FAILED and d["errors"][0]["type"] == "quality"
        assert run(["review", f, "--out", str(tmp / "rv"), "--fail-on", "err", "--json"])[0] == EXIT_OK


def test_new_templates_export_cleanly():
    """Chaque gabarit de `pixvox new` s'exporte à 0 pixel d'écart et passe l'analyse sans alerte."""
    with tmpdir() as tmp:
        files = []
        for kind in KINDS:
            code, d = run(["new", f"my_{kind}", "--kind", kind, "--dir", str(tmp), "--json"])
            assert code == EXIT_OK and d["file"].endswith(f"my_{kind}.py"), d
            files.append(d["file"])
        assert run(["new", "my_block", "--dir", str(tmp)])[0] == EXIT_USAGE          # existe déjà
        assert run(["new", "Bad-Name", "--dir", str(tmp)])[0] == EXIT_USAGE
        code, d = run(["export", *files, "--pack", str(tmp / "pack"), "--json"])
        assert code == EXIT_OK and len(d["assets"]) == len(KINDS), d["errors"]
        code, d = run(["review", *files, "--out", str(tmp / "rv"), "--fail-on", "warn", "--json"])
        assert code == EXIT_OK, d["errors"]


def test_doctor_and_summary():
    with tmpdir() as tmp:
        code, d = run(["doctor", "--json"])
        assert code == EXIT_OK and d["selftest"]["ok"] and d["python"]["ok"]
        assert isinstance(d["mod_build"]["possible"], bool)
        f = _write(tmp, "a.py", ASSETS)
        code, d = run(["export", f, "--pack", str(tmp / "pack"), "--json"])
        res = tmp / "result.json"
        res.write_text(json.dumps(d), encoding="utf-8")
        code, s = run(["summary", str(res), "--json"])
        assert code == EXIT_OK and "| `blk` | block | ✅ 0 px" in s["text"]
        code, s = run(["summary", str(res), "--format", "text", "--json"])
        assert code == EXIT_OK and "blk (block) : OK 0 px" in s["text"]
        assert run(["summary", str(tmp / "absent.json")])[0] == EXIT_USAGE


def test_mod_command_without_build():
    with tmpdir() as tmp:
        f = _write(tmp, "a.py", ASSETS)
        code, d = run(["mod", f, "--modid", "cli_test", "--loader", "neoforge", "--out", str(tmp / "mod"), "--json"])
        assert code == EXIT_OK and d["loader"] == "neoforge" and d["jar"] is None and d["build"] is None
        assert all(a["verified"] for a in d["assets"])
        assert (tmp / "mod/src/main/resources/META-INF/neoforge.mods.toml").exists()
        assert run(["mod", f, "--modid", "minecraft", "--out", str(tmp / "m2"), "--json"])[0] == EXIT_USAGE
        tall = _write(tmp, "tall.py", "from pixvox import *\ndef build():\n"
                                      "    return Model('tall', Volume(6, 48, 6, fill='#888888'))\n")
        code, d = run(["mod", tall, "--modid", "cli_test", "--out", str(tmp / "m3"), "--json"])
        assert code == EXIT_FAILED and d["errors"][0]["type"] == "refused", d["errors"]
        assert not (tmp / "m3").exists()                                 # rien d'écrit pour un mod refusé


def test_outputs_never_wipe_user_folders():
    """`--pack .` ou un dossier de travail : refus (code 2) et rien d'effacé ; un dossier pixvox se recrée."""
    with tmpdir() as tmp:
        work = tmp / "work"
        work.mkdir()
        f = _write(work, "a.py", ASSETS)
        (work / "notes.txt").write_text("à garder", encoding="utf-8")
        code, d = _cli("export", f, "--pack", ".", cwd=work)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "output_dir", d["errors"]
        code, d = _cli("export", f, "--pack", str(tmp / "other"), cwd=work)
        assert code == EXIT_OK
        keep = tmp / "keep"
        keep.mkdir()
        (keep / "x.txt").write_text("x", encoding="utf-8")
        code, d = _cli("export", f, "--pack", str(keep), cwd=work)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "output_dir"
        code, d = _cli("mod", f, "--modid", "keep_test", "--out", str(keep), cwd=work)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "output_dir"
        assert (work / "notes.txt").exists() and (work / "a.py").exists() and (keep / "x.txt").exists()
        assert run(["export", f, "--pack", str(tmp / "other"), "--json"])[0] == EXIT_OK   # dossier pixvox : recréé


def test_contract_edge_cases():
    with tmpdir() as tmp:
        f = _write(tmp, "a.py", ASSETS)
        quit_ = _write(tmp, "quit.py", "import sys\nsys.exit(0)\n")
        code, d = _cli("export", quit_, "--pack", str(tmp / "p"), cwd=tmp)
        assert code == EXIT_USAGE and d["errors"][0]["type"] == "asset_code"       # sys.exit n'est pas un succès
        code, d = run(["export", f, "--pack", str(tmp / "p"), "--ns", "Bad NS", "--json"])
        assert code == EXIT_USAGE and "--ns" in d["errors"][0]["message"]
        code, d = run(["export", f, "--js"])
        assert code == EXIT_USAGE and d["seconds"] == 0.0                        # pas d'abréviation de --json
        assert run(["view", f, "--size", "0", "--json"])[0] == EXIT_USAGE
        lst = tmp / "list.json"
        lst.write_text("[1, 2]", encoding="utf-8")
        assert run(["summary", str(lst), "--json"])[0] == EXIT_USAGE
        code, d = run(["export", f, "--pack", str(tmp / "p2"), "--json"])
        assert all("ticks" in a["verify"] for a in d["assets"]), d["assets"]
        from pixvox.cli import MC_TARGETS
        from pixvox.export import DEFAULT_MC, TARGETS
        assert MC_TARGETS == tuple(TARGETS) and MC_TARGETS[0] == DEFAULT_MC     # --mc sans importer numpy


def test_say_survives_a_closed_reader():
    from pixvox._io import say

    class Closed:
        encoding = "utf-8"

        def write(self, _):
            raise BrokenPipeError

        def fileno(self):
            raise ValueError("pas de descripteur")

    say("bonjour", file=Closed())                                         # ne lève rien
