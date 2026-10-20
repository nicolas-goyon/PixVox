"""Outils partagés par les tests.

Les imports de pixvox sont faits dans les fonctions : chaque étage de la pile de PR n'a pas encore tous
les modules, et un test ne doit dépendre que de ce qu'il teste.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                      # tests lancés sans installer le paquet (skill, clone)
    sys.path.insert(0, str(ROOT))

VIEWS = ((225.0, 30.0), (45.0, -30.0), (135, 20), (315, -45), (0, 89.9), (90, -89.9))
JITTER = (0.313, 0.227)                            # aucun centre de pixel pile sur une frontière de texel


def require(*relpaths: str) -> None:
    """Saute le test (unittest.SkipTest, compris par pytest et tests/run.py) si ces fichiers du dépôt
    manquent : c'est le cas dans le skill décompressé, qui n'embarque ni scripts/ ni .claude/."""
    missing = [p for p in relpaths if not (ROOT / p).exists()]
    if missing:
        raise unittest.SkipTest(f"fichiers du dépôt absents : {', '.join(missing)}")


@contextmanager
def tmpdir():
    """Dossier temporaire, nettoyé même si Windows garde un fichier ouvert."""
    with tempfile.TemporaryDirectory(prefix="pixvox_test_", ignore_cleanup_errors=True) as d:
        yield Path(d)


def marked_volume(seed: int = 1):
    """Volume asymétrique : bruit + blobs + un « L » de repère sur chaque face."""
    from pixvox import FACES, Sprite, Volume, ramp
    v = Volume(16)
    v.noise(ramp("#7a7a7a", 5), cells=4, seed=seed)
    v.blobs(ramp("#3fd0c8", 5), count=4, seed=seed + 2, on_edges=2, on_corners=1)
    for i, f in enumerate(FACES):
        s = Sprite(16)
        s.rect(1, 1, 1, 6, ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"][i])
        s.rect(1, 6, 4, 6, "#ffffff")
        v.paint_face(f, s)
    return v


def diff(qa, qb, views=VIEWS, size: int = 200) -> int:
    """Pixels différents entre deux listes de quads, sous plusieurs angles (rendu sans ombrage)."""
    from pixvox.render import compare, fit_camera, render
    total = 0
    for view in views:
        cam = fit_camera(qa, view, size, size, jitter=JITTER)
        n, _ = compare(render(qa, cam, shading="flat"), render(qb, cam, shading="flat"))
        total += n
    return total


def cube_model_quads(faces: dict, textures: dict | None = None):
    """Quads du modèle vanilla minecraft:block/cube texturé par `faces` (relu comme le jeu)."""
    from pixvox import FACES
    from pixvox.mcmodel import ModelLoader
    loader = ModelLoader(extra_textures={f"t:block/{f}": faces[f] for f in FACES})
    tex = textures or {f: f"t:block/{f}" for f in FACES}
    return loader.quads({"parent": "minecraft:block/cube", "textures": tex})


def design_shape(res: int, scale: float = 1.0):
    """Petit objet décrit en unités de conception (corps, tête, anneau)."""
    from pixvox import Volume, ramp
    v = Volume.design((24, 32, 12), res=res, scale=scale)
    body = v.m_segment((12, 2, 6), (12, 26, 6), 6, 3) | v.m_sphere((12, 28, 6), 3.5)
    ring = v.m_torus((12, 30, 6), 4.5, 0.6, axis="y")
    v.set(body, "#b0a8a0")
    v.set(ring, "#d8b25a")
    v.shade(body, ramp("#b0a8a0", 5), ao=0.5)
    return v


def pillar_volume():
    """Colonne de 1,5 x 2,5 x 0,625 blocs (multibloc 2 x 3 x 1)."""
    from pixvox import Volume
    v = Volume(24, 40, 10)
    v.set(v.m_segment((12, 2, 5), (12, 36, 5), 6, 3), "#a0a0a0")
    return v


def animated_model():
    """Vasque animée (braises pulse lumineuses) + flammes fire() sur 4 plans."""
    from pixvox import Model, Volume, fire, pulse, ramp
    v = Volume(10, 6, 10)
    v.set(v.m_cylinder((5, 5), 4.6, 0, 3), "#555560")
    v.shade(v.solid, ramp("#555560", 5))
    hot = v.m_exposed("up") & v.m_noise(0.5, cells=2, seed=1, mask=v.m_exposed("up"))
    fr = pulse(v.frames(8), hot, ramp("#e05010", 5), seed=2)
    m = Model("anim_test", fr, frametime=3, emissive=hot, emission=11)
    m.add_cross(fire(16, frames=8, seed=1), center=(8, 8), y=3, width=9, height=12, planes=4, emission=15)
    return m
