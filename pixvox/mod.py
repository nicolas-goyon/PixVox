"""pixvox.mod — export en MOD Fabric ou NeoForge (Minecraft 26.3), ou NeoForge 1.21.1 (mc="1.21.1") : de
vrais blocs, pas seulement des apparences.

export_mod(assets, "out/mod", modid="mon_mod") écrit un projet Gradle complet :
  - les ressources (modèles, textures animées, blockstates, définitions d'items) — les mêmes que le
    resource pack, vérifiées pareil — dans src/main/resources/assets/<modid>/ ;
  - le code Java qui enregistre chaque asset :
      Block (cube)   -> bloc plein (états 'axis' / 'facing' gérés) ;
      Model          -> bloc à forme libre : contour et collision calculés depuis les voxels, lumière,
                        particules (flammes, fumée…), orientation 'facing' / 'axis' ;
      MultiBlock     -> UN bloc à plusieurs parties (propriétés facing + part) : posé d'un coup si la
                        place est libre, détruit d'un coup, lâche un seul objet ;
      Item           -> item simple ;
  - les données : tables de butin (format 26.3), tags d'outil (pioche, hache…), noms (en_us, fr_fr),
    un onglet créatif ;
  - fabric.mod.json, build.gradle, Gradle wrapper. `./gradlew build` (JDK 25) -> build/libs/<modid>-<version>.jar
Cible 1.21.1 : Java 21, ressources de l'export 1.21.1, tables de butin au format 1.21.1, code Java adapté
par _java_1_21_1 (noms vérifiés avec javap dans le jar 1.21.1 de NeoForge et par la compilation en CI).
Le comportement en jeu se règle avec asset.props = Props(...) (dureté, son, lumière, outil, particules…).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np

from ._io import MARKER, mark_output_dir, prepare_output_dir, say
from .assets import PARTICLES, Block, Item, Model, MultiBlock, Multipart, Props
from .export import ExportError, ResourcePack, dumps, greedy_boxes
from .variants import Variant

TEMPLATES = Path(__file__).parent / "mod_templates"
FABRIC = {"minecraft": "26.3", "loader": "0.19.5", "loom": "1.18-SNAPSHOT", "fabric_api": "0.163.0+26.3",
          "java": 25}
NEOFORGE = {"minecraft": "26.3", "neoforge": "26.3.0.90", "moddev": "2.0.148", "java": 25}
NEOFORGE_1_21_1 = {"minecraft": "1.21.1", "neoforge": "21.1.259", "moddev": "2.0.148", "java": 21}
LOADERS = ("fabric", "neoforge")
MOD_TARGETS = ("26.3", "1.21.1")      # --mc : 1.21.1 existe seulement pour NeoForge
RESERVED_IDS = {"minecraft", "realms", "brigadier", "java", "fabric", "fabricloader", "fabric_api", "neoforge",
                "forge", "mixinextras", "c", "common"}
JAVA_KEYWORDS = set("""abstract assert boolean break byte case catch char class const continue default do double
else enum extends final finally float for goto if implements import instanceof int interface long native new
package private protected public return short static strictfp super switch synchronized this throw throws transient
try void volatile while true false null var record yield sealed permits""".split())
FACINGS = ("north", "east", "south", "west")


def _camel(name: str) -> str:
    s = "".join(w[:1].upper() + w[1:] for w in name.split("_") if w)
    return s if s and s[0].isalpha() else "B" + s


def _const(name: str) -> str:
    c = name.upper()
    return c if c[0].isalpha() else "B_" + c


def _title(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split("_") if w)


def _f(x: float) -> str:
    x = round(float(x), 4)
    return str(int(x)) if x == int(x) else repr(x)


# ============================================================================ formes (collision / contour)
def _occupancy(vol, voxel_size: float, origin, offset=(0, 0, 0), sub: int = 4) -> np.ndarray:
    """Occupation du bloc [0,16]³ (unités modèle), échantillonnée `sub` fois par pixel : (16·sub)³ booléens.
    offset : coin du bloc dans le repère du modèle (cellule d'un multibloc)."""
    n = 16 * sub
    c = (np.arange(n) + 0.5) / sub
    idx, ok = [], []
    for k in range(3):
        i = np.floor((c + offset[k] - origin[k]) / voxel_size).astype(int)
        ok.append((i >= 0) & (i < vol.shape[k]))
        idx.append(np.clip(i, 0, vol.shape[k] - 1))
    occ = vol.solid[np.ix_(idx[0], idx[1], idx[2])]
    return occ & ok[0][:, None, None] & ok[1][None, :, None] & ok[2][None, None, :]


def shape_boxes(vol, voxel_size: float = 1.0, origin=(0, 0, 0), offset=(0, 0, 0), max_boxes: int = 24,
                fill: float = 0.35) -> list:
    """Boîtes (x0, y0, z0, x1, y1, z1) en pixels 0–16 approchant la forme des voxels (contour et
    collision du bloc) : découpage glouton sur une grille de 1 px, sinon 2 px ; au-delà de `max_boxes`
    boîtes, une boîte par tranche horizontale (emprise de chaque étage). Les plans n'ont pas de forme."""
    sub = 4
    occ = _occupancy(vol, voxel_size, origin, offset, sub)
    if not occ.any():
        return []
    orders = ((0, 2, 1), (1, 0, 2), (2, 1, 0), (0, 1, 2), (1, 2, 0), (2, 0, 1))
    for g in (1, 2):
        m = 16 // g
        frac = occ.reshape(m, g * sub, m, g * sub, m, g * sub).mean(axis=(1, 3, 5))
        grid = frac >= fill
        if not grid.any():
            continue
        best = min((greedy_boxes(grid, grid, o) for o in orders), key=len)
        if len(best) <= max_boxes:
            return [tuple(float(v * g) for v in lo) + tuple(float(v * g) for v in hi) for lo, hi in best]
    # repli : une boîte par tranche (étages de même emprise, au pixel près, arrondie à 2 px)
    px = occ.reshape(16, sub, 16, sub, 16, sub).mean(axis=(1, 3, 5)) >= fill
    if not px.any():
        px = occ.reshape(16, sub, 16, sub, 16, sub).any(axis=(1, 3, 5))
    out, prev, y0 = [], None, 0
    for y in range(17):
        fp = None
        if y < 16 and px[:, y, :].any():
            xs, zs = np.nonzero(px[:, y, :])
            fp = (2 * (xs.min() // 2), 2 * (zs.min() // 2), min(16, 2 * (-(-(xs.max() + 1) // 2))),
                  min(16, 2 * (-(-(zs.max() + 1) // 2))))
        if fp != prev:
            if prev is not None:
                out.append((float(prev[0]), float(y0), float(prev[1]), float(prev[2]), float(y), float(prev[3])))
            prev, y0 = fp, y
    return out


def rot_box_y(b, turns: int):
    """Quart(s) de tour horaire vu de dessus (comme "y": 90 d'un blockstate) autour du centre du bloc."""
    x0, y0, z0, x1, y1, z1 = b
    for _ in range(turns % 4):
        x0, z0, x1, z1 = 16 - z1, x0, 16 - z0, x1
    return (x0, y0, z0, x1, y1, z1)


def rot_box_axis(b, axis: str):
    """Rotation des blockstates 'axis' : y = debout ; z = "x": 90 ; x = "x": 90, "y": 90."""
    x0, y0, z0, x1, y1, z1 = b
    if axis == "z":
        return (x0, z0, 16 - y1, x1, z1, 16 - y0)
    if axis == "x":
        return (y0, z0, x0, y1, z1, x1)
    return b


def _enc(boxes) -> str:
    return ";".join(",".join(_f(v) for v in b) for b in boxes)


# ============================================================================ projet
class _Ctx:
    def __init__(self, modid, pkg, main, loader="fabric", mc="26.3"):
        self.modid, self.pkg, self.main, self.loader, self.mc = modid, pkg, main, loader, mc
        self.decls: list[str] = []
        self.multi_classes: dict = {}
        self.lang = {"en_us": {}, "fr_fr": {}}
        self.loot: dict = {}
        self.tags: dict = {}
        self.blockstates: dict = {}
        self.summary: list = []
        self.first_item = None
        self.checks: list = []          # (constante, nom, lumière, nb de parties ou 0) pour le test JUnit
        self.item_checks: list = []
        self.variant_checks: list = []  # (constante, nom, classe vanilla, {propriété: valeurs}) pour le test JUnit
        self.variant_classes: set = set()   # sous-classes à générer (constructeurs protégés du jeu)
        self.item_tags: dict = {}
        self.recipes: dict = {}
        self.tints: list = []           # (constante, "grass" | "foliage" | "water") : couleurs de biome (client)


def _props_java(p: Props, *, full: bool, immovable: bool = False, light_expr: str | None = None) -> str:
    blast = p.blast if p.blast is not None else (max(p.strength, 6.0) if p.tool == "pickaxe" else p.strength)
    s = f"BlockBehaviour.Properties.of().strength({_f(p.strength)}f, {_f(blast)}f).sound(SoundType.{p.sound.upper()})"
    if light_expr:
        s += f".lightLevel(state -> {light_expr})"
    elif p.light:
        s += f".lightLevel(state -> {int(p.light)})"
    if p.requires_tool:
        s += ".requiresCorrectToolForDrops()"
    if not full:
        s += ".noOcclusion()"
    if not p.collision:
        s += ".noCollision()"
    if immovable:
        s += ".pushReaction(PushReaction.IMMOVEABLE)"
    return s


def _fx_java(p: Props, turns_from=None) -> str:
    if not p.particles:
        return "null"
    main, extra = PARTICLES[p.particles]
    x, y, z = p.particle_at
    return (f"new Fx(ParticleTypes.{main}, {('ParticleTypes.' + extra) if extra else 'null'}, {_f(x)}, {_f(y)}, "
            f"{_f(z)}, 4, {_f(p.particle_rate)}f)")


def _names(ctx: _Ctx, kind: str, name: str, p: Props | None):
    names = dict((p.names if p and p.names else {}) or {})
    en = names.get("en_us", _title(name))
    fr = names.get("fr_fr", en)
    key = f"{kind}.{ctx.modid}.{name}"
    ctx.lang["en_us"][key] = en
    ctx.lang["fr_fr"][key] = fr
    for lang, txt in names.items():
        ctx.lang.setdefault(lang, {})[key] = txt


def _tags(ctx: _Ctx, name: str, p: Props):
    ident = f"{ctx.modid}:{name}"
    if p.tool:
        ctx.tags.setdefault(f"mineable/{p.tool}", []).append(ident)
    if p.tier:
        ctx.tags.setdefault(f"needs_{p.tier}_tool", []).append(ident)


def _loot(ctx: _Ctx, name: str, state: dict | None = None):
    entry = {"type": "minecraft:item", "name": f"{ctx.modid}:{name}"}
    if ctx.mc == "1.21.1":                           # conditions en liste, block_state_property
        if state:
            entry["conditions"] = [{"condition": "minecraft:block_state_property", "block": f"{ctx.modid}:{name}",
                                    "properties": state}]
        ctx.loot[name] = {"type": "minecraft:block", "random_sequence": f"{ctx.modid}:blocks/{name}",
                          "pools": [{"conditions": [{"condition": "minecraft:survives_explosion"}],
                                     "entries": [entry], "rolls": 1}]}
        return
    if state:
        entry = {"type": "minecraft:item", "condition": {"type": "minecraft:match_block",
                                                         "blocks": f"{ctx.modid}:{name}", "state": state},
                 "name": f"{ctx.modid}:{name}"}
    ctx.loot[name] = {"type": "minecraft:block",
                      "pools": [{"condition": {"type": "minecraft:survives_explosion"}, "entries": [entry], "rolls": 1}],
                      "random_sequence": f"{ctx.modid}:blocks/{name}"}


def _register_block(ctx: _Ctx, a: Block):
    p = a.props or Props()
    const = _const(a.name)
    opaque = a.effective_render_type() == "solid"      # pixels transparents : ne pas cacher les voisins
    props = _props_java(p, full=opaque)
    fx = _fx_java(p)
    if a.states == "axis":
        factory = "RotatedPillarBlock::new" if fx == "null" else \
            f"p -> new PixvoxAxisBlock(p, ModContent.shapes3(\"{_enc([(0, 0, 0, 16, 16, 16)])}\"), true, {fx})"
        kind = "bloc plein (axe)"
    elif a.states == "facing":
        full = _enc([(0, 0, 0, 16, 16, 16)])
        factory = f"p -> new PixvoxFacingBlock(p, ModContent.shapes4(\"{'|'.join([full] * 4)}\"), true, {fx})"
        kind = "bloc plein (orienté)"
    else:
        factory = "Block::new" if fx == "null" else \
            f"p -> new PixvoxBlock(p, Shapes.block(), true, {fx})"
        kind = "bloc plein"
    ctx.decls.append(("block", const, a.name, factory, props))
    ctx.checks.append((const, a.name, int(p.light), 0))
    if a.tint:
        ctx.tints.append((const, a.tint))
    _names(ctx, "block", a.name, p)
    _tags(ctx, a.name, p)
    _loot(ctx, a.name)
    ctx.summary.append((a.name, kind, p))


def _register_model(ctx: _Ctx, m: Model):
    p = m.props or Props()
    const = _const(m.name)
    boxes = shape_boxes(m.volume, m.voxel_size, m.origin)
    if not boxes:
        boxes = [(0, 0, 0, 16, 16, 16)]
    fx = _fx_java(p)
    coll = "true" if p.collision else "false"
    if m.states == "facing":
        enc = "|".join(_enc([rot_box_y(b, k) for b in boxes]) for k in range(4))
        factory = f'p -> new PixvoxFacingBlock(p, ModContent.shapes4("{enc}"), {coll}, {fx})'
        kind = "modèle (orienté)"
    elif m.states == "axis":
        enc = "|".join(_enc([rot_box_axis(b, ax) for b in boxes]) for ax in ("x", "y", "z"))
        factory = f'p -> new PixvoxAxisBlock(p, ModContent.shapes3("{enc}"), {coll}, {fx})'
        kind = "modèle (axe)"
    else:
        factory = f'p -> new PixvoxBlock(p, ModContent.shape("{_enc(boxes)}"), {coll}, {fx})'
        kind = "modèle"
    ctx.decls.append(("block", const, m.name, factory, _props_java(p, full=False)))
    ctx.checks.append((const, m.name, int(p.light), 0))
    if m.tint:
        ctx.tints.append((const, m.tint))
    _names(ctx, "block", m.name, p)
    _tags(ctx, m.name, p)
    _loot(ctx, m.name)
    ctx.summary.append((m.name, f"{kind}, forme {len(boxes)} boîte(s)", p))


def multi_layout(mb: MultiBlock, parts: list) -> tuple:
    """(index de l'ancre, décalages des parties par rapport à l'ancre) — l'ancre est la partie du rang
    du bas la plus proche du centre : c'est le bloc que le joueur pose."""
    cells = [c for c, _ in parts]
    ymin = min(c[1] for c in cells)
    nx, _, nz = mb.blocks
    cx, cz = (nx - 1) / 2.0, (nz - 1) / 2.0
    cand = [i for i, c in enumerate(cells) if c[1] == ymin]
    anchor = min(cand, key=lambda i: ((cells[i][0] - cx) ** 2 + (cells[i][2] - cz) ** 2, cells[i][2], cells[i][0]))
    a = cells[anchor]
    return anchor, [(c[0] - a[0], c[1] - a[1], c[2] - a[2]) for c in cells]


def _register_multi(ctx: _Ctx, mb: MultiBlock, parts: list):
    p = mb.props or Props(strength=2.0)
    const = _const(mb.name)
    cls = _camel(mb.name) + "Block"
    anchor, offsets = multi_layout(mb, parts)
    vs = mb.voxel_size
    per_part = []
    for (bx, by, bz), _ in parts:
        b = shape_boxes(mb.volume, vs, (0, 0, 0), offset=(bx * 16, by * 16, bz * 16), max_boxes=16)
        per_part.append(b)
    enc = "|".join("/".join(_enc([rot_box_y(b, k) for b in bs]) for bs in per_part) for k in range(4))
    off = ";".join(",".join(str(int(v)) for v in o) for o in offsets)
    fx = _fx_java(p)
    fx_part = 0
    if p.particles:      # partie qui contient le point d'émission (unités du volume entier)
        px, py, pz = p.particle_at
        for i, ((bx, by, bz), _) in enumerate(parts):
            if bx * 16 <= px < bx * 16 + 16 and by * 16 <= py < by * 16 + 16 and bz * 16 <= pz < bz * 16 + 16:
                fx_part = i
                fx = fx.replace(f"{_f(px)}, {_f(py)}, {_f(pz)}", f"{_f(px - bx * 16)}, {_f(py - by * 16)}, {_f(pz - bz * 16)}")
    ctx.multi_classes[cls] = len(parts)
    coll = "true" if p.collision else "false"
    light_expr = None
    if p.light and mb.emissive is not None:          # seules les parties qui contiennent la source éclairent
        r = mb.res
        lit = [i for i, ((bx, by, bz), _) in enumerate(parts)
               if mb.emissive[bx * r:(bx + 1) * r, by * r:(by + 1) * r, bz * r:(bz + 1) * r].any()]
        if lit and len(lit) < len(parts):
            light_expr = (f"java.util.Set.of({', '.join(str(i) for i in lit)}).contains(state.getValue({cls}.PART))"
                          f" ? {int(p.light)} : 0")
    factory = (f'p -> new {cls}(p, ModContent.offsets("{off}"), {anchor}, ModContent.multiShapes("{enc}"), '
               f'{coll}, {fx}, {fx_part})')
    ctx.decls.append(("block", const, mb.name, factory, _props_java(p, full=False, immovable=True,
                                                                    light_expr=light_expr)))
    ctx.checks.append((const, mb.name, int(p.light), len(parts)))
    variants = {}
    for k, f in enumerate(FACINGS):
        for i, (_, ref) in enumerate(parts):
            v = {"model": ref}
            if k:
                v["y"] = 90 * k
            variants[f"facing={f},part={i}"] = v
    ctx.blockstates[mb.name] = {"variants": variants}
    _names(ctx, "block", mb.name, p)
    _tags(ctx, mb.name, p)
    _loot(ctx, mb.name, {"part": str(anchor)})
    ctx.summary.append((mb.name, f"multibloc {len(parts)} parties ({mb.blocks[0]}x{mb.blocks[1]}x{mb.blocks[2]}), "
                                 f"ancre = partie {anchor}", p))
    return anchor, offsets


def _register_item(ctx: _Ctx, it: Item):
    ctx.decls.append(("item", _const(it.name), it.name, None, None))
    ctx.item_checks.append((_const(it.name), it.name))
    _names(ctx, "item", it.name, it.props)
    ctx.summary.append((it.name, "item", None))


WOOD_SOUNDS = ("wood", "cherry_wood", "bamboo_wood", "nether_wood")
# variante -> (classe vanilla, tag de bloc, tag d'objet, tag « wooden_ » si le bloc sonne comme du bois)
VARIANT_JAVA = {
    "slab": ("SlabBlock", "slabs", "slabs", "wooden_slabs"),
    "stairs": ("StairBlock", "stairs", "stairs", "wooden_stairs"),
    "wall": ("WallBlock", "walls", "walls", None),
    "fence": ("FenceBlock", "fences", "fences", "wooden_fences"),
    "fence_gate": ("FenceGateBlock", "fence_gates", "fence_gates", None),
    "button": ("ButtonBlock", "buttons", "buttons", "wooden_buttons"),
    "pressure_plate": ("PressurePlateBlock", "pressure_plates", None, "wooden_pressure_plates"),
}
_VARIANT_NAMES = {"slab": ("Slab", "Dalle"), "stairs": ("Stairs", "Escalier"), "wall": ("Wall", "Mur"),
                  "fence": ("Fence", "Barrière"), "fence_gate": ("Fence Gate", "Portillon"),
                  "button": ("Button", "Bouton"), "pressure_plate": ("Pressure Plate", "Plaque de pression")}


def _variant_names(ctx: _Ctx, v: Variant) -> None:
    """Noms affichés : ceux des Props de la variante s'ils lui sont propres, sinon tirés du bloc plein
    (« Mossy Stone Slab », « Dalle de pierre moussue »)."""
    p = v.props
    if p is not None and p is not v.base.props and p.names:
        _names(ctx, "block", v.name, p)
        return
    bn = dict((v.base.props.names if v.base.props and v.base.props.names else {}) or {})
    en_base = bn.get("en_us", _title(v.base.name))
    en, fr = _VARIANT_NAMES[v.shape]
    key = f"block.{ctx.modid}.{v.name}"
    ctx.lang["en_us"][key] = f"{en_base} {en}"
    fr_base = bn.get("fr_fr")                      # sans nom français, le bloc plein garde son nom anglais : idem
    ctx.lang["fr_fr"][key] = f"{fr} de {fr_base[:1].lower() + fr_base[1:]}" if fr_base else f"{en_base} {en}"


def _register_variant(ctx: _Ctx, v: Variant, base_const: str | None):
    """Vrai bloc vanilla (SlabBlock, StairBlock, WallBlock…) : raccords, ouverture, appui gérés par le jeu ;
    tags (minecraft:slabs, walls… : le mur et la barrière ne se raccordent qu'aux blocs de leur tag), table
    de butin (dalle double = 2), recette de taille depuis le bloc plein s'il est dans le mod."""
    p = v.props or Props()
    const = _const(v.name)
    cls, btag, itag, wtag = VARIANT_JAVA[v.shape]
    wood = p.sound in WOOD_SOUNDS
    opaque = v.base.effective_render_type() == "solid"
    if v.shape in ("button", "pressure_plate"):
        props = (f"BlockBehaviour.Properties.of().noCollision().strength(0.5f).sound(SoundType.{p.sound.upper()})"
                 ".pushReaction(PushReaction.POPPED)" + (".requiresCorrectToolForDrops()" if p.requires_tool else ""))
    else:
        props = _props_java(p, full=opaque)
    set_type = "BlockSetType.OAK" if wood else "BlockSetType.STONE"
    base_state = "Blocks.STONE.defaultBlockState()"
    if base_const:
        base_state = f"{base_const}{'.get()' if ctx.loader == 'neoforge' else ''}.defaultBlockState()"
    factory = {
        "slab": "SlabBlock::new",
        "stairs": f"p -> new PixvoxStairBlock({base_state}, p)",
        "wall": "WallBlock::new",
        "fence": "FenceBlock::new",
        "fence_gate": "p -> new FenceGateBlock(WoodType.OAK, p)",
        "button": f"p -> new PixvoxButtonBlock({set_type}, {30 if wood else 20}, p)",
        "pressure_plate": f"p -> new PixvoxPressurePlateBlock({set_type}, p)",
    }[v.shape]
    if v.shape in ("stairs", "button", "pressure_plate"):
        ctx.variant_classes.add(cls)
    ctx.decls.append(("block", const, v.name, factory, props))
    ctx.variant_checks.append((const, v.name, cls, v.properties))
    _variant_names(ctx, v)
    _tags(ctx, v.name, p)
    ident = f"{ctx.modid}:{v.name}"
    ctx.tags.setdefault(btag, []).append(ident)
    if wood and wtag:
        ctx.tags.setdefault(wtag, []).append(ident)
    if itag:
        ctx.item_tags.setdefault(itag, []).append(ident)
    if v.shape == "slab":
        _loot_slab(ctx, v.name)
    else:
        _loot(ctx, v.name)
    if base_const:
        n = 2 if v.shape == "slab" else 1
        base_id = f"{ctx.modid}:{v.base.name}"
        ctx.recipes[f"{v.name}_from_{v.base.name}_stonecutting"] = {
            "type": "minecraft:stonecutting",
            "ingredient": {"item": base_id} if ctx.mc == "1.21.1" else base_id,
            "result": {"count": n, "id": ident}}
    from .variants import LABELS
    ctx.summary.append((v.name, f"{LABELS[v.shape]} de {v.base.name}", p))


def _loot_slab(ctx: _Ctx, name: str) -> None:
    """Table de butin d'une dalle, au format vanilla de chaque version : 2 dalles pour une dalle double."""
    ident = f"{ctx.modid}:{name}"
    if ctx.mc == "1.21.1":
        entry = {"type": "minecraft:item", "name": ident, "functions": [
            {"function": "minecraft:set_count", "add": False, "count": 2.0,
             "conditions": [{"condition": "minecraft:block_state_property", "block": ident,
                             "properties": {"type": "double"}}]},
            {"function": "minecraft:explosion_decay"}]}
        pool = {"bonus_rolls": 0.0, "entries": [entry], "rolls": 1.0}
    else:
        entry = {"type": "minecraft:item", "name": ident, "modifier": [
            {"type": "minecraft:set_count", "count": 2,
             "condition": {"type": "minecraft:match_block", "blocks": ident, "state": {"type": "double"}}},
            {"type": "minecraft:explosion_decay"}]}
        pool = {"entries": [entry], "rolls": 1}
    ctx.loot[name] = {"type": "minecraft:block", "pools": [pool], "random_sequence": f"{ctx.modid}:blocks/{name}"}


_TINT_SOURCE = {"grass": "grass", "foliage": "foliage", "water": "water"}          # BlockTintSources (26.3)
_TINT_1_21_1 = {   # (couleur dans le monde, couleur par défaut / de l'objet) — BiomeColors, GrassColor, FoliageColor
    "grass": ("BiomeColors.getAverageGrassColor(level, pos)", "GrassColor.getDefaultColor()"),
    "foliage": ("BiomeColors.getAverageFoliageColor(level, pos)", "FoliageColor.getDefaultColor()"),
    "water": ("BiomeColors.getAverageWaterColor(level, pos)", "0x3F76E4"),
}


def _client_files(ctx: _Ctx) -> dict:
    """Couleurs de biome des blocs teintés, côté client seulement. 26.3 : BlockTintSources (Fabric :
    BlockColorRegistry dans un ClientModInitializer ; NeoForge : RegisterColorHandlersEvent.BlockTintSources),
    la teinte des objets étant dans items/<nom>.json. 1.21.1 : BlockColor (BiomeColors) et ItemColor
    (RegisterColorHandlersEvent.Block / .Item). Noms vérifiés par javap dans les jars des deux versions."""
    if not ctx.tints:
        return {}
    pkg, main = ctx.pkg, ctx.main
    get = ".get()" if ctx.loader == "neoforge" else ""
    by_kind: dict = {}
    for const, kind in ctx.tints:
        by_kind.setdefault(kind, []).append(f"ModContent.{const}{get}")
    if ctx.mc == "1.21.1":
        blocks = "\n".join(
            f"        event.register((state, level, pos, tintIndex) -> level != null && pos != null\n"
            f"                ? {_TINT_1_21_1[k][0]} : {_TINT_1_21_1[k][1]}, {', '.join(v)});"
            for k, v in by_kind.items())
        items = "\n".join(f"        event.register((stack, tintIndex) -> 0xFF000000 | {_TINT_1_21_1[k][1]}, {', '.join(v)});"
                          for k, v in by_kind.items())
        body = f'''import net.minecraft.client.renderer.BiomeColors;
import net.minecraft.world.level.FoliageColor;
import net.minecraft.world.level.GrassColor;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.neoforge.client.event.RegisterColorHandlersEvent;

/** Couleurs de biome des blocs teintés (client seulement, généré par pixvox). */
public final class ModClient {{
    private ModClient() {{
    }}

    static void register(IEventBus bus) {{
        bus.addListener(ModClient::blockColors);
        bus.addListener(ModClient::itemColors);
    }}

    private static void blockColors(RegisterColorHandlersEvent.Block event) {{
{blocks}
    }}

    private static void itemColors(RegisterColorHandlersEvent.Item event) {{
{items}
    }}
}}
'''
        return {"ModClient.java": f"package {pkg};\n\n{body}"}
    regs = "\n".join(f"        %REG%(List.of(BlockTintSources.{_TINT_SOURCE[k]}()), {', '.join(v)});"
                      for k, v in by_kind.items())
    if ctx.loader == "fabric":
        return {f"{main}Client.java": f'''package {pkg};

import java.util.List;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.rendering.v1.BlockColorRegistry;
import net.minecraft.client.color.block.BlockTintSources;

/** Couleurs de biome des blocs teintés (client seulement, généré par pixvox). */
public class {main}Client implements ClientModInitializer {{
    @Override
    public void onInitializeClient() {{
{regs.replace("%REG%", "BlockColorRegistry.register")}
    }}
}}
'''}
    return {"ModClient.java": f'''package {pkg};

import java.util.List;

import net.minecraft.client.color.block.BlockTintSources;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.neoforge.client.event.RegisterColorHandlersEvent;

/** Couleurs de biome des blocs teintés (client seulement, généré par pixvox). */
public final class ModClient {{
    private ModClient() {{
    }}

    static void register(IEventBus bus) {{
        bus.addListener(ModClient::colors);
    }}

    private static void colors(RegisterColorHandlersEvent.BlockTintSources event) {{
{regs.replace("%REG%", "event.register")}
    }}
}}
'''}


def _variant_classes(ctx: _Ctx) -> dict:
    """Sous-classes publiques des blocs vanilla dont le constructeur est protégé (StairBlock, ButtonBlock,
    PressurePlateBlock : vérifié par javap en 26.3 et 1.21.1)."""
    pkg = ctx.pkg
    src = {
        "StairBlock": ("PixvoxStairBlock", "BlockState base, BlockBehaviour.Properties props", "base, props",
                       "import net.minecraft.world.level.block.state.BlockState;\n"),
        "ButtonBlock": ("PixvoxButtonBlock", "BlockSetType type, int ticks, BlockBehaviour.Properties props",
                        "type, ticks, props", "import net.minecraft.world.level.block.state.properties.BlockSetType;\n"),
        "PressurePlateBlock": ("PixvoxPressurePlateBlock", "BlockSetType type, BlockBehaviour.Properties props",
                               "type, props", "import net.minecraft.world.level.block.state.properties.BlockSetType;\n"),
    }
    files = {}
    for cls in sorted(ctx.variant_classes):
        name, params, args, imp = src[cls]
        files[f"block/{name}.java"] = (f"package {pkg}.block;\n\nimport net.minecraft.world.level.block.{cls};\n"
                                       f"import net.minecraft.world.level.block.state.BlockBehaviour;\n{imp}\n"
                                       f"/** {cls} vanilla (constructeur protégé dans le jeu), généré par pixvox. */\n"
                                       f"public class {name} extends {cls} {{\n"
                                       f"    public {name}({params}) {{\n        super({args});\n    }}\n}}\n")
    return files


# ============================================================================ sources Java
_SHAPE_HELPERS = '''
    /** "x0,y0,z0,x1,y1,z1;…" en pixels (0–16), comme Block.box. */
    public static VoxelShape shape(String boxes) {
        VoxelShape s = Shapes.empty();
        if (boxes.isEmpty()) return s;
        for (String b : boxes.split(";")) {
            String[] v = b.split(",");
            s = Shapes.or(s, Block.box(Double.parseDouble(v[0]), Double.parseDouble(v[1]), Double.parseDouble(v[2]),
                    Double.parseDouble(v[3]), Double.parseDouble(v[4]), Double.parseDouble(v[5])));
        }
        return s;
    }

    /** Quatre orientations (nord, est, sud, ouest) séparées par '|'. */
    public static VoxelShape[] shapes4(String s) {
        String[] p = s.split("\\\\|", -1);
        return new VoxelShape[]{shape(p[0]), shape(p[1]), shape(p[2]), shape(p[3])};
    }

    /** Trois axes (x, y, z) séparés par '|'. */
    public static VoxelShape[] shapes3(String s) {
        String[] p = s.split("\\\\|", -1);
        return new VoxelShape[]{shape(p[0]), shape(p[1]), shape(p[2])};
    }

    /** Multibloc : orientations séparées par '|', parties par '/'. */
    public static VoxelShape[][] multiShapes(String s) {
        String[] f = s.split("\\\\|", -1);
        VoxelShape[][] out = new VoxelShape[f.length][];
        for (int i = 0; i < f.length; i++) {
            String[] parts = f[i].split("/", -1);
            out[i] = new VoxelShape[parts.length];
            for (int j = 0; j < parts.length; j++) out[i][j] = shape(parts[j]);
        }
        return out;
    }

    /** Décalages des parties d'un multibloc : "x,y,z;…". */
    public static int[][] offsets(String s) {
        String[] p = s.split(";");
        int[][] out = new int[p.length][3];
        for (int i = 0; i < p.length; i++) {
            String[] v = p[i].split(",");
            for (int k = 0; k < 3; k++) out[i][k] = Integer.parseInt(v[k]);
        }
        return out;
    }
'''

_CONTENT_IMPORTS = '''import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.CreativeModeTab;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.FenceBlock;
import net.minecraft.world.level.block.FenceGateBlock;
import net.minecraft.world.level.block.RotatedPillarBlock;
import net.minecraft.world.level.block.SlabBlock;
import net.minecraft.world.level.block.SoundType;
import net.minecraft.world.level.block.WallBlock;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.properties.BlockSetType;
import net.minecraft.world.level.block.state.properties.WoodType;
import net.minecraft.world.level.material.PushReaction;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;
'''


def _fabric_files(ctx: _Ctx) -> dict:
    pkg, main, modid = ctx.pkg, ctx.main, ctx.modid
    files = {}
    files[f"{main}.java"] = f'''package {pkg};

import net.fabricmc.api.ModInitializer;
import net.minecraft.resources.Identifier;

/** Point d'entrée du mod (généré par pixvox). */
public class {main} implements ModInitializer {{
    public static final String MOD_ID = "{modid}";

    @Override
    public void onInitialize() {{
        ModContent.init();
    }}

    public static Identifier id(String path) {{
        return Identifier.fromNamespaceAndPath(MOD_ID, path);
    }}
}}
'''
    decls = []
    for kind, const, name, factory, props in ctx.decls:
        if kind == "item":
            decls.append(f'    public static final Item {const} = item("{name}");')
        else:
            decls.append(f'    public static final Block {const} = block("{name}", {factory},\n            {props});')
    files["ModContent.java"] = f'''package {pkg};

import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

import net.fabricmc.fabric.api.creativetab.v1.FabricCreativeModeTab;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.item.BlockItem;
{_CONTENT_IMPORTS}
import {pkg}.block.*;

/** Tous les blocs et items du mod (généré par pixvox — régénérez plutôt que de modifier à la main). */
@SuppressWarnings("unused")
public final class ModContent {{
    public static final List<Item> ITEMS = new ArrayList<>();

    private ModContent() {{
    }}

    private static <B extends Block> B block(String name, Function<BlockBehaviour.Properties, B> factory,
                                             BlockBehaviour.Properties props) {{
        ResourceKey<Block> key = ResourceKey.create(Registries.BLOCK, {main}.id(name));
        B block = Registry.register(BuiltInRegistries.BLOCK, key, factory.apply(props.setId(key)));
        ResourceKey<Item> itemKey = ResourceKey.create(Registries.ITEM, {main}.id(name));
        ITEMS.add(Registry.register(BuiltInRegistries.ITEM, itemKey,
                new BlockItem(block, new Item.Properties().setId(itemKey).useBlockDescriptionPrefix())));
        return block;
    }}

    private static Item item(String name) {{
        ResourceKey<Item> key = ResourceKey.create(Registries.ITEM, {main}.id(name));
        Item item = Registry.register(BuiltInRegistries.ITEM, key, new Item(new Item.Properties().setId(key)));
        ITEMS.add(item);
        return item;
    }}
{_SHAPE_HELPERS}
{chr(10).join(decls)}

    public static final CreativeModeTab TAB = Registry.register(BuiltInRegistries.CREATIVE_MODE_TAB,
            ResourceKey.create(Registries.CREATIVE_MODE_TAB, {main}.id("main")),
            FabricCreativeModeTab.builder()
                    .title(Component.translatable("itemGroup.{modid}.main"))
                    .icon(() -> new ItemStack({ctx.first_item}))
                    .displayItems((params, output) -> ITEMS.forEach(output::accept))
                    .build());

    public static void init() {{
        // le chargement de la classe enregistre tout
    }}
}}
'''
    return files


def _neoforge_files(ctx: _Ctx) -> dict:
    pkg, main, modid = ctx.pkg, ctx.main, ctx.modid
    client_call = "\n        if (dist.isClient()) ModClient.register(modEventBus);" if ctx.tints else ""
    dist_arg = ", Dist dist" if ctx.tints else ""           # FML injecte Dist ; seulement s'il sert
    dist_import = "import net.neoforged.api.distmarker.Dist;\n" if ctx.tints else ""
    files = {}
    files[f"{main}.java"] = f'''package {pkg};

import net.minecraft.resources.Identifier;
{dist_import}import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;

/** Point d'entrée du mod (généré par pixvox). */
@Mod({main}.MOD_ID)
public class {main} {{
    public static final String MOD_ID = "{modid}";

    public {main}(IEventBus modEventBus{dist_arg}) {{
        ModContent.register(modEventBus);{client_call}
    }}

    public static Identifier id(String path) {{
        return Identifier.fromNamespaceAndPath(MOD_ID, path);
    }}
}}
'''
    decls = []
    for kind, const, name, factory, props in ctx.decls:
        if kind == "item":
            decls.append(f'    public static final DeferredItem<Item> {const} = ITEMS.registerSimpleItem("{name}");')
        else:
            decls.append(f'    public static final DeferredBlock<Block> {const} = block("{name}", {factory},\n'
                         f'            () -> {props});')
    files["ModContent.java"] = f'''package {pkg};

import java.util.function.Function;
import java.util.function.Supplier;

import net.minecraft.core.registries.Registries;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.neoforge.registries.DeferredBlock;
import net.neoforged.neoforge.registries.DeferredHolder;
import net.neoforged.neoforge.registries.DeferredItem;
import net.neoforged.neoforge.registries.DeferredRegister;
{_CONTENT_IMPORTS}
import {pkg}.block.*;

/** Tous les blocs et items du mod (généré par pixvox — régénérez plutôt que de modifier à la main). */
@SuppressWarnings("unused")
public final class ModContent {{
    public static final DeferredRegister.Blocks BLOCKS = DeferredRegister.createBlocks({main}.MOD_ID);
    public static final DeferredRegister.Items ITEMS = DeferredRegister.createItems({main}.MOD_ID);
    public static final DeferredRegister<CreativeModeTab> TABS =
            DeferredRegister.create(Registries.CREATIVE_MODE_TAB, {main}.MOD_ID);

    private ModContent() {{
    }}

    private static DeferredBlock<Block> block(String name, Function<BlockBehaviour.Properties, ? extends Block> factory,
                                              Supplier<BlockBehaviour.Properties> props) {{
        DeferredBlock<Block> block = BLOCKS.registerBlock(name, factory, props);
        ITEMS.registerSimpleBlockItem(name, block);
        return block;
    }}
{_SHAPE_HELPERS}
{chr(10).join(decls)}

    public static final DeferredHolder<CreativeModeTab, CreativeModeTab> TAB = TABS.register("main",
            () -> CreativeModeTab.builder()
                    .title(Component.translatable("itemGroup.{modid}.main"))
                    .icon(() -> new ItemStack({ctx.first_item}.get()))
                    .displayItems((params, output) -> ITEMS.getEntries().forEach(e -> output.accept(e.get())))
                    .build());

    public static void register(IEventBus bus) {{
        BLOCKS.register(bus);
        ITEMS.register(bus);
        TABS.register(bus);
    }}
}}
'''
    return files


# 1.21.1 : updateShape a son ancienne signature, dont l'ordre des voisins diffère
_UPDATE_SHAPE_26 = """    protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks, BlockPos pos,
                                     Direction direction, BlockPos neighborPos, BlockState neighborState,
                                     RandomSource random) {{""".replace("{{", "{")
_UPDATE_SHAPE_1_21_1 = """    protected BlockState updateShape(BlockState state, Direction direction, BlockState neighborState,
                                     LevelAccessor level, BlockPos pos, BlockPos neighborPos) {"""
_RENAMES_1_21_1 = (
    ("import net.minecraft.resources.Identifier;", "import net.minecraft.resources.ResourceLocation;"),
    ("public static Identifier id(", "public static ResourceLocation id("),
    ("return Identifier.fromNamespaceAndPath(", "return ResourceLocation.fromNamespaceAndPath("),
    ("import net.minecraft.world.level.LevelReader;\nimport net.minecraft.world.level.ScheduledTickAccess;\n",
     "import net.minecraft.world.level.LevelAccessor;\n"),
    (_UPDATE_SHAPE_26, _UPDATE_SHAPE_1_21_1),
    ("return super.updateShape(state, level, ticks, pos, direction, neighborPos, neighborState, random);",
     "return super.updateShape(state, direction, neighborState, level, pos, neighborPos);"),
    ("BLOCKS.registerBlock(name, factory, props)", "BLOCKS.registerBlock(name, factory, props.get())"),
    (".noCollision()", ".noCollission()"),
    ("PushReaction.IMMOVEABLE", "PushReaction.BLOCK"),
    ("PushReaction.POPPED", "PushReaction.DESTROY"),           # cassé quand un piston le pousse
    ("BuiltInRegistries.BLOCK.getValue(", "BuiltInRegistries.BLOCK.get("),
    ("BuiltInRegistries.ITEM.getValue(", "BuiltInRegistries.ITEM.get("),
)


SOUNDS_NOT_IN_1_21_1 = {"resin_bricks", "iron"}               # absents du jar NeoForge 1.21.1 (compileJava)
PARTICLES_NOT_IN_1_21_1 = {"FIREFLY", "COPPER_FIRE_FLAME"}


def _check_props_1_21_1(a) -> None:
    """Refuse tout de suite un son ou une particule que 1.21.1 n'a pas : le projet ne compilerait pas."""
    p = a.props
    if p is None:
        return
    if p.sound.lower() in SOUNDS_NOT_IN_1_21_1:
        raise ExportError(f"{a.name} : le son {p.sound!r} n'existe pas en Minecraft 1.21.1")
    bad = PARTICLES_NOT_IN_1_21_1 & set(PARTICLES.get(p.particles) or ())
    if bad:
        raise ExportError(f"{a.name} : la particule {p.particles!r} ({', '.join(sorted(bad))}) n'existe pas en Minecraft "
                          "1.21.1")


def _java_1_21_1(txt: str) -> str:
    """Source Java 26.3 -> 1.21.1 : seuls ces noms et signatures diffèrent (vérifiés à la compilation)."""
    for old, new in _RENAMES_1_21_1:
        txt = txt.replace(old, new)
    return txt


def _java_files(ctx: _Ctx) -> dict:
    """Sources Java de la cible du mod."""
    files = _java_files_26(ctx)
    return {k: _java_1_21_1(v) for k, v in files.items()} if ctx.mc == "1.21.1" else files


def _java_files_26(ctx: _Ctx) -> dict:
    """Sources Java : point d'entrée + ModContent (selon le chargeur) et classes de blocs (communes)."""
    pkg = ctx.pkg
    files = _fabric_files(ctx) if ctx.loader == "fabric" else _neoforge_files(ctx)
    files.update(_variant_classes(ctx))
    files.update(_client_files(ctx))
    files["block/Fx.java"] = f'''package {pkg}.block;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.particles.SimpleParticleType;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.Level;

/** Particules d'ambiance (feu, fumée, étincelles…) émises au point (x, y, z) en pixels du bloc. */
public record Fx(SimpleParticleType main, SimpleParticleType extra, double x, double y, double z, double spread,
                 float chance) {{
    static int turns(Direction facing) {{
        return switch (facing) {{
            case EAST -> 1;
            case SOUTH -> 2;
            case WEST -> 3;
            default -> 0;
        }};
    }}

    public void spawn(Level level, BlockPos pos, Direction facing, RandomSource random) {{
        if (random.nextFloat() >= chance) return;
        double px = x, pz = z;
        for (int i = 0; i < turns(facing); i++) {{
            double t = px;
            px = 16 - pz;
            pz = t;
        }}
        double s = spread / 16.0;
        double bx = pos.getX() + px / 16.0, by = pos.getY() + y / 16.0, bz = pos.getZ() + pz / 16.0;
        level.addParticle(main, bx + (random.nextDouble() - 0.5) * s, by, bz + (random.nextDouble() - 0.5) * s,
                0.0, 0.015, 0.0);
        if (extra != null && random.nextFloat() < 0.35f) {{
            level.addParticle(extra, bx + (random.nextDouble() - 0.5) * s, by + 0.15, bz + (random.nextDouble() - 0.5) * s,
                    0.0, 0.04, 0.0);
        }}
    }}
}}
'''
    files["block/PixvoxBlock.java"] = f'''package {pkg}.block;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Bloc à forme libre : contour/collision issus des voxels, particules d'ambiance optionnelles. */
public class PixvoxBlock extends Block {{
    protected final VoxelShape shape;
    protected final boolean collision;
    protected final Fx fx;

    public PixvoxBlock(BlockBehaviour.Properties props, VoxelShape shape, boolean collision, Fx fx) {{
        super(props);
        this.shape = shape;
        this.collision = collision;
        this.fx = fx;
    }}

    protected VoxelShape shapeFor(BlockState state) {{
        return shape;
    }}

    protected Direction facingOf(BlockState state) {{
        return Direction.NORTH;
    }}

    @Override
    protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return shapeFor(state);
    }}

    @Override
    protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return collision ? shapeFor(state) : Shapes.empty();
    }}

    @Override
    public void animateTick(BlockState state, Level level, BlockPos pos, RandomSource random) {{
        if (fx != null) fx.spawn(level, pos, facingOf(state), random);
    }}
}}
'''
    files["block/PixvoxFacingBlock.java"] = f'''package {pkg}.block;

import net.minecraft.core.Direction;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.Mirror;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Bloc orienté (4 directions) : la face avant (nord du modèle) regarde le joueur qui le pose. */
public class PixvoxFacingBlock extends PixvoxBlock {{
    public static final EnumProperty<Direction> FACING = HorizontalDirectionalBlock.FACING;
    private final VoxelShape[] shapes;   // nord, est, sud, ouest

    public PixvoxFacingBlock(BlockBehaviour.Properties props, VoxelShape[] shapes, boolean collision, Fx fx) {{
        super(props, shapes[0], collision, fx);
        this.shapes = shapes;
        registerDefaultState(stateDefinition.any().setValue(FACING, Direction.NORTH));
    }}

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(FACING);
    }}

    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {{
        return defaultBlockState().setValue(FACING, context.getHorizontalDirection().getOpposite());
    }}

    @Override
    protected VoxelShape shapeFor(BlockState state) {{
        return shapes[Fx.turns(state.getValue(FACING))];
    }}

    @Override
    protected Direction facingOf(BlockState state) {{
        return state.getValue(FACING);
    }}

    @Override
    protected BlockState rotate(BlockState state, Rotation rotation) {{
        return state.setValue(FACING, rotation.rotate(state.getValue(FACING)));
    }}

    @Override
    protected BlockState mirror(BlockState state, Mirror mirror) {{
        return state.rotate(mirror.getRotation(state.getValue(FACING)));
    }}
}}
'''
    files["block/PixvoxAxisBlock.java"] = f'''package {pkg}.block;

import net.minecraft.core.Direction;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.RotatedPillarBlock;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Bloc à axe (comme une bûche) : axe = face cliquée. */
public class PixvoxAxisBlock extends PixvoxBlock {{
    public static final EnumProperty<Direction.Axis> AXIS = RotatedPillarBlock.AXIS;
    private final VoxelShape[] shapes;   // x, y, z

    public PixvoxAxisBlock(BlockBehaviour.Properties props, VoxelShape[] shapes, boolean collision, Fx fx) {{
        super(props, shapes[1], collision, fx);
        this.shapes = shapes;
        registerDefaultState(stateDefinition.any().setValue(AXIS, Direction.Axis.Y));
    }}

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(AXIS);
    }}

    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {{
        return defaultBlockState().setValue(AXIS, context.getClickedFace().getAxis());
    }}

    @Override
    protected VoxelShape shapeFor(BlockState state) {{
        return shapes[state.getValue(AXIS).ordinal()];
    }}

    @Override
    protected BlockState rotate(BlockState state, Rotation rotation) {{
        return RotatedPillarBlock.rotatePillar(state, rotation);
    }}
}}
'''
    files["block/PixvoxMultiBlock.java"] = f'''package {pkg}.block;

import java.util.HashMap;
import java.util.Map;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.RandomSource;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.ScheduledTickAccess;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.level.block.state.properties.IntegerProperty;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/**
 * Objet de plusieurs blocs : chaque partie est un état (facing, part) de ce bloc.
 * Posé d'un coup si toute la place est libre ; si une partie disparaît, les autres suivent
 * (comme une porte) ; seule la partie d'ancrage lâche l'objet (table de butin).
 */
public abstract class PixvoxMultiBlock extends Block {{
    public static final EnumProperty<Direction> FACING = HorizontalDirectionalBlock.FACING;
    private final int[][] offsets;          // partie -> décalage depuis l'ancre (face avant au nord)
    private final int anchor;
    private final VoxelShape[][] shapes;    // [nord, est, sud, ouest][partie]
    private final boolean collision;
    private final Fx fx;
    private final int fxPart;
    private final Map<Long, Integer> index = new HashMap<>();

    protected PixvoxMultiBlock(BlockBehaviour.Properties props, int[][] offsets, int anchor, VoxelShape[][] shapes,
                               boolean collision, Fx fx, int fxPart) {{
        super(props);
        this.offsets = offsets;
        this.anchor = anchor;
        this.shapes = shapes;
        this.collision = collision;
        this.fx = fx;
        this.fxPart = fxPart;
        for (int i = 0; i < offsets.length; i++) index.put(BlockPos.asLong(offsets[i][0], offsets[i][1], offsets[i][2]), i);
        registerDefaultState(stateDefinition.any().setValue(FACING, Direction.NORTH).setValue(part(), anchor));
    }}

    /** Propriété « part » (0 … nombre de parties - 1), déclarée par la sous-classe générée. */
    public abstract IntegerProperty part();

    public int partCount() {{
        return offsets.length;
    }}

    /** Décalage tourné d'un quart de tour horaire (vu de dessus) par cran, comme "y": 90 d'un blockstate. */
    static int[] rotate(int[] o, int turns) {{
        int x = o[0], z = o[2];
        for (int i = 0; i < ((turns % 4) + 4) % 4; i++) {{
            int t = x;
            x = -z;
            z = t;
        }}
        return new int[]{{x, o[1], z}};
    }}

    public BlockPos partPos(BlockPos anchorPos, int part, Direction facing) {{
        int[] o = rotate(offsets[part], Fx.turns(facing));
        return anchorPos.offset(o[0], o[1], o[2]);
    }}

    public BlockPos anchorPos(BlockPos pos, BlockState state) {{
        int[] o = rotate(offsets[state.getValue(part())], Fx.turns(state.getValue(FACING)));
        return pos.offset(-o[0], -o[1], -o[2]);
    }}

    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {{
        Direction facing = context.getHorizontalDirection().getOpposite();
        BlockPos a = context.getClickedPos();
        Level level = context.getLevel();
        for (int i = 0; i < offsets.length; i++) {{
            BlockPos p = partPos(a, i, facing);
            if (level.isOutsideBuildHeight(p) || !level.getBlockState(p).canBeReplaced(context)) return null;
        }}
        return defaultBlockState().setValue(FACING, facing).setValue(part(), anchor);
    }}

    @Override
    public void setPlacedBy(Level level, BlockPos pos, BlockState state, LivingEntity placer, ItemStack stack) {{
        super.setPlacedBy(level, pos, state, placer, stack);
        if (level.isClientSide()) return;
        Direction facing = state.getValue(FACING);
        for (int i = 0; i < offsets.length; i++) {{
            if (i != anchor) level.setBlock(partPos(pos, i, facing), state.setValue(part(), i), Block.UPDATE_ALL);
        }}
    }}

    @Override
    protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks, BlockPos pos,
                                     Direction direction, BlockPos neighborPos, BlockState neighborState,
                                     RandomSource random) {{
        Direction facing = state.getValue(FACING);
        BlockPos a = anchorPos(pos, state);
        int[] rel = rotate(new int[]{{neighborPos.getX() - a.getX(), neighborPos.getY() - a.getY(),
                neighborPos.getZ() - a.getZ()}}, 4 - Fx.turns(facing));
        Integer expected = index.get(BlockPos.asLong(rel[0], rel[1], rel[2]));
        if (expected != null && !(neighborState.is(this) && neighborState.getValue(FACING) == facing
                && neighborState.getValue(part()) == expected)) {{
            return Blocks.AIR.defaultBlockState();          // une partie voisine a disparu : on suit
        }}
        return super.updateShape(state, level, ticks, pos, direction, neighborPos, neighborState, random);
    }}

    @Override
    public BlockState playerWillDestroy(Level level, BlockPos pos, BlockState state, Player player) {{
        if (!level.isClientSide() && player.isCreative() && state.getValue(part()) != anchor) {{
            BlockPos a = anchorPos(pos, state);            // créatif : pas d'objet lâché par l'ancre
            if (level.getBlockState(a).is(this)) {{
                level.setBlock(a, Blocks.AIR.defaultBlockState(), Block.UPDATE_ALL | Block.UPDATE_SUPPRESS_DROPS);
            }}
        }}
        return super.playerWillDestroy(level, pos, state, player);
    }}

    @Override
    protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return shapes[Fx.turns(state.getValue(FACING))][state.getValue(part())];
    }}

    @Override
    protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {{
        return collision ? getShape(state, level, pos, context) : Shapes.empty();
    }}

    @Override
    public void animateTick(BlockState state, Level level, BlockPos pos, RandomSource random) {{
        if (fx != null && state.getValue(part()) == fxPart) fx.spawn(level, pos, state.getValue(FACING), random);
    }}

    @Override
    protected BlockState rotate(BlockState state, Rotation rotation) {{
        return state.setValue(FACING, rotation.rotate(state.getValue(FACING)));
    }}
}}
'''
    for cls, n in ctx.multi_classes.items():
        files[f"block/{cls}.java"] = f'''package {pkg}.block;

import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.IntegerProperty;
import net.minecraft.world.phys.shapes.VoxelShape;

/** Multibloc de {n} parties (généré par pixvox). */
public class {cls} extends PixvoxMultiBlock {{
    public static final IntegerProperty PART = IntegerProperty.create("part", 0, {n - 1});

    public {cls}(BlockBehaviour.Properties props, int[][] offsets, int anchor, VoxelShape[][] shapes, boolean collision,
                 Fx fx, int fxPart) {{
        super(props, offsets, anchor, shapes, collision, fx, fxPart);
    }}

    @Override
    public IntegerProperty part() {{
        return PART;
    }}

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(FACING, PART);
    }}
}}
'''
    return files


def _test_java(ctx: _Ctx) -> str:
    text = _test_java_26(ctx)
    return _java_1_21_1(text) if ctx.mc == "1.21.1" else text


def _test_java_26(ctx: _Ctx) -> str:
    pkg, main = ctx.pkg, ctx.main
    neo = ctx.loader == "neoforge"
    get = ".get()" if neo else ""
    blocks = "\n".join(f'        check("{n}", ModContent.{c}{get}, {light}, {parts});' for c, n, light, parts in ctx.checks)
    items = "\n".join(f'        assertSame(ModContent.{c}{get}, BuiltInRegistries.ITEM.getValue({main}.id("{n}")), "{n}");'
                      for c, n in ctx.item_checks)
    variants = "\n".join(
        f'        checkVariant("{n}", ModContent.{c}{get}, {cls}.class, new String[][]{{'
        + ", ".join("{" + ", ".join(f'"{x}"' for x in [k, *vals]) + "}" for k, vals in props.items()) + "});"
        for c, n, cls, props in ctx.variant_checks)
    if neo:
        boot = ("    // NeoForge (FML JUnit) : le jeu est déjà amorcé avec le mod chargé avant les tests.\n")
        boot_imports = ""
        list_check = "        assertFalse(ModContent.ITEMS.getEntries().isEmpty());"
    else:
        boot = '''    @BeforeAll
    static void boot() {
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        FabricLoader.getInstance().getEntrypoints("main", ModInitializer.class).forEach(ModInitializer::onInitialize);
    }
'''
        boot_imports = ('''import net.fabricmc.api.ModInitializer;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.SharedConstants;
import net.minecraft.server.Bootstrap;
import org.junit.jupiter.api.BeforeAll;
''')
        list_check = "        assertFalse(ModContent.ITEMS.isEmpty());"
    return f'''package {pkg};

import static org.junit.jupiter.api.Assertions.*;

{boot_imports}import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.level.EmptyBlockGetter;
import net.minecraft.world.level.block.*;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import net.minecraft.world.phys.shapes.CollisionContext;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.TreeSet;

import {pkg}.block.PixvoxMultiBlock;

/**
 * Test de fumée généré par pixvox : démarre les registres de Minecraft (sans ouvrir le jeu) avec le mod,
 * puis vérifie chaque bloc (enregistrement, item, lumière, formes de tous les états) et la géométrie des
 * multiblocs (chaque partie retrouve son ancre, dans les 4 orientations).
 */
public class GeneratedContentTest {{
{boot}
    static void check(String name, Block expected, int light, int parts) {{
        Block b = BuiltInRegistries.BLOCK.getValue({main}.id(name));
        assertSame(expected, b, name);
        assertSame(BuiltInRegistries.ITEM.getValue({main}.id(name)), b.asItem(), name + " : item");
        int maxLight = 0;
        for (BlockState s : b.getStateDefinition().getPossibleStates()) {{
            maxLight = Math.max(maxLight, s.getLightEmission());
            if (parts == 0) assertEquals(light, s.getLightEmission(), name + " : lumière");
            assertFalse(s.getShape(EmptyBlockGetter.INSTANCE, BlockPos.ZERO, CollisionContext.empty()).isEmpty(),
                    name + " : forme vide pour " + s);
        }}
        assertEquals(light, maxLight, name + " : lumière maximale");
        if (parts > 0) {{
            PixvoxMultiBlock m = (PixvoxMultiBlock) b;
            assertEquals(parts, m.partCount(), name);
            assertEquals(4 * parts, b.getStateDefinition().getPossibleStates().size(), name);
            BlockPos a = new BlockPos(100, 64, -50);
            for (Direction f : Direction.Plane.HORIZONTAL) {{
                for (int i = 0; i < parts; i++) {{
                    BlockState s = b.defaultBlockState().setValue(PixvoxMultiBlock.FACING, f).setValue(m.part(), i);
                    assertEquals(a, m.anchorPos(m.partPos(a, i, f), s), name + " partie " + i + " " + f);
                }}
            }}
        }}
    }}

    /** Variante de construction : vrai bloc vanilla, et chaque propriété du blockstate écrit par pixvox
     *  existe dans le jeu avec exactement les mêmes valeurs. */
    static void checkVariant(String name, Block expected, Class<?> cls, String[][] props) {{
        Block b = BuiltInRegistries.BLOCK.getValue({main}.id(name));
        assertSame(expected, b, name);
        assertSame(BuiltInRegistries.ITEM.getValue({main}.id(name)), b.asItem(), name + " : item");
        assertTrue(cls.isInstance(b), name + " : " + cls.getSimpleName() + " attendu");
        for (String[] p : props) {{
            Property<?> prop = b.getStateDefinition().getProperty(p[0]);
            assertNotNull(prop, name + " : propriété " + p[0]);
            TreeSet<String> got = new TreeSet<>();
            for (Object v : prop.getPossibleValues()) got.add(valueName(prop, v));
            assertEquals(new TreeSet<>(Arrays.asList(p).subList(1, p.length)), got, name + " : valeurs de " + p[0]);
        }}
        assertFalse(b.defaultBlockState().getShape(EmptyBlockGetter.INSTANCE, BlockPos.ZERO,
                CollisionContext.empty()).isEmpty(), name + " : forme vide");
    }}

    @SuppressWarnings({{"unchecked", "rawtypes"}})
    static String valueName(Property prop, Object value) {{
        return prop.getName((Comparable) value);
    }}

    @Test
    void content() {{
{blocks}
{variants}
{items}
{list_check}
    }}
}}
'''


def _neo_versions(ctx: _Ctx) -> dict:
    return NEOFORGE_1_21_1 if ctx.mc == "1.21.1" else NEOFORGE


def _build_gradle(tests: bool = True) -> str:
    return '''plugins {
	id 'net.fabricmc.fabric-loom' version "${loom_version}"
}

base {
	archivesName = project.archives_base_name
}

dependencies {
	minecraft "com.mojang:minecraft:${project.minecraft_version}"
	implementation "net.fabricmc:fabric-loader:${project.loader_version}"
	implementation "net.fabricmc.fabric-api:fabric-api:${project.fabric_api_version}"
}

processResources {
	def version = project.version
	inputs.property "version", version
	filesMatching("fabric.mod.json") {
		expand "version": version
	}
}

tasks.withType(JavaCompile).configureEach {
	it.options.release = 25
	it.options.encoding = "UTF-8"
}

java {
	sourceCompatibility = JavaVersion.VERSION_25
	targetCompatibility = JavaVersion.VERSION_25
}
''' + ('''
// Test de fumée (src/test) : registres de Minecraft + initialisation du mod, sans lancer le jeu.
dependencies {
	testImplementation "net.fabricmc:fabric-loader-junit:${project.loader_version}"
}

test {
	useJUnitPlatform()
	testLogging {
		events "passed", "failed"
		exceptionFormat "full"
	}
}
''' if tests else "")


# ============================================================================ API
def export_mod(assets, out="out/mod", modid: str = "pixvox_mod", name: str | None = None, *,
               loader: str = "fabric", version: str = "1.0.0", authors=("pixvox",), description: str | None = None,
               package: str | None = None, license: str = "All-Rights-Reserved", build: bool = False,
               java_home: str | None = None, zip_path=None, quiet: bool = False, tests: bool = True,
               mc: str | None = None) -> dict:
    """Écrit un projet de mod complet dans `out` (recréé) pour Minecraft 26.3 :
    loader='fabric' (Fabric Loader + Fabric API) ou 'neoforge' (NeoForge, ModDevGradle) ; ou pour
    Minecraft 1.21.1 : mc="1.21.1", loader='neoforge' seulement (NeoForge 21.1, Java 21).
    build=True lance `./gradlew build` (JDK de la cible requis : java_home, ou JAVA_HOME), qui exécute aussi le
    test de fumée généré (tests=True : registres du jeu + mod chargés dans JUnit, sans ouvrir le jeu). Retourne {project, jar, summary, assets}."""
    if loader not in LOADERS:
        raise ValueError(f"loader = {' ou '.join(LOADERS)}")
    mc = mc or MOD_TARGETS[0]
    if mc not in MOD_TARGETS:
        raise ValueError(f"mc={mc!r} inconnu : {', '.join(MOD_TARGETS)}")
    if mc == "1.21.1" and loader != "neoforge":
        raise ValueError("Minecraft 1.21.1 : seul NeoForge est pris en charge (--loader neoforge)")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", modid):
        raise ValueError("modid : minuscules, chiffres et _, commence par une lettre (2–64 caractères)")
    if modid in RESERVED_IDS:
        raise ValueError(f"modid {modid!r} réservé (jeu ou chargeur) : choisissez un identifiant propre au mod")
    pkg = package or f"pixvox.{modid}"
    if any(seg in JAVA_KEYWORDS or not re.fullmatch(r"[a-z_][a-z0-9_]*", seg) for seg in pkg.split(".")):
        raise ValueError(f"package Java invalide : {pkg!r}")
    names = [a.name for a in assets]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"noms en double : {sorted(dup)}")
    final = Path(out)
    if final.exists() and any(final.iterdir()) and not (final / MARKER).is_file():
        prepare_output_dir(final, "dossier du projet de mod")      # refus explicite AVANT tout travail
    root = final.with_name(final.name + ".tmp_pixvox")      # généré à côté, échangé seulement si tout réussit
    if root.exists():
        shutil.rmtree(root)
    try:
        result = _write_project(assets, root, final, modid, name, pkg, names, loader=loader, version=version,
                                authors=authors, description=description, license=license, tests=tests, mc=mc)
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise
    prepare_output_dir(final, "dossier du projet de mod")
    root.rename(final)
    result["project"] = final
    ctx = result.pop("_ctx")
    infos = result["assets"]
    root = final
    if zip_path:
        _zip_project(root, Path(zip_path))
        result["zip"] = Path(zip_path)
    result["mc"] = mc
    if build:
        result["jar"] = build_mod(root, java_home, quiet=quiet, java=required_java(mc))
    if not quiet:
        for n, kind, p in ctx.summary:
            extra = ""
            if p is not None:
                extra = f" | son {p.sound}, dureté {_f(p.strength)}" + (f", lumière {p.light}" if p.light else "") + \
                        (f", particules {p.particles}" if p.particles else "") + (f", outil {p.tool}" if p.tool else "")
            say(f"[mod] {modid}:{n} — {kind}{extra}")
        bad = [i for i in infos if i["verify"]["diff_px"] or i["verify"].get("missing")]
        say(f"[mod] ressources vérifiées : {'OK' if not bad else 'ÉCARTS ' + str([i['name'] for i in bad])}")
        say(f"[mod] projet : {root}" + (f" | jar : {result['jar']}" if result["jar"] else ""))
    return result


def _write_project(assets, root: Path, final: Path, modid, name, pkg, names, *, loader, version, authors,
                   description, license, tests, mc="26.3") -> dict:
    res = root / "src" / "main" / "resources"
    main = _camel(modid) + "Mod"
    ctx = _Ctx(modid, pkg, main, loader, mc)
    pack = ResourcePack(res, modid, mod_mode=True, mc="1.21.1" if mc == "1.21.1" else None)
    neo = _neo_versions(ctx)
    infos = []
    for a in assets:
        if isinstance(a, Multipart):
            raise ExportError(f"{a.name} : pixvox mod ne génère pas encore de Multipart ; l'exporter avec pixvox export "
                              "et enregistrer le bloc et ses propriétés dans le mod")
        if mc == "1.21.1":
            _check_props_1_21_1(a)
        infos.append(pack.add(a))           # ExportError si un modèle est invalide pour le jeu : pas de mod bancal
        for w in infos[-1].get("warnings", []):
            say(f"[mod] ATTENTION {a.name} : {w}")
    for a in assets:
        if isinstance(a, MultiBlock):
            _register_multi(ctx, a, pack.multi_parts[a.name])
        elif isinstance(a, Block):
            _register_block(ctx, a)
        elif isinstance(a, Model):
            _register_model(ctx, a)
        elif isinstance(a, Item):
            _register_item(ctx, a)
        else:
            continue
        if ctx.first_item is None:
            ctx.first_item = _const(a.name)
    in_mod = {a.name for a in assets if isinstance(a, Block)}
    for a in assets:                    # après les blocs pleins : l'escalier lit l'état de son bloc plein
        if isinstance(a, Variant):
            _register_variant(ctx, a, _const(a.base.name) if a.base.name in in_mod else None)
            if ctx.first_item is None:
                ctx.first_item = _const(a.name)
    # ressources propres au mod
    for n, bs in ctx.blockstates.items():
        (res / "assets" / modid / "blockstates" / f"{n}.json").write_text(dumps(bs) + "\n", encoding="utf-8")
    lang_dir = res / "assets" / modid / "lang"
    lang_dir.mkdir(parents=True, exist_ok=True)
    title = name or _title(modid)
    for lang, d in ctx.lang.items():
        d = dict(d)
        d[f"itemGroup.{modid}.main"] = title
        (lang_dir / f"{lang}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for n, lt in ctx.loot.items():
        p = res / "data" / modid / "loot_table" / "blocks" / f"{n}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(lt, indent=2) + "\n", encoding="utf-8")
    for kind, tags in (("block", ctx.tags), ("item", ctx.item_tags)):
        for tag, vals in tags.items():
            p = res / "data" / "minecraft" / "tags" / kind / f"{tag}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"values": vals}, indent=2) + "\n", encoding="utf-8")
    for n, r in ctx.recipes.items():
        p = res / "data" / modid / "recipe" / f"{n}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    if pack.icon_img is not None:
        from .png import save_png
        save_png(res / "assets" / modid / "icon.png", pack.icon_img)
    desc = description or f"Blocs créés avec pixvox : {', '.join(names)}"
    jdir = root / "src" / "main" / "java" / Path(*pkg.split("."))
    for rel, txt in _java_files(ctx).items():
        p = jdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    for f in ("gradlew", "gradlew.bat"):
        shutil.copy(TEMPLATES / f, root / f)
    os.chmod(root / "gradlew", 0o755)
    (root / "gradle" / "wrapper").mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATES / "gradle" / "wrapper" / "gradle-wrapper.jar", root / "gradle" / "wrapper" / "gradle-wrapper.jar")
    wp = "gradle-wrapper.properties" if loader == "fabric" else "neoforge-gradle-wrapper.properties"
    shutil.copy(TEMPLATES / "gradle" / "wrapper" / wp, root / "gradle" / "wrapper" / "gradle-wrapper.properties")
    if loader == "fabric":
        fmj = {"schemaVersion": 1, "id": modid, "version": "${version}", "name": title, "description": desc,
               "authors": list(authors), "license": license, "icon": f"assets/{modid}/icon.png", "environment": "*",
               "entrypoints": {"main": [f"{pkg}.{main}"],
                               **({"client": [f"{pkg}.{main}Client"]} if ctx.tints else {})},
               "depends": {"fabricloader": f">={FABRIC['loader']}", "minecraft": f"~{FABRIC['minecraft']}",
                           "java": f">={FABRIC['java']}", "fabric-api": "*"}}
        (res / "fabric.mod.json").write_text(json.dumps(fmj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (root / "build.gradle").write_text(_build_gradle(tests), encoding="utf-8")
        if tests:
            tdir = root / "src" / "test" / "java" / Path(*pkg.split("."))
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "GeneratedContentTest.java").write_text(_test_java(ctx), encoding="utf-8")
        (root / "settings.gradle").write_text(
            "pluginManagement {\n\trepositories {\n\t\tmaven {\n\t\t\tname = 'Fabric'\n"
            "\t\t\turl = 'https://maven.fabricmc.net/'\n\t\t}\n\t\tmavenCentral()\n\t\tgradlePluginPortal()\n\t}\n}\n\n"
            f"rootProject.name = '{modid}'\n", encoding="utf-8")
        (root / "gradle.properties").write_text(
            "org.gradle.jvmargs=-Xmx2G\norg.gradle.parallel=true\norg.gradle.configuration-cache=true\n\n"
            f"minecraft_version={FABRIC['minecraft']}\nloader_version={FABRIC['loader']}\nloom_version={FABRIC['loom']}\n"
            f"fabric_api_version={FABRIC['fabric_api']}\n\nversion={version}\ngroup={pkg}\narchives_base_name={modid}\n",
            encoding="utf-8")
    else:
        header = 'modLoader="javafml"\nloaderVersion="[4,)"\n' if mc == "1.21.1" else ""     # obligatoires pour FML 4
        toml = (f'{header}license="{license}"\n\n[[mods]]\nmodId="{modid}"\nversion="{version}"\ndisplayName="{title}"\n'
                f'logoFile="assets/{modid}/icon.png"\nauthors="{", ".join(authors)}"\n'
                f"description='''\n{desc}\n'''\n\n"
                f'[[dependencies.{modid}]]\n    modId="neoforge"\n    type="required"\n'
                f'    versionRange="[{neo["neoforge"]},)"\n    ordering="NONE"\n    side="BOTH"\n\n'
                f'[[dependencies.{modid}]]\n    modId="minecraft"\n    type="required"\n'
                f'    versionRange="[{neo["minecraft"]}]"\n    ordering="NONE"\n    side="BOTH"\n')
        (res / "META-INF").mkdir(parents=True, exist_ok=True)
        (res / "META-INF" / "neoforge.mods.toml").write_text(toml, encoding="utf-8")
        (root / "build.gradle").write_text(_neoforge_gradle(tests, neo), encoding="utf-8")
        if tests:
            tdir = root / "src" / "test" / "java" / Path(*pkg.split("."))
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "GeneratedContentTest.java").write_text(_test_java(ctx), encoding="utf-8")
        (root / "settings.gradle").write_text(
            "pluginManagement {\n    repositories {\n        gradlePluginPortal()\n    }\n}\n\nplugins {\n"
            "    id 'org.gradle.toolchains.foojay-resolver-convention' version '1.0.0'\n}\n\n"
            f"rootProject.name = '{modid}'\n", encoding="utf-8")
        (root / "gradle.properties").write_text(
            "org.gradle.jvmargs=-Xmx2G\norg.gradle.daemon=true\norg.gradle.parallel=true\norg.gradle.caching=true\n"
            "org.gradle.configuration-cache=true\n\n"
            f"minecraft_version={neo['minecraft']}\nneo_version={neo['neoforge']}\n\n"
            f"mod_id={modid}\nmod_version={version}\nmod_group_id={pkg}\n", encoding="utf-8")
    (root / ".gitignore").write_text(".gradle/\nbuild/\nrun/\n*.iml\n.idea/\nout/\n", encoding="utf-8")
    mark_output_dir(root)
    (root / "README.md").write_text(_readme(modid, title, version, ctx), encoding="utf-8")
    return {"project": final, "jar": None, "summary": ctx.summary, "assets": infos, "_ctx": ctx}


def _neoforge_gradle(tests: bool = True, neo: dict = NEOFORGE) -> str:
    test_cfg = '''
// Test de fumée (src/test) : NeoForge charge le jeu et le mod dans JUnit, sans ouvrir de fenêtre.
neoForge {
    unitTest {
        enable()
        testedMod = mods."${mod_id}"
    }
}

dependencies {
    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.2'
    testRuntimeOnly 'org.junit.platform:junit-platform-launcher'
}

test {
    useJUnitPlatform()
    testLogging {
        events "passed", "failed"
        exceptionFormat "full"
    }
}
''' if tests else ""
    return f'''plugins {{
    id 'java-library'
    id 'net.neoforged.moddev' version '{neo["moddev"]}'
}}

version = mod_version
group = mod_group_id

base {{
    archivesName = mod_id
}}

java.toolchain.languageVersion = JavaLanguageVersion.of({neo["java"]})

neoForge {{
    version = project.neo_version
    runs {{
        client {{
            client()
        }}
        server {{
            server()
            programArgument '--nogui'
        }}
    }}
    mods {{
        "${{mod_id}}" {{
            sourceSet(sourceSets.main)
        }}
    }}
}}

tasks.withType(JavaCompile).configureEach {{
    options.encoding = 'UTF-8'
}}
''' + test_cfg


def _readme(modid, title, version, ctx) -> str:
    neo = _neo_versions(ctx)
    rows = "\n".join(f"| `{modid}:{n}` | {k} |" for n, k, _ in ctx.summary)
    if ctx.loader == "neoforge":
        return f"""# {title} — mod NeoForge pour Minecraft {neo['minecraft']} (généré par pixvox)

| identifiant | type |
|---|---|
{rows}

## Construire le .jar

Il faut Java {neo['java']} (Gradle le télécharge au besoin). Dans ce dossier :

```
./gradlew build          # Windows : gradlew.bat build
```

La première construction prépare Minecraft {neo['minecraft']} + NeoForge {neo['neoforge']} (plusieurs minutes).
Le mod est dans `build/libs/{modid}-{version}.jar` : copiez-le dans `mods/` d'une instance NeoForge.
Tester directement : `./gradlew runClient`. `./gradlew test` (aussi lancé par `build`) charge le jeu et le
mod dans JUnit, sans fenêtre, et vérifie chaque bloc.

## Contenu

- `src/main/java/…/ModContent.java` : enregistrement (DeferredRegister) des blocs, items et de l'onglet créatif.
- `src/main/resources/assets/{modid}/` : modèles, textures (animées : `.png.mcmeta`), blockstates, items, noms.
- `src/main/resources/data/` : tables de butin (format 26.3) et tags d'outil.

Ce projet est régénéré par `python -m pixvox mod … --loader neoforge` : modifiez plutôt les assets pixvox.
"""
    return f"""# {title} — mod Fabric pour Minecraft {FABRIC['minecraft']} (généré par pixvox)

| identifiant | type |
|---|---|
{rows}

## Construire le .jar

Il faut un **JDK {FABRIC['java']}** (par ex. Temurin 25). Puis, dans ce dossier :

```
./gradlew build          # Windows : gradlew.bat build
```

Le mod est dans `build/libs/{modid}-{version}.jar`. Copiez-le dans le dossier `mods/` d'une instance
Fabric {FABRIC['minecraft']} (Fabric Loader ≥ {FABRIC['loader']}) avec **Fabric API**.

Tester directement : `./gradlew runClient` lance le jeu avec le mod (compte de développement hors ligne).
`./gradlew test` (aussi lancé par `build`) démarre les registres du jeu sans l'ouvrir et vérifie chaque bloc.

## Contenu

- `src/main/java/…/ModContent.java` : enregistrement des blocs (dureté, son, lumière, formes…).
- `src/main/resources/assets/{modid}/` : modèles, textures (animées : `.png.mcmeta`), blockstates, items, noms.
- `src/main/resources/data/` : tables de butin (format 26.3) et tags d'outil.

Ce projet est régénéré par `python -m pixvox mod …` : modifiez plutôt les fichiers d'assets pixvox.
"""


def _zip_project(root: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if p.is_file() and rel.parts[0] not in (".gradle", "build", "run") and p.name != MARKER:
                info = zipfile.ZipInfo(f"{root.name}/{rel.as_posix()}")
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if p.name == "gradlew" else 0o644) << 16
                z.writestr(info, p.read_bytes())


def _java_exe(home) -> Path:
    return Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")


def find_java(java_home: str | None = None) -> str | None:
    """Dossier d'un JDK : java_home, $JAVA_HOME, ou le `java` du PATH (la version se lit avec java_version)."""
    cands = [java_home, os.environ.get("JAVA_HOME")]
    for c in cands:
        if c and _java_exe(c).exists():
            return c
    j = shutil.which("java")
    if j:
        return str(Path(os.path.realpath(j)).parent.parent)
    return None


def java_version(java_home: str | None) -> int | None:
    """Version majeure du JDK (25 pour « 25.0.1 »), ou None si illisible."""
    if not java_home:
        return None
    try:
        r = subprocess.run([str(_java_exe(java_home)), "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'version "(\d+)(?:\.(\d+))?', r.stderr + r.stdout)
    if not m:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major          # « 1.8 » -> 8


def required_java(mc: str | None = None) -> int:
    """Version de JDK qu'exige la compilation d'un mod de cette cible."""
    return NEOFORGE_1_21_1["java"] if mc == "1.21.1" else FABRIC["java"]


def build_mod(project, java_home: str | None = None, timeout: int = 1800, quiet: bool = False,
              java: int | None = None) -> Path:
    """Compile le projet avec le Gradle wrapper. Retourne le chemin du .jar ; le journal complet est
    écrit dans build_log.txt."""
    project = Path(project)
    need = java or FABRIC["java"]
    jh = find_java(java_home)
    if jh is None:
        raise RuntimeError(f"JDK {need} introuvable : passez java_home=… ou définissez JAVA_HOME")
    ver = java_version(jh)
    if ver is not None and ver < need:
        raise RuntimeError(f"JDK {ver} trouvé dans {jh}, il faut un JDK {need} ou plus récent")
    env = dict(os.environ, JAVA_HOME=jh, PATH=f"{Path(jh) / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    wrapper = project.resolve() / ("gradlew.bat" if os.name == "nt" else "gradlew")
    cmd = [str(wrapper), "build", "--no-daemon", "--console=plain", "--stacktrace"]
    r = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    log = r.stdout + "\n" + r.stderr
    (project / "build_log.txt").write_text(log, encoding="utf-8")
    if r.returncode != 0:
        errs = [ln for ln in log.splitlines() if "error:" in ln or "FAILURE" in ln or "What went wrong" in ln]
        raise RuntimeError("échec de la compilation :\n" + "\n".join(errs[:30] or log.splitlines()[-40:]))
    jars = [p for p in (project / "build" / "libs").glob("*.jar") if not p.name.endswith("-sources.jar")]
    if not jars:
        raise RuntimeError("compilation terminée mais aucun .jar trouvé")
    if not quiet:
        say(f"[mod] compilation OK -> {jars[0]}")
    return jars[0]
