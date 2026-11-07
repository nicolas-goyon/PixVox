"""Import d'un modèle JSON (dossier, .zip, .jar) ou Blockbench en volume (#26) : aller-retour exact, plans,
avertissements, fichier d'asset écrit, ligne de commande. Aucun fichier de Mojang : un jar factice imite le
jeu ; un test facultatif lit un vrai jar (variable PIXVOX_MC_JAR)."""
import base64
import io
import json
import os
import zipfile

import numpy as np

from testkit import animated_model, design_shape, tmpdir


def _raises(exc, text: str, fn) -> None:
    try:
        fn()
    except exc as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"{exc.__name__} attendue ({text})")


def _png(arr) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.asarray(arr, np.uint8), "RGBA").save(buf, "PNG")
    return buf.getvalue()


def _diff(a, b) -> int:
    """Pixels différents entre deux assets (rendu brut, 4 angles, tick 0)."""
    from pixvox.render import compare, fit_camera, render
    total = 0
    for view in ((225, 30), (45, -30), (135, 25), (0, 89.9)):
        qa, qb = a.quads(0), b.quads(0)
        cam = fit_camera(qa, view, 256, 256, jitter=(0.313, 0.227))
        total += compare(render(qa, cam, shading="flat"), render(qb, cam, shading="flat"))[0]
    return total


def test_round_trip_through_export_is_exact():
    """Un modèle exporté par pixvox, réimporté puis réexporté, se vérifie à 0 px contre l'original (voxels,
    plans, position), à 16 et à 32 voxels par bloc."""
    from pixvox import Model, Volume, ramp
    from pixvox.export import export_assets, verified
    from pixvox.importer import import_model
    fine = Volume.design((16, 12, 16), res=32)
    fine.set(fine.m_ellipsoid((16, 10, 16), (12, 9, 12)), "#7a8a5a")
    fine.noise(ramp("#7a8a5a", 4), cells=4, seed=2, mask=fine.solid)
    for m in (Model("design_test", design_shape(16)), animated_model(), Model("fine_test", fine)):
        with tmpdir() as tmp:
            export_assets([m], tmp / "a", log=None)
            imp = import_model(tmp / "a", f"pixvox:block/{m.name}", res=m.volume.res)
            assert len(imp.planes) == len(m.planes), m.name
            back = imp.to_model(m.name + "_r")
            res = export_assets([back], tmp / "b", log=None)
            assert verified(res["infos"][0]), res["infos"][0]["verify"]
            assert _diff(m, back) == 0, m.name


