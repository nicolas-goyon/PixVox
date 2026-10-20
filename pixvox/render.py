"""pixvox.render — rasteriseur logiciel : projection orthographique, z-buffer, texels nets.

Deux sources de géométrie :
  - quads_from_volume : rendu « vérité terrain » d'un volume (chaque face de voxel visible) ;
  - pixvox.mcmodel.model_quads : rendu d'un modèle Minecraft JSON (éléments + UV), tel que le jeu l'affiche.
Comparer les deux permet de vérifier un export pixel par pixel.

Vues prédéfinies (yaw, pitch en degrés, rotations à droite comme dans Minecraft) :
  INVENTORY = (225, 30) : l'icône d'inventaire — dessus, face EST à gauche, face NORD à droite.
  BACK      = (45, -30) : vue opposée par dessous — dessous, OUEST à gauche, SUD à droite.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .volume import AXIS, FACE_AXES, FACES, NORMALS

INVENTORY = (225.0, 30.0)
BACK = (45.0, -30.0)
FRONT_N = (180.0, 0.0)     # regarde la face nord de face
FRONT_S = (0.0, 0.0)
SIDE_E = (270.0, 0.0)
SIDE_W = (90.0, 0.0)
TOP = (0.0, 90.0)          # vue de dessus, nord en haut, ouest à gauche

# Éclairage GUI de Minecraft (deux lumières diffuses dans l'espace vue, ambiant 0.4, puissance 0.6)
_GUI_L0 = np.array([-0.2225, 0.1715, 0.9598])
_GUI_L1 = np.array([-0.2150, 0.9719, 0.0966])
# Ombrage directionnel « dans le monde » (sans occlusion ambiante)
WORLD_SHADE = {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8, "west": 0.6, "east": 0.6}
NIGHT = 0.2               # vue « night » : luminosité d'une face sans light_emission, la nuit, sans torche
SHADINGS = ("gui", "world", "night", "flat")


def closest_face(n) -> str:
    """Direction Minecraft la plus proche d'une normale (comme FaceBakery.calculateFacing)."""
    best, face = -2.0, "up"
    for f, d in NORMALS.items():
        dot = float(np.dot(n, d))
        if dot > best + 1e-9:
            best, face = dot, f
    return face


@dataclass
class Quad:
    p0: np.ndarray            # coin 3D associé à uv0
    e1: np.ndarray            # arête vers le coin associé à uv1
    e2: np.ndarray            # arête vers le coin associé à uv2
    uv0: tuple                # coordonnées texels (u, v) aux trois coins
    uv1: tuple
    uv2: tuple
    tex: np.ndarray           # (h, w, 4) uint8
    normal: np.ndarray
    face: str = ""
    shade: bool = True
    tag: str = ""
    uvmin: tuple = field(default=None)
    uvmax: tuple = field(default=None)
    emission: int = 0         # light_emission 0–15 (luminosité propre, visible en vue « night »)
    shade_dir: str | None = None   # direction utilisée pour l'ombrage (shade_direction_override)

    def __post_init__(self):
        us = [self.uv0[0], self.uv1[0], self.uv2[0], self.uv1[0] + self.uv2[0] - self.uv0[0]]
        vs = [self.uv0[1], self.uv1[1], self.uv2[1], self.uv1[1] + self.uv2[1] - self.uv0[1]]
        if self.uvmin is None:
            self.uvmin = (min(us), min(vs))
        if self.uvmax is None:
            self.uvmax = (max(us), max(vs))

    def corners(self):
        return [self.p0, self.p0 + self.e1, self.p0 + self.e1 + self.e2, self.p0 + self.e2]

    def translated(self, d) -> Quad:
        q = Quad(self.p0 + np.asarray(d, float), self.e1, self.e2, self.uv0, self.uv1, self.uv2, self.tex,
                 self.normal, self.face, self.shade, self.tag, self.uvmin, self.uvmax, self.emission, self.shade_dir)
        return q


def rot_matrix(yaw: float, pitch: float) -> np.ndarray:
    """R = Rx(pitch) · Ry(yaw) (main droite), comme ItemTransform de Minecraft (rotationXYZ)."""
    a, b = math.radians(yaw), math.radians(pitch)
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    return rx @ ry


