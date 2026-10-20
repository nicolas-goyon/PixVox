"""Export resource pack : chaque fichier écrit est relu comme le jeu et comparé au volume."""
import json

from PIL import Image

from pixvox import Anim, Block, Item, Model, MultiBlock, Sprite, Volume, export_pack, fire, flow, ramp
from pixvox.assets import Plane
from pixvox.export import ExportError, ResourcePack, optimize_model, plane_element
from pixvox.mcmodel import ModelLoader
from pixvox.render import plane_quads, quads_from_volume
from testkit import animated_model, design_shape, diff, marked_volume, pillar_volume, tmpdir


def test_model_export_both_strategies():
    v = Volume(12, 10, 12)
    v.set(v.m_ellipsoid((6, 4, 6), (5.5, 4.5, 5.5)), "#40a0a0")
    v.shade(v.solid, ramp("#40a0a0", 5))
    v.set(v.m_cylinder((6, 6), 1.5, 0, 9), "#d0c0a0")
    m = Model("blob", v)
    for strat in ("boxes", "palette"):
        opt = optimize_model(m, strat)
        loader = ModelLoader(extra_textures={"t:block/a": opt.atlas.image})
        qm = loader.quads({"textures": {"0": "t:block/a"}, "elements": opt.elements})
        assert diff(quads_from_volume(v, offset=m.origin), qm) == 0, strat


def test_pack_roundtrip():
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        info = pack.add(Block("cube_test", marked_volume()))
        assert info["verify"]["diff_px"] == 0
        sp = Sprite(16)
        sp.rect(4, 4, 11, 11, "#ff8800")
        pack.add(Item("item_test", sp))
        pack.finish(tmp / "p.zip")
        meta = json.loads((tmp / "pack" / "pack.mcmeta").read_text(encoding="utf-8"))
        assert meta["pack"]["min_format"] <= meta["pack"]["max_format"]
        assert (tmp / "pack" / "assets" / "pixvox" / "items" / "cube_test.json").exists()
        assert (tmp / "p.zip").stat().st_size > 0


def test_multiblock_export():
    v = pillar_volume()
    v.set(v.m_torus((12, 37, 5), 5, 1.2, axis="z"), "#d0b050")
    v.shade(v.solid, ramp("#a0a0a0", 5), ao=0.5)
    mb = MultiBlock("pillar", v)
    assert mb.blocks == (2, 3, 1)
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        info = pack.add(mb)
        assert info["verify"]["diff_px"] == 0, info["verify"]
        assert info["parts"] == len(mb.cells())
        pack.finish(tmp / "p.zip")
        place = (tmp / "pack_datapack/data/pixvox/function/place/pillar.mcfunction").read_text(encoding="utf-8")
        assert place.count("summon minecraft:item_display") == info["parts"] and "Rotation:[180f,0f]" in place
        for cell in mb.cells():
            name = "{}_{}_{}.json".format(*cell)
            m = json.loads((tmp / "pack/assets/pixvox/models/block/pillar" / name).read_text(encoding="utf-8"))
            for el in m["elements"]:
                assert all(-16 <= c <= 32 for c in el["from"] + el["to"])
        assert (tmp / "p_datapack.zip").exists()


def test_planes_match_minecraft_loader():
    """Plans à divers angles : référence trigonométrique == élément JSON exporté relu par le loader
    (rotation ±45° max, au-delà le plan est posé sur l'autre axe)."""
    tex = Sprite(16)
    tex.noise(ramp("#cc5522", 5), seed=2)
    tex.rect(2, 1, 4, 9, "#ffffff")                                      # repère asymétrique
    tex.data[12:, :, 3] = 0                                              # bas transparent (cutout)
    for ang in (0, 22.5, 45, -45, 67.5, 90, -67.5, -90, 30, 135):
        p = Plane(tex, (7, 9), 2, 12, 14, ang, 15, False)
        el = plane_element(p, "f")
        rot = el.get("rotation", {}).get("angle", 0)
        assert -45 <= rot <= 45, (ang, rot)
        loader = ModelLoader(extra_textures={"t:block/f": tex})
        qm = loader.quads({"textures": {"f": "t:block/f"}, "elements": [el]})
        qr = plane_quads(p.center, p.y, p.width, p.height, p.angle, tex.data, 15, False)
        assert all(q.emission == 15 and not q.shade for q in qm)
        assert diff(qr, qm, ((225, 30), (45, -20), (160, 10), (300, 60), (90, 0))) == 0, ang


def test_animated_model_export_roundtrip():
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        m = animated_model()
        info = pack.add(m)
        assert info["verify"]["diff_px"] == 0 and info["verify"]["ticks"] >= 8, info["verify"]
        root = tmp / "pack/assets/pixvox"
        model = json.loads((root / "models/block/anim_test.json").read_text(encoding="utf-8"))
        assert set(model["textures"]) >= {"0", "1", "p0", "particle"}
        meta = json.loads((root / "textures/block/anim_test_anim.png.mcmeta").read_text(encoding="utf-8"))
        assert meta["animation"]["frametime"] == 3
        assert json.loads((root / "textures/block/anim_test_p0.png.mcmeta").read_text(encoding="utf-8"))["animation"]
        planes = [e for e in model["elements"] if e["faces"].get("north", e["faces"].get("west", {}))
                  .get("texture") == "#p0"]
        assert len(planes) == 4
        for e in planes:
            assert e["light_emission"] == 15 and e["shade_direction_override"] == "up" and e["shade"] is False
            assert abs(e.get("rotation", {}).get("angle", 0)) in (0, 45)
        assert any(e.get("light_emission") == 11 for e in model["elements"])
        assert model.get("render_type") == "minecraft:cutout"
        # falsification : ordre des images inversé dans le .mcmeta -> la vérification le voit
        mp = root / "textures/block/anim_test_p0.png.mcmeta"
        mp.write_text(json.dumps({"animation": {"frametime": 2, "frames": list(range(7, -1, -1))}}), encoding="utf-8")
        bad = pack._verify_ticks("pixvox:block/anim_test", m, m.quads)
        assert bad["diff_px"] > 200, bad


