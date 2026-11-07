"""Matériaux (#27) : raccords sans couture, joints jamais posés sur une face entière, résolution libre,
arguments par mot-clé, export vérifié des exemples, `pixvox new --material`, catalogue à jour."""
import numpy as np

from testkit import require, tmpdir


def _raises(exc, text: str, fn) -> None:
    try:
        fn()
    except exc as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"{exc.__name__} attendue ({text})")


def _joint_only(face: np.ndarray) -> bool:
    """Face réduite à un joint : au plus 3 couleurs (le mortier en a 3), ou une teinte qui couvre plus de 80 %
    (joint + quelques rivets). Une lame de bois ordinaire a 5 couleurs, sa teinte de base vers 66 %."""
    rgb = face[..., :3].reshape(-1, 3)
    cols, counts = np.unique(rgb, axis=0, return_counts=True)
    return len(cols) <= 3 or counts.max() / len(rgb) > 0.8


def test_joint_only_detector():
    from pixvox import Volume
    from pixvox.materials import bricks
    v = bricks(Volume(16), seed=1)
    bad = v.face("north").data.copy()
    bad[...] = v.data[0, 0, 0]                                       # face uniforme
    assert _joint_only(bad)
    mortar = bad.copy()
    mortar[::2, :, :3] = (163, 157, 146)                             # 2 teintes de mortier
    assert _joint_only(mortar) and not _joint_only(v.face("up").data)


def _recipes():
    from pixvox.materials import bricks, cut_stone, metal, ore, planks
    return {"planks": lambda v: planks(v, wood="spruce", seed=3), "bricks": lambda v: bricks(v, seed=1),
            "cut_stone": lambda v: cut_stone(v, seed=2), "ore": lambda v: ore(v, seed=4),
            "metal": lambda v: metal(v, color="#c1734b", patina=0.4, seed=5)}


def test_materials_tile_without_seams_and_never_cover_a_face_with_joints():
    from pixvox import FACES, Block, Volume
    from pixvox.analyze import analyze_block
    for name, paint in _recipes().items():
        for n in (16, 32):
            v = Volume(n, res=n)
            paint(v)
            assert v.solid.all(), name
            seams = [f for f in analyze_block(Block("m", v)) if f.topic == "Raccords"]
            assert seams and all(f.level == "OK" for f in seams), (name, n, [f.msg for f in seams])
            for face in FACES:                                      # un joint ne couvre jamais toute une face
                assert not _joint_only(v.face(face).data), (name, n, face)
        a, b = Volume(16), Volume(16)
        paint(a)
        paint(b)
        assert np.array_equal(a.data, b.data), f"{name} : même graine, même bloc"


def test_material_arguments_and_results():
    from pixvox import Volume
    from pixvox.materials import WOODS, bricks, metal, ore, planks
    v = Volume(16)
    _raises(TypeError, "positional", lambda: planks(v, "oak"))                      # règle 4 : par mot-clé
    _raises(ValueError, "wood='teak' inconnu", lambda: planks(v, wood="teak"))
    _raises(ValueError, "diviser 16", lambda: bricks(v, length=6))
    _raises(ValueError, "patina entre 0 et 1", lambda: metal(v, patina=2))
    _raises(ValueError, "bloc cubique", lambda: planks(Volume(8, 16, 16), wood="oak"))
    assert planks(Volume(16), wood="cherry") is not None and len(WOODS) >= 8
    w = Volume(16)
    glow = ore(w, crystal="#e0a030", seed=1)
    assert glow.dtype == bool and glow.any() and (glow & w.solid).sum() == glow.sum()
    assert not np.array_equal(metal(Volume(16), patina=0.0).data, metal(Volume(16), patina=0.6).data)


def test_material_examples_export_on_both_targets_and_new_command():
    import runpy

    from pixvox.cli import run
    from pixvox.export import export_assets, verified
    from testkit import ROOT
    blocks = runpy.run_path(str(ROOT / "examples" / "materials.py"))["build"]()
    assert len(blocks) == 6
    with tmpdir() as tmp:
        for mc in ("1.21.4+", "1.21.1"):
            res = export_assets(blocks, tmp / mc.replace("+", "p") / "pack", mc=mc, log=None)
            assert len(res["infos"]) == 6 and not res["refused"]
            assert all(verified(i) for i in res["infos"]), [(i["name"], i["verify"]) for i in res["infos"]]
        for m in ("planks", "bricks", "cut_stone", "ore", "metal"):
            code, out = run(["new", f"mon_{m}", "--material", m, "--dir", str(tmp / "new"), "--json"])
            assert code == 0 and out["material"] == m, out
            assert f"from pixvox.materials import {m}" in (tmp / "new" / f"mon_{m}.py").read_text(encoding="utf-8")
        code, out = run(["export", *sorted(str(p) for p in (tmp / "new").glob("*.py")), "--pack", str(tmp / "np"),
                         "--json"])
        assert code == 0 and len(out["assets"]) == 5 and all(a["verified"] for a in out["assets"]), out
        code, out = run(["new", "x", "--kind", "model", "--material", "ore", "--dir", str(tmp), "--json"])
        assert code == 2 and "--kind block" in out["errors"][0]["message"]


def test_materials_catalog_is_up_to_date():
    """docs/images/materiaux.png doit être régénéré avec les recettes (python scripts/readme_images.py --only
    materiaux) : rendu et PNG déterministes, la CI le vérifie aussi."""
    require("scripts/readme_images.py", "docs/images/materiaux.png")
    import runpy
    import sys
    import unittest
    if not sys.platform.startswith("linux"):           # polices des étiquettes propres à chaque système
        raise unittest.SkipTest("catalogue comparé octet pour octet sous Linux seulement (job « exemples » de la CI)")

    from testkit import ROOT
    mod = runpy.run_path(str(ROOT / "scripts" / "readme_images.py"), run_name="readme_images")
    assert mod["check_catalog"]() == 0
