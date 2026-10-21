"""Étape principale de l'action GitHub (scripts/action_run.py) : motifs, arguments, sorties, résumé."""
import importlib.util
import json
import os

from testkit import ROOT, require, tmpdir


def _action_run():
    require("scripts/action_run.py")
    spec = importlib.util.spec_from_file_location("action_run", ROOT / "scripts" / "action_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _outputs(path):
    out, lines, i = {}, path.read_text(encoding="utf-8").splitlines(), 0
    while i < len(lines):
        if "<<PIXVOX_EOF" in lines[i]:
            key, i, buf = lines[i].split("<<")[0], i + 1, []
            while lines[i] != "PIXVOX_EOF":
                buf.append(lines[i])
                i += 1
            out[key] = "\n".join(buf)
        else:
            k, _, v = lines[i].partition("=")
            out[k] = v
        i += 1
    return out


def _run(tmp, **env):
    action_run = _action_run()
    old_env, old_cwd = dict(os.environ), os.getcwd()
    os.environ.update({"GITHUB_OUTPUT": str(tmp / "gh_out"), "GITHUB_STEP_SUMMARY": str(tmp / "gh_sum"),
                       "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]), **env})
    (tmp / "gh_out").write_text("", encoding="utf-8")
    try:
        os.chdir(tmp)
        assert action_run.main() == 0
        return _outputs(tmp / "gh_out")
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)


def test_glob_patterns_and_quoted_args():
    action_run = _action_run()
    with tmpdir() as tmp:
        (tmp / "assets" / "sub").mkdir(parents=True)
        src = (ROOT / "examples" / "lumenite_shard.py").read_text(encoding="utf-8")
        (tmp / "assets" / "sub" / "shard.py").write_text(src, encoding="utf-8")
        old = os.getcwd()
        try:
            os.chdir(tmp)
            assert action_run.expand("assets/**/*.py nope_*.py") == ["assets/sub/shard.py", "nope_*.py"]
        finally:
            os.chdir(old)
        o = _run(tmp, PIXVOX_CMD="export", PIXVOX_FILES="assets/**/*.py",
                 PIXVOX_ARGS='--pack out/pack --zip "out/mon pack.zip"')
        assert o["exit-code"] == "0" and o["ok"] == "true", o
        assert (tmp / "out" / "mon pack.zip").exists()
        doc = json.loads((tmp / "out" / "pixvox-export.json").read_text(encoding="utf-8"))
        assert doc["ok"] and doc["assets"][0]["name"] == "lumenite_shard"
        assert "pixvox export" in (tmp / "gh_sum").read_text(encoding="utf-8")
        assert o["artifact-name"].startswith("pixvox-export-") and o["upload-path"].splitlines()[0].endswith("/out")


def test_bad_args_and_missing_files_are_reported():
    with tmpdir() as tmp:
        o = _run(tmp, PIXVOX_CMD="export", PIXVOX_FILES="x.py", PIXVOX_ARGS="--zip 'non fermé")
        assert o["exit-code"] == "2" and o["ok"] == "false"                 # jamais un faux succès
        from pixvox.cli import SCHEMA
        doc = json.loads((tmp / "out" / "pixvox-export.json").read_text(encoding="utf-8"))
        assert doc["schema"] == SCHEMA                                      # même contrat que pixvox --json
        o = _run(tmp, PIXVOX_CMD="export", PIXVOX_FILES="absent_*.py", PIXVOX_ARGS="",
                 PIXVOX_ARTIFACT_NAME="mon-artefact", PIXVOX_UPLOAD_PATH="out/*.zip\n!out/x")
        assert o["exit-code"] == "2" and o["artifact-name"] == "mon-artefact"
        paths = o["upload-path"].splitlines()
        assert paths[0].endswith("/out/*.zip") and paths[1].startswith("!") and paths[2].endswith("pixvox-export.json")
