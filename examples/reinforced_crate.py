"""Caisse renforcée : planches peintes face par face + cadre métallique sur les 12 arêtes.

Le cadre est posé dans le VOLUME : chaque voxel d'arête n'a qu'une couleur, vue de n'importe quelle face.
L'éclairage du cadre est pensé en 3D (arêtes du haut claires, du bas sombres) donc cohérent partout.
"""
import numpy as np

from pixvox import FACES, Block, Props, Sprite, Volume, equalize, perlin, ramp

WOOD = ramp("#9b6b3d", n=5, spread=0.30, hue_shift=14)
IRON = ramp("#5c626c", n=5, spread=0.44, hue_shift=10, tint=0.012)
BRASS = ramp("#b98a40", n=4, spread=0.34, hue_shift=18)


def planks(seed: int, joints=(8, 3, 6), shadow_top: bool = True) -> Sprite:
    """12x12 : 3 planches horizontales (3 px + 1 px de joint), fibres étirées le long de x."""
    grain = equalize(perlin((12, 12), (1, 5), seed=seed, octaves=2)).T          # (h, w) dans [0, 1]
    lv = np.full((12, 12), 2)
    lv[grain > 0.82] = 3                                                           # fibres claires, rares
    lv[grain < 0.18] = 1                                                           # fibres sombres, rares
    for b, r0 in enumerate((0, 4, 8)):
        lv[r0] += 1                                                                # arête haute de planche : +1
        lv[r0 + 2] -= 1                                                            # arête basse : -1
        lv[r0:r0 + 3, joints[b]] = 0                                               # about de planche
        lv[r0:r0 + 3, (joints[b] + 1) % 12] += 1                                   # lèvre éclairée après l'about
        lv[r0 + 3] = 0                                                             # joint sombre
    if shadow_top:
        lv[0] -= 1                                                                 # ombre portée du cadre
    return Sprite.from_levels(np.clip(lv, 0, len(WOOD) - 1), WOOD)


def build():
    v = Volume(16, fill=WOOD[2])
    for i, f in enumerate(FACES):
        sp = planks(seed=20 + i, joints=[(8, 3, 6), (5, 9, 2), (2, 7, 10)][i % 3], shadow_top=f not in ("up", "down"))
        if f in ("up", "down"):
            sp = sp.rot90()                                  # planches du couvercle perpendiculaires
        v.paint_face(f, sp, at=(2, 2))                       # intérieur 12x12 : ne touche aucune arête

    # distances (bord, arête, coin) de chaque voxel
    d = np.sort(np.stack([np.minimum(v.X, 15 - v.X), np.minimum(v.Y, 15 - v.Y), np.minimum(v.Z, 15 - v.Z)], -1), -1)
    face_d, edge_d, corner_d = d[..., 0], d[..., 1], d[..., 2]
    top, bottom = v.Y == 15, v.Y == 0

    frame = (face_d == 0) & (edge_d < 2)
    v.set(frame, IRON[2])
    v.set(frame & (edge_d == 0), IRON[3])                  # arête vive : éclat du métal
    v.set(frame & (edge_d == 0) & top, IRON[4])            # arêtes du haut : prennent la lumière
    v.set(frame & bottom, IRON[1])                         # barres du bas : dans l'ombre
    v.set(frame & (edge_d == 0) & bottom, IRON[2])
    v.set(frame & (edge_d == 1) & ~top & ~bottom & (v.Y == 14), IRON[1])   # ombre sous la barre haute

    bracket = (face_d == 0) & (corner_d < 4)
    v.set(bracket, BRASS[1])
    v.set(bracket & (edge_d == 0), BRASS[2])
    v.set(bracket & (edge_d == 0) & top, BRASS[3])
    rivet = (face_d == 0) & (edge_d == 2) & (corner_d == 2)
    v.set(rivet, BRASS[3])
    b = Block("reinforced_crate", v, seamless=False)
    b.props = Props(strength=2.5, sound="wood", tool="axe",
                    names={"fr_fr": "Caisse renforcée", "en_us": "Reinforced Crate"})  # export mod
    return b
