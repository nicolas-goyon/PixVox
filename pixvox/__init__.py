"""pixvox — atelier pixel-art / voxel-art pour Minecraft, piloté par code (humains, agents, logiciels).

Boucle de travail :
    1. décrire l'asset en Python (Volume / Sprite) ;
    2. review(asset) -> planche PNG + rapport texte ;
    3. regarder, lire, corriger ;
    4. export_pack([...]) -> resource pack Java vérifié par re-rendu ;
       export_mod([...]) -> mod Fabric / NeoForge.

Ligne de commande : `pixvox --help` (ou `python -m pixvox`) ; résultats --json : docs/cli.md.
"""
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


def review(asset, out_dir="out", show_report=True):
    """Planche de revue PNG + rapport texte (+ planche d'animation et GIF). Retourne (png, rapport)."""
    from .review import review as _review
    return _review(asset, out_dir, show_report)


def view(asset, yaw, pitch, size=600, shading="gui", path=None, out_dir="out", persp=0.0, tick=0):
    """Rendu à un angle libre (blocs, modèles, multiblocs, items extrudés).
    shading : 'gui' | 'world' | 'night' | 'flat' ; persp > 0 : perspective (1.5–3, conseillé par dessous) ;
    tick : instant d'une animation (20 ticks = 1 s)."""
    from .review import view as _view
    return _view(asset, yaw, pitch, size, shading, path, out_dir, persp, tick)


def animate(asset, out_dir="out"):
    """Planche des images d'une animation + GIF à la vitesse du jeu. Retourne (png, gif)."""
    from .review import anim_sheet
    return anim_sheet(asset, out_dir)


def compare(assets, path="out/compare.png", size=300):
    """Planche de variantes côte à côte."""
    from .review import compare_sheet
    return compare_sheet(assets, path, size)


def analyze(asset):
    """Liste de constats (Finding : level OK | INFO | WARN | ERR, topic, msg)."""
    from .analyze import analyze as _analyze
    return _analyze(asset)


def export_pack(assets, root="out/pack", namespace="pixvox", zip_path=None, replace=None,
                description="Créé avec pixvox", mc=None):
    """Écrit un resource pack Java et vérifie chaque asset par re-rendu.

    replace : dict {nom_asset: "minecraft:stone"} pour remplacer l'apparence d'un bloc/item vanilla
              sans propriétés (test immédiat en jeu sans mod).
    mc      : version de Minecraft visée, "1.21.4+" (défaut : 1.21.4 → 26.3) ou "1.21.1" (NeoForge 21.1 :
              models/item, lumière en neoforge_data, render_type ; les fichiers vérifiés sont ceux de 1.21.1).
    Lève ExportError si un asset est refusé (les autres sont exportés) ; renvoie les infos d'export
    (info["verify"]["diff_px"] == 0 : export fidèle).
    """
    from .export import ExportError, export_assets
    res = export_assets(assets, root, namespace, zip_path, replace, description, mc=mc)
    if res["refused"]:
        raise ExportError(f"{len(res['refused'])} asset(s) refusé(s), absents du pack : "
                          + " | ".join(m for _, m in res["refused"]))
    return res["infos"]


def export_mod(assets, out="out/mod", modid="pixvox_mod", name=None, **kw):
    """Projet de mod Minecraft 26.3 (loader="fabric" ou "neoforge") : vrais blocs (formes, lumière,
    particules, multiblocs posables). build=True compile le .jar (JDK 25). Voir pixvox.mod.export_mod."""
    from .mod import export_mod as _export_mod
    return _export_mod(assets, out, modid, name, **kw)


__all__ = ["Block", "Item", "Model", "MultiBlock", "Plane", "Props", "Anim", "Timing", "fire", "pulse",
           "flow", "FIRE", "SOUL_FIRE", "EMBER", "SOUL_EMBER", "Volume", "Sprite", "Ramp", "ramp",
           "ramp_between", "rgba", "hexa", "mix", "adjust", "lighten", "darken", "shade", "lightness",
           "luminance", "delta_e", "nearest", "perlin", "worley", "equalize", "FACES", "NORMALS",
           "FACE_AXES", "face_coords", "review", "view", "animate", "compare", "analyze", "export_pack",
           "export_mod"]