@dataclass
class Camera:
    R: np.ndarray
    scale: float              # pixels par unité de modèle (1 unité = 1/16 de bloc = 1 texel standard)
    cx: float                 # centre de l'image en coordonnées vue
    cy: float
    W: int
    H: int
    cz: float = 0.0           # perspective : profondeur (coordonnées vue) du plan de mise au point
    persp: float = 0.0        # perspective : distance œil -> ce plan (unités modèle) ; 0 = orthographique
    ox: float = 0.0           # décalage de l'image en pixels
    oy: float = 0.0

    @property
    def eye(self) -> np.ndarray:
        return np.array([self.cx, self.cy, self.cz + self.persp])

    def project(self, p):
        v = self.R @ np.asarray(p, float)
        k = 1.0
        if self.persp:
            k = self.persp / max(self.cz + self.persp - v[2], 1e-6)
        return np.array([self.W / 2 + self.ox + (v[0] - self.cx) * k * self.scale,
                         self.H / 2 + self.oy - (v[1] - self.cy) * k * self.scale, v[2]])


def fit_camera(quads, view=INVENTORY, W: int = 400, H: int = 400, margin: float = 0.07,
               jitter=(0.0, 0.0), persp: float = 0.0) -> Camera:
    """Caméra cadrée sur la géométrie.

    jitter : décalage (pixels) pour les comparaisons, afin qu'aucun centre de pixel ne tombe pile sur
             une frontière de texel (cas ambigu).
    persp  : 0 = projection orthographique (comme l'icône d'inventaire) ; sinon perspective, l'œil étant
             à `persp` fois la diagonale de l'objet (1.5–3 : naturel). La perspective lève l'illusion
             d'optique des vues par dessous (un cube vu d'en bas en orthographique ressemble à un coin
             de pièce vu d'en haut : il paraît creux).
    """
    R = rot_matrix(*view)
    pts = np.array([R @ c for q in quads for c in q.corners()]) if quads else np.zeros((1, 3))
    if not persp:
        x0, y0 = pts[:, 0].min(), pts[:, 1].min()
        x1, y1 = pts[:, 0].max(), pts[:, 1].max()
        bw, bh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        scale = min(W * (1 - 2 * margin) / bw, H * (1 - 2 * margin) / bh)
        return Camera(R, scale, (x0 + x1) / 2 + jitter[0] / scale, (y0 + y1) / 2 - jitter[1] / scale, W, H)
    lo, hi = pts.min(0), pts.max(0)
    c = (lo + hi) / 2
    D = float(persp) * max(float(np.linalg.norm(hi - lo)), 1e-6)
    k = D / (c[2] + D - pts[:, 2])
    sx, sy = (pts[:, 0] - c[0]) * k, (pts[:, 1] - c[1]) * k
    bw, bh = max(sx.max() - sx.min(), 1e-6), max(sy.max() - sy.min(), 1e-6)
    scale = min(W * (1 - 2 * margin) / bw, H * (1 - 2 * margin) / bh)
    ox = -(sx.max() + sx.min()) / 2 * scale + jitter[0]
    oy = (sy.max() + sy.min()) / 2 * scale + jitter[1]
    return Camera(R, scale, c[0], c[1], W, H, c[2], D, ox, oy)


def gui_camera(gui_scale: int = 2, view=INVENTORY, center=(8, 8, 8), display_scale: float = 0.625) -> Camera:
    """Caméra « taille réelle » d'une case d'inventaire (16 px GUI x gui_scale)."""
    R = rot_matrix(*view)
    c = R @ np.asarray(center, float)
    size = 16 * gui_scale
    return Camera(R, display_scale * gui_scale, c[0], c[1], size, size)


def _shade_factor(q: Quad, R: np.ndarray, shading: str) -> float:
    if shading == "flat":
        return 1.0
    if shading in ("world", "night"):
        f = WORLD_SHADE.get(q.shade_dir or q.face, 1.0) if q.shade else 1.0
        if shading == "night":
            f *= NIGHT + (1.0 - NIGHT) * min(15, max(0, q.emission)) / 15.0
        return f
    if not q.shade:
        return 1.0
    n = R @ (np.asarray(NORMALS[q.shade_dir], float) if q.shade_dir else q.normal)
    f = 0.4 + 0.6 * (max(0.0, float(n @ _GUI_L0)) + max(0.0, float(n @ _GUI_L1)))
    return min(1.0, f)


