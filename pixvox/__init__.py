"""pixvox — atelier pixel-art / voxel-art pour Minecraft, piloté par code (humains, agents, logiciels)."""
from .anim import EMBER, FIRE, SOUL_EMBER, SOUL_FIRE, Anim, Timing, fire, flow, pulse
from .assets import Block, Item, Model, MultiBlock, Plane, Props
from .color import (
    Ramp,
    adjust,
    darken,
    delta_e,
    hexa,
    lighten,
    lightness,
    luminance,
    mix,
    nearest,
    ramp,
    ramp_between,
    rgba,
    shade,
)
from .noise import equalize, perlin, worley
from .sprite import Sprite
from .volume import FACE_AXES, FACES, NORMALS, Volume, face_coords

__version__ = "0.1.0"


def export_pack(assets, root="out/pack", namespace="pixvox", zip_path=None, replace=None,
                description="Créé avec pixvox"):
    """Écrit un resource pack Java et vérifie chaque asset par re-rendu.

    replace : dict {nom_asset: "minecraft:stone"} pour remplacer l'apparence d'un bloc/item vanilla
              sans propriétés (test immédiat en jeu sans mod).
    Lève ExportError si un asset est refusé (les autres sont exportés) ; renvoie les infos d'export
    (info["verify"]["diff_px"] == 0 : export fidèle).
    """
    from .export import ExportError, export_assets
    res = export_assets(assets, root, namespace, zip_path, replace, description)
    if res["refused"]:
        raise ExportError(f"{len(res['refused'])} asset(s) refusé(s), absents du pack : "
                          + " | ".join(m for _, m in res["refused"]))
    return res["infos"]


__all__ = ["Block", "Item", "Model", "MultiBlock", "Plane", "Props", "Anim", "Timing", "fire", "pulse",
           "flow", "FIRE", "SOUL_FIRE", "EMBER", "SOUL_EMBER", "Volume", "Sprite", "Ramp", "ramp",
           "ramp_between", "rgba", "hexa", "mix", "adjust", "lighten", "darken", "shade", "lightness",
           "luminance", "delta_e", "nearest", "perlin", "worley", "equalize", "FACES", "NORMALS",
           "FACE_AXES", "face_coords", "export_pack"]
