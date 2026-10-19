"""Lanterne de cuivre : cage en cuivre patiné autour d'un cœur lumineux (modèle libre d'un bloc).

- Le cœur est un volume plein lumineux (emissive, emission 15) vu entre les montants : pas besoin de
  transparence, les ouvertures de la cage suffisent.
- La patine vert-de-gris suit un bruit 3D périodique et se dépose surtout sur le dessus des surfaces.
- Props : lumière 15 comme une lanterne vanilla, son « copper », à la pioche.
"""
from pixvox import Model, Props, Volume, ramp

COPPER = ramp("#b8673b", n=5, spread=0.32, hue_shift=14)
PATINA = ramp("#5fa58a", n=4, spread=0.25, hue_shift=-8)
GLOW = ramp("#ffc864", n=4, spread=0.22, hue_shift=18)
LIGHT = (-0.45, 1.0, -0.3)


def build():
    v = Volume.design((16, 16, 16), res=16)
    base = v.m_cuboid((3.5, 0, 3.5), (12.5, 1.5, 12.5)) | v.m_cuboid((4.5, 1.5, 4.5), (11.5, 2.5, 11.5))
    cap = v.m_cuboid((4.5, 10.5, 4.5), (11.5, 11.5, 11.5)) | v.m_cuboid((5.5, 11.5, 5.5), (10.5, 12.5, 10.5))
    posts = v.m_cuboid((4.5, 2.5, 4.5), (5.5, 10.5, 5.5)) | v.m_cuboid((10.5, 2.5, 4.5), (11.5, 10.5, 5.5)) | \
        v.m_cuboid((4.5, 2.5, 10.5), (5.5, 10.5, 11.5)) | v.m_cuboid((10.5, 2.5, 10.5), (11.5, 10.5, 11.5))
    band = (v.m_cuboid((4.5, 6, 4.5), (11.5, 7, 11.5)) & ~v.m_cuboid((5.5, 6, 5.5), (10.5, 7, 10.5)))
    handle = (v.m_cuboid((6.5, 12.5, 7.5), (7.5, 14.5, 8.5)) | v.m_cuboid((8.5, 12.5, 7.5), (9.5, 14.5, 8.5))
              | v.m_cuboid((6.5, 14.5, 7.5), (9.5, 15.5, 8.5)))                  # anneau posé sur le chapeau
    frame = base | cap | posts | band | handle
    core = v.m_cuboid((6, 2.5, 6), (10, 10.5, 10))
    v.set(frame, COPPER[2])
    v.shade(frame, COPPER, light=LIGHT, contrast=1.15, bias=0.05, noise=0.12, seed=3, ao=0.5)
    top = frame & v.m_exposed("up")
    patina = (frame & v.m_noise(0.78, cells=3, seed=9, mask=frame)) | (top & v.m_noise(0.62, cells=4, seed=4, mask=top))
    v.set(patina, PATINA[1])
    v.shade(patina, PATINA, light=LIGHT, noise=0.2, seed=5)
    v.set(core, GLOW[2])
    v.shade(core, GLOW, light=(0, 1, 0), contrast=0.6, bias=0.25, noise=0.25, seed=7)
    m = Model("copper_lantern", v, emissive=core, emission=15, inventory_scale=1.15, inventory_center=True)
    m.props = Props(strength=3.5, sound="copper", light=15, tool="pickaxe",
                    names={"fr_fr": "Lanterne de cuivre", "en_us": "Copper Lantern"})
    return m
