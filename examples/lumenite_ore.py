"""Minerai de lumenite : pierre + amas de cristaux 3D qui s'enroulent autour des arêtes.

La pierre au contact des cristaux est teintée de leur couleur (lueur), un amas est posé à cheval
sur une arête : il apparaît sur deux faces avec exactement les mêmes voxels. Les cristaux sont
lumineux (emissive) : ils restent visibles dans une grotte sombre, comme un minerai « émissif ».
"""
from pixvox import Block, Props, Volume, ramp

STONE = ramp("#7b7d83", n=4, spread=0.13, hue_shift=10, tint=0.003)
ORE = ramp("#3cc8bb", n=5, spread=0.48, hue_shift=22)


def build():
    v = Volume(16)
    v.noise(STONE, cells=3, octaves=3, seed=11)                    # pierre : grandes masses + détail fin
    ore = v.blobs(ORE, count=5, radius=(1.5, 2.3), seed=4, on_edges=1,
                  light=(-0.4, 1.0, -0.3))                          # cristaux, dont un à cheval sur une arête
    glow = v.m_dilate(ore, wrap=True) & ~ore                        # la pierre qui touche un cristal...
    v.tint(glow, ORE[1], 0.3)                                       # ...prend un reflet teal (lueur)
    b = Block("lumenite_ore", v, emissive=ore, emission=11)       # cristaux visibles dans le noir
    b.props = Props(strength=3.0, sound="stone", light=4, tool="pickaxe", tier="iron", requires_tool=True,
                    names={"fr_fr": "Minerai de lumenite", "en_us": "Lumenite Ore"})  # export mod
    return b