def _fake_jar(path) -> None:
    """Jar factice à la manière du jeu : parents vanilla, lanterne (boîtes hors grille), fleur (plans en croix),
    marche tournée de 22,5°, item plat, texture animée."""
    lantern = np.zeros((16, 16, 4), np.uint8)
    lantern[...] = (60, 64, 80, 255)
    lantern[2:9, 0:6] = (240, 150, 70, 255)
    flower = np.zeros((16, 16, 4), np.uint8)
    flower[8:16, 7:9] = (40, 140, 40, 255)
    flower[3:8, 5:11] = (200, 30, 40, 255)
    m = "assets/minecraft/models/block/"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("assets/minecraft/textures/block/lantern.png", _png(np.concatenate([lantern, lantern])))
        z.writestr("assets/minecraft/textures/block/lantern.png.mcmeta", json.dumps({"animation": {}}))
        z.writestr("assets/minecraft/textures/block/poppy.png", _png(flower))
        z.writestr(m + "block.json", json.dumps({"textures": {}}))
        z.writestr(m + "template_lantern.json", json.dumps({"parent": "block/block", "elements": [
            {"from": [5, 0, 5], "to": [11, 7, 11], "faces": {f: {"uv": [0, 2, 6, 9], "texture": "#lantern"} for f in
                                                             ("north", "south", "east", "west")}
             | {"up": {"uv": [0, 9, 6, 15], "texture": "#lantern"}, "down": {"uv": [0, 9, 6, 15], "texture": "#lantern"}}},
            {"from": [6, 7, 6], "to": [10, 9, 10], "faces": {f: {"uv": [1, 10, 5, 12], "texture": "#lantern"} for f in
                                                              ("north", "south", "east", "west", "up", "down")}},
            {"from": [6.5, 9, 8], "to": [9.5, 11, 8], "faces": {f: {"uv": [11, 1, 14, 3], "texture": "#lantern"} for f in
                                                                 ("north", "south")}}]}))
        z.writestr(m + "lantern.json", json.dumps({"parent": "minecraft:block/template_lantern",
                                                   "textures": {"lantern": "minecraft:block/lantern"}}))
        z.writestr(m + "cross.json", json.dumps({"parent": "block/block", "elements": [
            {"from": [0.8, 0, 8], "to": [15.2, 16, 8], "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45},
             "shade": False, "faces": {f: {"uv": [0, 0, 16, 16], "texture": "#cross"} for f in ("north", "south")}},
            {"from": [8, 0, 0.8], "to": [8, 16, 15.2], "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45},
             "shade": False, "faces": {f: {"uv": [0, 0, 16, 16], "texture": "#cross"} for f in ("west", "east")}}]}))
        z.writestr(m + "poppy.json", json.dumps({"parent": "minecraft:block/cross", "textures": {"cross": "block/poppy"}}))
        z.writestr(m + "tilted.json", json.dumps({"parent": "block/block", "textures": {"t": "block/poppy"},
                                                  "elements": [{"from": [4, 0, 4], "to": [12, 8, 12],
                                                                "rotation": {"origin": [8, 4, 8], "axis": "y", "angle": 22.5},
                                                                "faces": {"up": {"texture": "#t"}}}]}))
        z.writestr("assets/minecraft/models/item/stick.json", json.dumps({"parent": "item/generated"}))


def test_import_from_a_jar_planes_and_warnings():
    from pixvox import Volume
    from pixvox.export import export_assets, verified
    from pixvox.importer import ModelImportError, import_model
    with tmpdir() as tmp:
        jar = tmp / "client.jar"
        _fake_jar(jar)
        imp = import_model(jar, "minecraft:block/lantern", res=16)
        assert imp.volume.shape == (6, 9, 6) and imp.origin == (5.0, 0.0, 5.0)
        assert len(imp.planes) == 1 and abs(imp.planes[0]["width"] - 3) < 1e-9          # anse : un plan
        assert any("plus fins que la grille" in w for w in imp.warnings) is False
        assert any("animée" in w for w in imp.warnings)
        top = imp.volume.data[2, 8, 2]
        assert tuple(top[:3]) == (60, 64, 80) and imp.volume.solid.sum() == 6 * 7 * 6 + 4 * 2 * 4
        fine = import_model(jar, "minecraft:block/lantern", res=4)                       # grille de 4 voxels
        assert any("plus fins que la grille" in w for w in fine.warnings)
        poppy = import_model(jar, "minecraft:block/poppy")
        assert not poppy.volume.solid.any() and len(poppy.planes) == 2
        assert sorted(p["angle"] for p in poppy.planes) == [45.0, 135.0] and not poppy.planes[0]["shade"]
        tilted = import_model(jar, "minecraft:block/tilted")
        assert any("multiple de 90" in w for w in tilted.warnings) and tilted.volume.solid.any()
        _raises(ModelImportError, "introuvable", lambda: import_model(jar, "minecraft:block/nope"))
        _raises(ModelImportError, "item/generated", lambda: import_model(jar, "minecraft:item/stick"))
        res = export_assets([imp.to_model("lantern_imp"), poppy.to_model("poppy_imp")], tmp / "p", log=None)
        assert all(verified(i) for i in res["infos"]), [i["verify"] for i in res["infos"]]
        v = Volume.from_model(jar, "minecraft:block/lantern")
        assert v.shape == (6, 9, 6) and any("plan(s) non gardés" in x for x in v.log)
        with zipfile.ZipFile(jar) as z, zipfile.ZipFile(tmp / "pack.zip", "w") as out:   # un .zip aussi
            for n in z.namelist():
                out.writestr(n, z.read(n))
        assert import_model(tmp / "pack.zip", "minecraft:block/lantern").volume.shape == (6, 9, 6)


