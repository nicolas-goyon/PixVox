"""Bûche : cernes concentriques au cœur, écorce sur la peau latérale, rotation par axe (states='axis').

En voxels, l'écorce est la couche extérieure des 4 côtés : sur le dessus elle forme
naturellement l'anneau du bord, de la même couleur que le haut des faces latérales.
Le blockstate tourne le modèle entier : couchée, la bûche garde des arêtes cohérentes.
"""
import numpy as np

from pixvox import Block, Props, Volume, perlin, ramp

BARK = ramp("#5b4a3a", n=4, spread=0.24, hue_shift=12)
WOOD = ramp("#c8a877", n=4, spread=0.20, hue_shift=14)


def build():
    v = Volume(16)
    # cernes : distance à l'axe vertical, légèrement ondulée (bruit 3D périodique)
    wobble = perlin(v.shape, (3, 2, 3), seed=4, octaves=2)
    r = np.hypot(v.X + 0.5 - 8, v.Z + 0.5 - 8) + 0.9 * wobble
    lv = np.where(np.floor(r / 1.5) % 2 == 0, 2, 1)
    lv = np.where(r < 1.6, 0, lv)                                        # cœur sombre
    lv = np.where((r > 5.6) & (r < 6.6), 3, lv)                          # aubier clair sous l'écorce
    cols = np.array(WOOD, dtype=np.uint8)
    v.set(None, cols[lv])
    # écorce : couche extérieure des 4 côtés, sillons verticaux (bruit étiré le long de y)
    side = np.minimum.reduce([v.X, 15 - v.X, v.Z, 15 - v.Z]) == 0
    v.noise(BARK, cells=(6, 1, 6), octaves=2, seed=9, mask=side, weights=[2, 3, 3, 1])
    b = Block("ashen_log", v, states="axis", seamless="horizontal")
    b.props = Props(strength=2.0, sound="wood", tool="axe",
                    names={"fr_fr": "Bûche cendrée", "en_us": "Ashen Log"})  # export mod
    return b
