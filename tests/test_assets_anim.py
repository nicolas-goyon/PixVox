"""Assets (Block, Model, MultiBlock, Item) et animation (Timing, Anim, fire, pulse, flow)."""
import numpy as np

from pixvox import Anim, Block, Model, MultiBlock, Sprite, Timing, Volume, fire, flow, pulse, ramp
from pixvox.render import fit_camera, render
from testkit import design_shape, marked_volume, tmpdir


def test_from_faces_conflicts():
    top = Sprite(16, fill="#808080")
    top.rect(0, 0, 15, 0, "#ff0000")          # rangée nord du dessus en rouge
    side = Sprite(16, fill="#808080")
    b = Block.from_textures("t", side=side, end=top)
    edges = {tuple(sorted({f for f, *_ in c["faces"]})) for c in b.conflicts}
    # La même texture « end » sur up ET down : sa rangée du haut touche le NORD sur la face up,
    # mais le SUD sur la face down (l'axe v de down est inversé) -> 2 arêtes en conflit.
    assert len(b.conflicts) == 32, len(b.conflicts)
    assert all({"north", "up"} <= set(e) or {"down", "south"} <= set(e) for e in edges), edges
    assert Block("ok", marked_volume()).conflicts == []


def test_timing_and_mcmeta():
    t = Timing(3, order=[0, 2, (1, 7)])
    assert t.sequence(3) == [(0, 3), (2, 3), (1, 7)] and t.period(3) == 13
    assert t.at(3, 0)[0] == 0 and t.at(3, 4)[0] == 2 and t.at(3, 7)[0] == 1 and t.at(3, 13)[0] == 0
    assert t.mcmeta(3) == {"animation": {"frametime": 3, "frames": [0, 2, {"index": 1, "time": 7}]}}
    fr = [np.full((16, 16, 4), (k * 40, 0, 0, 255), np.uint8) for k in range(4)]
    a = Anim(fr, frametime=2, interpolate=True)
    assert a.strip().shape == (64, 16, 4) and a.duration == 0.4
    mid = a.at(1)                                         # à mi-chemin entre l'image 0 et 1 : fondu
    assert 15 <= int(mid[0, 0, 0]) <= 25
    b = Anim.from_strip(a.strip(), frametime=2)
    assert b.n == 4 and np.array_equal(b[3].data, a[3].data)
    try:
        Anim([np.zeros((16, 16, 4), np.uint8), np.zeros((8, 8, 4), np.uint8)])
        raise AssertionError("tailles différentes acceptées")
    except ValueError:
        pass


def test_anim_strip_roundtrip_reads_mcmeta():
    with tmpdir() as tmp:
        a = Anim(fire(16, frames=4, seed=2).frames, frametime=3, interpolate=True, order=[0, 2, (1, 6), 3])
        a.save(tmp / "a.png")
        b = Anim.from_strip(tmp / "a.png")
        assert (b.frametime, b.timing.interpolate, b.timing.sequence(4)) == (3, True, a.timing.sequence(4))


def test_fire_is_cutout_deterministic_and_keyword_only():
    for shape in ("bush", "sheet"):
        a = fire(16, frames=16, seed=4, shape=shape)
        st = a.strip()
        assert set(np.unique(st[..., 3])) <= {0, 255}                    # cutout pur
        assert 0.2 < (st[..., 3] > 0).mean() < 0.85
        assert np.array_equal(st, fire(16, frames=16, seed=4, shape=shape).strip())
    try:
        fire(16, 8)
        raise AssertionError("fire(16, 8) positionnel accepté")
    except TypeError:
        pass


def test_pulse_and_flow_only_touch_their_mask():
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 5), cells=4, seed=1)
    m = v.m_noise(0.6, cells=4, seed=2)
    for gen in (lambda fr: pulse(fr, m, ramp("#e06010", 6), seed=3),
                lambda fr: flow(fr, m, ramp("#e06010", 6), seed=3, direction=(0, -1, 0))):
        fr = gen(v.frames(12))
        stack = np.stack([f.data for f in fr])
        assert (stack[:, ~m] == v.data[~m]).all()                       # hors masque : rien ne bouge
        assert (stack[:, m] != stack[:1, m]).any()                      # dans le masque : ça bouge
        Block("anim_ok", fr)                                             # accepté (même forme partout)


def test_animated_geometry_is_refused():
    v = Volume(16, fill="#808080")
    f2 = v.frames(2)
    f2[1].clear(f2[1].m_box(0, 0, 0, 3, 3, 3))
    try:
        Block("bad", f2)
        raise AssertionError("géométrie animée acceptée")
    except ValueError:
        pass


def test_resolution_sets_voxel_size():
    m32 = Model("hd", design_shape(32))
    assert m32.voxel_size == 0.5
    assert Model("fig", design_shape(16, scale=0.5)).voxel_size == 1.0
    mb = MultiBlock("hd_multi", design_shape(32))
    assert mb.res == 32 and mb.blocks == (2, 2, 1)


def test_emissive_parts_glow_at_night():
    v = Volume(16)
    v.noise(ramp("#5a5c63", 4), cells=3, seed=1)
    ore = v.blobs(ramp("#3cc8bb", 5), count=4, seed=2, on_edges=1)
    b = Block("glow_ore", v, emissive=ore, emission=11)
    q = b.quads(0)
    night = render(q, fit_camera(q, (225, 30), 128, 128), shading="night")
    day = render(q, fit_camera(q, (225, 30), 128, 128), shading="world")
    lit = (night[..., :3].max(-1) > 90) & (night[..., 3] > 0)
    assert 30 < lit.sum() < (day[..., :3].max(-1) > 90).sum()           # seuls les cristaux brillent
