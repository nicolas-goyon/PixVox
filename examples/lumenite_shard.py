"""Éclat de lumenite : item plat dessiné pixel par pixel en ASCII (contrôle total de chaque pixel).

Deux prismes parallèles à 45° qui sortent d'un éclat de roche. Lumière en haut à gauche (convention
vanilla) : facette gauche claire, facette droite sombre, arête vive « h » le long du grand cristal.
"""
from pixvox import Item, Props, Sprite, ramp

ORE = ramp("#3cc8bb", n=5, spread=0.48, hue_shift=22)        # même rampe que le minerai
STONE = ramp("#7c7c80", n=5, spread=0.30, hue_shift=10, tint=0.010)

ART = """
..............o.
.............owo
...........oohbo
..........ollbo.
.........ohlbmo.
........ohlbmo..
.......ohlbmoho.
......ohlbmohbo.
.....ollbmolbmo.
....ollbmolbmo..
...ollbmolbmo...
.oollbmolbmo....
o4llbmolbmo.....
o43322lbmo......
.o322111o.......
..oooooo........
"""

LEGEND = {
    "o": "#0b3336",                                  # contour : teinte froide très sombre, pas du noir
    "m": ORE[1], "b": ORE[2], "l": ORE[3], "h": ORE[4], "w": "#ffffff",
    "1": STONE[0], "2": STONE[1], "3": STONE[2], "4": STONE[3],
}


def build():
    it = Item("lumenite_shard", Sprite.from_ascii(ART, LEGEND))
    it.props = Props(names={"fr_fr": "Éclat de lumenite", "en_us": "Lumenite Shard"})  # export mod
    return it