def render(quads, cam: Camera, bg=None, shading: str = "gui", eps_px: float = 2e-3,
           return_depth: bool = False, alpha_cutoff: int = 1):
    """Rend une liste de Quads. Retourne une image (H, W, 4) uint8 (et le z-buffer si demandé).

    shading : 'gui' (icône d'inventaire), 'world' (ombrage des faces en jeu), 'night' (nuit sans torche :
              seules les faces à light_emission restent claires) ou 'flat' (couleurs brutes).
    Les texels opaques (alpha 255) passent dans le z-buffer ; les semi-transparents sont mélangés ensuite.
    """
    if shading not in SHADINGS:
        raise ValueError(f"shading={shading!r} : choisir parmi {', '.join(SHADINGS)}")
    W, H = cam.W, cam.H
    img = np.zeros((H, W, 4), dtype=float)
    if bg is not None:
        from .color import rgba
        img[...] = rgba(bg)
    zbuf = np.full((H, W), -np.inf)
    fbuf = np.full((H, W), -np.inf)       # orientation de la face retenue (départage des pixels d'arête)
    mbuf = np.full((H, W), -1e9)          # marge (px, <= 0) : < 0 si le pixel n'est couvert que par la tolérance
    translucent = []
    for q in quads:
        nv = cam.R @ q.normal
        P0v = cam.R @ q.p0
        if cam.persp:
            if float((cam.eye - P0v) @ nv) <= 1e-9:
                continue                              # face vue de dos (perspective)
        elif nv[2] <= 1e-9:
            continue                                  # face vue de dos
        P0 = cam.project(q.p0)
        P1 = cam.project(q.p0 + q.e1)
        P2 = cam.project(q.p0 + q.e2)
        P3 = cam.project(q.p0 + q.e1 + q.e2)
        A1, A2 = P1[:2] - P0[:2], P2[:2] - P0[:2]
        cs = np.array([P0[:2], P1[:2], P2[:2], P3[:2]])
        ix0 = max(0, int(math.floor(cs[:, 0].min())))
        ix1 = min(W, int(math.ceil(cs[:, 0].max())) + 1)
        iy0 = max(0, int(math.floor(cs[:, 1].min())))
        iy1 = min(H, int(math.ceil(cs[:, 1].max())) + 1)
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        px, py = np.meshgrid(np.arange(ix0, ix1) + 0.5, np.arange(iy0, iy1) + 0.5)
        if cam.persp:
            # lancer de rayon : œil -> pixel, intersection avec le plan du quad (UV exactes en perspective)
            E1v, E2v = cam.R @ q.e1, cam.R @ q.e2
            N = np.cross(E1v, E2v)
            eye = cam.eye
            dxr = (px - W / 2 - cam.ox) / cam.scale
            dyr = -(py - H / 2 - cam.oy) / cam.scale
            dzr = -cam.persp
            denom = dxr * N[0] + dyr * N[1] + dzr * N[2]
            with np.errstate(divide="ignore", invalid="ignore"):
                lam = float((P0v - eye) @ N) / denom
            X = eye[0] + lam * dxr - P0v[0]
            Y = eye[1] + lam * dyr - P0v[1]
            Z = eye[2] + lam * dzr - P0v[2]
            w1, w2 = np.cross(E2v, N), np.cross(E1v, N)
            s = (X * w1[0] + Y * w1[1] + Z * w1[2]) / float(E1v @ w1)
            t = (X * w2[0] + Y * w2[1] + Z * w2[2]) / float(E2v @ w2)
            es = eps_px / max(float(np.hypot(*A1)), 1e-6)       # tolérance en PIXELS (pas en fraction du quad)
            et = eps_px / max(float(np.hypot(*A2)), 1e-6)
            inside = (lam > 0) & (s >= -es) & (s <= 1 + es) & (t >= -et) & (t <= 1 + et)
            depth = Z + P0v[2]
        else:
            det = A1[0] * A2[1] - A1[1] * A2[0]
            if abs(det) < 1e-9:
                continue
            dx, dy = px - P0[0], py - P0[1]
            s = (dx * A2[1] - dy * A2[0]) / det
            t = (A1[0] * dy - A1[1] * dx) / det
            es = eps_px / max(float(np.hypot(*A1)), 1e-6)       # tolérance en PIXELS (pas en fraction du quad)
            et = eps_px / max(float(np.hypot(*A2)), 1e-6)
            inside = (s >= -es) & (s <= 1 + es) & (t >= -et) & (t <= 1 + et)
            depth = P0[2] + s * (P1[2] - P0[2]) + t * (P2[2] - P0[2])
        if not inside.any():
            continue
        L1, L2 = max(float(np.hypot(*A1)), 1e-6), max(float(np.hypot(*A2)), 1e-6)
        margin = np.minimum(np.minimum(s, 1 - s) * L1, np.minimum(t, 1 - t) * L2)
        margin = np.where(inside, np.minimum(margin, 0.0), -1e9)
        s = np.where(inside, s, 0.0)
        t = np.where(inside, t, 0.0)
        u = q.uv0[0] + s * (q.uv1[0] - q.uv0[0]) + t * (q.uv2[0] - q.uv0[0])
        v = q.uv0[1] + s * (q.uv1[1] - q.uv0[1]) + t * (q.uv2[1] - q.uv0[1])
        th, tw = q.tex.shape[:2]
        u = np.clip(u, q.uvmin[0], q.uvmax[0] - 1e-4)
        v = np.clip(v, q.uvmin[1], q.uvmax[1] - 1e-4)
        iu = np.clip(np.floor(u).astype(int), 0, tw - 1)
        iv = np.clip(np.floor(v).astype(int), 0, th - 1)
        texel = q.tex[iv, iu].astype(float)
        a = texel[..., 3]
        f = _shade_factor(q, cam.R, shading)
        rgb = texel[..., :3] * f
        sub_z = zbuf[iy0:iy1, ix0:ix1]
        sub_f = fbuf[iy0:iy1, ix0:ix1]
        sub_m = mbuf[iy0:iy1, ix0:ix1]
        # Le plus proche gagne. À égalité de profondeur (pixel pile sur une arête, faces coplanaires
        # voisines, surcouche) : d'abord le quad qui contient VRAIMENT le centre du pixel (pas seulement
        # grâce à la tolérance anti-trous), puis la face la plus tournée vers la caméra, puis la dernière
        # dessinée (comme le test de profondeur LEQUAL du jeu pour une surcouche).
        facing = float(nv[2])
        tie = np.abs(depth - sub_z) <= 1e-7
        better = (margin > sub_m + 1e-9) | ((np.abs(margin - sub_m) <= 1e-9) & (facing >= sub_f - 1e-9))
        opaque = inside & (a >= 255) & ((depth > sub_z + 1e-7) | (tie & better))
        sub_img = img[iy0:iy1, ix0:ix1]
        sub_img[opaque, :3] = rgb[opaque]
        sub_img[opaque, 3] = 255
        sub_z[opaque] = depth[opaque]
        sub_f[opaque] = facing
        sub_m[opaque] = margin[opaque]
        semi = inside & (a >= alpha_cutoff) & (a < 255)
        if semi.any():
            translucent.append((float(np.mean(depth[semi])), iy0, ix0, semi, depth, rgb, a))
    for _, iy0, ix0, semi, depth, rgb, a in sorted(translucent, key=lambda e: e[0]):
        h, w = semi.shape
        sub_img = img[iy0:iy0 + h, ix0:ix0 + w]
        sub_z = zbuf[iy0:iy0 + h, ix0:ix0 + w]
        m = semi & (depth >= sub_z - 1e-7)
        al = (a / 255.0)[..., None]
        sub_img[m, :3] = sub_img[m, :3] * (1 - al[m]) + rgb[m] * al[m]
        sub_img[m, 3] = np.maximum(sub_img[m, 3], a[m])
    out = np.clip(np.round(img), 0, 255).astype(np.uint8)
    return (out, zbuf) if return_depth else out


