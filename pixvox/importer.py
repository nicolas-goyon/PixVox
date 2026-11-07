"""pixvox.importer — modèle JSON Minecraft ou Blockbench → volume éditable (#26).

    imp = import_model("chemin/du/pack", "ns:block/lanterne", res=16)   # dossier, .zip ou .jar
    imp = import_bbmodel("lanterne.bbmodel", res=16)
    m = imp.to_model()                                                  # Model + plans, prêt à retoucher

Voxelisation : chaque élément (boîte, avec sa rotation) remplit les voxels dont le centre est à l'intérieur ;
chaque voxel de surface prend la couleur du texel que montre la face posée sur lui (projection sur le quad
de la face, UV et rotation d'UV comprises, lus par pixvox.mcmodel comme le jeu les lit). Un modèle exporté
par pixvox revient donc à l'identique : réimporté puis réexporté, il se vérifie à 0 px contre l'original.

Limites assumées, signalées dans `warnings` : un élément d'épaisseur nulle (plan, plantes en croix) devient
un plan (`add_plane`) ; un détail plus fin que la grille (élément qui ne tombe pas sur la grille de `res`)
est arrondi ; un élément tourné d'un angle qui n'est pas un multiple de 90° est voxelisé approximativement ;
un voxel dont toutes les faces sont transparentes est retiré. Un pack peut être un dossier, un .zip ou le
.jar du jeu (lu sur place, rien n'est copié dans le dépôt).
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .mcmodel import ModelLoader, _rotate, element_quads, norm_id
from .sprite import Sprite
from .volume import Volume

__all__ = ["Imported", "ModelImportError", "import_model", "import_bbmodel", "write_asset"]


class ModelImportError(ValueError):
    """Modèle impossible à importer (introuvable, sans éléments…)."""


@dataclass
class Imported:
    """Résultat d'un import : volume, échelle et position (comme Model), plans, avertissements."""
    name: str
    volume: Volume
    voxel_size: float
    origin: tuple
    planes: list = field(default_factory=list)       # dicts : texture (Sprite), center, y, width, height, angle…
    warnings: list = field(default_factory=list)
    source: str = ""

    def to_model(self, name: str | None = None):
        from .assets import Model
        m = Model(name or self.name, self.volume, voxel_size=self.voxel_size, origin=self.origin)
        for p in self.planes:
            m.add_plane(p["texture"], center=p["center"], y=p["y"], width=p["width"], height=p["height"],
                        angle=p["angle"], emission=p["emission"], shade=p["shade"])
        return m


# ----------------------------------------------------------------------------------------- sources
class _Pack:
    """Dossier de pack, ou .zip / .jar dont les assets/ sont extraits dans un dossier temporaire."""

    def __init__(self, path):
        self.path = Path(path)
        self.tmp = None
        if self.path.is_file() and zipfile.is_zipfile(self.path):
            self.tmp = Path(tempfile.mkdtemp(prefix="pixvox_import_"))
            with zipfile.ZipFile(self.path) as z:
                for n in z.namelist():
                    if n.startswith("assets/") and n.endswith((".json", ".png", ".mcmeta")):
                        z.extract(n, self.tmp)
            self.root = self.tmp
        elif self.path.is_dir():
            self.root = self.path
        else:
            raise ModelImportError(f"pack introuvable : {path} (dossier, .zip ou .jar attendu)")

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


