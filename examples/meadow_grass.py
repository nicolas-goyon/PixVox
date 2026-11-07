"""Herbe de prairie — bloc d'herbe teinté par le biome (tint="grass").

La terre est colorée ; l'herbe est peinte en GRIS clair, car le jeu multiplie ces voxels par la couleur
du biome (vert franc en plaine, olive dans le marais, jaune dans le désert). `cap` pose la couche
d'herbe sur le dessus et la fait couler sur les côtés : les voxels qu'il a changés forment le masque
`tinted`. À l'export, le dessus (entièrement teinté) porte tintindex, et chaque côté reçoit une surcouche
qui ne contient que les coulures, comme le liseré de l'herbe vanilla. Quelques brins plus clairs et
plus sombres gardent du relief une fois teintés.
"""
import numpy as np

from pixvox import Block, Volume, ramp

DIRT = ramp("#7a5638", n=5, spread=0.22, hue_shift=8, tint=0.01)
GRASS = ramp("#b8b8b8", n=5, spread=0.34, hue_shift=0, tint=0)   # gris pur : la couleur vient du biome


def build():
    v = Volume(16)
    v.noise(DIRT, cells=4, octaves=2, seed=21)
    before = v.data.copy()
    v.cap(GRASS, depth=(1, 4), seed=5, cells=4)
    tinted = (v.data != before).any(axis=-1) & v.solid
    # brins : quelques voxels d'herbe plus clairs sur le dessus (toujours gris)
    rng = np.random.default_rng(8)
    top = np.zeros(v.shape, bool)
    top[:, 15, :] = rng.random((16, 16)) < 0.12
    v.data[top & tinted] = (214, 214, 214, 255)
    return Block("meadow_grass", v, tint="grass", tinted=tinted, seamless="horizontal")
