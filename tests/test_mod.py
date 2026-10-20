"""Export en mod Fabric / NeoForge : projet Gradle complet, sans lancer Gradle.

La compilation (JDK 25 + réseau Maven) est faite par la CI (job « mods ») ou à la main :
python -m pixvox mod examples/brazier.py --modid demo --build
"""
import json
import os

from pixvox import Block, MultiBlock, Props
from pixvox.mod import export_mod, find_java, java_version, multi_layout, rot_box_y, shape_boxes
from testkit import animated_model, marked_volume, pillar_volume, tmpdir


def test_mod_project_generation():
    """Fichiers, enregistrements, données 26.3, formes et multibloc cohérents, pour les deux chargeurs."""
    assert rot_box_y((0, 0, 0, 16, 4, 2), 1) == (14, 0, 0, 16, 4, 16)          # face nord -> est
    assert rot_box_y((1, 2, 3, 5, 6, 7), 4) == (1, 2, 3, 5, 6, 7)
    m = animated_model()
    m.props = Props(light=15, sound="lantern", particles="flame", names={"fr_fr": "Brasero test"})
    mb = MultiBlock("pillar", pillar_volume())
    boxes = shape_boxes(m.volume, m.voxel_size, m.origin)
    assert 1 <= len(boxes) <= 24 and all(0 <= c <= 16 for b in boxes for c in b)
    with tmpdir() as tmp:
        for loader in ("fabric", "neoforge"):
            res = export_mod([m, mb, Block("plain_test", marked_volume())], tmp / loader, "pv_test",
                             loader=loader, quiet=True)
            root = res["project"]
            java = root / "src/main/java/pixvox/pv_test"
            content = (java / "ModContent.java").read_text(encoding="utf-8")
            assert "ANIM_TEST" in content and "PILLAR" in content and "PLAIN_TEST" in content
            assert ".lightLevel(state -> 15)" in content and "ParticleTypes.FLAME" in content
            assert (java / "block/PillarBlock.java").exists() and (java / "block/PixvoxMultiBlock.java").exists()
            assert (root / "src/test/java/pixvox/pv_test/GeneratedContentTest.java").exists()
            rs = root / "src/main/resources"
            meta = rs / ("fabric.mod.json" if loader == "fabric" else "META-INF/neoforge.mods.toml")
            assert meta.exists()
            bs = json.loads((rs / "assets/pv_test/blockstates/pillar.json").read_text(encoding="utf-8"))
            n = len(mb.cells())
            assert len(bs["variants"]) == 4 * n and bs["variants"]["facing=east,part=0"]["y"] == 90
            loot = json.loads((rs / "data/pv_test/loot_table/blocks/pillar.json").read_text(encoding="utf-8"))
            anchor, offs = multi_layout(mb, [(c, None) for c in sorted(mb.cells())])
            entry = loot["pools"][0]["entries"][0]
            assert loot["pools"][0]["condition"]["type"] == "minecraft:survives_explosion"
            assert entry["condition"]["type"] == "minecraft:match_block"
            assert entry["condition"]["state"]["part"] == str(anchor) and offs[anchor] == (0, 0, 0)
            tags = json.loads((rs / "data/minecraft/tags/block/mineable/pickaxe.json").read_text(encoding="utf-8"))
            assert "pv_test:anim_test" in tags["values"]
            lang = json.loads((rs / "assets/pv_test/lang/fr_fr.json").read_text(encoding="utf-8"))
            assert lang["block.pv_test.anim_test"] == "Brasero test"
            assert (rs / "assets/pv_test/textures/block/anim_test_p0.png.mcmeta").exists()
            assert not (rs / "pack.mcmeta").exists()                              # un mod n'en a pas besoin
            assert (root / "gradle/wrapper/gradle-wrapper.jar").exists() and (root / "gradlew.bat").exists()
            if os.name != "nt":
                assert (root / "gradlew").stat().st_mode & 0o111


def test_mod_export_refuses_bad_ids_and_keeps_previous_project():
    with tmpdir() as tmp:
        out = tmp / "mod"
        export_mod([Block("a_block", marked_volume())], out, "good_id", quiet=True)
        for bad in ("minecraft", "Bad-Id", "x"):
            try:
                export_mod([Block("a_block", marked_volume())], out, bad, quiet=True)
                raise AssertionError(f"modid {bad!r} accepté")
            except ValueError:
                pass
        assert (out / "src/main/resources/fabric.mod.json").exists()          # ancien projet intact


def test_java_probe_never_crashes():
    jh = find_java()
    v = java_version(jh)
    assert jh is None or isinstance(jh, str)
    assert v is None or v >= 1
    assert java_version(None) is None and java_version("/chemin/inexistant") is None