def import_model(pack, ref: str, res: int = 16, mc: str = "1.21.4+", name: str | None = None) -> Imported:
    """Importe le modèle `ref` (« ns:block/nom ») d'un pack (dossier, .zip, .jar) en volume de `res` voxels par
    bloc, lu comme la version `mc` le lit."""
    src = _Pack(pack)
    try:
        loader = ModelLoader([src.root], mc=mc)
        try:
            resolved = loader.resolve(norm_id(ref))
        except FileNotFoundError as e:
            raise ModelImportError(f"modèle {ref} introuvable dans {pack}") from e
        if loader.missing and not resolved["elements"]:
            raise ModelImportError(f"modèle {ref} introuvable dans {pack} ({', '.join(loader.missing)})")
        if not resolved["elements"]:
            raise ModelImportError(f"{ref} n'a pas d'éléments (item plat item/generated, ou modèle builtin) : rien à "
                               "voxeliser ; pour un item plat, partir de sa texture (Item)")
        nm = name or norm_id(ref).split("/")[-1]
        imp = _voxelize(resolved["elements"], lambda key: loader._tex_for(resolved["textures"], key), res, nm, mc)
        animated = sorted({norm_id(t) for t in resolved["textures"].values()
                           if not str(t).startswith("#") and loader._find("textures", t, ".png.mcmeta") is not None})
        if animated:
            imp.warnings.append(f"texture(s) animée(s) importée(s) à leur première image : {', '.join(animated)}")
        missing = sorted(set(loader.missing))
        if missing:
            imp.warnings.append(f"textures manquantes (damier magenta) : {', '.join(missing)}")
        imp.source = f"{Path(pack).name} {norm_id(ref)}"
        return imp
    finally:
        src.close()


