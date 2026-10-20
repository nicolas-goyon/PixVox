"""Pierre moussue — démonstration avant / après sur l'erreur des arêtes à deux couleurs.

1. mossy_stone_naive : dessiné « à l'ancienne », une texture par face (dessus, côté, dessous).
   La rangée du haut de la texture de côté et le bord de la texture du dessus sont dessinés
   séparément : le même mini-cube d'arête a deux couleurs. L'analyse les compte et les marque.
2. mossy_stone_fixed : mêmes textures, unifiées par l'outil (fix=True).
3. mossy_stone : version voxel. La mousse a une épaisseur qui varie en (x, z) : elle déborde
   sur les côtés en coulures qui se suivent d'une face à l'autre, y compris dans les coins.
"""
import numpy as np

from pixvox import Block, Sprite, Volume, equalize, perlin, ramp

STONE = ramp("#7d7d82", n=4, spread=0.16, hue_shift=10, tint=0.010)
MOSS = ramp("#5f8f3a", n=5, spread=0.34, hue_shift=20)


def naive() -> Block:
    top = Sprite(16).noise(MOSS, cells=4, seed=5)
    side = Sprite(16).noise(STONE, cells=4, seed=6)
    depth = 1 + np.floor(equalize(perlin((16,), 4, seed=7)) * 3.999).astype(int)     # 1..4 par colonne
    for u in range(16):
        for v in range(depth[u]):
            side[u, v] = MOSS[3 if v == 0 else 2]
        side[u, depth[u] - 1] = MOSS[1]                                                # bas de la coulure
    bottom = Sprite(16).noise(STONE, cells=4, seed=8)
    return Block.from_textures("mossy_stone_naive", side=side, top=top, bottom=bottom, seamless="horizontal")


def fixed() -> Block:
    b = naive()
    return Block.from_faces("mossy_stone_fixed", b.faces(), fix=True, seamless="horizontal")


def voxel() -> Block:
    v = Volume(16)
    v.noise(STONE, cells=4, octaves=2, seed=11)
    v.cap(MOSS, depth=(1, 4), seed=3, cells=4)          # épaisseur variable en (x, z) -> coulures cohérentes
    return Block("mossy_stone", v, seamless="horizontal")


def build():
    return [naive(), fixed(), voxel()]
