"""Matériaux de construction — une recette de pixvox.materials par bloc (voir la planche docs/images/materiaux.png).

Chaque recette peint le volume en 3D avec des motifs dont la période divise 16 et du bruit périodique :
les blocs se raccordent sans couture, et un joint de mortier ou un about de planche passe d'une face à
l'autre par l'arête. Pour partir d'une recette : `pixvox new mon_bloc --kind block --material bricks`.
"""
from pixvox import Block, Props, Volume
from pixvox.materials import bricks, cut_stone, metal, ore, planks


def build():
    out = []
    out.append(Block("oak_boards", planks(Volume(16), wood="oak", seed=1)))
    out.append(Block("red_bricks", bricks(Volume(16), color="#965040", seed=2)))
    out.append(Block("cut_stone_blocks", cut_stone(Volume(16), color="#8f8f8f", seed=3)))
    v = Volume(16)
    glow = ore(v, crystal="#e0a030", seed=4)
    out.append(Block("amber_ore", v, emissive=glow, emission=6))
    out.append(Block("iron_plates", metal(Volume(16), color="#a3a8b0", seed=5)))
    out.append(Block("weathered_copper_plates", metal(Volume(16), color="#c1734b", patina=0.45, seed=6)))
    for b, sound, tool in zip(out, ("wood", "stone", "stone", "stone", "metal", "copper"),
                              ("axe", "pickaxe", "pickaxe", "pickaxe", "pickaxe", "pickaxe")):
        b.props = Props(sound=sound, tool=tool, strength=2.0 if sound == "wood" else 3.0)
    return out