def import_bbmodel(path, res: int = 16, name: str | None = None) -> Imported:
    """Importe un modèle Blockbench (.bbmodel : JSON, textures incluses en data URI) en volume."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    rw = float((data.get("resolution") or {}).get("width", 16))
    rh = float((data.get("resolution") or {}).get("height", 16))
    textures = {}
    for i, t in enumerate(data.get("textures", [])):
        src = t.get("source", "")
        if not src.startswith("data:image/png;base64,"):
            raise ModelImportError(f"{p.name} : texture {t.get('name', i)} non incluse (enregistrer le .bbmodel avec les "
                               "textures)")
        with Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))) as im:
            textures[f"#{i}"] = np.asarray(im.convert("RGBA")).copy()
    warnings = []
    elements = []
    for el in data.get("elements", []):
        if el.get("type", "cube") != "cube":
            warnings.append(f"élément {el.get('name', '?')} de type {el.get('type')} ignoré (seuls les cubes)")
            continue
        jel = {"from": el["from"], "to": el["to"], "faces": {}}
        rot = [float(r) for r in el.get("rotation", [0, 0, 0])]
        axes = [(a, r) for a, r in zip("xyz", rot) if abs(r) > 1e-9]
        if len(axes) > 1:
            warnings.append(f"élément {el.get('name', '?')} tourné sur plusieurs axes : seule la rotation "
                            f"{axes[0][0]} est appliquée")
        if axes:
            jel["rotation"] = {"origin": el.get("origin", [8, 8, 8]), "axis": axes[0][0], "angle": axes[0][1]}
        for f, fd in (el.get("faces") or {}).items():
            if fd.get("texture") is None:
                continue
            u0, v0, u1, v1 = fd.get("uv", [0, 0, rw, rh])
            jel["faces"][f] = {"texture": f"#{fd['texture']}", "rotation": fd.get("rotation", 0),
                               "uv": [u0 * 16 / rw, v0 * 16 / rh, u1 * 16 / rw, v1 * 16 / rh]}
        elements.append(jel)
    if not elements:
        raise ModelImportError(f"{p.name} : aucun cube à voxeliser")
    imp = _voxelize(elements, lambda key: textures.get(key, _magenta()), res, name or p.stem, "1.21.4+")
    imp.warnings = warnings + imp.warnings
    imp.source = p.name
    return imp


def _magenta():
    a = np.zeros((2, 2, 4), np.uint8)
    a[...] = (248, 0, 248, 255)
    a[0, 1] = a[1, 0] = (0, 0, 0, 255)
    return a


# ----------------------------------------------------------------------------------------- voxelisation
def _on_grid(x: float, vs: float) -> bool:
    return abs(x / vs - round(x / vs)) < 1e-6


def _voxelize(elements: list, tex_lookup, res: int, name: str, mc: str) -> Imported:
    vs = 16.0 / res
    warnings = []
    boxes, flats = [], []
    for el in elements:
        thin = [k for k in range(3) if abs(float(el["to"][k]) - float(el["from"][k])) < 1e-9]
        (flats if thin else boxes).append(el)
    if not boxes and not flats:
        raise ModelImportError("aucun élément")
    off_grid = sum(1 for el in boxes if not all(_on_grid(float(c), vs) for c in list(el["from"]) + list(el["to"])))
    if off_grid:
        warnings.append(f"{off_grid} élément(s) plus fins que la grille de {res} voxels par bloc : arrondis "
                        f"(essayer res={res * 2})")
    tilted = [el for el in boxes if "rotation" in el and abs(float(el["rotation"].get("angle", 0))) % 90 > 1e-9]
    if tilted:
        warnings.append(f"{len(tilted)} élément(s) tourné(s) d'un angle qui n'est pas un multiple de 90° : "
                        "voxelisé(s) approximativement (escaliers de voxels)")
    planes = [_plane(el, tex_lookup, mc, warnings) for el in flats]
    planes = [p for p in planes if p is not None]
    if not boxes:
        v = Volume(1, 1, 1)
        warnings.append("modèle fait seulement de plans : volume vide")
        return Imported(name, v, vs, (8.0, 0.0, 8.0), planes, warnings)

    quads_by_el = [element_quads(el, tex_lookup, (0.0, 0.0, 0.0), mc) for el in boxes]
    pts = np.concatenate([_corners(el) for el in boxes])            # emprise : les 8 coins, pas les seules faces
    lo = np.floor(pts.min(axis=0) / vs + 1e-6).astype(int)
    hi = np.ceil(pts.max(axis=0) / vs - 1e-6).astype(int)
    shape = tuple(int(x) for x in np.maximum(hi - lo, 1))
    origin = lo * vs
    idx = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1)
    centers = origin + (idx + 0.5) * vs                                 # (sx, sy, sz, 3) en unités modèle

    color = np.zeros(shape + (4,), np.uint8)
    painted = np.zeros(shape, bool)
    seen_clear = np.zeros(shape, bool)                                  # face transparente posée sur le voxel
    occ = np.zeros(shape, bool)
    for el, quads in zip(boxes, quads_by_el):
        frm, to = np.asarray(el["from"], float), np.asarray(el["to"], float)
        c = centers.reshape(-1, 3)
        if "rotation" in el:
            inv = dict(el["rotation"])
            inv["angle"] = -float(inv.get("angle", 0))
            inv.pop("rescale", None)
            c = _rotate(c, inv)
        inside = np.all((c >= frm - 1e-9) & (c <= to + 1e-9), axis=1).reshape(shape)
        occ |= inside
        cell = centers[inside]
        if not len(cell):
            continue
        sel = np.argwhere(inside)
        for q in quads:
            n = np.asarray(q.normal, float)
            n = n / (np.linalg.norm(n) or 1)
            rel = cell - q.p0
            d = rel @ n                                                  # < 0 : à l'intérieur de l'élément
            a = (rel @ q.e1) / float(q.e1 @ q.e1)
            b = (rel @ q.e2) / float(q.e2 @ q.e2)
            on = (d < 0) & (d >= -vs) & (a >= -1e-9) & (a <= 1 + 1e-9) & (b >= -1e-9) & (b <= 1 + 1e-9)
            if not on.any():
                continue
            tex = q.tex
            th, tw = tex.shape[:2]
            u = q.uv0[0] + a[on] * (q.uv1[0] - q.uv0[0]) + b[on] * (q.uv2[0] - q.uv0[0])
            v = q.uv0[1] + a[on] * (q.uv1[1] - q.uv0[1]) + b[on] * (q.uv2[1] - q.uv0[1])
            tu = np.clip(np.floor(u).astype(int), 0, tw - 1)
            tv = np.clip(np.floor(v).astype(int), 0, th - 1)
            px = tex[tv, tu]
            ii = sel[on]
            for (x, y, z), p in zip(ii, px):
                if p[3] == 0:
                    seen_clear[x, y, z] = True
                elif not painted[x, y, z]:
                    color[x, y, z] = p
                    painted[x, y, z] = True
    drop = occ & seen_clear & ~painted                                  # seules des faces transparentes dessus
    if drop.any():
        warnings.append(f"{int(drop.sum())} voxel(s) sous des pixels transparents retirés")
    occ &= ~drop
    hidden = occ & ~painted
    if hidden.any():                                                    # intérieur : couleur du voisin peint
        _fill_from_neighbours(color, painted, occ)
    color[~occ] = 0
    vol = Volume(*shape, res=res)
    vol.data[...] = color
    vol.log.append(f"import : {len(boxes)} boîte(s), {len(planes)} plan(s), {res} voxels par bloc")
    vol.log += [f"import : {w}" for w in warnings]
    return Imported(name, vol, vs, tuple(float(x) for x in origin), planes, warnings)


def _corners(el: dict) -> np.ndarray:
    """Les 8 coins d'une boîte d'élément, tournés comme l'élément."""
    frm, to = np.asarray(el["from"], float), np.asarray(el["to"], float)
    c = np.array([[(to if i & 1 else frm)[0], (to if i & 2 else frm)[1], (to if i & 4 else frm)[2]] for i in range(8)])
    return _rotate(c, el["rotation"]) if "rotation" in el else c


