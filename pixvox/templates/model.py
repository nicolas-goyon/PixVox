"""Modèle à forme libre « __TITLE__ » (__NAME__), créé par `pixvox new`.

Un modèle est un volume de voxels quelconque (ici un champignon) exporté en éléments optimisés + atlas.
Il doit tenir dans [-16, 32] unités : au-delà d'un bloc et demi, utiliser un MultiBlock. Étapes suivantes :
    pixvox review __FILE__
    pixvox export __FILE__
"""
from pixvox import Model, Props, Volume, ramp

CAP = ramp("#c0503a", n=5, spread=0.40, hue_shift=18)
STEM = ramp("#d8cbb0", n=4, spread=0.25)


def build():
    v = Volume.design((16, 14, 16), res=16)          # unités de conception : 16 = un bloc (res=32 : plus fin)
    stem = v.m_cylinder((8, 8), 2.0, 0, 8)
    cap = v.m_ellipsoid((8, 8, 8), (6.5, 4.0, 6.5)) & (v.DY >= 7)
    v.set(stem, STEM[2])
    v.set(cap, CAP[2])
    v.shade(cap, CAP, light=(-0.4, 1.0, -0.3), ao=0.4)
    v.shade(stem, STEM, ao=0.6)
    m = Model("__NAME__", v)
    m.props = Props(strength=0.5, sound="wood", tool=None,             # cassé à la main, comme une plante
                    names={"fr_fr": "__TITLE__", "en_us": "__TITLE__"})
    return m
