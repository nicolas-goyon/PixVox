"""pixvox.mcmodel — lecture et rendu des modèles JSON de Minecraft Java.

Cette implémentation est volontairement INDÉPENDANTE du code d'export : elle reproduit la logique du
jeu (FaceInfo = ordre des sommets d'une face, BlockElement.uvsByFace = UV automatiques,
BlockFaceUV = rotation des UV). Rendre un modèle exporté avec ce module puis le comparer au rendu
direct du volume valide l'export pixel par pixel.

Aussi utilisable pour prévisualiser n'importe quel modèle d'un resource pack (ex. sortie Blockbench).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .render import Quad, closest_face

# Coins de chaque face, dans l'ordre des sommets du jeu (net.minecraft.client.renderer.FaceInfo)
FACE_INFO = {
    "down":  [("min", "min", "max"), ("min", "min", "min"), ("max", "min", "min"), ("max", "min", "max")],
    "up":    [("min", "max", "min"), ("min", "max", "max"), ("max", "max", "max"), ("max", "max", "min")],
    "north": [("max", "max", "min"), ("max", "min", "min"), ("min", "min", "min"), ("min", "max", "min")],
    "south": [("min", "max", "max"), ("min", "min", "max"), ("max", "min", "max"), ("max", "max", "max")],
    "west":  [("min", "max", "min"), ("min", "min", "min"), ("min", "min", "max"), ("min", "max", "max")],
    "east":  [("max", "max", "max"), ("max", "min", "max"), ("max", "min", "min"), ("max", "max", "min")],
}
NORMAL = {"down": (0, -1, 0), "up": (0, 1, 0), "north": (0, 0, -1), "south": (0, 0, 1),
          "west": (-1, 0, 0), "east": (1, 0, 0)}


def auto_uv(face: str, frm, to) -> list:
    """UV par défaut d'une face d'élément (BlockElement.uvsByFace)."""
    fx, fy, fz = frm
    tx, ty, tz = to
    return {
        "down": [fx, 16 - tz, tx, 16 - fz],
        "up": [fx, fz, tx, tz],
        "north": [16 - tx, 16 - ty, 16 - fx, 16 - fy],
        "south": [fx, 16 - ty, tx, 16 - fy],
        "west": [fz, 16 - ty, tz, 16 - fy],
        "east": [16 - tz, 16 - ty, 16 - fz, 16 - fy],
    }[face]


def _cube_element(tex_for_face: dict) -> dict:
    return {"from": [0, 0, 0], "to": [16, 16, 16],
            "faces": {f: {"texture": t, "cullface": f} for f, t in tex_for_face.items()}}


_SIDES = ("north", "south", "west", "east")
BUILTIN = {
    "minecraft:block/block": {"textures": {}},
    "minecraft:block/cube": {"parent": "minecraft:block/block",
                             "elements": [_cube_element({f: "#" + f for f in
                                                         ("down", "up", "north", "south", "west", "east")})]},
    "minecraft:block/cube_all": {"parent": "minecraft:block/cube",
                                 "textures": {"particle": "#all", **{f: "#all" for f in
                                              ("down", "up", "north", "south", "west", "east")}}},
    "minecraft:block/cube_column": {"parent": "minecraft:block/cube",
                                    "textures": {"particle": "#side", "down": "#end", "up": "#end",
                                                 **{f: "#side" for f in _SIDES}}},
    "minecraft:block/cube_bottom_top": {"parent": "minecraft:block/cube",
                                        "textures": {"particle": "#side", "down": "#bottom", "up": "#top",
                                                     **{f: "#side" for f in _SIDES}}},
    "minecraft:block/orientable": {"parent": "minecraft:block/cube",
                                   "textures": {"particle": "#front", "down": "#top", "up": "#top",
                                                "north": "#front", "south": "#side", "west": "#side",
                                                "east": "#side"}},
    "minecraft:item/generated": {"textures": {}, "builtin": "generated"},
}


def norm_id(ref: str) -> str:
    return ref if ":" in ref else "minecraft:" + ref


def missing_texture() -> np.ndarray:
    t = np.zeros((16, 16, 4), np.uint8)
    t[..., 3] = 255
    yy, xx = np.mgrid[0:16, 0:16]
    t[((yy // 8) + (xx // 8)) % 2 == 0] = (248, 0, 248, 255)
    return t


class ModelLoader:
    """Charge des modèles depuis un ou plusieurs dossiers de resource pack (contenant assets/)."""

    def __init__(self, pack_roots=(), extra_textures: dict | None = None, tick: float = 0):
        self.roots = [Path(p) for p in pack_roots]
        self.extra = dict(extra_textures or {})
        self.missing: list[str] = []
        self.tick = tick              # textures animées : image affichée à ce tick (lu dans le .png.mcmeta)
        self._cache: dict = {}        # une seule copie de chaque texture (un atlas peut servir à 5000 faces)

    def _find(self, kind: str, ref: str, ext: str):
        ns, path = norm_id(ref).split(":", 1)
        for r in self.roots:
            p = r / "assets" / ns / kind / (path + ext)
            if p.exists():
                return p
        return None

    def raw_model(self, ref: str) -> dict:
        ref = norm_id(ref)
        p = self._find("models", ref, ".json")
        if p is not None:
            return json.loads(p.read_text(encoding="utf-8"))
        if ref in BUILTIN:
            return BUILTIN[ref]
        raise FileNotFoundError(f"modèle introuvable : {ref}")

    def resolve(self, model) -> dict:
        """Fusionne la chaîne de parents : textures (enfant prioritaire), éléments (le plus proche)."""
        chain = []
        m = self.raw_model(model) if isinstance(model, str) else model
        seen = 0
        while m is not None and seen < 32:
            chain.append(m)
            parent = m.get("parent")
            m = self.raw_model(parent) if parent else None
            seen += 1
        textures, elements, builtin, ao = {}, None, None, True
        for m in reversed(chain):
            textures.update(m.get("textures", {}))
            if "elements" in m:
                elements = m["elements"]
            if "builtin" in m:
                builtin = m["builtin"]
            if "ambientocclusion" in m:
                ao = m["ambientocclusion"]
        return {"textures": textures, "elements": elements or [], "builtin": builtin, "ambientocclusion": ao}

    def texture(self, ref: str) -> np.ndarray:
        ref = norm_id(ref)
        key = (ref, self.tick)
        if key not in self._cache:
            self._cache[key] = self._load_texture(ref)
        return self._cache[key]

    def _load_texture(self, ref: str) -> np.ndarray:
        if ref in self.extra:
            t = self.extra[ref]
            return np.asarray(t.data if hasattr(t, "data") else t)
        p = self._find("textures", ref, ".png")
        if p is None:
            self.missing.append(ref)
            return missing_texture()
        with Image.open(p) as im:
            img = np.array(im.convert("RGBA"))
        meta = p.with_name(p.name + ".mcmeta")
        anim = None
        if meta.exists():
            anim = json.loads(meta.read_text(encoding="utf-8")).get("animation")
        if anim is not None:                                # texture animée : image affichée à self.tick
            fw = int(anim.get("width", img.shape[1]))
            fh = int(anim.get("height", fw if "width" in anim else img.shape[1]))
            n = img.shape[0] // fh
            ft = int(anim.get("frametime", 1))
            seq = []
            for e in anim.get("frames", range(n)):
                if isinstance(e, dict):
                    seq.append((int(e["index"]), int(e.get("time", ft))))
                else:
                    seq.append((int(e), ft))
            period = sum(d for _, d in seq)
            t = float(self.tick) % period
            k = 0
            while k < len(seq) - 1 and t >= seq[k][1]:      # image affichée à ce tick
                t -= seq[k][1]
                k += 1
            i, d = seq[k]
            frame = img[i * fh:(i + 1) * fh, :fw]
            if anim.get("interpolate") and t > 0:
                j = seq[(k + 1) % len(seq)][0]
                nxt = img[j * fh:(j + 1) * fh, :fw].astype(float)
                frame = np.clip(np.round(frame.astype(float) * (1 - t / d) + nxt * (t / d)), 0, 255).astype(np.uint8)
            return frame
        return img

    @staticmethod
    def _deref(textures: dict, key: str) -> str | None:
        k = key
        for _ in range(16):
            if not k.startswith("#"):
                return k
            k = textures.get(k[1:])
            if k is None:
                return None
        return None

    def quads(self, model, offset=(0, 0, 0)) -> list:
        res = self.resolve(model)
        out = []
        off = np.asarray(offset, float)
        for el in res["elements"]:
            out += element_quads(el, lambda key: self._tex_for(res["textures"], key), off)
        if res["builtin"] == "generated":
            layer = self._deref(res["textures"], "#layer0")
            if layer:
                out += flat_item_quads(self.texture(layer), off)
        return out

    def _tex_for(self, textures, key):
        ref = self._deref(textures, key)
        if ref is None:
            self.missing.append(key)
            return missing_texture()
        return self.texture(ref)


def _rot_matrix(rot: dict) -> np.ndarray:
    axis = rot.get("axis", "y")
    ang = math.radians(float(rot.get("angle", 0)))
    c, s = math.cos(ang), math.sin(ang)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rotate(points: np.ndarray, rot: dict) -> np.ndarray:
    axis = rot.get("axis", "y")
    ang = math.radians(float(rot.get("angle", 0)))
    origin = np.asarray(rot.get("origin", [8, 8, 8]), float)
    M = _rot_matrix(rot)
    p = (points - origin) @ M.T
    if rot.get("rescale"):
        k = 1.0 / max(abs(math.cos(ang)), 1e-6)
        scale = np.array([1.0, 1.0, 1.0])
        for a in "xyz":
            if a != axis:
                scale["xyz".index(a)] = k
        p = p * scale
    return p + origin


def element_quads(el: dict, tex_lookup, offset=(0.0, 0.0, 0.0)) -> list:
    offset = np.asarray(offset, float)
    frm = np.asarray(el["from"], float)
    to = np.asarray(el["to"], float)
    lim = {"min": frm, "max": to}
    out = []
    for face, fd in el.get("faces", {}).items():
        tex = tex_lookup(fd["texture"])
        th, tw = tex.shape[:2]
        uv = fd.get("uv") or auto_uv(face, frm, to)
        rot = int(fd.get("rotation", 0)) % 360
        verts = np.array([[lim[a][0], lim[b][1], lim[c][2]] for a, b, c in FACE_INFO[face]], float)
        normal = np.asarray(NORMAL[face], float)
        if "rotation" in el:
            verts = _rotate(verts, el["rotation"])
            normal = _rot_matrix(el["rotation"]) @ normal
        uvs = []
        for i in range(4):
            j = (i + rot // 90) % 4
            u = uv[0] if j in (0, 1) else uv[2]
            v = uv[1] if j in (0, 3) else uv[3]
            uvs.append((u * tw / 16.0, v * th / 16.0))
        v0 = verts[0] + offset
        shade = bool(fd.get("shade", el.get("shade", True)))
        sdo = el.get("shade_direction_override")
        shade_dir = None
        if sdo == "up":
            shade = False                                   # remplace "shade": false depuis 26.x
        elif sdo:
            shade, shade_dir = True, sdo
        facing = closest_face(normal) if "rotation" in el else face
        out.append(Quad(v0, verts[1] - verts[0], verts[3] - verts[0], uvs[0], uvs[1], uvs[3], tex,
                        normal, facing, shade, tag="mc", emission=int(el.get("light_emission", 0)),
                        shade_dir=shade_dir))
    return out


def flat_item_quads(tex: np.ndarray, offset=(0.0, 0.0, 0.0)) -> list:
    """Approximation d'item/generated : la texture sur une plaque d'épaisseur 1 (faces avant/arrière)."""
    th, tw = tex.shape[:2]
    out = []
    z0, z1 = 7.5, 8.5
    p0 = np.array([0.0, 16.0, z1]) + offset
    out.append(Quad(p0, np.array([16.0, 0, 0]), np.array([0, -16.0, 0]), (0, 0), (tw, 0), (0, th), tex,
                    np.array([0, 0, 1.0]), "south", tag="item"))
    p0 = np.array([16.0, 16.0, z0]) + offset
    out.append(Quad(p0, np.array([-16.0, 0, 0]), np.array([0, -16.0, 0]), (tw, 0), (0, 0), (tw, th), tex,
                    np.array([0, 0, -1.0]), "north", tag="item"))
    return out
