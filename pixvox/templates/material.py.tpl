"""Bloc « __TITLE__ » (__NAME__), créé par `pixvox new --material __MATERIAL__`.

La recette `__MATERIAL__` de pixvox.materials peint le volume en 3D : le bloc se raccorde sans couture à ses
voisins, et ses joints passent d'une face à l'autre par l'arête. Changer les réglages (couleur, graine,
tailles), puis :
    pixvox review __FILE__        # planche PNG + rapport : regarder avant de juger
    pixvox watch __FILE__ --html  # planche refaite à chaque sauvegarde
    pixvox export __FILE__        # resource pack vérifié (0 pixel d'écart attendu)
"""
from pixvox import Block, Props, Volume
from pixvox.materials import __MATERIAL__


def build():
    v = Volume(16)
    __CALL__
    b = Block("__NAME__", v__EXTRA__)
    b.props = Props(strength=__STRENGTH__, sound="__SOUND__", tool="__TOOL__",     # utilisé par `pixvox mod`
                    names={"fr_fr": "__TITLE__", "en_us": "__TITLE__"})
    return b
