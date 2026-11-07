"""Pierre moussue déclinée — famille de construction tirée du bloc plein (voir mossy_stone.py).

`bloc.variants()` donne la dalle, l'escalier, le mur, la barrière, le portillon, le bouton et la plaque de
pression, avec les textures du bloc plein. Chaque élément montre la peau du bloc plein à cet endroit,
dans la direction où il regarde : la dalle du bas montre le bas des côtés (pierre), la marche de
l'escalier le haut (coulures de mousse), et les raccords sont ceux du bloc plein. Les modèles sont écrits
déjà orientés : un escalier tourné vers l'est montre la face « est » du volume, qui diffère des autres.

Dans un mod (`pixvox mod`), ce sont de vrais blocs vanilla (SlabBlock, StairBlock, WallBlock…) : le mur
se raccorde aux autres murs, la barrière aux barrières, la dalle double donne deux dalles, et le
tailleur de pierre les tire du bloc plein.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))      # bloc plein : examples/mossy_stone.py
from mossy_stone import voxel  # noqa: E402


def build():
    return voxel().variants()
