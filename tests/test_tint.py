"""Teinte de biome (tintindex) : couleurs, faces teintées et surcouche, export vérifié, refus."""
import json

import numpy as np

from testkit import tmpdir


def _raises(exc, text: str, fn) -> None:
    try:
        fn()
    except exc as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"{exc.__name__} attendue ({text})")


def _turf():
    """Bloc d'herbe : terre + couche grise teintée (dessus entier, coulures sur les côtés)."""
    from pixvox import Block, Volume, ramp
    v = Volume(16)
    v.noise(ramp("#79553a", 4), cells=4, seed=4)
    before = v.data.copy()
    v.cap(ramp("#b4b4b4", 5, spread=0.3), depth=(1, 4), seed=7, cells=4)
    tinted = (v.data != before).any(axis=-1) & v.solid
    return Block("turf_test", v, tint="grass", tinted=tinted, seamless="horizontal")


def _leaves():
    from pixvox import Block, Volume, ramp
    v = Volume(16)
    v.noise(ramp("#9a9a9a", 4, spread=0.4), cells=4, seed=3)
    v.data[np.random.default_rng(1).random(v.shape) < 0.12] = 0           # trous : rendu cutout
    return Block("leaves_test", v, tint="foliage")


def _basin():
    from pixvox import Model, Volume
    v = Volume(8, 6, 8, fill="#7a7a7a")
    water = np.zeros(v.shape, bool)
    water[1:7, 4:6, 1:7] = True
    v.data[water] = (200, 200, 200, 255)
    return Model("basin_test", v, tint="water", tinted=water)


def test_tint_colors_and_masks():
    from pixvox.tint import BIOMES, apply_tint, tint_color
    assert tint_color("grass") == (0x91, 0xBD, 0x59) and tint_color("water", "swamp") == (0x61, 0x7B, 0x64)
    assert set(BIOMES) >= {"plains", "swamp", "desert", "jungle"}
    px = np.array([[[255, 255, 255, 255], [128, 128, 128, 200]]], np.uint8)
    out = apply_tint(px, (100, 50, 0), mask=np.array([[True, False]]))
    assert out[0, 0].tolist() == [100, 50, 0, 255] and out[0, 1].tolist() == [128, 128, 128, 200]
    assert apply_tint(px, (100, 50, 0))[0, 1].tolist() == [50, 25, 0, 200]      # texture × couleur / 255, arrondi
    t = _turf()
    lay = t.tint_layout()
    assert lay["up"] == "all" and lay["north"] == "overlay" and "down" not in lay
    assert set(t.tint_overlays()) == {"north", "south", "west", "east"}
    ov = t.tint_overlays()["north"].data
    assert (ov[..., 3] > 0).any() and (ov[..., 3] == 0).any()                     # pixels teintés seulement
    assert _leaves().tint_layout() == {f: "all" for f in ("up", "down", "north", "south", "west", "east")}
    up = t.tinted_faces_at(0, "desert")["up"].data
    assert not np.array_equal(up, t.tinted_faces_at(0, "plains")["up"].data)


def test_tinted_assets_export_verified_on_both_targets():
    from pixvox.export import ResourcePack, verified
    from pixvox.mcmodel import ModelLoader
    for mc in ("1.21.4+", "1.21.1"):
        with tmpdir() as tmp:
            pack = ResourcePack(tmp / "pack", mc=mc)
            infos = {a.name: pack.add(a) for a in (_turf(), _leaves(), _basin())}
            for name, info in infos.items():
                assert verified(info), (mc, name, info["verify"])
                assert any("teinte" in w for w in info["warnings"]), info["warnings"]   # sans mod : gris
            assert infos["turf_test"]["tint"] == "grass" and infos["turf_test"]["tint_faces"] == 5
            assert infos["basin_test"]["tinted_elements"] >= 1
            a = tmp / "pack" / "assets" / "pixvox"
            m = json.loads((a / "models/block/turf_test.json").read_text(encoding="utf-8"))
            base, over = m["elements"]
            assert base["faces"]["up"]["tintindex"] == 0 and "tintindex" not in base["faces"]["north"]
            assert sorted(over["faces"]) == ["east", "north", "south", "west"]
            assert all(fd["tintindex"] == 0 for fd in over["faces"].values())
            assert m["textures"]["north_tint"] == "pixvox:block/turf_test_tint_north"   # coulures propres à chaque côté
            assert (m.get("render_type") == "minecraft:cutout") == (mc == "1.21.1")
            basin = json.loads((a / "models/block/basin_test.json").read_text(encoding="utf-8"))
            tinted = [e for e in basin["elements"] if any("tintindex" in fd for fd in e["faces"].values())]
            assert tinted and all(e["from"][1] >= 4 for e in tinted)          # seule l'eau (y 4–6)
            if mc != "1.21.1":
                item = json.loads((a / "items/turf_test.json").read_text(encoding="utf-8"))
                assert item["model"]["tints"] == [{"type": "minecraft:grass", "temperature": 0.5, "downfall": 1.0}]
            # la vérification voit une teinte oubliée : relu sans couleur, le bloc reste gris
            t = _turf()
            grey = ModelLoader([tmp / "pack"], mc=pack.target.mc).quads("pixvox:block/turf_test")
            assert pack.verify(None, t.quads(0), quads=grey)["diff_px"] > 0