# ----------------------------------------------------------------------------- géométrie
def face_quad(face: str, lo, hi, tex: np.ndarray, shade: bool = True, tag: str = "") -> Quad:
    """Quad de la face `face` de la boîte [lo, hi] (unités modèle) texturée par `tex` posé
    dans l'orientation FACE_AXES (texel (0,0) = coin u=0, v=0)."""
    lax, lside, uax, udir, vax, vdir = FACE_AXES[face]
    la, ua, va = AXIS[lax], AXIS[uax], AXIS[vax]
    p0 = np.zeros(3)
    p0[la] = hi[la] if lside > 0 else lo[la]
    p0[ua] = lo[ua] if udir > 0 else hi[ua]
    p0[va] = lo[va] if vdir > 0 else hi[va]
    e1 = np.zeros(3)
    e2 = np.zeros(3)
    e1[ua] = (hi[ua] - lo[ua]) * udir
    e2[va] = (hi[va] - lo[va]) * vdir
    th, tw = tex.shape[:2]
    return Quad(p0, e1, e2, (0.0, 0.0), (float(tw), 0.0), (0.0, float(th)), tex,
                np.array(NORMALS[face], float), face, shade, tag)


def _rects(mask: np.ndarray) -> list:
    """Découpe un masque 2D (H, W) en rectangles pleins (v0, u0, v1, u1), bornes exclusives."""
    H, W = mask.shape
    used = np.zeros_like(mask)
    out = []
    for v in range(H):
        for u in range(W):
            if not mask[v, u] or used[v, u]:
                continue
            u1 = u
            while u1 < W and mask[v, u1] and not used[v, u1]:
                u1 += 1
            v1 = v + 1
            while v1 < H and mask[v1, u:u1].all() and not used[v1, u:u1].any():
                v1 += 1
            used[v:v1, u:u1] = True
            out.append((v, u, v1, u1))
    return out