def _fill_from_neighbours(color, painted, occ, max_steps: int = 64) -> None:
    done = painted.copy()
    for _ in range(max_steps):
        todo = occ & ~done
        if not todo.any():
            return
        for axis in range(3):
            for step in (1, -1):
                src = np.roll(done, step, axis=axis)
                col = np.roll(color, step, axis=axis)
                edge = [slice(None)] * 3
                edge[axis] = 0 if step == 1 else -1
                src[tuple(edge)] = False                               # pas de bouclage d'un bord à l'autre
                take = todo & src & ~done
                color[take] = col[take]
                done |= take
                todo &= ~take


def _plane(el: dict, tex_lookup, mc: str, warnings: list):
    """Élément d'épaisseur nulle → plan vertical (comme Model.add_plane), sinon None + avertissement."""
    frm, to = np.asarray(el["from"], float), np.asarray(el["to"], float)
    thin = [k for k in range(3) if abs(to[k] - frm[k]) < 1e-9]
    if thin == [1] or len(thin) != 1:
        warnings.append("plan horizontal (ou dégénéré) ignoré : seuls les plans verticaux deviennent add_plane")
        return None
    axis = thin[0]                                                      # 2 : plan face nord/sud, 0 : est/ouest
    rot = el.get("rotation")
    if rot and rot.get("axis", "y") != "y":
        warnings.append("plan tourné autour d'un axe horizontal ignoré")
        return None
    angle = float(rot.get("angle", 0)) if rot else 0.0
    face = "south" if axis == 2 else "east"
    fd = el.get("faces", {}).get(face) or el.get("faces", {}).get("north" if axis == 2 else "west")
    if fd is None:
        warnings.append("plan sans face texturée ignoré")
        return None
    one = {**el, "faces": {face: fd}}
    one.pop("rotation", None)
    q = element_quads(one, tex_lookup, (0.0, 0.0, 0.0), mc)[0]
    us = [q.uv0[0], q.uv1[0], q.uv2[0]]
    vs = [q.uv0[1], q.uv1[1], q.uv2[1]]
    u0, u1 = int(round(min(us))), int(round(max(us)))
    v0, v1 = int(round(min(vs))), int(round(max(vs)))
    crop = q.tex[v0:max(v1, v0 + 1), u0:max(u1, u0 + 1)].copy()
    if q.uv1[0] < q.uv0[0]:
        crop = crop[:, ::-1]                                            # UV inversées : texture retournée
    if q.uv2[1] < q.uv0[1]:
        crop = crop[::-1]
    width = (to - frm)[2 if axis == 0 else 0]
    nd = el.get("neoforge_data") or {}
    emission = max(int(el.get("light_emission", 0)), int(nd.get("block_light", 0)))
    shade = not (el.get("shade") is False or el.get("shade_direction_override") == "up")
    return {"texture": Sprite(data=crop), "center": (float((frm[0] + to[0]) / 2), float((frm[2] + to[2]) / 2)),
            "y": float(frm[1]), "width": float(width), "height": float(to[1] - frm[1]),
            "angle": angle + (90.0 if axis == 0 else 0.0), "emission": emission, "shade": shade}


