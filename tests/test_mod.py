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


def test_multipart_is_refused_by_mod():
    from pixvox import Model, Multipart, Part, Volume
    from pixvox.export import ExportError
    v = Volume(4, 4, 4)
    v.set(None, "#888888")
    with tmpdir() as tmp:
        try:
            export_mod([Multipart("mp", [Part(Model("mp_base", v))])], tmp / "mod", "demo")
        except ExportError as e:
            assert "Multipart" in str(e)
        else:
            raise AssertionError("Multipart accepté par pixvox mod")


def test_mod_project_for_1_21_1():
    a = Block("bloc_test", marked_volume())
    mb = MultiBlock("pilier", pillar_volume())
    with tmpdir() as tmp:
        res = export_mod([a, mb], tmp / "mod", "demo_old", loader="neoforge", mc="1.21.1", quiet=True)
        assert res["mc"] == "1.21.1" and all(i["verify"]["diff_px"] == 0 for i in res["assets"])
        root = tmp / "mod"
        data = root / "src/main/resources"
        assert (data / "assets/demo_old/models/item/bloc_test.json").exists()
        assert not (data / "assets/demo_old/items").exists()
        loot = json.loads((data / "data/demo_old/loot_table/blocks/pilier.json").read_text(encoding="utf-8"))
        pool = loot["pools"][0]
        assert pool["conditions"] == [{"condition": "minecraft:survives_explosion"}]
        assert pool["entries"][0]["conditions"][0]["condition"] == "minecraft:block_state_property"
        toml = (data / "META-INF/neoforge.mods.toml").read_text(encoding="utf-8")
        assert 'modLoader="javafml"' in toml and 'versionRange="[1.21.1]"' in toml
        assert "of(21)" in (root / "build.gradle").read_text(encoding="utf-8")
        assert "neo_version=21.1." in (root / "gradle.properties").read_text(encoding="utf-8")
        java = "\n".join(p.read_text(encoding="utf-8") for p in (root / "src").rglob("*.java"))
        for gone in ("Identifier", "ScheduledTickAccess", "IMMOVEABLE", "noCollision", "ITEM.getValue", "BLOCK.getValue"):
            assert gone not in java, gone
        assert "ResourceLocation.fromNamespaceAndPath" in java and "LevelAccessor level, BlockPos pos" in java


def test_mod_1_21_1_is_neoforge_only():
    from pixvox.mod import required_java
    assert (required_java("1.21.1"), required_java("26.3"), required_java()) == (21, 25, 25)
    with tmpdir() as tmp:
        for kw in ({"loader": "fabric", "mc": "1.21.1"}, {"loader": "neoforge", "mc": "1.20.1"}):
            try:
                export_mod([Block("b", marked_volume())], tmp / "mod", "demo", quiet=True, **kw)
            except ValueError as e:
                assert "1.2" in str(e)
            else:
                raise AssertionError(kw)


def test_mod_1_21_1_refuses_what_the_game_does_not_have():
    from pixvox.assets import PARTICLES
    from pixvox.export import ExportError
    from pixvox.mod import PARTICLES_NOT_IN_1_21_1
    particle = next(k for k, v in PARTICLES.items() if PARTICLES_NOT_IN_1_21_1 & set(v))
    for props in (Props(sound="iron"), Props(particles=particle)):
        block = Block("bloc_test", marked_volume())
        block.props = props
        with tmpdir() as tmp:
            try:
                export_mod([block], tmp / "mod", "demo_old", loader="neoforge", mc="1.21.1", quiet=True)
            except ExportError as e:
                assert "1.21.1" in str(e)
            else:
                raise AssertionError(props)