def _bbmodel(path, rot=(0, 0, 0), embed=True):
    tex = np.zeros((32, 32, 4), np.uint8)
    tex[...] = (200, 120, 40, 255)
    tex[:16, :16] = (40, 90, 200, 255)
    src = "data:image/png;base64," + base64.b64encode(_png(tex)).decode() if embed else "lanterne.png"
    faces = {f: {"uv": [0, 0, 16, 16], "texture": 0} for f in ("north", "south", "east", "west", "down")}
    faces["up"] = {"uv": [16, 16, 32, 32], "texture": 0}
    path.write_text(json.dumps({"meta": {"format_version": "4.10"}, "resolution": {"width": 32, "height": 32},
                                "elements": [{"name": "corps", "type": "cube", "from": [4, 0, 4], "to": [12, 8, 12],
                                              "rotation": list(rot), "origin": [8, 4, 8], "faces": faces},
                                             {"name": "maillage", "type": "mesh"}],
                                "textures": [{"name": "t", "source": src}]}), encoding="utf-8")


def test_import_blockbench_and_command_line():
    from pixvox.cli import run
    from pixvox.importer import ModelImportError, import_bbmodel
    with tmpdir() as tmp:
        _bbmodel(tmp / "boite.bbmodel")
        imp = import_bbmodel(tmp / "boite.bbmodel")
        assert imp.volume.shape == (8, 8, 8) and any("mesh" in w for w in imp.warnings)
        assert tuple(imp.volume.data[0, 4, 0, :3]) == (40, 90, 200)                     # côtés : quart bleu
        assert tuple(imp.volume.data[4, 7, 4, :3]) == (200, 120, 40)                    # dessus : quart orange
        _bbmodel(tmp / "tourne.bbmodel", rot=(0, 22.5, 22.5))
        assert any("plusieurs axes" in w for w in import_bbmodel(tmp / "tourne.bbmodel").warnings)
        _bbmodel(tmp / "lien.bbmodel", embed=False)
        _raises(ModelImportError, "non incluse", lambda: import_bbmodel(tmp / "lien.bbmodel"))
        # ligne de commande : .bbmodel puis pack, fichier relu et exporté vérifié
        code, out = run(["import", str(tmp / "boite.bbmodel"), "--out", str(tmp / "a" / "boite.py"), "--json"])
        assert code == 0 and out["shape"] == [8, 8, 8] and out["name"] == "boite", out
        code, out = run(["import", str(tmp / "boite.bbmodel"), "--out", str(tmp / "a" / "boite.py"), "--json"])
        assert code == 2 and "--force" in out["errors"][0]["message"]
        jar = tmp / "client.jar"
        _fake_jar(jar)
        code, out = run(["import", str(jar), "minecraft:block/poppy", "--out", str(tmp / "a" / "coquelicot.py"),
                         "--name", "coquelicot", "--json"])
        assert code == 0 and out["planes"] == 2 and len(out["files"]) == 3, out
        code, out = run(["import", str(jar), "--json"])
        assert code == 2 and "ns:block/nom" in out["errors"][0]["message"]
        code, out = run(["export", str(tmp / "a" / "boite.py"), str(tmp / "a" / "coquelicot.py"),
                         "--pack", str(tmp / "pack"), "--json"])
        assert code == 0 and all(a["verified"] for a in out["assets"]), out


def test_import_real_game_jar():
    """Intégration facultative : lanterne et chaudron d'un vrai jar client (PIXVOX_MC_JAR, jamais versé)."""
    import unittest

    from pixvox.export import export_assets, verified
    from pixvox.importer import import_model
    jar = os.environ.get("PIXVOX_MC_JAR")
    if not jar:
        raise unittest.SkipTest("PIXVOX_MC_JAR non défini (chemin d'un jar client de Minecraft)")
    with tmpdir() as tmp:
        models = [import_model(jar, f"minecraft:block/{n}", mc="1.21.1").to_model(f"{n}_imp")
                  for n in ("lantern", "cauldron")]
        res = export_assets(models, tmp / "p", log=None)
        assert all(verified(i) for i in res["infos"])
