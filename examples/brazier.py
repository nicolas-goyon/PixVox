"""Brasero en fer forgé : vasque sur quatre pieds, braises qui palpitent, flammes animées.

- La vasque, les pieds et les braises sont des voxels (16 par bloc) : un seul volume, décrit une fois.
- Les braises sont animées (16 images, pulse) et lumineuses (light_emission) : elles rougeoient la nuit.
- Les flammes sont quatre plans croisés (un X comme le feu de camp vanilla + une croix droite, avec
  deux animations différentes pour éviter l'effet « copie ») portant des textures animées 16x16
  générées par fire() ; ils sont pleinement lumineux (light_emission 15).
Variante « soul » : feu bleu des âmes, braises froides.
"""
import numpy as np

from pixvox import EMBER, FIRE, SOUL_EMBER, SOUL_FIRE, Model, Props, Volume, fire, pulse, ramp

IRON = ramp("#36353b", n=5, spread=0.26, hue_shift=12, tint=0.01)        # fer forgé sombre, un peu bleuté
CHAR = ramp("#2c2624", n=4, spread=0.14, hue_shift=6)                     # charbon éteint
LIGHT = (-0.5, 1.0, -0.35)
FRAMES = 16


def brazier_volume(res: int = 16):
    v = Volume.design((16, 11, 16), res=res)
    cx, cz = 8.0, 8.0
    r = np.hypot(v.DX - cx, v.DZ - cz)
    # --- vasque : paroi évasée de y=5 à y=10, fond plein, lèvre en tore
    y = v.DY
    outer = 3.9 + (y - 5.0) * 0.68                     # rayon extérieur : 3,9 au fond -> 7,3 au bord
    wall = (y >= 5) & (y < 10) & (r <= outer) & (r >= outer - 1.25)
    floor = (y >= 5) & (y < 6.2) & (r <= outer)
    lip = v.m_torus((cx, 10.0, cz), 6.9, 0.85, axis="y")
    bowl = wall | floor | lip
    # --- pieds : quatre jambes galbées aux diagonales, patins au sol
    legs = np.zeros(v.shape, bool)
    for a in (45, 135, 225, 315):
        ca, sa = np.cos(np.radians(a)), np.sin(np.radians(a))
        p = lambda d, h, ca=ca, sa=sa: (cx + d * ca, h, cz + d * sa)   # noqa: E731 (point à distance d de l'axe)
        legs |= v.m_tube([p(3.6, 6.0), p(5.2, 3.6), p(5.6, 1.4), p(6.2, 0.5)], [0.95, 0.85, 0.8, 0.8])
        legs |= v.m_ellipsoid(p(6.2, 0.5), (1.3, 0.55, 1.3))
    stem = v.m_cylinder((cx, cz), 1.6, 3, 5)              # moyeu sous la vasque
    iron = bowl | legs | stem
    # --- braises : tas bombé dans la vasque
    heap = v.m_ellipsoid((cx, 7.6, cz), (6.0, 2.6, 6.0)) & (y >= 6.2) & (r < outer - 1.2) & (y < 9.6)
    v.set(iron, IRON[2])
    v.set(heap, CHAR[1])
    v.shade(iron, IRON, light=LIGHT, contrast=1.2, bias=0.1, noise=0.08, seed=3, ao=0.6)
    v.shade(heap, CHAR, light=LIGHT, contrast=0.9, noise=0.35, seed=4)
    rivets = bowl & v.m_exposed("north") & (np.abs(y - 8.0) < 0.6) & (np.abs(v.DX - cx) < 0.6)
    rivets |= bowl & v.m_exposed("south") & (np.abs(y - 8.0) < 0.6) & (np.abs(v.DX - cx) < 0.6)
    rivets |= bowl & (v.m_exposed("west") | v.m_exposed("east")) & (np.abs(y - 8.0) < 0.6) & (np.abs(v.DZ - cz) < 0.6)
    v.set(rivets, IRON[4])
    top = heap & v.m_exposed("up")
    embers = top & v.m_noise(0.55, cells=4, seed=11, mask=top)          # ~45 % du dessus rougeoie
    return v, embers


def build_brazier(name="brazier", fire_ramp=FIRE, ember_ramp=EMBER, seed=1, soul=False):
    v, embers = brazier_volume()
    frames = v.frames(FRAMES)
    pulse(frames, embers, ember_ramp, seed=5, speed=1, amplitude=0.55, variation=0.5, bias=0.08)
    m = Model(name, frames, frametime=2, emissive=embers, emission=12,
              inventory_scale=0.82, inventory_center=True)
    big = fire(16, frames=FRAMES, seed=seed, palette=fire_ramp)
    small = fire(16, frames=FRAMES, seed=seed + 6, palette=fire_ramp)
    # pied des flammes dans les braises (y = 8) : assez étroit pour rester dans la vasque évasée
    m.add_cross(big, center=(8, 8), y=8, width=12.5, height=15.5, planes=2, emission=15)            # X
    m.add_cross(small, center=(8, 8), y=8, width=10.5, height=14, planes=2, angle=0, emission=15)   # +
    # comportement en jeu (export mod) : métal, éclaire comme une lanterne, flammes et fumée
    m.props = Props(strength=3.5, sound="lantern", light=10 if soul else 15, tool="pickaxe",
                    particles="soul" if soul else "flame", particle_at=(8, 12, 8), particle_rate=0.5,
                    names={"fr_fr": "Brasero des âmes" if soul else "Brasero",
                           "en_us": "Soul Brazier" if soul else "Brazier"})
    return m


def build():
    return [build_brazier(),
            build_brazier("soul_brazier", SOUL_FIRE, SOUL_EMBER, seed=3, soul=True)]
