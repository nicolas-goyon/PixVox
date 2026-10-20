"""Statue d'ange, décrite UNE fois en unités de conception, puis voxelisée à la demande.

L'espace de conception fait 48 x 56 x 16 unités (16 unités = 1 bloc à l'échelle 1) :
  - angel_volume(res=16)              -> 3 x 3,5 x 1 blocs, 16 voxels par bloc (vanilla)
  - angel_volume(res=32)              -> même taille, deux fois plus fin (HD)
  - angel_volume(res=16, scale=16/56) -> figurine qui tient dans un seul bloc
Sculptée avec des primitives continues (cônes, capsules, ellipsoïdes inclinés, tore), modelée par la
lumière 3D (shade + occlusion), puis découpée automatiquement en parties d'un bloc à l'export.
Face avant = NORD (z = 0). Les ailes sont à l'arrière (z ≈ 10–15).
"""
import numpy as np

from pixvox import Model, MultiBlock, Props, Volume, ramp

MARBLE = ramp("#d2cec5", n=6, spread=0.40, hue_shift=8, tint=0.006)
PLINTH = ramp("#8f8b85", n=5, spread=0.30, hue_shift=8, tint=0.006)
GOLD = ramp("#d8b25a", n=4, spread=0.34, hue_shift=16, dark_chroma=0.1)
MOSS = ramp("#5f8a3a", n=4, spread=0.28, hue_shift=10)
LIGHT = (-0.55, 1.0, -0.35)          # lumière d'en haut, un peu de l'ouest et de l'avant
WING_ROLL = 26.0
EXTENT = (48, 56, 16)                # espace de conception (unités)


def wing(v: Volume, side: int):
    """Aile : deux ellipsoïdes inclinés (grandes rémiges + pointe basse). side = +1 est, -1 ouest."""
    main = v.m_ellipsoid((24 + side * 11.5, 38.5, 12.4), (9.2, 14.0, 2.1), rotation=(0, 0, -WING_ROLL * side))
    low = v.m_ellipsoid((24 + side * 13.5, 27.0, 12.8), (6.0, 10.5, 1.7), rotation=(0, 0, -12 * side))
    root = v.m_segment((24 + side * 3, 35, 11.5), (24 + side * 9, 41, 12.2), 2.2, 1.6)
    return main | low | root


def feathers(v: Volume, side: int):
    """Écailles de plumes dans le repère incliné de l'aile : (bord sombre, reflet), en unités de conception."""
    a = np.radians(-WING_ROLL * side)
    dx, dy = v.DX - (24 + side * 11.5), v.DY - 38.5
    u = -dx * np.sin(a) + dy * np.cos(a)            # le long de l'aile (vers le haut)
    w = (dx * np.cos(a) + dy * np.sin(a)) * side    # en travers (vers l'extérieur)
    row = np.floor(u / 3.2)
    off = 1.7 * (row % 2)
    cell = np.floor((w + off) / 3.4)
    du = u - row * 3.2                              # 0 en bas de la rangée
    dw = (w + off) - cell * 3.4 - 1.7               # -1.7..1.7 dans la plume
    k = 1.0 / v.vpu                                 # épaisseur des traits : un voxel, quelle que soit la résolution
    edge = du < 0.75 * k + 0.22 * dw ** 2
    glint = (~edge) & (du < 1.75 * k + 0.22 * dw ** 2)
    return edge, glint


