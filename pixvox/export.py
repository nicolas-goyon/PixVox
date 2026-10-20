"""pixvox.export — export Minecraft Java Edition (resource pack) et optimisation des modèles voxel.

Disposition produite (namespace `pixvox` par défaut) :
  assets/<ns>/textures/block/<nom>[_face].png     textures des blocs / atlas des modèles voxel
  assets/<ns>/textures/item/<nom>.png             textures des items plats
  assets/<ns>/models/block/<nom>.json             modèle (éléments explicites, UV explicites)
  assets/<ns>/models/item/<nom>.json              items plats (item/generated)
  assets/<ns>/blockstates/<nom>.json              pour un mod qui enregistre le bloc <ns>:<nom>
  assets/<ns>/items/<nom>.json                    définition d'item (1.21.4+) -> composant item_model

Textures animées : bande verticale PNG + <texture>.png.mcmeta. Pour un modèle animé, les faces fixes
vont dans l'atlas statique (#0), les faces qui changent dans un atlas animé (#1) ; les plans texturés
(flammes…) ont chacun leur texture (#p0, #p1…).

Chaque export est re-rendu depuis les fichiers écrits (JSON + PNG relus du disque) avec un moteur
indépendant (pixvox.mcmodel) puis comparé au rendu direct du volume : « vérification d'export » — pour
chaque image d'une animation.
"""
from __future__ import annotations

import itertools
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from ._io import MARKER, mark_output_dir, prepare_output_dir, say
from .anim import Anim, preview_ticks
from .assets import Block, Item, Model, MultiBlock, Plane
from .mcmodel import ModelLoader
from .render import BACK, INVENTORY, compare, fit_camera, quads_from_volume, render, rot_matrix
from .volume import FACES, NORMALS, face_coords


class ExportError(ValueError):
    """Asset refusé à l'export (le jeu ne chargerait pas le modèle)."""


def check_bounds(name: str, elements: list) -> None:
    """Minecraft refuse un modèle dont un élément sort de [-16, 32] (from/to, avant rotation)."""
    bad = [e for e in elements if min(e["from"] + e["to"]) < -16 or max(e["from"] + e["to"]) > 32]
    if bad:
        lo = min(min(e["from"] + e["to"]) for e in bad)
        hi = max(max(e["from"] + e["to"]) for e in bad)
        raise ExportError(f"{name} : {len(bad)} élément(s) hors des limites [-16, 32] du jeu (de {lo:g} à {hi:g}) — "
                          "Minecraft refuserait ce modèle. Réduire l'objet (Volume.design(…, scale=…), voxel_size), "
                          "raccourcir les plans, ou en faire un MultiBlock")


PACK_MIN_FORMAT = 46     # 1.21.4 : dossier items/ + composant item_model
PACK_MAX_FORMAT = 97     # 26.3 (format 97.1) — dernière version connue lors de l'écriture
DATAPACK_MIN_FORMAT = 61  # 1.21.4 (data pack)
DATAPACK_MAX_FORMAT = 121  # 26.3 (data pack ; à confirmer sur le wiki)


