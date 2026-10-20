"""Objet de plusieurs blocs « __TITLE__ » (__NAME__), créé par `pixvox new`.

Un MultiBlock n'a pas de limite de taille : il est découpé en parties d'un bloc (atlas partagé, miniature
d'inventaire). Sans mod, un datapack le pose ; avec `pixvox mod`, c'est un vrai bloc posé d'un coup.
    pixvox review __FILE__
    pixvox export __FILE__
"""
from pixvox import MultiBlock, Props, Volume, ramp

STONE = ramp("#a8a29a", n=5, spread=0.30, hue_shift=8)
GOLD = ramp("#d8b25a", n=4, spread=0.35, hue_shift=16)


def build():
    v = Volume.design((16, 32, 16), res=16)          # 1 x 2 x 1 blocs ; res=32 pour plus de finesse
    shaft = v.m_cylinder((8, 8), 4.5, 3, 28)
    base = v.m_cuboid((2, 0, 2), (14, 3, 14))
    top = v.m_cuboid((3, 28, 3), (13, 31, 13))
    ring = v.m_torus((8, 20, 8), 5.0, 1.0, axis="y")
    stone = shaft | base | top
    v.set(stone, STONE[2])
    v.shade(stone, STONE, light=(-0.4, 1.0, -0.3), ao=0.6)
    v.set(ring, GOLD[2])
    v.shade(ring, GOLD, light=(-0.4, 1.0, -0.3))
    mb = MultiBlock("__NAME__", v)
    mb.props = Props(strength=2.0, sound="stone", tool="pickaxe",
                     names={"fr_fr": "__TITLE__", "en_us": "__TITLE__"})
    return mb