def test_mod_registers_construction_variants():
    """Variantes : vrais blocs vanilla (sous-classes pour les constructeurs protégés), tags qui permettent
    les raccords, butin de la dalle double et recette de taille au format de chaque version, test JUnit."""
    base = Block("plain_test", marked_volume())
    base.props = Props(sound="wood", tool="axe", names={"fr_fr": "Planche test", "en_us": "Test Plank"})
    for loader, mc in (("fabric", "26.3"), ("neoforge", "26.3"), ("neoforge", "1.21.1")):
        with tmpdir() as tmp:
            res = export_mod([*base.variants(), base], tmp / "mod", "pv_test", loader=loader, mc=mc, quiet=True)
            root = res["project"]
            java = root / "src/main/java/pixvox/pv_test"
            content = (java / "ModContent.java").read_text(encoding="utf-8")
            assert content.index("PLAIN_TEST =") < content.index("PLAIN_TEST_STAIRS =")    # bloc plein déclaré avant
            get = ".get()" if loader == "neoforge" else ""
            assert f"new PixvoxStairBlock(PLAIN_TEST{get}.defaultBlockState(), p)" in content
            assert "SlabBlock::new" in content and "new FenceGateBlock(WoodType.OAK, p)" in content
            assert "new PixvoxButtonBlock(BlockSetType.OAK, 30, p)" in content           # bois : 30 ticks
            assert f"PushReaction.{'DESTROY' if mc == '1.21.1' else 'POPPED'}" in content   # nom selon la version
            for cls in ("PixvoxStairBlock", "PixvoxButtonBlock", "PixvoxPressurePlateBlock"):
                assert (java / f"block/{cls}.java").exists(), cls
            test = (root / "src/test/java/pixvox/pv_test/GeneratedContentTest.java").read_text(encoding="utf-8")
            assert test.count('checkVariant("') == 7
            assert '{"shape", "straight", "inner_left", "inner_right", "outer_left", "outer_right"}' in test
            data = root / "src/main/resources/data"
            tdir = data / "minecraft/tags/block"
            tags = {p.relative_to(tdir).with_suffix("").as_posix(): json.loads(p.read_text(encoding="utf-8"))["values"]
                    for p in tdir.rglob("*.json")}
            assert tags["walls"] == ["pv_test:plain_test_wall"] and "pv_test:plain_test_fence" in tags["wooden_fences"]
            assert "pv_test:plain_test_fence" in tags["fences"]          # FenceBlock ne se raccorde qu'à son tag
            assert "pv_test:plain_test_slab" in tags["mineable/axe"]
            assert (data / "minecraft/tags/item/slabs.json").exists()
            loot = json.loads((data / "pv_test/loot_table/blocks/plain_test_slab.json").read_text(encoding="utf-8"))
            recipe = json.loads((data / "pv_test/recipe/plain_test_slab_from_plain_test_stonecutting.json")
                                .read_text(encoding="utf-8"))
            assert recipe["result"] == {"count": 2, "id": "pv_test:plain_test_slab"}
            entry = loot["pools"][0]["entries"][0]
            if mc == "1.21.1":
                assert recipe["ingredient"] == {"item": "pv_test:plain_test"}
                assert entry["functions"][0]["conditions"][0]["properties"] == {"type": "double"}
            else:
                assert recipe["ingredient"] == "pv_test:plain_test"
                assert entry["modifier"][0]["condition"]["state"] == {"type": "double"}
            lang = json.loads((root / "src/main/resources/assets/pv_test/lang/fr_fr.json").read_text(encoding="utf-8"))
            assert lang["block.pv_test.plain_test_slab"] == "Dalle de planche test"
            assert lang["block.pv_test.plain_test_fence_gate"] == "Portillon de planche test"
    with tmpdir() as tmp:                       # sans le bloc plein : escalier sur la pierre, pas de recette
        root = export_mod(base.variants("stairs"), tmp / "mod", "pv_test", quiet=True)["project"]
        assert "new PixvoxStairBlock(Blocks.STONE.defaultBlockState(), p)" in \
            (root / "src/main/java/pixvox/pv_test/ModContent.java").read_text(encoding="utf-8")
        assert not (root / "src/main/resources/data/pv_test/recipe").exists()