# ----------------------------------------------------------------------------------------- fichier d'asset
def write_asset(imp: Imported, out, name: str | None = None) -> list:
    """Écrit un fichier d'asset de départ (`out`, .py) : volume en tranches ASCII (une légende de couleurs) si
    elles tiennent, sinon dans `<nom>.npz` à côté ; textures des plans en PNG à côté. Renvoie les fichiers écrits."""
    from .color import hexa
    from .png import save_png
    from .sprite import ASCII_CHARS
    out = Path(out)
    nm = name or imp.name
    out.parent.mkdir(parents=True, exist_ok=True)
    written = [out]
    v = imp.volume
    cols = sorted(v.colors())
    ascii_ok = len(cols) <= len(ASCII_CHARS) and np.prod(v.shape) <= 32 ** 3
    lines = [f'"""Modèle « {nm} » importé par `pixvox import` ({imp.source}), {int(round(16 / imp.voxel_size))} '
             'voxels par bloc.', "",
             "Le volume est éditable comme n'importe quel volume pixvox (tranches de BAS en HAUT : ligne = z nord→sud,",
             "colonne = x ouest→est). Étapes suivantes : pixvox review / watch / export sur ce fichier."]
    if imp.warnings:
        lines += ["", "Avertissements de l'import :"] + [f"- {w}" for w in imp.warnings]
    lines += ['"""', "from pathlib import Path", ""]
    lines += ["import numpy as np", ""] if not ascii_ok else []
    lines += ["from pixvox import Model, Sprite, Volume", "", "HERE = Path(__file__).resolve().parent", ""]
    if ascii_ok:
        legend = {c: ASCII_CHARS[i] for i, c in enumerate(cols)}
        lines.append("LEGEND = {" + ", ".join(f'"{ch}": "{hexa(c)}"' for c, ch in legend.items()) + "}")
        lines.append("SLICES = [")
        for y in range(v.shape[1]):
            rows = []
            for z in range(v.shape[2]):
                rows.append("".join("." if v.data[x, y, z, 3] == 0 else legend[tuple(int(t) for t in v.data[x, y, z])]
                                    for x in range(v.shape[0])))
            lines.append('    """\n' + "\n".join(rows) + '\n""",' + f"  # y={y}")
        lines.append("]")
        make = "    v = Volume.from_slices(SLICES, LEGEND)"
    else:
        npz = out.with_suffix(".npz")
        np.savez_compressed(npz, data=v.data)
        written.append(npz)
        make = (f'    data = np.load(HERE / "{npz.name}")["data"]\n'
                "    v = Volume(*data.shape[:3])\n    v.data[...] = data")
    lines += ["", "", "def build():", make,
              f'    m = Model("{nm}", v, voxel_size={imp.voxel_size!r}, origin={tuple(round(o, 6) for o in imp.origin)!r})']
    for i, p in enumerate(imp.planes):
        png = out.with_name(f"{nm}_p{i}.png")
        save_png(png, p["texture"].data)
        written.append(png)
        lines.append(f'    m.add_plane(Sprite.load(HERE / "{png.name}"), center={p["center"]!r}, y={p["y"]!r}, '
                     f'width={p["width"]!r}, height={p["height"]!r}, angle={p["angle"]!r}, '
                     f'emission={p["emission"]}, shade={p["shade"]})')
    lines += ["    return m", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return written
