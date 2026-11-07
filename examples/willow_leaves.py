"""Feuilles de saule — feuillage entièrement teinté par le biome (tint="foliage"), avec des trous.

Tout le volume est teinté (pas de masque) : les feuilles sont peintes en niveaux de gris et prennent la
couleur des feuillages du biome. Les trous viennent d'un bruit 3D périodique seuillé : comme ils sont
creusés dans le volume, ils se suivent d'une face à l'autre et d'un bloc au voisin (raccords sans
couture), et le rendu devient « cutout » (pixels 100 % transparents). Des grappes plus claires imitent
les feuilles tournées vers la lumière.
"""

from pixvox import Block, Volume, equalize, perlin, ramp

LEAF = ramp("#a8a8a8", n=4, spread=0.24, hue_shift=0, tint=0)   # gris pur : la couleur vient du biome
LIGHT = ramp("#d0d0d0", n=3, spread=0.16, hue_shift=0, tint=0)


def build():
    v = Volume(16)
    v.noise(LEAF, cells=4, octaves=1, seed=31)
    v.blobs(LIGHT, count=5, seed=32)
    holes = equalize(perlin((16, 16, 16), 4, seed=33, octaves=2)) < 0.13
    v.data[holes] = 0
    return Block("willow_leaves", v, tint="foliage")
