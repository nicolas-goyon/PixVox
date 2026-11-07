"""Variantes de construction : géométrie conforme aux blocs vanilla, export vérifié, refus."""
import json

import numpy as np

from testkit import marked_volume, tmpdir

# Blockstates vanilla (oak_stairs, stone_button) : (modèle, x, y) par état. La vérification d'export compare
# les fichiers à la géométrie de pixvox ; ce test compare cette géométrie au jeu, pour ne pas se tromper de
# côté (marche vers `facing`, gauche / droite, bouton collé au mur opposé à `facing`).
_STAIRS_MODELS = {
    "straight": [((0, 0, 0), (16, 8, 16)), ((8, 8, 0), (16, 16, 16))],
    "inner": [((0, 0, 0), (16, 8, 16)), ((8, 8, 0), (16, 16, 16)), ((0, 8, 8), (8, 16, 16))],
    "outer": [((0, 0, 0), (16, 8, 16)), ((8, 8, 8), (16, 16, 16))],
}
_STAIRS_Y = {  # (facing, shape) -> y, pour half=bottom ; half=top : x=180 et y du tableau _STAIRS_TOP_Y
    ("east", "straight"): 0, ("east", "inner_left"): 270, ("east", "inner_right"): 0, ("east", "outer_left"): 270,
    ("east", "outer_right"): 0,
    ("north", "straight"): 270, ("north", "inner_left"): 180, ("north", "inner_right"): 270,
    ("north", "outer_left"): 180, ("north", "outer_right"): 270,
    ("south", "straight"): 90, ("south", "inner_left"): 0, ("south", "inner_right"): 90, ("south", "outer_left"): 0,
    ("south", "outer_right"): 90,
    ("west", "straight"): 180, ("west", "inner_left"): 90, ("west", "inner_right"): 180, ("west", "outer_left"): 90,
    ("west", "outer_right"): 180,
}
_STAIRS_TOP_Y = {
    ("east", "straight"): 0, ("east", "inner_left"): 0, ("east", "inner_right"): 90, ("east", "outer_left"): 0,
    ("east", "outer_right"): 90,
    ("north", "straight"): 270, ("north", "inner_left"): 270, ("north", "inner_right"): 0,
    ("north", "outer_left"): 270, ("north", "outer_right"): 0,
    ("south", "straight"): 90, ("south", "inner_left"): 90, ("south", "inner_right"): 180,
    ("south", "outer_left"): 90, ("south", "outer_right"): 180,
    ("west", "straight"): 180, ("west", "inner_left"): 180, ("west", "inner_right"): 270,
    ("west", "outer_left"): 180, ("west", "outer_right"): 270,
}
_BUTTON = {  # (face, facing) -> (x, y) ; modèle [5,0,6]-[11,2,10] (enfoncé : épaisseur 1)
    ("floor", "east"): (0, 90), ("floor", "north"): (0, 0), ("floor", "south"): (0, 180), ("floor", "west"): (0, 270),
    ("wall", "east"): (90, 90), ("wall", "north"): (90, 0), ("wall", "south"): (90, 180), ("wall", "west"): (90, 270),
    ("ceiling", "east"): (180, 270), ("ceiling", "north"): (180, 180), ("ceiling", "south"): (180, 0),
    ("ceiling", "west"): (180, 90),
}


def _grid(boxes) -> np.ndarray:
    g = np.zeros((32, 32, 32), bool)                    # demi-pixels
    for lo, hi in boxes:
        a = [round(v * 2) for v in lo]
        b = [round(v * 2) for v in hi]
        g[a[0]:b[0], a[1]:b[1], a[2]:b[2]] = True
    return g


