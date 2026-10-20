"""Analyse (raccords, boucles d'animation…), planches de revue et exemples fournis."""
import re
import runpy

import numpy as np

from pixvox import Block, Item, Model, MultiBlock, Sprite, Volume, fire, flow, pulse, ramp
from pixvox.analyze import analyze, anim_findings, seam_scores
from pixvox.anim import Timing
from pixvox.review import compare_sheet, review_data, view
from testkit import ROOT, animated_model, pillar_volume, tmpdir


def test_periodic_noise_has_no_seam():
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 5), cells=4, octaves=2, seed=3)
    for f, s in v.faces().items():
        rh, rv, _, _ = seam_scores(s.data)
        assert rh < 0.6 and rv < 0.6, (f, rh, rv)
    grad = Sprite(16)
    for x in range(16):
        grad.rect(x, 0, x, 15, (60 + 10 * x, 60 + 10 * x, 70 + 10 * x))   # dégradé : vraie couture
    assert seam_scores(grad.data)[0] > 0.6
    v2 = Volume(16)
    v2.cells(ramp("#7a7a7a", 5), count=14, seed=5)                    # pavés périodiques : pas de couture
    assert all(max(seam_scores(t.data)[:2]) <= 0.6 for t in v2.faces().values())


def test_fire_loops_without_a_jump():
    for shape in ("bush", "sheet"):
        a = fire(16, frames=16, seed=4, shape=shape)
        stack = np.stack([f.data.reshape(-1, 4) for f in a.frames])
        assert not [f for f in anim_findings("feu", stack, a.timing) if f.level == "WARN"]


def test_loop_detector_and_pulse_flow():
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 5), cells=4, seed=1)
    m = v.m_noise(0.6, cells=4, seed=2)
    for gen in (lambda fr: pulse(fr, m, ramp("#e06010", 6), seed=3),
                lambda fr: flow(fr, m, ramp("#e06010", 6), seed=3, direction=(0, -1, 0))):
        b = Block("anim_ok", gen(v.frames(12)))
        found = analyze(b)
        bad = [f.line() for f in found if f.level in ("WARN", "ERR") and f.topic == "Animation"]
        assert not bad and any(f.topic == "Animation" and f.level == "OK" for f in found), bad
    # animation qui « s'éclaircit » sans revenir : à-coup à la boucle, détecté
    stack = np.stack([np.full((50, 4), (20 * k, 20 * k, 20 * k, 255), np.uint8) for k in range(10)])
    stack[:, ::2] = 128                                                  # la moitié ne bouge pas
    assert any(f.level == "WARN" and "à-coup" in f.msg for f in anim_findings("x", stack, Timing(2)))


def test_review_sheets_for_every_kind():
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 4), cells=4, seed=1)
    peb = Volume(6, 4, 6)
    peb.set(peb.m_ellipsoid((3, 2, 3), (2.8, 1.9, 2.8)), "#888888")
    s = Sprite(16)
    s.ellipse(8, 8, 5, 5, "#55aa55").outline("#102010")
    assets = [Block("blk", v), Model("peb", peb, inventory_scale=1.5, inventory_center=True), Item("itm", s),
              MultiBlock("pil", pillar_volume()), animated_model()]
    with tmpdir() as tmp:
        for a in assets:
            r = review_data(a, tmp)
            assert r["sheet"].exists() and r["report_file"].exists() and r["findings"], a.name
            assert r["report"].startswith(f"=== {a.name}")
            if a.name == "anim_test":
                assert r["anim"] and all(p.exists() for p in r["anim"])
            else:
                assert r["anim"] is None
        assert view(assets[0], 135, 20, 200, out_dir=tmp).exists()
        assert compare_sheet(assets[:3], tmp / "cmp.png", 120).exists()


def test_examples_build_with_unique_valid_names():
    names = []
    for f in sorted((ROOT / "examples").glob("*.py")):
        res = runpy.run_path(str(f))["build"]()
        names += [a.name for a in (res if isinstance(res, (list, tuple)) else [res])]
    assert len(names) >= 10 and len(names) == len(set(names)), names
    assert all(re.fullmatch(r"[a-z0-9_]+", n) for n in names), names
