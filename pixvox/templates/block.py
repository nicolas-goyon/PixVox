"""Bloc plein « __TITLE__ » (__NAME__), créé par `pixvox new`.

Un bloc est un VOLUME de 16 x 16 x 16 voxels : ses 6 textures sont lues sur la peau du volume, donc un
voxel d'arête a toujours la même couleur sur ses deux faces. Étapes suivantes :
    pixvox review __FILE__        # planche PNG + rapport : regarder avant de juger
    pixvox export __FILE__        # resource pack vérifié (0 pixel d'écart attendu)
"""
from pixvox import Block, Props, Volume, ramp

STONE = ramp("#7b7d83", n=4, spread=0.13, hue_shift=10)      # rampe sombre -> clair
ACCENT = ramp("#d0a040", n=5, spread=0.45, hue_shift=20)


def build():
    v = Volume(16)
    v.noise(STONE, cells=3, octaves=3, seed=1)                   # pierre : grandes masses + détail fin
    v.blobs(ACCENT, count=4, radius=(1.4, 2.2), seed=2, on_edges=1)   # inclusions, dont une sur une arête
    b = Block("__NAME__", v)
    b.props = Props(strength=1.5, sound="stone", tool="pickaxe",          # utilisé par `pixvox mod`
                    names={"fr_fr": "__TITLE__", "en_us": "__TITLE__"})
    return b