def quads_from_volume(vol, offset=(0, 0, 0), voxel_size: float = 1.0, emissive=None, emission: int = 15) -> list:
    """Rendu exact d'un volume : pour chaque direction et chaque couche, les faces de voxels exposées
    (voisin vide) regroupées en rectangles texturés. C'est la référence « vérité terrain ».
    emissive : masque des voxels lumineux (leurs faces reçoivent emission, visible en vue 'night')."""
    from .volume import face_coords
    sx, sy, sz = vol.shape
    off = np.asarray(offset, float)
    quads = []
    for f in FACES:
        lax, lside, *_ = FACE_AXES[f]
        a = AXIS[lax]
        exposed = vol.m_exposed(f)
        for layer in range(vol.shape[a]):
            lo = [0, 0, 0]
            hi = [sx, sy, sz]
            lo[a], hi[a] = layer, layer + 1
            X, Y, Z = face_coords(f, lo, hi)
            m = exposed[X, Y, Z]
            if not m.any():
                continue
            tex = vol.data[X, Y, Z].copy()
            full = face_quad(f, np.array(lo, float) * voxel_size + off, np.array(hi, float) * voxel_size + off,
                             tex, tag=f"{f}@{layer}")
            H, W = m.shape
            groups = [(m, 0)] if emissive is None else [(m & ~emissive[X, Y, Z], 0),
                                                         (m & emissive[X, Y, Z], int(emission))]
            for mm, em in groups:
                for v0, u0, v1, u1 in _rects(mm):
                    p0 = full.p0 + full.e1 * (u0 / W) + full.e2 * (v0 / H)
                    quads.append(Quad(p0, full.e1 * ((u1 - u0) / W), full.e2 * ((v1 - v0) / H),
                                      (float(u0), float(v0)), (float(u1), float(v0)), (float(u0), float(v1)),
                                      tex, full.normal, f, True, full.tag, emission=em))
    return quads


def plane_quads(center, y: float, width: float, height: float, angle: float, tex: np.ndarray,
                emission: int = 0, shade: bool = False, tag: str = "plane") -> list:
    """Les deux faces d'un plan vertical texturé (Plane), calculées directement par trigonométrie :
    la texture apparaît entière, haut en haut, non inversée vue de chaque côté (comme un élément
    Minecraft d'épaisseur nulle avec uv [0, 0, 16, 16] sur ses deux faces)."""
    a = math.radians((float(angle) + 90.0) % 180.0 - 90.0)
    d = np.array([math.cos(a), 0.0, -math.sin(a)])
    n = np.array([math.sin(a), 0.0, math.cos(a)])
    top = np.array([float(center[0]), float(y) + float(height), float(center[1])])
    th, tw = tex.shape[:2]
    e2 = np.array([0.0, -float(height), 0.0])
    out = []
    for p0, e1, nn in ((top - d * width / 2, d * width, n), (top + d * width / 2, -d * width, -n)):
        out.append(Quad(p0, e1, e2, (0.0, 0.0), (float(tw), 0.0), (0.0, float(th)), tex, nn, closest_face(nn),
                        shade, tag, emission=int(emission)))
    return out


