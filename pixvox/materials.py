"""pixvox.materials — matériaux de construction prêts à l'emploi, peints dans le volume (#27).

Chaque recette peint un Volume en 3D (voxel d'abord, règle 1) avec des motifs dont la période divise la
taille du bloc et du bruit périodique : un bloc se raccorde sans couture à ses voisins, et un même joint
passe d'une face à l'autre par l'arête. Arguments par mot-clé seulement (règle 4) :

    v = Volume(16)
    planks(v, wood="spruce", seed=3)          # planches : 4 lames, fibres, abouts décalés
    bricks(v, color="#8e4a3a", seed=1)         # briques 8 × 4 en quinconce, joints de mortier
    cut_stone(v, color="#8a8a8a", seed=2)      # pierre de taille : blocs biseautés en quinconce
    glow = ore(v, crystal="#3fd0c8", seed=4)   # roche + cristaux (renvoie leur masque : emissive=glow)
    metal(v, color="#c1734b", patina=0.4)      # plaques rivetées, brossées ; vert-de-gris selon patina

Toutes renvoient le volume (sauf `ore`, qui renvoie le masque des cristaux) et acceptent un Volume de
16, 32 ou 64 voxels par bloc (les motifs gardent leur taille en pixels de 16). `pixvox new --kind block
--material bricks` part d'une recette. Planche catalogue : docs/images/materiaux.png.
"""
from __future__ import annotations

import numpy as np

from .color import Ramp, ramp
from .noise import equalize, perlin

__all__ = ["MATERIALS", "WOODS", "planks", "bricks", "cut_stone", "ore", "metal"]

MATERIALS = ("planks", "bricks", "cut_stone", "ore", "metal")
# couleur moyenne des planches vanilla de chaque essence (référence ; le motif est celui de pixvox)
WOODS = {"oak": "#a2834f", "spruce": "#735531", "birch": "#c4b179", "jungle": "#a0734d", "acacia": "#a8592f",
         "dark_oak": "#4b311a", "mangrove": "#773934", "cherry": "#e1b2a6", "pale_oak": "#e2d8d3",
         "bamboo": "#c3ad53", "crimson": "#653047", "warped": "#2b6963"}


def _grid(v):
    """Coordonnées (px, py, pz) en pixels de 16 (un voxel d'un volume HD = une fraction de pixel)."""
    sx, sy, sz = v.shape
    if not (sx == sy == sz) or sx % 16:
        raise ValueError(f"matériau : bloc cubique de 16, 32 ou 64 voxels attendu (reçu {v.shape})")
    u = sx // 16
    X, Y, Z = np.meshgrid(np.arange(sx), np.arange(sy), np.arange(sz), indexing="ij")
    return X // u, Y // u, Z // u, sx


def _paint(v, levels: np.ndarray, r: Ramp) -> None:
    pal = np.array(list(r), np.uint8)
    v.data[...] = pal[np.clip(levels, 0, len(r) - 1)]


def _ramp(c, n: int, spread: float, **kw) -> Ramp:
    return c if isinstance(c, Ramp) else ramp(c, n=n, spread=spread, **kw)


def _shades(ids: np.ndarray, seed: int, span: int) -> np.ndarray:
    """Écart de teinte (-span..span) tiré par identifiant de pièce (brique, lame, plaque), reproductible."""
    rng = np.random.default_rng(seed)
    table = rng.integers(-span, span + 1, int(ids.max()) + 1)
    return table[ids]


def planks(volume, *, wood: str = "oak", seed: int = 0, boards: int = 4, color=None):
    """Planches horizontales : `boards` lames par bloc (4 en vanilla), fibres étirées, joint sombre sous chaque
    lame et lèvre claire dessus, un about (fin de lame) par lame et par direction, décalé d'une lame à l'autre.
    wood : essence (WOODS) ; color : couleur ou Ramp qui la remplace."""
    if 16 % boards or boards < 2:
        raise ValueError("boards doit diviser 16 (2, 4, 8)")
    px, py, pz, n = _grid(volume)
    r = _ramp(color or WOODS.get(wood) or _bad("wood", wood, WOODS), 5, 0.32, hue_shift=12)
    h = 16 // boards
    jy = _joint_at(h, clear=(0, h - 1))
    ly = _local(py, h, jy)                                       # 0 = joint, h-1 = lèvre : hors des bords
    b = ((py - jy) % 16) // h
    grain = equalize(perlin((n, n, n), (2, 12, 2), seed=seed, octaves=2))
    lv = np.full(px.shape, 2) + _shades(b, seed + 1, 0)
    lv[grain > 0.82] = 3
    lv[grain < 0.16] = 1
    lv[ly == h - 1] += 1                                         # lèvre éclairée en haut de lame
    lv[ly == 0] = 0                                              # joint sous la lame
    rng = np.random.default_rng(seed + 2)
    jx, jz = 1 + rng.permutation(13)[:boards], 1 + rng.permutation(13)[:boards]   # abouts dans 1..13 : hors des bords
    for k in range(boards):
        lane = b == k
        lv[lane & (px == jx[k])] = 0                                 # about vu sur les faces nord / sud / dessus
        lv[lane & (px == jx[k] + 1) & (ly != 0)] += 1
        lv[lane & (pz == jz[k])] = 0                                 # about vu sur les faces est / ouest
        lv[lane & (pz == jz[k] + 1) & (ly != 0)] += 1
    _paint(volume, lv, r)
    return volume