def test_animated_block_and_item_export():
    with tmpdir() as tmp:
        v = Volume(16)
        joints = v.cells(ramp("#3a3337", 5), count=8, seed=3, mortar_width=0.95)
        fr = flow(v.frames(6), joints, ramp("#e2600f", 5), seed=2)
        pack = ResourcePack(tmp / "pack")
        info = pack.add(Block("lava_test", fr, frametime=4))
        assert info["verify"]["diff_px"] == 0 and info["animated"] >= 1, info
        tex = tmp / "pack/assets/pixvox/textures/block"
        strips = list(tex.glob("lava_test*.png"))
        for p in strips:
            with Image.open(p) as im:
                if im.size[1] > 16:
                    assert p.with_name(p.name + ".mcmeta").exists(), p
        assert strips
        frames = []
        for k in range(4):
            s = Sprite(16)
            s.ellipse(8, 8, 3 + k, 3 + k, "#44aaff").outline("#102040")
            frames.append(s)
        info = pack.add(Item("pulse_item", Anim(frames, frametime=5)))
        assert info["verify"]["diff_px"] == 0 and info["verify"]["views"] == 4
        assert (tmp / "pack/assets/pixvox/textures/item/pulse_item.png.mcmeta").exists()


def test_any_resolution_exports_exactly():
    """16, 32 voxels par bloc, multibloc HD, bloc plein HD (textures 32x32) : vérification à 0 pixel."""
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        assert pack.add(Model("hd", design_shape(32)))["verify"]["diff_px"] == 0
        assert pack.add(MultiBlock("hd_multi", design_shape(32)))["verify"]["diff_px"] == 0
        hd = Volume(32, res=32)
        hd.noise(ramp("#7a7a7a", 5), cells=4, seed=2)
        assert pack.add(Block("hd_block", hd))["verify"]["diff_px"] == 0
        png = tmp / "pack/assets/pixvox/textures/block/hd_block.png"
        with Image.open(png if png.exists() else next(png.parent.glob("hd_block*.png"))) as im:
            assert im.size == (32, 32)


def test_export_refuses_what_the_game_rejects():
    tall = Volume(6, 48, 6, fill="#888888")                              # 48 unités de haut > 32
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        try:
            pack.add(Model("tall", tall))
            raise AssertionError("modèle hors limites accepté")
        except ExportError as e:
            assert "[-16, 32]" in str(e)
        m = Model("flames", Volume(8, 4, 8, fill="#555555"))
        m.add_cross(fire(16, frames=4, seed=1), y=20, height=24, width=30)
        try:
            export_pack([m, Block("ok_block", marked_volume())], tmp / "p2")
            raise AssertionError("plans hors limites acceptés")
        except ExportError:
            assert (tmp / "p2/assets/pixvox/models/block/ok_block.json").exists()   # les autres sont exportés
        try:
            export_pack([MultiBlock("pil", pillar_volume())], tmp / "p3", replace={"pil": "minecraft:stone"})
            raise AssertionError("--replace multibloc accepté")
        except ExportError as e:
            assert "MultiBlock" in str(e)


def test_emissive_block_and_multiblock_export():
    v = Volume(16)
    v.noise(ramp("#5a5c63", 4), cells=3, seed=1)
    ore = v.blobs(ramp("#3cc8bb", 5), count=4, seed=2, on_edges=1)
    b = Block("glow_ore", v, emissive=ore, emission=11)
    mv = Volume(16, 32, 16)
    mv.set(mv.m_box(4, 0, 4, 11, 30, 11), "#777777")
    core = mv.m_box(6, 20, 3, 9, 26, 12)
    mv.set(core, "#ffcc33")
    mb = MultiBlock("lamp_post", mv, emissive=core, emission=14)
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        info = pack.add(b)
        assert info["verify"]["diff_px"] == 0 and info["glow_faces"] >= 2
        model = json.loads((tmp / "pack/assets/pixvox/models/block/glow_ore.json").read_text(encoding="utf-8"))
        assert len(model["elements"]) == 2 and model["elements"][1]["light_emission"] == 11
        info = pack.add(mb)
        assert info["verify"]["diff_px"] == 0
        part = json.loads((tmp / "pack/assets/pixvox/models/block/lamp_post/0_1_0.json").read_text(encoding="utf-8"))
        assert any(e.get("light_emission") == 14 for e in part["elements"])


def test_logging_never_crashes_on_a_narrow_console():
    """Console Windows redirigée (cp1252) : « → » ne doit pas faire planter un export ou une revue."""
    import io

    from pixvox._io import say
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
    say("vérification → OK", file=buf)
    buf.flush()
    assert buf.buffer.getvalue() == "vérification ? OK\n".encode("cp1252")