def _zip_dir(root: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file() and p.name != MARKER:
                z.write(p, p.relative_to(root).as_posix())


def _num(x: float):
    x = float(x)
    return int(round(x)) if abs(x - round(x)) < 1e-9 else round(x, 5)


# ============================================================================ découpage en boîtes
def greedy_boxes(required: np.ndarray, fillable: np.ndarray, order=(0, 2, 1), used: np.ndarray | None = None):
    """Découpe gloutonne en boîtes : couvre tous les voxels `required`, peut englober des voxels
    `fillable` (jokers, ex. voxels cachés), jamais deux fois le même voxel."""
    shape = required.shape
    used = np.zeros(shape, bool) if used is None else used
    boxes = []
    a0, a1, a2 = order
    for i2 in range(shape[a2]):
        for i1 in range(shape[a1]):
            for i0 in range(shape[a0]):
                p = [0, 0, 0]
                p[a0], p[a1], p[a2] = i0, i1, i2
                p = tuple(p)
                if not required[p] or used[p]:
                    continue
                lo = list(p)
                hi = [p[0] + 1, p[1] + 1, p[2] + 1]
                for ax in (a0, a1, a2):
                    while hi[ax] < shape[ax]:
                        region = tuple(slice(lo[k], hi[k]) if k != ax else slice(hi[ax], hi[ax] + 1)
                                       for k in range(3))
                        if fillable[region].all() and not used[region].any():
                            hi[ax] += 1
                        else:
                            break
                used[tuple(slice(lo[k], hi[k]) for k in range(3))] = True
                boxes.append((tuple(lo), tuple(hi)))
    return boxes


def _exposed_any(vol, face, lo, hi) -> bool:
    X, Y, Z = face_coords(face, lo, hi)
    n = NORMALS[face]
    nx, ny, nz = X + n[0], Y + n[1], Z + n[2]
    sx, sy, sz = vol.shape
    out = (nx < 0) | (ny < 0) | (nz < 0) | (nx >= sx) | (ny >= sy) | (nz >= sz)
    solid = vol.solid
    inside = ~out
    nb_solid = np.zeros_like(out)
    nb_solid[inside] = solid[nx[inside], ny[inside], nz[inside]]
    return bool((out | ~nb_solid).any())


# ============================================================================ atlas
@dataclass
class Atlas:
    image: np.ndarray                              # image 0 (size, size, 4)
    size: int
    rects: dict = field(default_factory=dict)       # clé patch -> (x, y, w, h) en texels
    frames: list = field(default_factory=list)      # toutes les images (atlas animé) ; [image] sinon

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    def strip(self) -> np.ndarray:
        """Bande verticale de toutes les images (PNG d'une texture animée)."""
        return np.concatenate(self.frames, axis=0) if self.frames else self.image

    def uv(self, key) -> list:
        x, y, w, h = self.rects[key]
        k = 16.0 / self.size
        return [_num(x * k), _num(y * k), _num((x + w) * k), _num((y + h) * k)]


def _as_t(p: np.ndarray) -> np.ndarray:
    """Patch (h, w, 4) -> (1, h, w, 4) ; un patch animé est déjà (T, h, w, 4)."""
    return p if p.ndim == 4 else p[None]


def atlas_key_for(p: np.ndarray):
    """Clé de dédoublonnage : patch uni à chaque image -> pastille ; sinon le contenu complet."""
    p4 = _as_t(p)
    flat = p4.reshape(p4.shape[0], -1, 4)
    if (flat == flat[:, :1]).all():
        return ("swatch", flat[:, 0].tobytes())
    return ("patch", p4.shape, p4.tobytes())


def _is_static(p4: np.ndarray) -> bool:
    return p4.shape[0] == 1 or bool((p4 == p4[:1]).all())


def pack_atlas(patches: list, min_size: int = 16, max_size: int = 1024) -> Atlas:
    """Range des patchs dans une texture carrée puissance de 2 (rangement par étagères).
    patchs (h, w, 4), ou (T, h, w, 4) pour un atlas animé (même T pour tous ; une image d'atlas par
    image d'animation, même disposition). Les patchs identiques sont dédoublonnés ; un patch uni
    devient une pastille 2x2."""
    items = {}
    T = None
    for p in patches:
        p4 = _as_t(np.asarray(p))
        if T is None:
            T = p4.shape[0]
        elif p4.shape[0] != T:
            raise ValueError("patchs animés de longueurs différentes")
        key = atlas_key_for(p4)
        if key in items:
            continue
        if key[0] == "swatch":
            flat = p4.reshape(T, -1, 4)
            items[key] = np.broadcast_to(flat[:, 0][:, None, None, :], (T, 2, 2, 4)).copy()
        else:
            items[key] = p4
    T = T or 1
    order = sorted(items.items(), key=lambda kv: (-kv[1].shape[1], -kv[1].shape[2]))
    size = min_size
    while size <= max_size:
        x = y = shelf = 0
        rects = {}
        ok = True
        for key, p in order:
            h, w = p.shape[1:3]
            x += x % 2
            if x + w > size:
                y += shelf
                y += y % 2
                x, shelf = 0, 0
            if y + h > size or w > size:
                ok = False
                break
            rects[key] = (x, y, w, h)
            x += w
            shelf = max(shelf, h)
        if ok:
            img = np.zeros((T, size, size, 4), np.uint8)
            for key, (px, py, w, h) in rects.items():
                img[:, py:py + h, px:px + w] = items[key]
            atlas = Atlas(img[0], size, {}, [img[t] for t in range(T)])
            for key, r in rects.items():
                atlas.rects[key] = (r[0], r[1], 1, 1) if key[0] == "swatch" else r
            return atlas
        size *= 2
    raise ValueError(f"atlas trop grand (> {max_size} px) : réduisez la taille du modèle")


def _atlases(stacks) -> tuple:
    """Sépare les faces fixes (atlas statique, texture #0) et celles qui changent (atlas animé, #1).
    stacks : liste de {face: pile (T, h, w, 4)}."""
    static = [p[0] for fl in stacks for p in fl.values() if _is_static(p)]
    anim = [p for fl in stacks for p in fl.values() if not _is_static(p)]
    return (pack_atlas(static) if static else None), (pack_atlas(anim) if anim else None)


def _face_json(p4, a0: Atlas | None, a1: Atlas | None) -> dict:
    if _is_static(p4):
        return {"uv": a0.uv(atlas_key_for(p4[0])), "texture": "#0"}
    return {"uv": a1.uv(atlas_key_for(p4)), "texture": "#1"}


# ============================================================================ modèle voxel -> éléments
@dataclass
class ModelExport:
    strategy: str
    elements: list
    atlas: Atlas | None                 # faces fixes (texture #0)
    n_faces: int
    alternatives: dict
    anim_atlas: Atlas | None = None     # faces animées (texture #1), une image par image d'animation

    @property
    def main_atlas(self) -> Atlas:
        return self.atlas if self.atlas is not None else self.anim_atlas

    @property
    def texture_size(self) -> int:
        return max(a.size for a in (self.atlas, self.anim_atlas) if a is not None)


def _stack(frames) -> np.ndarray:
    return np.stack([f.data for f in frames])          # (T, sx, sy, sz, 4)


def _face_stacks(datas, vol, boxes) -> list:
    """Pour chaque boîte (lo, hi, émissive) : {face: pile (T, H, W, 4)} des faces exposées."""
    out = []
    for lo, hi, _ in boxes:
        fl = {}
        for f in FACES:
            if _exposed_any(vol, f, lo, hi):
                X, Y, Z = face_coords(f, lo, hi)
                fl[f] = datas[:, X, Y, Z]
        out.append(fl)
    return out


def _build(datas, vol, boxes, voxel_size, origin, emission: int = 15):
    stacks = _face_stacks(datas, vol, boxes)
    a0, a1 = _atlases(stacks)
    elements = []
    nf = 0
    for (lo, hi, em), fl in zip(boxes, stacks):
        if not fl:
            continue
        frm = [_num(origin[k] + lo[k] * voxel_size) for k in range(3)]
        to = [_num(origin[k] + hi[k] * voxel_size) for k in range(3)]
        faces = {}
        for f, p4 in fl.items():
            fd = _face_json(p4, a0, a1)
            n = NORMALS[f]
            k = [i for i in range(3) if n[i] != 0][0]
            coord = to[k] if n[k] > 0 else frm[k]
            if (n[k] > 0 and abs(coord - 16) < 1e-9) or (n[k] < 0 and abs(coord) < 1e-9):
                fd["cullface"] = f
            faces[f] = fd
            nf += 1
        el = {"from": frm, "to": to, "faces": faces}
        if em and emission:
            el["light_emission"] = int(emission)
        elements.append(el)
    return elements, a0, a1, nf


def _best_boxes(req, fil, used0):
    """Meilleur découpage glouton (6 ordres d'axes) ; renvoie (boîtes, masque des voxels utilisés)."""
    best = None
    for order in itertools.permutations((0, 1, 2)):
        u = used0.copy()
        b = greedy_boxes(req, fil, order, u)
        if best is None or len(b) < len(best[0]):
            best = (b, u)
    return best


def optimize_model(model: Model, strategy: str = "auto") -> ModelExport:
    """Convertit le volume en éléments Minecraft.

    'boxes'   : boîtes par forme (peu d'éléments) + atlas de patchs texturés ;
    'palette' : boîtes par couleur (plus d'éléments) + minuscule texture palette ;
    'auto'    : garde la meilleure (éléments d'abord, puis taille de texture).
    Les voxels cachés servent de jokers pour fusionner davantage. Un volume animé est traité image par
    image avec la MÊME géométrie (faces fixes -> atlas #0, faces qui changent -> atlas animé #1) ; les
    voxels `emissive` forment des éléments à part (light_emission).
    """
    vol = model.volume
    frames = getattr(model, "frames", [vol])
    datas = _stack(frames)
    surface = vol.m_surface()
    hidden = vol.m_hidden()
    solid = vol.solid
    E = getattr(model, "emissive", None)
    E = None if E is None else (np.asarray(E, bool) & solid)
    emission = getattr(model, "emission", 15)
    results = {}
    if strategy in ("auto", "boxes"):
        used = np.zeros(vol.shape, bool)
        boxes = []
        groups = [(False, solid)] if E is None else [(True, E), (False, solid & ~E)]
        for em, fil in groups:
            req = surface & fil
            if req.any():
                b, used = _best_boxes(req, fil | (hidden & ~used), used)
                boxes += [(lo, hi, em) for lo, hi in b]
        results["boxes"] = _build(datas, vol, boxes, model.voxel_size, model.origin, emission)
    if strategy in ("auto", "palette"):
        T = datas.shape[0]
        vox = np.moveaxis(datas, 0, 3).reshape(vol.shape + (T * 4,))
        if E is not None:
            vox = np.concatenate([vox, E[..., None].astype(np.uint8)], axis=-1)
        sel = solid.reshape(-1)
        flat = vox.reshape(-1, vox.shape[-1])
        keys, inv, counts = np.unique(flat[sel], axis=0, return_inverse=True, return_counts=True)
        label = np.full(sel.shape, -1)
        label[sel] = np.asarray(inv).ravel()
        label = label.reshape(vol.shape)
        best = None
        for order in itertools.permutations((0, 1, 2)):
            used = np.zeros(vol.shape, bool)
            boxes = []
            for ci in np.argsort(-counts):
                same = label == ci
                em = bool(keys[ci][-1]) if E is not None else False
                boxes += [(lo, hi, em) for lo, hi in greedy_boxes(same & surface, same | hidden, order, used)]
            if best is None or len(boxes) < len(best):
                best = boxes
        # colore les voxels-jokers de chaque boîte avec la couleur de la boîte (faces unies, chaque image)
        datas2 = datas.copy()
        for lo, hi, _ in best:
            region = tuple(slice(lo[k], hi[k]) for k in range(3))
            vis = surface[region]
            if vis.any():
                sub = datas2[(slice(None),) + region]
                sub[...] = sub[:, vis][:, 0][:, None, None, None, :]
        results["palette"] = _build(datas2, vol, best, model.voxel_size, model.origin, emission)
    summary = {k: {"elements": len(v[0]), "faces": v[3],
                   "texture": max(a.size for a in (v[1], v[2]) if a is not None)} for k, v in results.items()}
    if strategy == "auto" and len(results) == 2:
        a, b = summary["boxes"], summary["palette"]
        pick = "palette" if b["elements"] <= a["elements"] * 1.15 else "boxes"
    else:
        pick = next(iter(results))
    el, a0, a1, nf = results[pick]
    return ModelExport(pick, el, a0, nf, summary, a1)


def plane_element(p: Plane, tex_key: str) -> dict:
    """Élément Minecraft d'épaisseur nulle pour un plan : faces avant/arrière, texture entière.
    Rotation limitée à ±45° (au-delà, le plan est posé sur l'autre axe) : valide avant 1.21.11 tant que
    l'angle est un multiple de 22,5°."""
    a = p.norm_angle()
    cx, cz = p.center
    w, h, y = p.width, p.height, p.y
    if abs(a) <= 45:
        frm, to, faces, rot = [cx - w / 2, y, cz], [cx + w / 2, y + h, cz], ("north", "south"), a
    else:
        frm, to, faces, rot = [cx, y, cz - w / 2], [cx, y + h, cz + w / 2], ("west", "east"), (a - 90 if a > 0 else a + 90)
    el = {"from": [_num(v) for v in frm], "to": [_num(v) for v in to],
          "faces": {f: {"uv": [0, 0, 16, 16], "texture": "#" + tex_key} for f in faces}}
    if abs(rot) > 1e-9:
        el["rotation"] = {"origin": [_num(cx), _num(y), _num(cz)], "axis": "y", "angle": _num(round(rot, 4))}
    if p.emission:
        el["light_emission"] = int(p.emission)
    if not p.shade:
        el["shade"] = False                              # 1.21.4 … 26.2
        el["shade_direction_override"] = "up"            # 26.3+ (le champ "shade" y est ignoré)
    return el


def asset_ticks(asset, max_frames: int = 48) -> list:
    """Ticks à vérifier : le début de chaque image de chaque animation de l'asset."""
    return preview_ticks(getattr(asset, "anims", []), max_frames, starts_only=True)


# ============================================================================ multibloc
@dataclass
class MultiExport:
    elements: dict           # cellule (bx, by, bz) -> éléments en coordonnées locales [0, 16]
    miniature: ModelExport  # objet entier ré-échantillonné pour tenir dans un bloc (icône d'inventaire)
    mini_model: Model
    atlas: Atlas | None       # faces fixes (#0), partagé par toutes les parties
    stats: dict
    anim_atlas: Atlas | None = None   # faces animées (#1)

    @property
    def main_atlas(self) -> Atlas:
        return self.atlas if self.atlas is not None else self.anim_atlas


def miniature_model(mb: MultiBlock) -> Model:
    """Miniature d'inventaire : le volume ré-échantillonné (couleur majoritaire) pour tenir dans 16³
    voxels vanilla, centré dans le bloc. Bien plus léger que l'objet entier mis à l'échelle."""
    sx, sy, sz = mb.volume.shape
    f = min(1.0, 16.0 / max(sx, sy, sz))
    small = [fr.resample(factor=f, threshold=0.25) if f < 1 else fr.copy() for fr in mb.frames]   # fins gardés
    for v in small:
        v.res, v.vpu = 16, 1.0
    tx, ty, tz = small[0].shape
    t = mb.timing
    em = None
    if getattr(mb, "emissive", None) is not None:
        from .volume import Volume
        mask = Volume(*mb.volume.shape)
        mask.data[mb.volume.solid] = (0, 0, 0, 255)
        mask.data[mb.volume.solid & mb.emissive] = (255, 255, 255, 255)
        ms = mask.resample(factor=f, threshold=0.25) if f < 1 else mask
        em = (ms.data[..., 0] > 127) & small[0].solid
    return Model(f"{mb.name}_mini", small if len(small) > 1 else small[0], voxel_size=1.0,
                 origin=((16 - tx) / 2, (16 - ty) / 2, (16 - tz) / 2), frametime=t.frametime,
                 interpolate=t.interpolate, order=t.order, emissive=em, emission=getattr(mb, "emission", 15))


def optimize_multiblock(mb: MultiBlock) -> MultiExport:
    """Découpe l'objet en parties d'un bloc, chacune optimisée (boîtes gloutonnes, 6 ordres d'axes),
    les faces cachées étant calculées sur l'objet ENTIER (pas de faces internes entre deux parties).
    Un atlas est partagé par toutes les parties (plus un atlas animé si l'objet est animé)."""
    vol = mb.volume
    datas = _stack(mb.frames)
    surface, solid = vol.m_surface(), vol.solid
    r = mb.res
    vs = mb.voxel_size
    parts = {}
    E = getattr(mb, "emissive", None)
    E = None if E is None else (np.asarray(E, bool) & solid)
    hidden = solid & ~surface
    for cell in mb.cells():
        c0 = [cell[k] * r for k in range(3)]
        sl = tuple(slice(c0[k], min(c0[k] + r, vol.shape[k])) for k in range(3))
        groups = [(False, solid[sl])] if E is None else [(True, E[sl]), (False, solid[sl] & ~E[sl])]
        used = np.zeros(solid[sl].shape, bool)
        boxes = []
        for em, fil in groups:
            req = surface[sl] & fil
            if req.any():
                b, used = _best_boxes(req, fil | (hidden[sl] & ~used), used)
                boxes += [(lo, hi, em) for lo, hi in b]
        bf = []
        for lo, hi, em in boxes:
            glo = tuple(lo[k] + c0[k] for k in range(3))
            ghi = tuple(hi[k] + c0[k] for k in range(3))
            fl = {}
            for f in FACES:
                if _exposed_any(vol, f, glo, ghi):
                    X, Y, Z = face_coords(f, glo, ghi)
                    fl[f] = datas[:, X, Y, Z]
            if fl:
                bf.append((glo, ghi, fl, em))
        if bf:
            parts[cell] = bf
    a0, a1 = _atlases([fl for bf in parts.values() for _, _, fl, _ in bf])

    def elements_for(bf, scale, offset, cull):
        els = []
        for lo, hi, fl, em in bf:
            frm = [_num(offset[k] + lo[k] * scale) for k in range(3)]
            to = [_num(offset[k] + hi[k] * scale) for k in range(3)]
            faces = {}
            for f, p4 in fl.items():
                fd = _face_json(p4, a0, a1)
                n = NORMALS[f]
                k = [i for i in range(3) if n[i] != 0][0]
                coord = to[k] if n[k] > 0 else frm[k]
                if cull and ((n[k] > 0 and abs(coord - 16) < 1e-9) or (n[k] < 0 and abs(coord) < 1e-9)):
                    fd["cullface"] = f
                faces[f] = fd
            el = {"from": frm, "to": to, "faces": faces}
            if em and mb.emission:
                el["light_emission"] = int(mb.emission)
            els.append(el)
        return els

    elements = {cell: elements_for(bf, vs, [-cell[k] * 16 for k in range(3)], True) for cell, bf in parts.items()}
    mm = miniature_model(mb)
    mini = optimize_model(mm)
    counts = [len(e) for e in elements.values()]
    stats = {"parts": len(elements), "elements_total": sum(counts), "elements_max": max(counts),
             "elements_min": min(counts), "texture": max(a.size for a in (a0, a1) if a is not None),
             "mini_elements": len(mini.elements), "mini_shape": mm.volume.shape,
             "animated_faces": sum(1 for bf in parts.values() for _, _, fl, _ in bf for p in fl.values()
                                   if not _is_static(p)),
             "emissive_elements": sum(1 for bf in parts.values() for *_, em in bf if em)}
    return MultiExport(elements, mini, mm, a0, stats, a1)


# ============================================================================ bloc plein
def _tex_key(t):
    if isinstance(t, Anim):
        return ("anim", t.strip().tobytes(), json.dumps(t.mcmeta(), sort_keys=True))
    return ("img", np.asarray(t.data).tobytes())


def cube_textures(block: Block) -> tuple[dict, dict]:
    """Dédoublonne les 6 faces (animées ou non). Retourne ({face: suffixe}, {suffixe: Sprite | Anim})."""
    faces = block.face_anims() if block.given_faces is None else block.faces()
    groups: dict = {}
    for f in FACES:
        groups.setdefault(_tex_key(faces[f]), []).append(f)
    face_to_suffix, textures = {}, {}
    if len(groups) == 1:
        face_to_suffix = {f: "" for f in FACES}
        textures[""] = faces["up"]
        return face_to_suffix, textures
    for fs in groups.values():
        s = set(fs)
        if s == {"north", "south", "west", "east"}:
            suf = "_side"
        elif s == {"up", "down"}:
            suf = "_end"
        elif len(fs) == 1:
            suf = {"up": "_top", "down": "_bottom"}.get(fs[0], "_" + fs[0])
        else:
            suf = "_" + "_".join(fs)
        for f in fs:
            face_to_suffix[f] = suf
        textures[suf] = faces[fs[0]]
    return face_to_suffix, textures


def glow_textures(block: Block) -> tuple[dict, dict]:
    """Surcouche lumineuse d'un bloc : ({face: suffixe}, {suffixe: Sprite | Anim}), faces dédoublonnées."""
    glow = block.glow_anims() if block.emissive is not None else {}
    groups: dict = {}
    for f, t in glow.items():
        groups.setdefault(_tex_key(t), []).append(f)
    f2s, textures = {}, {}
    for fs in groups.values():
        suf = "" if len(groups) == 1 else "_" + "_".join(fs)
        for f in fs:
            f2s[f] = suf
        textures[suf] = glow[fs[0]]
    return f2s, textures


def cube_model_json(ns: str, name: str, face_to_suffix: dict, glow_to_suffix: dict | None = None,
                    emission: int = 15) -> dict:
    tex = {f: f"{ns}:block/{name}{face_to_suffix[f]}" for f in FACES}
    tex["particle"] = tex["north"]
    elements = [{
        "from": [0, 0, 0], "to": [16, 16, 16],
        "faces": {f: {"uv": [0, 0, 16, 16], "texture": "#" + f, "cullface": f} for f in FACES},
    }]
    if glow_to_suffix:
        # surcouche aux mêmes coordonnées (comme le liseré de l'herbe vanilla), dessinée par-dessus,
        # pleinement éclairée : les pixels lumineux restent visibles dans le noir
        tex.update({f"{f}_glow": f"{ns}:block/{name}_glow{suf}" for f, suf in glow_to_suffix.items()})
        elements.append({"from": [0, 0, 0], "to": [16, 16, 16], "light_emission": int(emission),
                         "faces": {f: {"uv": [0, 0, 16, 16], "texture": f"#{f}_glow", "cullface": f}
                                   for f in FACES if f in glow_to_suffix}})
    return {"parent": "minecraft:block/block", "textures": tex, "elements": elements}


# ============================================================================ resource pack
def dumps(obj) -> str:
    """JSON indenté, mais listes de nombres sur une ligne ([0, 0, 16, 16]) : lisible et compact."""
    txt = json.dumps(obj, indent=2, ensure_ascii=False)
    return re.sub(r"\[\s+([-0-9.,\s]+?)\s+\]",
                  lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]", txt)



class ResourcePack:
    def __init__(self, root, namespace: str = "pixvox", description: str = "Créé avec pixvox",
                 min_format: int = PACK_MIN_FORMAT, max_format: int = PACK_MAX_FORMAT, mod_mode: bool = False):
        self.root = Path(root)
        self.ns = namespace
        self.description = description
        self.min_format, self.max_format = min_format, max_format
        self.entries: list[dict] = []
        self.icon_img = None
        self.functions: dict = {}           # nom -> (lignes de placement, lignes de retrait)
        self.mod_mode = mod_mode            # ressources d'un mod : un bloc par multibloc (facing + part)
        self.multi_parts: dict = {}         # nom -> [(cellule, modèle)] dans l'ordre des parties

    # -------------------------------------------------------------- écriture bas niveau
    def _p(self, *parts) -> Path:
        p = self.root.joinpath("assets", *parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _json(self, path: Path, obj) -> None:
        path.write_text(dumps(obj) + "\n", encoding="utf-8")

    def _png(self, path: Path, arr: np.ndarray) -> None:
        Image.fromarray(np.asarray(arr, np.uint8), "RGBA").save(path)

    def _texture(self, kind: str, name: str, tex, timing=None) -> str:
        """Écrit textures/<kind>/<name>.png, plus <name>.png.mcmeta si la texture est animée.
        tex : tableau (h, w, 4), Sprite, Anim, ou Atlas (animé s'il a plusieurs images : `timing`).
        Renvoie l'identifiant de texture « ns:kind/name »."""
        path = self._p(self.ns, "textures", kind, f"{name}.png")
        meta = None
        if isinstance(tex, Anim):
            arr = tex.strip() if tex.n > 1 else tex.frames[0].data
            meta = tex.mcmeta() if tex.n > 1 else None
        elif isinstance(tex, Atlas):
            arr = tex.strip() if tex.animated else tex.image
            meta = timing.mcmeta(len(tex.frames)) if tex.animated else None
        else:
            arr = np.asarray(tex.data if hasattr(tex, "data") else tex)
        self._png(path, arr)
        mpath = path.with_name(path.name + ".mcmeta")
        if meta:
            self._json(mpath, meta)
        elif mpath.exists():
            mpath.unlink()
        return f"{self.ns}:{kind}/{name}"

    def write_meta(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        meta = {"pack": {
            "description": self.description,
            "pack_format": self.min_format,
            "supported_formats": [self.min_format, self.max_format],
            "min_format": self.min_format,
            "max_format": self.max_format,
        }}
        self._json(self.root / "pack.mcmeta", meta)
        if self.icon_img is not None:
            Image.fromarray(self.icon_img).save(self.root / "pack.png")

    # -------------------------------------------------------------- assets
    def add(self, asset, replace: str | None = None) -> dict:
        if isinstance(asset, Block):
            info = self._add_block(asset)
        elif isinstance(asset, MultiBlock):
            info = self._add_multiblock(asset)
        elif isinstance(asset, Model):
            info = self._add_model(asset)
        elif isinstance(asset, Item):
            info = self._add_item(asset)
        else:
            raise TypeError(f"asset inconnu : {asset!r}")
        if replace:
            info["replace"] = self._replace_vanilla(asset, replace, info)
        self.entries.append(info)
        return info

    @staticmethod
    def variants(model_ref: str, states: str | None) -> dict:
        """Variantes de blockstate. Rotation du modèle entier (sans uvlock) : les textures tournent
        avec la géométrie, donc chaque voxel d'arête garde une seule couleur."""
        m = {"model": model_ref}
        if states == "axis":
            return {"variants": {"axis=y": m, "axis=z": {**m, "x": 90}, "axis=x": {**m, "x": 90, "y": 90}}}
        if states == "facing":
            return {"variants": {"facing=north": m, "facing=east": {**m, "y": 90},
                                 "facing=south": {**m, "y": 180}, "facing=west": {**m, "y": 270}}}
        return {"variants": {"": m}}

    def _block_common(self, name: str, model_ref: str, states: str | None = None) -> None:
        self._json(self._p(self.ns, "blockstates", f"{name}.json"), self.variants(model_ref, states))
        self._json(self._p(self.ns, "items", f"{name}.json"),
                   {"model": {"type": "minecraft:model", "model": model_ref}})

    def _add_block(self, b: Block) -> dict:
        f2s, textures = cube_textures(b)
        for suf, t in textures.items():
            self._texture("block", f"{b.name}{suf}", t)
        g2s, glow = glow_textures(b)
        for suf, t in glow.items():
            self._texture("block", f"{b.name}_glow{suf}", t)
        model = cube_model_json(self.ns, b.name, f2s, g2s, b.emission)
        warnings = []
        if glow:
            warnings.append("surcouche lumineuse : rendu correct en 26.x (couche déduite des textures) ; avant 26.x il "
                            "faut un bloc en rendu cutout (mod, ou --replace sur un bloc cutout comme minecraft:glass), "
                            "sinon la face entière paraît pleinement éclairée")
        rt = b.effective_render_type()
        if rt != "solid":
            model["render_type"] = f"minecraft:{rt}"     # NeoForge ≤ 1.21.x ; en 26.x déduit des textures
        ref = f"{self.ns}:block/{b.name}"
        self._json(self._p(self.ns, "models", "block", f"{b.name}.json"), model)
        self._block_common(b.name, ref, b.states)
        diff = self._verify_ticks(ref, b, b.quads)
        self._icon_from(b.quads(0))
        n_anim = sum(isinstance(t, Anim) for t in list(textures.values()) + list(glow.values()))
        return {"name": b.name, "kind": "bloc", "model": ref, "textures": len(textures), "elements": len(model["elements"]),
                "glow_faces": len(g2s), "warnings": warnings,
                "verify": diff, "render_type": rt, "animated": n_anim,
                "layout": "1 texture" if len(textures) == 1 else ", ".join(
                    sorted({s.strip("_") or "all" for s in f2s.values()}))}

    @staticmethod
    def _alpha_kind(arrays) -> str:
        """'translucent' (alpha partiel), 'cutout' (pixels 100 % transparents) ou 'solid'."""
        semi = cut = False
        for a in arrays:
            al = np.asarray(a)[..., 3]
            semi |= bool(((al > 0) & (al < 255)).any())
            cut |= bool((al == 0).any())
        return "translucent" if semi else ("cutout" if cut else "solid")

    def _add_model(self, m: Model) -> dict:
        opt = optimize_model(m)
        elements = list(opt.elements)
        plane_vars: dict = {}
        plane_tex: dict = {}
        for pl in m.planes:
            k = _tex_key(pl.texture)
            if k not in plane_vars:
                var = f"p{len(plane_vars)}"
                plane_vars[k] = var
                plane_tex[var] = pl.texture
            elements.append(plane_element(pl, plane_vars[k]))
        check_bounds(m.name, elements)                  # avant d'écrire quoi que ce soit
        tex = {}
        if opt.atlas is not None:
            tex["0"] = self._texture("block", m.name, opt.atlas)
        if opt.anim_atlas is not None:
            tex["1"] = self._texture("block", f"{m.name}_anim", opt.anim_atlas, m.timing)
        for var, t in plane_tex.items():
            tex[var] = self._texture("block", f"{m.name}_{var}", t)
        tex["particle"] = tex.get("0") or tex.get("1") or next(iter(tex.values()))
        warnings = []
        odd = sorted({round(pl.norm_angle(), 3) for pl in m.planes
                      if abs(pl.norm_angle() / 22.5 - round(pl.norm_angle() / 22.5)) > 1e-6})
        if odd:
            warnings.append(f"plans à {odd}° : ce modèle ne chargera qu'à partir de 1.21.11 (avant : multiples de "
                            "22,5° seulement) alors que le pack annonce 1.21.4+")
        model = {"parent": "minecraft:block/block", "textures": tex, "elements": elements}
        if not m.ambient_occlusion:
            model["ambientocclusion"] = False
        if m.inventory_scale or m.inventory_center:
            sc, c = m.gui_transform()
            t = -(rot_matrix(*INVENTORY) @ (sc * (np.asarray(c, float) - 8.0)))
            t = np.clip(t, -80, 80)
            model["display"] = {"gui": {"rotation": [30, 225, 0],
                                        "translation": [_num(round(float(x), 3)) for x in t],
                                        "scale": [_num(round(sc, 4))] * 3}}
        surf = np.stack([f.data for f in m.frames])[:, m.volume.m_surface()]
        rt = self._alpha_kind([surf] + [pl.texture.strip() if isinstance(pl.texture, Anim) else pl.texture.data
                                        for pl in m.planes])
        if rt != "solid":
            model["render_type"] = f"minecraft:{rt}"
        ref = f"{self.ns}:block/{m.name}"
        self._json(self._p(self.ns, "models", "block", f"{m.name}.json"), model)
        self._block_common(m.name, ref, m.states)
        diff = self._verify_ticks(ref, m, m.quads)
        self._icon_from(m.quads(0))
        n_emit = sum(1 for e in opt.elements if e.get("light_emission"))
        return {"name": m.name, "kind": "modèle", "model": ref, "elements": len(elements),
                "voxel_elements": len(opt.elements), "planes": len(m.planes), "emissive_elements": n_emit,
                "faces": opt.n_faces, "texture_size": opt.texture_size, "strategy": opt.strategy,
                "alternatives": opt.alternatives, "verify": diff, "render_type": rt, "warnings": warnings,
                "animated": int(opt.anim_atlas is not None) + sum(isinstance(t, Anim) and t.n > 1 for t in
                                                                  {id(p.texture): p.texture for p in m.planes}.values())}

    def _add_multiblock(self, mb: MultiBlock) -> dict:
        opt = optimize_multiblock(mb)
        tex = {}
        if opt.atlas is not None:
            tex["0"] = self._texture("block", mb.name, opt.atlas)
        if opt.anim_atlas is not None:
            tex["1"] = self._texture("block", f"{mb.name}_anim", opt.anim_atlas, mb.timing)
        tex["particle"] = tex.get("0") or tex.get("1")
        base = {"parent": "minecraft:block/block", "textures": tex}
        if not mb.ambient_occlusion:
            base["ambientocclusion"] = False
        nx, ny, nz = mb.blocks
        ax, az = nx // 2, nz // 2
        place = [f"# {mb.name} : {nx} x {ny} x {nz} blocs, {len(opt.elements)} parties. Posé centré sur le bloc "
                 "d'exécution, face avant vers le NORD.",
                 "# Rotation:[180f,0f] compense la rotation de 180° des item_display (depuis 1.20)."]
        loader_refs = []
        parts = []
        for (bx, by, bz), els in sorted(opt.elements.items()):
            pid = f"{mb.name}_{bx}_{by}_{bz}"
            ref = f"{self.ns}:block/{mb.name}/{bx}_{by}_{bz}"
            self._json(self._p(self.ns, "models", "block", mb.name, f"{bx}_{by}_{bz}.json"), {**base, "elements": els})
            if not self.mod_mode:
                self._block_common(pid, ref)
            parts.append(((bx, by, bz), ref))
            loader_refs.append((ref, (bx * 16, by * 16, bz * 16)))
            place.append(f"execute align xyz run summon minecraft:item_display ~{bx - ax + 0.5:g} ~{by + 0.5:g} "
                         f"~{bz - az + 0.5:g} {{Rotation:[180f,0f],item:{{id:\"minecraft:stone\",count:1,"
                         f"components:{{\"minecraft:item_model\":\"{self.ns}:{pid}\"}}}},"
                         f"Tags:[\"pixvox\",\"pixvox.{mb.name}\"]}}")
        remove = [f"kill @e[type=minecraft:item_display,tag=pixvox.{mb.name},distance=..{2 * max(mb.blocks) + 2}]"]
        self.multi_parts[mb.name] = parts
        if not self.mod_mode:
            self.functions[mb.name] = (place, remove)
        mref = f"{self.ns}:block/{mb.name}"
        mtex = {}
        if opt.miniature.atlas is not None:
            mtex["0"] = self._texture("block", f"{mb.name}_mini", opt.miniature.atlas)
        if opt.miniature.anim_atlas is not None:
            mtex["1"] = self._texture("block", f"{mb.name}_mini_anim", opt.miniature.anim_atlas, mb.timing)
        mtex["particle"] = mtex.get("0") or mtex.get("1")
        self._json(self._p(self.ns, "models", "block", f"{mb.name}.json"),
                   {"parent": "minecraft:block/block", "textures": mtex, "elements": opt.miniature.elements})
        self._json(self._p(self.ns, "items", f"{mb.name}.json"), {"model": {"type": "minecraft:model", "model": mref}})

        # vérification : toutes les parties relues sur disque et remises en place == volume (chaque image)
        def parts_from_disk(tick):
            loader = ModelLoader([self.root], tick=tick)
            q = []
            for ref, off in loader_refs:
                q += loader.quads(ref, offset=off)
            return q
        diff = self._verify_ticks(None, mb, mb.quads, parts_from_disk)
        mm = opt.mini_model
        dmini = self._verify_ticks(mref, mm, mm.quads)
        diff["diff_px"] += dmini["diff_px"]
        diff["views"] += dmini["views"]
        diff["missing"] = sorted(set(diff["missing"]) | set(dmini["missing"]))
        self._icon_from(mb.quads(0))
        return {"name": mb.name, "kind": "multibloc", "model": mref, "parts": len(opt.elements),
                "elements": opt.stats["elements_total"], "elements_max": opt.stats["elements_max"],
                "texture_size": opt.stats["texture"], "blocks": mb.blocks, "verify": diff,
                "animated": int(opt.anim_atlas is not None)}

    def _add_item(self, it: Item) -> dict:
        src = it.anim if it.anim is not None else it.sprite
        self._texture("item", it.name, src)
        ref = f"{self.ns}:item/{it.name}"
        self._json(self._p(self.ns, "models", "item", f"{it.name}.json"),
                   {"parent": "minecraft:item/generated", "textures": {"layer0": ref}})
        self._json(self._p(self.ns, "items", f"{it.name}.json"),
                   {"model": {"type": "minecraft:model", "model": ref}})
        diff = 0
        ticks = asset_ticks(it, 64)
        for t in ticks:                               # chaque image relue sur disque == image voulue
            loader = ModelLoader([self.root], tick=t)
            back = loader.texture(ref)
            diff += int((np.abs(back.astype(int) - it.sprite_at(t).astype(int)).max(-1) > 0).sum())
        if self.icon_img is None:
            self.icon_img = np.array(it.sprite.to_image(8))
        return {"name": it.name, "kind": "item", "model": ref,
                "verify": {"diff_px": diff, "views": len(ticks), "ticks": len(ticks), "missing": []},
                "animated": int(it.animated)}

    def _replace_vanilla(self, asset, target: str, info: dict) -> str:
        """Remplace l'apparence d'un bloc/item vanilla SANS propriétés (stone, dirt, iron_ore…)
        pour tester tout de suite en jeu."""
        if isinstance(asset, MultiBlock):
            raise ExportError(f"{asset.name} : --replace ne s'applique pas à un MultiBlock (plusieurs blocs) ; "
                              "utiliser le datapack de placement, ou un mod (python -m pixvox mod …)")
        t = target.split(":", 1)[-1]
        if isinstance(asset, Item):
            self._json(self._p("minecraft", "items", f"{t}.json"),
                       {"model": {"type": "minecraft:model", "model": info["model"]}})
            return f"item minecraft:{t} -> {info['model']}"
        self._json(self._p("minecraft", "blockstates", f"{t}.json"), self.variants(info["model"], asset.states))
        self._json(self._p("minecraft", "items", f"{t}.json"),
                   {"model": {"type": "minecraft:model", "model": info["model"]}})
        return f"bloc + item minecraft:{t} -> {info['model']}"

    def _icon_from(self, vol) -> None:
        if self.icon_img is not None:
            return
        q = vol if isinstance(vol, list) else quads_from_volume(vol)
        self.icon_img = render(q, fit_camera(q, INVENTORY, 128, 128, 0.05), shading="gui")

    # -------------------------------------------------------------- vérification
    def verify(self, model_ref: str | None, vol, offset=(0, 0, 0), voxel_size: float = 1.0,
               views=(INVENTORY, BACK, (135, 25), (315, -40), (0, 89.9), (90, 0)), quads=None,
               tick: float = 0) -> dict:
        """Relit le modèle et les PNG écrits sur disque (image affichée au tick `tick` pour une texture
        animée), les rend comme Minecraft, et compare au rendu de référence (le volume, ou une liste de
        quads) sous plusieurs angles. 0 pixel différent = export fidèle."""
        loader = ModelLoader([self.root], tick=tick)
        qm = quads if quads is not None else loader.quads(model_ref)
        qv = vol if isinstance(vol, list) else quads_from_volume(vol, offset=offset, voxel_size=voxel_size)
        total = 0
        for view in views:
            cam = fit_camera(qv, view, 256, 256, jitter=(0.313, 0.227))
            a = render(qv, cam, shading="flat")
            b = render(qm, cam, shading="flat")
            n, _ = compare(a, b)
            total += n
        return {"diff_px": total, "views": len(views), "missing": sorted(set(loader.missing))}

    def _verify_ticks(self, model_ref, asset, ref_quads, disk_quads=None, max_ticks: int = 16) -> dict:
        """verify() à chaque début d'image des animations de l'asset (6 vues au tick 0, 3 ensuite)."""
        ticks = asset_ticks(asset, max_ticks)
        out = {"diff_px": 0, "views": 0, "missing": [], "ticks": len(ticks)}
        for k, t in enumerate(ticks):
            views = (INVENTORY, BACK, (135, 25), (315, -40), (0, 89.9), (90, 0)) if k == 0 else \
                (INVENTORY, BACK, (135, 25))
            d = self.verify(model_ref, ref_quads(t), views=views, tick=t,
                            quads=disk_quads(t) if disk_quads else None)
            out["diff_px"] += d["diff_px"]
            out["views"] += d["views"]
            out["missing"] = sorted(set(out["missing"]) | set(d["missing"]))
        return out

    # -------------------------------------------------------------- finalisation
    def finish(self, zip_path=None) -> Path | None:
        self.write_meta()
        lines = [
            "Pack généré par pixvox", "",
            f"Formats : min {self.min_format} (1.21.4) -> max {self.max_format} (26.3). Pour une version plus",
            "récente, augmentez max_format / supported_formats dans pack.mcmeta.", "",
            "Tester en jeu SANS mod (1.21.4+) :",
        ]
        for e in self.entries:
            n = e["name"]
            if e["kind"] == "item":
                lines.append(f"  /give @s minecraft:paper[minecraft:item_model=\"{self.ns}:{n}\"]")
            elif e["kind"] == "multibloc":
                lines.append(f"  /give @s minecraft:stone[minecraft:item_model=\"{self.ns}:{n}\"]   (miniature)")
                lines.append(f"  objet entier : datapack, puis /function {self.ns}:place/{n}  "
                             f"(retirer : /function {self.ns}:remove/{n})")
            else:
                lines.append(f"  /give @s minecraft:stone[minecraft:item_model=\"{self.ns}:{n}\"]")
                lines.append("  posé dans le monde (affichage seulement) :")
                lines.append(f"  /execute align xyz run summon minecraft:item_display ~0.5 ~0.5 ~0.5 "
                             f"{{Rotation:[180f,0f],item:{{id:\"minecraft:stone\",count:1,components:"
                             f"{{\"minecraft:item_model\":\"{self.ns}:{n}\"}}}}}}")
            if "replace" in e:
                lines.append(f"  (remplacement vanilla actif : {e['replace']})")
        lines += ["", "Remplacer un bloc vanilla (test rapide, blocs SANS propriétés : stone, dirt, iron_ore…) :",
                  "  python -m pixvox export mon_asset.py --replace nom_asset=minecraft:stone",
                  "  (objet lumineux ou à transparence : --replace nom_asset=minecraft:torch — lumière 14, cutout)",
                  "", "Textures animées : chaque bande PNG a son .png.mcmeta (frametime en ticks, 20 = 1 s).",
                  "", "Vrais blocs (collision, lumière, particules, multiblocs posables) : générer un mod",
                  "  python -m pixvox mod mes_assets.py --modid mon_mod --loader fabric|neoforge --build"]
        lines += ["", "Rotation:[180f,0f] : depuis 1.20 les item_display tournent le modèle de 180° ; on compense."]
        dp = self.write_datapack()
        self.datapack, self.datapack_zip = dp, None
        if dp:
            lines += ["", f"Datapack de placement : {dp.name} (à copier dans saves/<monde>/datapacks/, puis /reload)."]
        (self.root / "README_pixvox.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if dp and zip_path:
            zp = Path(zip_path)
            self.datapack_zip = zp.with_name(zp.stem + "_datapack.zip")
            _zip_dir(dp, self.datapack_zip)
        if zip_path:
            _zip_dir(self.root, Path(zip_path))
            return Path(zip_path)
        return None

    def write_datapack(self):
        """Datapack (dossier voisin du pack) avec les fonctions place/<nom> et remove/<nom>."""
        if not self.functions:
            return None
        dp = self.root.parent / f"{self.root.name}_datapack"
        prepare_output_dir(dp, "dossier du datapack")
        mark_output_dir(dp)
        (dp / "data" / self.ns / "function" / "place").mkdir(parents=True)
        (dp / "data" / self.ns / "function" / "remove").mkdir(parents=True)
        meta = {"pack": {"description": f"{self.description} — placement des objets multiblocs",
                         "pack_format": DATAPACK_MIN_FORMAT,
                         "supported_formats": [DATAPACK_MIN_FORMAT, DATAPACK_MAX_FORMAT],
                         "min_format": DATAPACK_MIN_FORMAT, "max_format": DATAPACK_MAX_FORMAT}}
        (dp / "pack.mcmeta").write_text(dumps(meta) + "\n", encoding="utf-8")
        for name, (place, remove) in self.functions.items():
            (dp / "data" / self.ns / "function" / "place" / f"{name}.mcfunction").write_text(
                "\n".join(place) + "\n", encoding="utf-8")
            (dp / "data" / self.ns / "function" / "remove" / f"{name}.mcfunction").write_text(
                "\n".join(remove) + "\n", encoding="utf-8")
        return dp


# ============================================================================ export d'une liste d'assets
KINDS_EN = {"bloc": "block", "modèle": "model", "multibloc": "multiblock", "item": "item"}
NAMESPACE_RE = re.compile(r"[a-z0-9_.-]+")


def verified(info: dict) -> bool:
    """Vrai si le re-rendu de l'export est identique à l'asset (0 pixel d'écart, aucune texture manquante)."""
    v = info["verify"]
    return v["diff_px"] == 0 and not v.get("missing")


def export_line(info: dict) -> str:
    """Ligne de journal lisible d'un asset exporté (« … | vérification 6 vues : OK »)."""
    v = info["verify"]
    status = "OK" if verified(info) else f"ÉCART {v['diff_px']} px" + (
        f", textures manquantes {v['missing']}" if v.get("missing") else "")
    extra = ""
    if info["kind"] == "modèle":
        extra = f", {info['elements']} éléments ({info['strategy']}), atlas {info['texture_size']}px"
        if info.get("planes"):
            extra += f", dont {info['planes']} plans"
    elif info["kind"] == "multibloc":
        b = info["blocks"]
        extra = (f", {b[0]}x{b[1]}x{b[2]} blocs, {info['parts']} parties, {info['elements']} éléments "
                 f"(max {info['elements_max']}/partie), atlas {info['texture_size']}px")
    elif info["kind"] == "bloc":
        extra = f", textures : {info['layout']}"
    if info.get("animated"):
        extra += f", {info['animated']} texture(s) animée(s)"
    ticks = f" × {v['ticks']} instants" if v.get("ticks", 1) > 1 else ""
    return (f"{info['name']} ({info['kind']}) -> {info['model']}{extra} | vérification {v['views']} vues{ticks} : "
            f"{status}" + (f" | {info['replace']}" if "replace" in info else ""))


def export_assets(assets, root="out/pack", namespace: str = "pixvox", zip_path=None, replace=None,
                  description: str = "Créé avec pixvox", log=say) -> dict:
    """Écrit un resource pack (recréé) et vérifie chaque asset par re-rendu, sans s'arrêter au premier refus.

    Retourne {"pack", "zip", "datapack", "datapack_zip", "infos": [...], "refused": [(nom, message)]}.
    log(ligne) reçoit le journal lisible (affiché par défaut ; None pour se taire).
    """
    log = log or (lambda *_: None)
    if not NAMESPACE_RE.fullmatch(namespace or ""):
        raise ExportError(f"namespace {namespace!r} invalide : minuscules, chiffres, _ . - (Minecraft refuse le reste)")
    root = prepare_output_dir(root, "dossier du pack")
    mark_output_dir(root)
    pack = ResourcePack(root, namespace, description)
    infos, refused = [], []
    for a in assets:
        try:
            infos.append(pack.add(a, (replace or {}).get(a.name)))
        except ExportError as e:
            refused.append((a.name, str(e)))
            log(f"[export] {a.name} : REFUSÉ — {e}")
    z = pack.finish(zip_path)
    for i in infos:
        log(f"[export] {export_line(i)}")
        for w in i.get("warnings", []):
            log(f"[export]   ATTENTION {i['name']} : {w}")
    log(f"[export] pack : {root}" + (f" | zip : {z}" if z else ""))
    return {"pack": root, "zip": z, "datapack": pack.datapack, "datapack_zip": pack.datapack_zip,
            "infos": infos, "refused": refused}