def _bad(name, value, choices):
    raise ValueError(f"{name}={value!r} inconnu ; choix : {', '.join(choices)}")


def _joint_at(period: int, offsets=(0,), clear=(0,)) -> int:
    """Position du joint dans sa période telle que les couches de bord (0 et 15) ne tombent jamais sur une
    coordonnée locale de `clear` (0 = le joint ; ajouter la lèvre si elle est d'une seule teinte) : sinon une
    face entière du bloc serait du joint (tout le dessus en mortier). Repli sur (0,) si impossible."""
    for keep in (tuple(clear), (0,)):
        for j in range(period):
            if all((b + o - j) % period not in keep for o in offsets for b in (0, 15)):
                return j
    raise ValueError(f"période {period} trop courte pour un joint hors des bords")


def _local(coord, period: int, joint: int, off=0):
    """Coordonnée dans la pièce, 0 = joint, 1 = juste après (lèvre / biseau), period-1 = juste avant."""
    return (coord + off - joint) % period


def _masonry(px, py, pz, course: int, length: int):
    """Appareil en quinconce, joints hors des bords : (ly, lx, lz) coordonnées locales dans la pièce (0 = joint)
    et identifiant de pièce (périodique : une pièce à cheval sur deux blocs garde sa teinte)."""
    jy = _joint_at(course)
    ly = _local(py, course, jy)
    c = ((py - jy) % 16) // course
    off = (c % 2) * (length // 2)
    jx = _joint_at(length, (0, length // 2))
    lx = _local(px, length, jx, off)
    lz = _local(pz, length, jx, off)
    per = 16 // length
    ix = ((px + off - jx) % 16) // length
    iz = ((pz + off - jx) % 16) // length
    ids = (c * per + ix) * per + iz
    return ly, lx, lz, ids


def bricks(volume, *, color="#965040", mortar="#a39d92", seed: int = 0, course: int = 4, length: int = 8):
    """Briques de `length` × `course` pixels (8 × 4 en vanilla) en quinconce, une teinte par brique, joints de
    mortier ; arête haute de brique claire, basse sombre. course et length doivent diviser 16."""
    if 16 % course or 16 % length or course < 3 or length < 4:
        raise ValueError("course (≥ 3) et length (≥ 4) doivent diviser 16")
    px, py, pz, n = _grid(volume)
    br = _ramp(color, 5, 0.30, hue_shift=10)
    mo = _ramp(mortar, 3, 0.10, hue_shift=0, tint=0)
    ly, lx, lz, ids = _masonry(px, py, pz, course, length)
    joint = (ly == 0) | (lx == 0) | (lz == 0)
    speck = equalize(perlin((n, n, n), 8, seed=seed, octaves=1))
    lv = 2 + _shades(ids, seed + 1, 1)
    lv = lv + (speck > 0.85) - (speck < 0.12)
    lv = np.where(ly == course - 1, lv + 1, lv)                              # arête haute de brique
    lv = np.where(ly == 1, lv - 1, lv)                                       # arête basse
    _paint(volume, lv, br)
    m = np.clip(1 + (speck > 0.7) - (speck < 0.2), 0, 2)
    volume.data[joint] = np.array(list(mo), np.uint8)[m[joint]]
    return volume


def cut_stone(volume, *, color="#8f8f8f", seed: int = 0, size: int = 8):
    """Pierre de taille : blocs de `size` pixels en quinconce, biseau clair en haut et à gauche, sombre en bas et à
    droite, joints creux. size doit diviser 16."""
    if 16 % size or size < 4:
        raise ValueError("size (≥ 4) doit diviser 16")
    px, py, pz, n = _grid(volume)
    r = _ramp(color, 6, 0.30, hue_shift=8, tint=0.008)
    ly, lx, lz, ids = _masonry(px, py, pz, size, size)
    joint = (ly == 0) | (lx == 0) | (lz == 0)
    grain = equalize(perlin((n, n, n), 4, seed=seed, octaves=2))
    lv = 3 + _shades(ids, seed + 1, 1) + (grain > 0.8) - (grain < 0.15)
    lv = np.where(ly == size - 1, lv + 1, lv)                                # biseau haut
    lv = np.where(ly == 1, lv - 1, lv)                                       # biseau bas
    lv = np.where((lx == 1) | (lz == 1), lv + 1, lv)                         # biseau gauche
    lv = np.where((lx == size - 1) | (lz == size - 1), lv - 1, lv)
    _paint(volume, np.clip(lv, 1, 5) * ~joint, r)
    return volume


def ore(volume, *, stone="#7d7d82", crystal="#3fd0c8", seed: int = 0, count: int = 5, radius=(1.2, 2.0)):
    """Roche + amas de cristaux (un sur une arête), contour sombre autour des cristaux. stone : couleur ou Ramp de
    la roche (ramp_from_vanilla("stone") s'accorde avec le jeu). Renvoie le MASQUE des cristaux, pour
    Block(…, emissive=masque) s'ils brillent."""
    _grid(volume)
    rock = _ramp(stone, 4, 0.16, hue_shift=10)
    cr = _ramp(crystal, 5, 0.45, hue_shift=20)
    volume.noise(rock, cells=3, octaves=3, seed=seed)
    mask = volume.blobs(cr, count=count, radius=radius, seed=seed + 1, on_edges=1)
    volume.tint(volume.m_dilate(mask, wrap=True) & ~mask, cr[1], 0.3)
    return mask


def metal(volume, *, color="#a3a8b0", patina: float = 0.0, seed: int = 0, plate: int = 8, rivets: bool = True,
          verdigris="#4fa58f"):
    """Plaques de `plate` pixels, brossées à l'horizontale, joints sombres, lèvre claire, rivets aux coins de
    chaque plaque. patina (0–1) : part de la surface gagnée par le vert-de-gris (cuivre : color="#c1734b")."""
    if 16 % plate or plate < 4:
        raise ValueError("plate (≥ 4) doit diviser 16")
    if not 0.0 <= patina <= 1.0:
        raise ValueError("patina entre 0 et 1")
    px, py, pz, n = _grid(volume)
    r = _ramp(color, 6, 0.40, hue_shift=10, tint=0.01)
    brushed = equalize(perlin((n, n, n), (2, 10, 2), seed=seed, octaves=1))       # stries horizontales
    j = _joint_at(plate)
    lx, ly, lz = _local(px, plate, j), _local(py, plate, j), _local(pz, plate, j)
    per = 16 // plate
    ids = ((((py - j) % 16) // plate) * per + ((px - j) % 16) // plate) * per + ((pz - j) % 16) // plate
    lv = 3 + _shades(ids, seed + 1, 1) + (brushed > 0.75) - (brushed < 0.2)
    seam = (lx == 0) | (ly == 0) | (lz == 0)
    lv = np.where((lx == 1) | (ly == plate - 1) | (lz == 1), lv + 1, lv)
    lv[seam] = 0
    if rivets:
        at = [k for k in (2, plate - 2) if k not in (_local(0, plate, j), _local(15, plate, j))] or [2]
        rx, ry, rz = np.isin(lx, at), np.isin(ly, at), np.isin(lz, at)
        head = (rx & ry) | (rx & rz) | (ry & rz)
        lv[head] = 5
        under = np.zeros_like(head)
        under[:, :-1, :] = head[:, 1:, :]                                    # ombre sous la tête du rivet
        lv[under & ~head & ~seam] = 1
    _paint(volume, lv, r)
    if patina > 0:
        rust = equalize(perlin((n, n, n), 3, seed=seed + 3, octaves=2))
        green = _ramp(verdigris, 4, 0.25, hue_shift=8)
        spot = rust > 1.0 - patina
        g = np.clip((rust - (1.0 - patina)) / max(patina, 1e-6) * 3.99, 0, 3).astype(int)
        volume.data[spot & ~seam] = np.array(list(green), np.uint8)[g[spot & ~seam]]
    return volume
