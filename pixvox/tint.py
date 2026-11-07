"""pixvox.tint — teinte de biome (herbe, feuillages, eau), comme `tintindex` dans Minecraft (#23).

Le jeu multiplie la texture d'une face qui porte `tintindex` par la couleur du biome où le bloc est posé.
Les voxels teintés se peignent donc en niveaux de gris (le clair donne la couleur du biome, le sombre
l'assombrit), comme les textures vanilla d'herbe et de feuilles. Marquer les voxels teintés d'un Block ou
d'un Model : `tint="grass" | "foliage" | "water"` et `tinted=masque` (tout le volume si absent).

Les colormaps vanilla (`grass.png`, `foliage.png`) appartiennent à Mojang et ne sont pas versées dans le
dépôt : pixvox utilise les couleurs de référence ci-dessous (celles du wiki Minecraft pour chaque biome,
relevées sur les colormaps aux température et humidité du biome ; le marais tire sa couleur d'un bruit,
c'est sa valeur la plus fréquente). Elles servent au rendu, aux planches et à la vérification ; en jeu,
la couleur vient toujours du biome réel (mod, ou bloc vanilla teinté remplacé par --replace).
"""
from __future__ import annotations

import numpy as np

from .color import rgba

__all__ = ["TINTS", "BIOMES", "tint_color", "apply_tint"]

TINTS = ("grass", "foliage", "water")
BIOMES = {   # biome : (herbe, feuillages, eau)
    "plains": ("#91bd59", "#77ab2f", "#3f76e4"),
    "forest": ("#79c05a", "#59ae30", "#3f76e4"),
    "jungle": ("#59c93c", "#30bb0b", "#3f76e4"),
    "swamp": ("#6a7039", "#6a7039", "#617b64"),
    "taiga": ("#86b783", "#68a464", "#287082"),
    "snowy_plains": ("#80b497", "#60a17b", "#3d57d6"),
    "desert": ("#bfb755", "#aea42a", "#32a598"),
    "badlands": ("#90814d", "#9e814d", "#3f76e4"),
}
DEFAULT_BIOME = "plains"
REVIEW_BIOMES = ("plains", "swamp", "desert")       # planche : trois climats contrastés

VANILLA_HINT = {
    "grass": "en jeu : mod (couleur enregistrée), ou --replace sur minecraft:grass_block",
    "foliage": "en jeu : mod (couleur enregistrée), ou --replace sur minecraft:oak_leaves",
    "water": "en jeu : mod (couleur enregistrée), ou --replace sur minecraft:water_cauldron",
}
# Teinte des objets (inventaire, main), indépendante du biome : celle des objets vanilla (bloc d'herbe :
# colormap à température 0,5 et humidité 1 ; feuilles de chêne : 0x48B518 ; eau : couleur de la plaine).
ITEM_TINTS = {
    "grass": {"type": "minecraft:grass", "temperature": 0.5, "downfall": 1.0},
    "foliage": {"type": "minecraft:constant", "value": -12012264},
    "water": {"type": "minecraft:constant", "value": -12618012},
}


def check_tint(tint: str | None, tinted, volume):
    """(tint, masque) validés : masque booléen de la forme du volume (tout le volume si absent)."""
    if tint is None:
        if tinted is not None:
            raise ValueError("tinted donné sans tint : préciser tint='grass', 'foliage' ou 'water'")
        return None, None
    if tint not in TINTS:
        raise ValueError(f"tint={tint!r} inconnu ; choix : {', '.join(TINTS)}")
    if tinted is None:
        return tint, volume.solid.copy()
    m = np.asarray(tinted)
    if m.dtype != bool or m.shape != volume.shape:
        raise ValueError(f"tinted : masque booléen de forme {volume.shape} attendu (reçu {m.dtype} {m.shape})")
    m = m & volume.solid
    return (tint, m) if m.any() else (None, None)


def tint_color(tint: str, biome: str = DEFAULT_BIOME) -> tuple:
    """(r, g, b) de la teinte `tint` dans le biome (couleurs de référence, voir le module)."""
    if biome not in BIOMES:
        raise ValueError(f"biome {biome!r} inconnu ; choix : {', '.join(BIOMES)}")
    return tuple(int(c) for c in rgba(BIOMES[biome][TINTS.index(tint)])[:3])


def apply_tint(data: np.ndarray, color, mask: np.ndarray | None = None) -> np.ndarray:
    """Couleurs × teinte, comme le jeu (texture × couleur / 255, arrondi) ; alpha inchangé. `mask` : seuls
    ces pixels / voxels (tous si None). Utilisé par le rendu de référence ET par le lecteur de modèles."""
    out = np.array(data, np.uint8, copy=True)
    c = np.asarray(color[:3], np.uint32)
    sel = np.ones(out.shape[:-1], bool) if mask is None else np.asarray(mask, bool)
    rgb = out[..., :3].astype(np.uint32)
    tinted = ((rgb * c + 127) // 255).astype(np.uint8)
    out[..., :3] = np.where(sel[..., None], tinted, out[..., :3])
    return out
