"""Champignon luminescent : modèle voxel libre, exporté en éléments Minecraft optimisés + atlas."""
import numpy as np

from pixvox import Model, Props, Volume, ramp

STEM = ramp("#dccfae", n=4, spread=0.30, hue_shift=12)
CAP = ramp("#2db7ae", n=5, spread=0.46, hue_shift=24)
GILL = ramp("#20575c", n=3, spread=0.14)
SPOT = ramp("#c8fff0", n=2, spread=0.10)


def build():
    v = Volume(16, 13, 16)
    # pied : légèrement évasé à la base
    stem = v.m_cylinder((8, 8), 1.6, 0, 8) | v.m_cylinder((8, 8), 2.3, 0, 0) | v.m_cylinder((8, 8), 2.0, 1, 1)
    v.set(stem, STEM[2])
    # chapeau : dôme ellipsoïdal, dessous creusé (lamelles visibles par en dessous)
    cap = v.m_ellipsoid((8, 7.2, 8), (6.8, 5.6, 6.8)) & (v.Y >= 7)
    hollow = v.m_ellipsoid((8, 6.2, 8), (5.2, 2.0, 5.2)) & (v.Y >= 7) & ~v.m_cylinder((8, 8), 1.6, 0, 12)
    v.set(cap, CAP[2])
    v.clear(hollow)
    # ombrage 3D automatique (lumière en haut, côté nord-ouest)
    v.shade(stem, STEM, contrast=1.3, bias=0.3)
    v.shade(cap, CAP, contrast=1.1, bias=-0.35, noise=0.14, seed=3)
    under = cap & v.m_exposed("down")
    v.set(under, GILL[1])
    v.set(under & (((v.X + v.Z) % 2) == 0), GILL[0])                  # lamelles en damier très sombre
    v.shift_ramp(stem & (v.Y >= 7), STEM, -1)                          # pied dans l'ombre du chapeau
    # taches claires sur le dessus du chapeau
    rng = np.random.default_rng(7)
    top = cap & v.m_exposed("up")
    cand = np.argwhere(top & (v.Y >= 10))
    for i in rng.choice(len(cand), 7, replace=False):
        x, y, z = cand[i]
        v.data[x, y, z] = SPOT[1]
        dx, dz = rng.choice([(1, 0), (0, 1), (-1, 0), (0, -1)])
        if top[x + dx, y, z + dz]:
            v.data[x + dx, y, z + dz] = SPOT[0]
    m = Model("glowcap", v)
    m.props = Props(strength=0.0, sound="grass", light=10, tool=None, collision=False, particles="glow",
                    particle_at=(8, 10, 8), particle_rate=0.15,
                    names={"fr_fr": "Champignon lueur", "en_us": "Glowcap"})  # export mod
    return m