def angel_volume(res: int = 16, scale: float = 1.0) -> Volume:
    v = Volume.design(EXTENT, res=res, scale=scale)
    # --- socle
    plinth = v.m_box(12, 0, 1, 35, 1, 14) | v.m_box(13, 2, 2, 34, 5, 13) | v.m_box(14, 6, 3, 33, 6, 12)
    # --- corps
    robe = v.m_segment((24, 7, 8), (24, 27, 8), 7.2, 4.5) | v.m_segment((24, 7, 8), (24, 9.5, 8), 7.6, 7.4)
    torso = v.m_segment((24, 26, 8), (24, 37, 8.3), 4.7, 5.3) | v.m_segment((19, 36.5, 8.4), (29, 36.5, 8.4), 2.5)
    neck = v.m_segment((24, 38, 8.3), (24, 41, 8.0), 1.7)
    head = v.m_sphere((24, 44.2, 7.8), 3.7)
    hair = v.m_ellipsoid((24, 45.3, 8.8), (4.0, 3.7, 3.7)) & ~((v.DZ < 7.0) & (v.DY < 46.2))
    arms = (v.m_segment((19.6, 36.3, 8.4), (18.6, 30.6, 6.3), 1.6) | v.m_segment((18.6, 30.6, 6.3), (23.3, 34.2, 3.3), 1.4)
            | v.m_segment((28.4, 36.3, 8.4), (29.4, 30.6, 6.3), 1.6) | v.m_segment((29.4, 30.6, 6.3), (24.7, 34.2, 3.3), 1.4))
    hands = v.m_ellipsoid((24, 35.4, 3.0), (1.3, 2.5, 1.3))
    wings = wing(v, +1) | wing(v, -1)
    halo = v.m_torus((24, 50.6, 8.4), 4.3, 0.8, axis="y")
    halo |= v.m_segment((24, 46.0, 11.0), (24, 50.6, 12.5), 1.0)        # tige de fixation (derrière la tête)

    statue = robe | torso | neck | head | hair | arms | hands | wings
    v.set(plinth, PLINTH[2])
    v.set(statue, MARBLE[3])
    v.set(halo, GOLD[2])

    # --- modelé par la lumière (normales 3D automatiques, cohérentes sous tous les angles)
    v.shade(plinth, PLINTH, light=LIGHT, contrast=1.1, bias=0.0, noise=0.10, seed=2)
    v.shade(statue, MARBLE, light=LIGHT, contrast=1.25, bias=-0.15, noise=0.06, seed=5, ao=0.7)
    v.shade(halo, GOLD, light=LIGHT, contrast=1.3, bias=0.3)

    # --- détails sculptés (en unités de conception : identiques à toute résolution)
    ang = np.arctan2(v.DZ - 8, v.DX - 24)
    folds = robe & ~torso & (np.cos(ang * 9) > 0.80) & (v.DY >= 9)          # plis verticaux de la robe
    v.shift_ramp(folds, MARBLE, -1)
    hem = robe & (v.DY < 9) & v.m_exposed("down")
    belt = robe & (v.DY >= 26) & (v.DY < 27)
    v.shift_ramp(hem | belt, MARBLE, -1)
    for side in (+1, -1):                                                   # plumes, au-delà de l'épaule
        wmask = wing(v, side) & ~torso & ((v.DX - 24) * side > 5)
        edge, glint = feathers(v, side)
        v.shift_ramp(wmask & edge, MARBLE, -1)
        v.shift_ramp(wmask & glint, MARBLE, +1)
    eyes = head & v.m_exposed("north") & (v.DY >= 44) & (v.DY < 45) & (((v.DX >= 22) & (v.DX < 24)) |
                                                                          ((v.DX >= 25) & (v.DX < 27)))
    v.shift_ramp(eyes, MARBLE, -3)                                          # yeux clos
    moss = plinth & (v.m_exposed("up") | v.m_exposed("north")) & v.m_noise(0.72, cells=4, seed=8)
    v.noise(MOSS, cells=4, seed=9, mask=moss)
    return v


def build():
    out = [
        MultiBlock("angel_statue", angel_volume(res=16)),                      # 3 x 3,5 x 1 blocs, vanilla
        MultiBlock("angel_statue_hd", angel_volume(res=32)),                   # même taille, 2x plus fin
        Model("angel_figurine", angel_volume(res=16, scale=16 / 56), states="facing"),   # tient dans un bloc
    ]
    names = ({"fr_fr": "Statue d'ange", "en_us": "Angel Statue"},
             {"fr_fr": "Statue d'ange (fine)", "en_us": "Angel Statue (fine)"},
             {"fr_fr": "Figurine d'ange", "en_us": "Angel Figurine"})
    for a, n in zip(out, names):                                               # export mod : marbre
        a.props = Props(strength=2.0, sound="calcite", tool="pickaxe", names=n)
    return out