def test_tint_refusals_and_review():
    from pixvox import Block, Volume
    from pixvox.review import review_data
    v = Volume(16, fill="#808080")
    em = np.zeros(v.shape, bool)
    em[0, 0, 0] = True
    _raises(ValueError, "tint='mauve' inconnu", lambda: Block("x", v, tint="mauve"))
    _raises(ValueError, "tinted donné sans tint", lambda: Block("x", v, tinted=em))
    _raises(ValueError, "à la fois teinté", lambda: Block("x", v, tint="grass", emissive=em))
    _raises(ValueError, "teinte de biome", lambda: _leaves().variants("slab"))
    with tmpdir() as tmp:
        r = review_data(_turf(), tmp)
        assert r["sheet"].exists() and "Teinte" in r["report"] and "niveaux de gris" in r["report"]


def test_mod_registers_biome_colors_client_side():
    """Couleurs de biome enregistrées côté client : BlockTintSources en 26.3 (Fabric : ClientModInitializer ;
    NeoForge : RegisterColorHandlersEvent.BlockTintSources, appelé si Dist est client), BlockColor et ItemColor
    en 1.21.1. Un mod sans bloc teinté ne change pas."""
    from pixvox import Block, Volume, export_mod
    plain = Block("plain_test", Volume(16, fill="#808080"))
    for loader, mc in (("fabric", "26.3"), ("neoforge", "26.3"), ("neoforge", "1.21.1")):
        with tmpdir() as tmp:
            root = export_mod([_turf(), _leaves(), _basin(), plain], tmp / "mod", "pv_test", loader=loader, mc=mc,
                              quiet=True)["project"]
            java = root / "src/main/java/pixvox/pv_test"
            if loader == "fabric":
                client = (java / "PvTestModClient.java").read_text(encoding="utf-8")
                assert "BlockColorRegistry.register(List.of(BlockTintSources.grass()), ModContent.TURF_TEST);" in client
                assert "BlockTintSources.water()), ModContent.BASIN_TEST" in client
                fmj = json.loads((root / "src/main/resources/fabric.mod.json").read_text(encoding="utf-8"))
                assert fmj["entrypoints"]["client"] == ["pixvox.pv_test.PvTestModClient"]
            else:
                main = (java / "PvTestMod.java").read_text(encoding="utf-8")
                assert "if (dist.isClient()) ModClient.register(modEventBus);" in main
                client = (java / "ModClient.java").read_text(encoding="utf-8")
                if mc == "1.21.1":
                    assert "BiomeColors.getAverageFoliageColor(level, pos) : FoliageColor.getDefaultColor(), " \
                           "ModContent.LEAVES_TEST.get());" in client
                    assert "event.register((stack, tintIndex) -> 0xFF000000 | GrassColor.getDefaultColor()" in client
                else:
                    assert "RegisterColorHandlersEvent.BlockTintSources event" in client
                    assert "event.register(List.of(BlockTintSources.foliage()), ModContent.LEAVES_TEST.get());" in client
        with tmpdir() as tmp:                                   # sans bloc teinté : rien de client
            root = export_mod([plain], tmp / "mod", "pv_test", loader=loader, mc=mc, quiet=True)["project"]
            java = root / "src/main/java/pixvox/pv_test"
            assert not (java / "ModClient.java").exists() and not (java / "PvTestModClient.java").exists()
