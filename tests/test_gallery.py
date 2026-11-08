"""Galerie (#29) : page statique construite en local, sans serveur ; chaque asset a ses images, ses liens et
le résultat de vérification des deux cibles. Le workflow publie seulement si GitHub Pages est activé."""
import json
import re

from testkit import ROOT, require, tmpdir


def test_gallery_builds_locally_with_images_links_and_checks():
    require("scripts/gallery.py", "examples/brazier.py", "examples/glowcap.py")
    import runpy
    mod = runpy.run_path(str(ROOT / "scripts" / "gallery.py"), run_name="gallery")
    with tmpdir() as tmp:
        site = tmp / "site"
        code = mod["main"](["--out", str(site), str(ROOT / "examples" / "brazier.py"),
                            str(ROOT / "examples" / "glowcap.py")])
        assert code == 0
        res = json.loads((site / "results.json").read_text(encoding="utf-8"))
        assert res["all_verified"] and res["files"] == 2 and res["targets"] == ["1.21.4+", "1.21.1"]
        page = (site / "index.html").read_text(encoding="utf-8")
        assets = [a for g in res["groups"] for a in g["assets"]]
        assert {a["name"] for a in assets} >= {"brazier", "soul_brazier", "glowcap"}
        for a in assets:
            assert set(a["checks"]) == {"1.21.4+", "1.21.1"} and all(c["verified"] for c in a["checks"].values())
            for rel in a["files"].values():
                assert (site / rel).is_file() and rel in page, rel
            assert f'id="{a["name"]}"' in page
        brazier = next(a for a in assets if a["name"] == "brazier")
        assert brazier["files"]["gif"].endswith(".gif")                    # animé : GIF d'une vue
        for src in re.findall(r'(?:src|href)="([^"#:]+)"', page):           # liens relatifs : tous présents
            assert (site / src).exists(), src
        assert "examples/brazier.py" in page and "pixvox export examples/brazier.py --mc 1.21.1" in page
        assert (site / ".nojekyll").exists()
        assert "<ul>" in page                                                # docstring en liste → vraie liste


def test_pages_workflow_publishes_only_when_pages_is_enabled():
    require(".github/workflows/pages.yml")
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    run = " ".join(s.get("run", "") for s in jobs["build"]["steps"])
    assert "scripts/gallery.py --out site" in run
    assert any(s.get("uses", "").startswith("actions/upload-pages-artifact@") for s in jobs["build"]["steps"])
    assert jobs["deploy"]["if"] == "needs.build.outputs.enabled == 'true'"
    assert jobs["deploy"]["steps"][0]["uses"].startswith("actions/deploy-pages@")
    assert wf["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