def _vanilla(boxes, x: int, y: int) -> np.ndarray:
    """Rotation de blockstate : x d'abord (x=90 : le bas va au sud), puis y (90 : le nord va à l'est)."""
    g = _grid(boxes)                                    # axes (x, y, z)
    for _ in range(x // 90):
        g = np.flip(np.swapaxes(g, 1, 2), axis=2)       # y' = z, z' = 16 − y
    for _ in range(y // 90):
        g = np.flip(np.swapaxes(g, 0, 2), axis=0)       # x' = 16 − z, z' = x
    return g


def test_variant_geometry_matches_vanilla_blockstates():
    from pixvox import Block
    b = Block("cube_test", marked_volume())
    stairs, button = b.variants("stairs", "button")
    for st in stairs.all_states():
        kind = st["shape"].split("_")[0]
        y = (_STAIRS_Y if st["half"] == "bottom" else _STAIRS_TOP_Y)[(st["facing"], st["shape"])]
        want = _vanilla(_STAIRS_MODELS[kind], 0 if st["half"] == "bottom" else 180, y)
        assert np.array_equal(_grid(stairs.boxes(st)), want), st
    for st in button.all_states():
        h = 1 if st["powered"] == "true" else 2
        x, y = _BUTTON[(st["face"], st["facing"])]
        assert np.array_equal(_grid(button.boxes(st)), _vanilla([((5, 0, 6), (11, h, 10))], x, y)), st
    # mur et barrière : côté nord tourné comme le multipart vanilla (y=90 : est)
    wall, fence = b.variants("wall", "fence")
    side = {n: bs for n, _, bs in wall.parts()}
    assert np.array_equal(_grid(side["_side_east"]), _vanilla(side["_side_north"], 0, 90))
    side = {n: bs for n, _, bs in fence.parts()}
    assert np.array_equal(_grid(side["_side_west"]), _vanilla(side["_side_north"], 0, 270))


def test_variants_export_verified_on_both_targets():
    from pixvox import Block
    from pixvox.export import ResourcePack, verified
    from pixvox.variants import SHAPES
    b = Block("cube_test", marked_volume())
    for mc in ("1.21.4+", "1.21.1"):
        with tmpdir() as tmp:
            pack = ResourcePack(tmp / "pack", mc=mc)
            pack.add(b)
            infos = {v.shape: pack.add(v) for v in b.variants()}
            assert set(infos) == set(SHAPES)
            for shape, info in infos.items():
                assert verified(info), (mc, shape, info["verify"])
            assets = tmp / "pack" / "assets" / "pixvox"
            stairs = json.loads((assets / "blockstates" / "cube_test_stairs.json").read_text(encoding="utf-8"))
            assert len(stairs["variants"]) == 40 and "facing=east,half=bottom,shape=straight" in stairs["variants"]
            assert not any("uvlock" in v or "x" in v or "y" in v for v in stairs["variants"].values())
            wall = json.loads((assets / "blockstates" / "cube_test_wall.json").read_text(encoding="utf-8"))
            assert wall["multipart"][0] == {"apply": {"model": "pixvox:block/cube_test_wall_post"}, "when": {"up": "true"}}
            slab = json.loads((assets / "models" / "block" / "cube_test_slab.json").read_text(encoding="utf-8"))
            el = slab["elements"][0]
            assert el["from"] == [0, 0, 0] and el["to"] == [16, 8, 16]
            assert el["faces"]["north"]["uv"] == [0, 8, 16, 16]             # moitié basse de la face nord
            assert el["faces"]["down"]["cullface"] == "down" and "cullface" not in el["faces"]["up"]
            assert slab["textures"]["north"] == "pixvox:block/cube_test_north"   # textures du bloc plein
            item = assets / ("items" if mc != "1.21.1" else "models/item") / "cube_test_wall.json"
            assert "cube_test_wall_inventory" in item.read_text(encoding="utf-8")


def _raises(exc, text: str, fn) -> None:
    try:
        fn()
    except exc as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"{exc.__name__} attendue ({text})")


def test_variants_without_the_base_block_and_refusals():
    from pixvox import Block, Volume
    from pixvox.export import ExportError, ResourcePack, verified
    from pixvox.variants import Variant
    b = Block("cube_test", marked_volume())
    with tmpdir() as tmp:
        pack = ResourcePack(tmp / "pack")
        info = pack.add(b.variants("slab")[0])                 # bloc plein absent : ses textures sont écrites
        assert verified(info)
        assert (tmp / "pack" / "assets" / "pixvox" / "textures" / "block" / "cube_test_north.png").exists()
        _raises(ExportError, "--replace", lambda: pack.add(b.variants("stairs")[0], replace="minecraft:stone_stairs"))
        from pixvox import export_mod
        _raises(ExportError, "variantes de construction", lambda: export_mod(b.variants("wall"), tmp / "mod", "demo"))
    from pixvox.cli import asset_kind
    assert asset_kind(b.variants("fence")[0]) == "variant" and asset_kind(b) == "block"
    names = [v.name for v in b.variants("slab", "wall", names={"wall": "cube_test_rempart"})]
    assert names == ["cube_test_slab", "cube_test_rempart"]
    _raises(ValueError, "variante inconnue", lambda: Variant(b, "door"))
    glow = Volume(16, fill="#808080")
    em = np.zeros(glow.shape, bool)
    em[0, 0, 0] = True
    _raises(ValueError, "emissive", lambda: Block("lueur", glow, emissive=em).variants("slab"))