def cube_quads(face_textures: dict, offset=(0, 0, 0), size: float = 16.0, skip=()) -> list:
    """Les 6 faces d'un bloc plein à partir de ses textures (orientation Minecraft)."""
    off = np.asarray(offset, float)
    return [face_quad(f, off, off + size, np.asarray(t.data if hasattr(t, "data") else t), tag=f)
            for f, t in face_textures.items() if f not in skip]


def item_quads(tex: np.ndarray, z0: float = 7.5, z1: float = 8.5) -> list:
    """Item plat extrudé comme item/generated : la texture devant et derrière, et une tranche de
    1 texel d'épaisseur sur chaque bord de pixel opaque (aspect de l'item tenu en main ou au sol)."""
    tex = np.asarray(tex)
    h, w = tex.shape[:2]
    sx, sy = 16.0 / w, 16.0 / h
    quads = [
        Quad(np.array([0.0, 16.0, z1]), np.array([16.0, 0, 0]), np.array([0, -16.0, 0]),
             (0.0, 0.0), (float(w), 0.0), (0.0, float(h)), tex, np.array([0, 0, 1.0]), "south", True, "item"),
        Quad(np.array([16.0, 16.0, z0]), np.array([-16.0, 0, 0]), np.array([0, -16.0, 0]),
             (float(w), 0.0), (0.0, 0.0), (float(w), float(h)), tex, np.array([0, 0, -1.0]), "north", True, "item"),
    ]
    op = tex[..., 3] > 0
    for v in range(h):
        for u in range(w):
            if not op[v, u]:
                continue
            px = tex[v:v + 1, u:u + 1]
            lo = np.array([u * sx, 16.0 - (v + 1) * sy, z0])
            hi = np.array([(u + 1) * sx, 16.0 - v * sy, z1])
            for face, (du, dv) in (("west", (-1, 0)), ("east", (1, 0)), ("up", (0, -1)), ("down", (0, 1))):
                nu, nv = u + du, v + dv
                if not (0 <= nu < w and 0 <= nv < h) or not op[nv, nu]:
                    quads.append(face_quad(face, lo, hi, px, tag="item-edge"))
    return quads


def tiled_cube_quads(face_textures: dict, n=(3, 3, 3), glow: dict | None = None, emission: int = 15) -> list:
    """Assemblage n_x x n_y x n_z de blocs identiques : seules les faces extérieures sont gardées
    (comme le culling du jeu). Sert à juger les raccords. glow : surcouche lumineuse {face: texture}."""
    quads = []
    nx, ny, nz = n
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                skip = []
                for f, (dx, dy, dz) in NORMALS.items():
                    a, b, c = i + dx, j + dy, k + dz
                    if 0 <= a < nx and 0 <= b < ny and 0 <= c < nz:
                        skip.append(f)
                quads += cube_quads(face_textures, (16 * i, 16 * j, 16 * k), skip=skip)
                if glow:
                    for q in cube_quads(glow, (16 * i, 16 * j, 16 * k), skip=skip):
                        q.emission = emission
                        quads.append(q)
    return quads


# ----------------------------------------------------------------------------- utilitaires image
def compare(img_a: np.ndarray, img_b: np.ndarray, tol: int = 2, strict: bool = False):
    """Compare deux rendus. Retourne (nb de pixels réellement différents, image de différence en rouge).

    Par défaut, un pixel qui tombe pile sur une frontière de texels (la couleur de chaque image
    existe dans le voisinage 3x3 de l'autre) est considéré ambigu et n'est pas compté : le jeu
    lui-même peut afficher l'une ou l'autre. Une vraie erreur d'UV donne des zones entières fausses.
    """
    A, B = img_a.astype(int), img_b.astype(int)
    d = np.abs(A - B).max(-1) > tol
    if not strict and d.any():
        H, W = d.shape
        pa = np.pad(A, ((1, 1), (1, 1), (0, 0)), mode="edge")
        pb = np.pad(B, ((1, 1), (1, 1), (0, 0)), mode="edge")
        b_in_a = np.zeros_like(d)
        a_in_b = np.zeros_like(d)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sa = pa[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
                sb = pb[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
                b_in_a |= np.abs(sa - B).max(-1) <= tol
                a_in_b |= np.abs(sb - A).max(-1) <= tol
        d &= ~(b_in_a & a_in_b)
    vis = img_a.copy()
    vis[d] = (255, 0, 64, 255)
    return int(d.sum()), vis
