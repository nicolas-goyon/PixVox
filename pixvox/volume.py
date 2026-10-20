"""pixvox.volume — volumes de voxels (le cœur « voxel-first » de pixvox).

Repère = repère des modèles Minecraft :
    x : ouest -> est      (0 .. sx-1)
    y : bas -> haut       (0 .. sy-1)
    z : nord -> sud       (0 .. sz-1)
Le voxel (i, j, k) occupe le cube [i, i+1] x [j, j+1] x [k, k+1] ; son centre est (i+.5, j+.5, k+.5).
Les primitives géométriques (sphère, cylindre…) prennent des coordonnées CONTINUES dans ce repère
(le bloc entier va de 0 à 16, son centre est (8, 8, 8)). Les boîtes (`m_box`) prennent des INDICES
de voxels, bornes incluses.

Pour un bloc plein, chaque texture de face est la couche extérieure du volume, lue avec exactement
la même orientation UV que Minecraft (voir FACE_AXES). Un voxel d'arête appartient à deux faces et
n'a qu'une couleur : la cohérence des arêtes est garantie par construction.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .color import Ramp, hexa, lightness, mix, rgba, unique_colors
from .color import adjust as adjust_color
from .noise import bell_weights, equalize, perlin, quantize_levels, worley
from .sprite import ASCII_CHARS, Sprite

FACES = ("up", "down", "north", "south", "west", "east")
NORMALS = {
    "up": (0, 1, 0), "down": (0, -1, 0),
    "north": (0, 0, -1), "south": (0, 0, 1),
    "west": (-1, 0, 0), "east": (1, 0, 0),
}
OPPOSITE = {"up": "down", "down": "up", "north": "south", "south": "north", "west": "east", "east": "west"}
AXIS = {"x": 0, "y": 1, "z": 2}

# Orientation des textures de faces (identique à Minecraft, cf. BlockElement.uvsByFace / FaceInfo).
# face: (axe de la couche, côté, axe u, sens u, axe v, sens v)
#   côté +1 = coordonnée max, -1 = min ; sens +1 = u/v croît avec la coordonnée, -1 = décroît.
FACE_AXES = {
    "up":    ("y", +1, "x", +1, "z", +1),   # vue de dessus, nord en haut de l'image, ouest à gauche
    "down":  ("y", -1, "x", +1, "z", -1),   # vue de dessous, sud en haut de l'image, ouest à gauche
    "north": ("z", -1, "x", -1, "y", -1),   # vue depuis le nord : est à gauche
    "south": ("z", +1, "x", +1, "y", -1),   # vue depuis le sud : ouest à gauche
    "west":  ("x", -1, "z", +1, "y", -1),   # vue depuis l'ouest : nord à gauche
    "east":  ("x", +1, "z", -1, "y", -1),   # vue depuis l'est : sud à gauche
}


def face_coords(face: str, lo=(0, 0, 0), hi=(16, 16, 16)):
    """Pour la face `face` de la boîte de voxels [lo, hi[, renvoie (X, Y, Z) de forme (H, W) :
    le voxel visible sous chaque texel (v=ligne, u=colonne) de la texture de cette face."""
    lax, lside, uax, udir, vax, vdir = FACE_AXES[face]
    la, ua, va = AXIS[lax], AXIS[uax], AXIS[vax]
    W, H = hi[ua] - lo[ua], hi[va] - lo[va]
    u, v = np.arange(W), np.arange(H)
    uc = lo[ua] + u if udir > 0 else hi[ua] - 1 - u
    vc = lo[va] + v if vdir > 0 else hi[va] - 1 - v
    lc = hi[la] - 1 if lside > 0 else lo[la]
    VV, UU = np.meshgrid(vc, uc, indexing="ij")
    out = [None, None, None]
    out[ua], out[va] = UU, VV
    out[la] = np.full((H, W), lc)
    return tuple(out)


def _norm(v):
    v = np.asarray(v, dtype=float)
    return v / (np.linalg.norm(v) + 1e-12)


def _rot_ypr(yaw: float, pitch: float = 0.0, roll: float = 0.0) -> np.ndarray:
    """Matrice de rotation Ry(yaw)·Rx(pitch)·Rz(roll) (degrés)."""
    a, b, c = (np.radians(x) for x in (yaw, pitch, roll))
    ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return ry @ rx @ rz


class Volume:
    def __init__(self, sx: int = 16, sy: int | None = None, sz: int | None = None, fill=None, res: int = 16):
        sy = sx if sy is None else sy
        sz = sx if sz is None else sz
        self.data = np.zeros((sx, sy, sz, 4), dtype=np.uint8)
        if fill is not None:
            self.data[...] = rgba(fill)
        self.log: list[str] = []
        self.res = int(res)          # voxels par bloc (16 = vanilla, 32 = HD…)
        self.vpu = self.res / 16.0   # voxels par unité de conception (1 unité = 1/16 de bloc à l'échelle 1)
        self.min_radius = 0.0        # rayon minimal des primitives, en voxels (évite qu'un détail fin disparaisse)

    @classmethod
    def design(cls, extent, res: int = 16, scale: float = 1.0, fill=None, min_radius: float = 0.75) -> Volume:
        """Volume « vectoriel » : on décrit l'objet en UNITÉS DE CONCEPTION (16 unités = 1 bloc à
        l'échelle 1, comme les pixels vanilla), puis on l'échantillonne à la résolution voulue.

        extent : taille de l'espace de conception (ex. (48, 56, 16) pour 3 x 3,5 x 1 blocs)
        res    : voxels par bloc (16 vanilla, 32 ou 64 = détail plus fin, 8 = gros pixels)
        scale  : taille réelle (1 = 16 unités par bloc ; 0.5 = objet deux fois plus petit)
        Toutes les primitives (sphères, segments, boîtes, rayons…) prennent alors des unités de
        conception : le même code produit l'objet à n'importe quelle résolution / taille.
        min_radius (voxels) : épaisseur minimale des primitives, pour qu'une auréole ou un doigt ne se
        brise pas en voxels isolés quand on réduit l'objet.
        """
        vpu = res / 16.0 * scale
        shape = tuple(max(1, int(round(float(e) * vpu))) for e in extent)
        v = cls(*shape, fill=fill, res=res)
        v.vpu = vpu
        v.min_radius = float(min_radius)
        v.log.append(f"design : {tuple(extent)} unités -> {shape} voxels (res {res}/bloc, échelle {scale:g})")
        return v

    # ------------------------------------------------------------------ propriétés
    @property
    def shape(self) -> tuple[int, int, int]:
        return tuple(self.data.shape[:3])  # type: ignore[return-value]

    @property
    def X(self):
        return np.broadcast_to(np.arange(self.shape[0])[:, None, None], self.shape)

    @property
    def Y(self):
        return np.broadcast_to(np.arange(self.shape[1])[None, :, None], self.shape)

    @property
    def Z(self):
        return np.broadcast_to(np.arange(self.shape[2])[None, None, :], self.shape)

    @property
    def solid(self) -> np.ndarray:
        return self.data[..., 3] > 0

    def frames(self, n: int) -> list:
        """n copies du volume : les images d'une animation (on ne change ensuite que les couleurs ;
        dans Minecraft la géométrie ne s'anime pas). Voir pixvox.anim.pulse / flow."""
        return [self.copy() for _ in range(int(n))]

    def copy(self) -> Volume:
        v = Volume(*self.shape, res=self.res)
        v.vpu = self.vpu
        v.min_radius = self.min_radius
        v.data = self.data.copy()
        v.log = list(self.log)
        return v

    @property
    def DX(self):
        """Abscisse du centre de chaque voxel en unités de conception (pour les motifs de détail)."""
        return (self.X + 0.5) / self.vpu

    @property
    def DY(self):
        return (self.Y + 0.5) / self.vpu

    @property
    def DZ(self):
        return (self.Z + 0.5) / self.vpu

    def _r(self, r: float) -> float:
        """Rayon en unités de conception, relevé au rayon minimal (min_radius voxels)."""
        return max(float(r), self.min_radius / self.vpu)

    def _vox(self, d: float) -> int:
        """Longueur en unités de conception -> nombre de voxels (au moins 1)."""
        return max(1, int(round(float(d) * self.vpu)))

    def colors(self) -> dict:
        return unique_colors(self.data)

    def _centers(self):
        """Centres des voxels en unités de conception."""
        return self.DX, self.DY, self.DZ

    def _delta(self, center, wrap=False):
        """Vecteurs (dx, dy, dz) des centres de voxels vers `center` (unités de conception ; périodiques
        si wrap)."""
        cx, cy, cz = self._centers()
        out = []
        for g, c, n in zip((cx, cy, cz), center, self.shape):
            d = g - c
            if wrap:
                period = n / self.vpu
                d = (d + period / 2.0) % period - period / 2.0
            out.append(d)
        return out

    # ------------------------------------------------------------------ masques
    def m_all(self) -> np.ndarray:
        return np.ones(self.shape, bool)

    def m_box(self, x0, y0, z0, x1, y1, z1) -> np.ndarray:
        """Boîte en « pixels » de conception, bornes INCLUSES (= indices de voxels à res 16, échelle 1)."""
        out = np.ones(self.shape, bool)
        for g, a, b in ((self.DX, x0, x1), (self.DY, y0, y1), (self.DZ, z0, z1)):
            out &= (g >= min(a, b)) & (g < max(a, b) + 1)
        return out

    def m_cuboid(self, lo, hi) -> np.ndarray:
        """Boîte CONTINUE [lo, hi[ en unités de conception : m_cuboid((0, 0, 0), (16, 2, 16)) = dalle de
        16 x 2 x 16 unités (à comparer avec m_box, dont les bornes sont incluses : m_box(0,0,0, 15,1,15)).
        Une dimension plus fine qu'un voxel garde un voxel d'épaisseur (le détail ne disparaît pas)."""
        out = np.ones(self.shape, bool)
        for g, a, b in zip(self._centers(), lo, hi):
            a, b = sorted((float(a), float(b)))
            c, half = (a + b) / 2.0, max((b - a) / 2.0, 0.5 / self.vpu)
            out &= (g >= c - half) & (g < c + half)
        return out

    def m_ellipsoid(self, center, radii, wrap: bool = False, rotation=None) -> np.ndarray:
        """Ellipsoïde (coordonnées continues). rotation=(yaw, pitch, roll) en degrés : tourne ses axes
        (yaw autour de y, pitch autour de x, roll autour de z) — ailes, feuilles, pétales inclinés."""
        dx, dy, dz = self._delta(center, wrap)
        if rotation is not None:
            M = _rot_ypr(*rotation)
            d = np.stack([dx, dy, dz], -1) @ M          # coordonnées dans le repère de l'ellipsoïde
            dx, dy, dz = d[..., 0], d[..., 1], d[..., 2]
        rx, ry, rz = (self._r(r) for r in radii)
        return (dx / rx) ** 2 + (dy / ry) ** 2 + (dz / rz) ** 2 <= 1.0

    def m_segment(self, a, b, r0: float, r1: float | None = None) -> np.ndarray:
        """Capsule (r1 = r0) ou cône arrondi (r1 ≠ r0) entre les points a et b (coordonnées continues).
        La brique de base pour sculpter : membres, troncs, cristaux (r1=0 : pointe), drapés."""
        r1 = r0 if r1 is None else r1
        r0, r1 = self._r(r0), self._r(r1)
        C = np.stack(self._centers(), -1)
        A, B = np.asarray(a, float), np.asarray(b, float)
        AB = B - A
        L2 = max(float(AB @ AB), 1e-9)
        t = np.clip(((C - A) @ AB) / L2, 0.0, 1.0)
        d = np.linalg.norm(C - (A + t[..., None] * AB), axis=-1)
        return d <= r0 + (r1 - r0) * t

    def m_tube(self, points, radii) -> np.ndarray:
        """Suite de segments (lianes, tentacules, plis) ; radii = un rayon ou un rayon par point."""
        pts = [np.asarray(p, float) for p in points]
        rs = list(radii) if isinstance(radii, (list, tuple, np.ndarray)) else [float(radii)] * len(pts)
        m = np.zeros(self.shape, bool)
        for i in range(len(pts) - 1):
            m |= self.m_segment(pts[i], pts[i + 1], rs[i], rs[i + 1])
        return m

    def m_torus(self, center, R: float, r: float, axis: str = "y") -> np.ndarray:
        """Tore (auréole, anneau) : grand rayon R autour de `axis`, épaisseur r."""
        dx, dy, dz = self._delta(center)
        a, b, h = {"x": (dy, dz, dx), "y": (dx, dz, dy), "z": (dx, dy, dz)}[axis]
        r = self._r(r)
        return (np.hypot(a, b) - R) ** 2 + h ** 2 <= r * r

    def m_sphere(self, center, r: float, wrap: bool = False) -> np.ndarray:
        return self.m_ellipsoid(center, (r, r, r), wrap)

    def m_cylinder(self, center2d, r: float, lo: int, hi: int, axis: str = "y") -> np.ndarray:
        """Cylindre d'axe `axis` ; center2d en coordonnées continues sur les deux autres axes ;
        lo/hi = « pixels » de conception (inclus) le long de l'axe."""
        cx, cy, cz = self._centers()
        a, b, h = {"x": (cy, cz, cx), "y": (cx, cz, cy), "z": (cx, cy, cz)}[axis]
        return ((a - center2d[0]) ** 2 + (b - center2d[1]) ** 2 <= r * r) & (h >= lo) & (h < hi + 1)

    def boundary_distance(self) -> np.ndarray:
        """Distance (en voxels) à la face extérieure la plus proche (0 = couche extérieure)."""
        sx, sy, sz = self.shape
        X, Y, Z = self.X, self.Y, self.Z
        return np.minimum.reduce([X, sx - 1 - X, Y, sy - 1 - Y, Z, sz - 1 - Z])

    def edge_distance(self) -> np.ndarray:
        """Distance à l'arête la plus proche (0 = voxel posé sur une des 12 arêtes)."""
        sx, sy, sz = self.shape
        X, Y, Z = self.X, self.Y, self.Z
        d = np.stack([np.minimum(X, sx - 1 - X), np.minimum(Y, sy - 1 - Y), np.minimum(Z, sz - 1 - Z)], -1)
        d = np.sort(d, axis=-1)
        return d[..., 1]

    def corner_distance(self) -> np.ndarray:
        sx, sy, sz = self.shape
        X, Y, Z = self.X, self.Y, self.Z
        d = np.stack([np.minimum(X, sx - 1 - X), np.minimum(Y, sy - 1 - Y), np.minimum(Z, sz - 1 - Z)], -1)
        return d.max(-1)

    def m_shell(self, depth: int = 1) -> np.ndarray:
        """Voxels à moins de `depth` (unités de conception) d'une face extérieure : la « peau »."""
        return self.boundary_distance() < self._vox(depth)

    def m_layer(self, face: str, depth: int = 1, offset: int = 0) -> np.ndarray:
        """Couche(s) de voxels collée(s) contre une face : offset = décalage vers l'intérieur."""
        lax, lside, *_ = FACE_AXES[face]
        a = AXIS[lax]
        idx = (self.X, self.Y, self.Z)[a]
        n = self.shape[a]
        dist = (n - 1 - idx) if lside > 0 else idx
        off = int(round(offset * self.vpu))
        return (dist >= off) & (dist < off + self._vox(depth))

    def m_edges(self, width: int = 1) -> np.ndarray:
        """Voxels le long des 12 arêtes, sur une largeur `width` (unités de conception)."""
        w = self._vox(width)
        return (self.edge_distance() < w) & (self.boundary_distance() < w)

    def m_corners(self, size: int = 1) -> np.ndarray:
        return self.corner_distance() < self._vox(size)

    def _neighbor_solid(self, d) -> np.ndarray:
        s = self.solid
        out = np.zeros_like(s)
        dx, dy, dz = d
        sx, sy, sz = self.shape
        src = s[max(0, dx):sx + min(0, dx), max(0, dy):sy + min(0, dy), max(0, dz):sz + min(0, dz)]
        out[max(0, -dx):sx + min(0, -dx), max(0, -dy):sy + min(0, -dy), max(0, -dz):sz + min(0, -dz)] = src
        return out

    def m_exposed(self, face: str) -> np.ndarray:
        """Voxels pleins dont le voisin dans la direction `face` est vide (ou hors volume)."""
        return self.solid & ~self._neighbor_solid(NORMALS[face])

    def m_surface(self) -> np.ndarray:
        """Voxels pleins visibles depuis au moins une direction."""
        m = np.zeros(self.shape, bool)
        for f in FACES:
            m |= self.m_exposed(f)
        return m

    def m_hidden(self) -> np.ndarray:
        """Voxels pleins entièrement entourés (invisibles : leur couleur n'a aucune importance)."""
        return self.solid & ~self.m_surface()

    def m_noise(self, threshold: float = 0.5, *, cells=4, octaves: int = 2, seed: int = 0,
                mask: np.ndarray | None = None) -> np.ndarray:
        """Masque aléatoire périodique : la fraction (1 - threshold) des voxels où le bruit est le plus fort."""
        n = perlin(self.shape, cells, seed=seed, octaves=octaves)
        ref = self.m_surface() if mask is None else mask
        t = equalize(n, ref if ref.any() else None)
        m = t > threshold
        return m if mask is None else (m & mask)

    # ------------------------------------------------------------------ écriture
    def set(self, mask: np.ndarray | None, color) -> Volume:
        """Écrit une couleur (ou un tableau (sx,sy,sz,4)) là où mask est vrai (None = partout)."""
        m = self.m_all() if mask is None else mask
        if isinstance(color, np.ndarray) and color.shape[:3] == self.shape:
            self.data[m] = color[m]
        else:
            self.data[m] = rgba(color)
        return self

    def fill(self, color) -> Volume:
        return self.set(None, color)

    def clear(self, mask: np.ndarray | None = None) -> Volume:
        return self.set(mask, None)

    def box(self, x0, y0, z0, x1, y1, z1, color) -> Volume:
        return self.set(self.m_box(x0, y0, z0, x1, y1, z1), color)

    def sphere(self, center, r, color, wrap=False) -> Volume:
        return self.set(self.m_sphere(center, r, wrap), color)

    def ellipsoid(self, center, radii, color, wrap=False) -> Volume:
        return self.set(self.m_ellipsoid(center, radii, wrap), color)

    def cylinder(self, center2d, r, lo, hi, color, axis="y") -> Volume:
        return self.set(self.m_cylinder(center2d, r, lo, hi, axis), color)

    def tint(self, mask, color, t: float = 0.5) -> Volume:
        """Mélange (OKLab) la couleur des voxels pleins du masque vers `color`."""
        m = (self.m_all() if mask is None else mask) & self.solid
        cache = {}
        for idx in zip(*np.nonzero(m)):
            c = tuple(int(v) for v in self.data[idx])
            if c not in cache:
                cache[c] = mix(c, color, t)
            self.data[idx] = cache[c]
        return self

    def adjust(self, mask, dL: float = 0.0, dC: float = 0.0, dh: float = 0.0, mulC: float = 1.0) -> Volume:
        """Décale clarté / chroma / teinte (OKLCH) des voxels pleins du masque."""
        m = (self.m_all() if mask is None else mask) & self.solid
        cache = {}
        for idx in zip(*np.nonzero(m)):
            c = tuple(int(v) for v in self.data[idx])
            if c not in cache:
                cache[c] = adjust_color(c, dL=dL, dC=dC, dh=dh, mulC=mulC)
            self.data[idx] = cache[c]
        return self

    def shift_ramp(self, mask, ramp: Ramp, steps: int) -> Volume:
        """Décale de `steps` crans dans `ramp` les voxels du masque dont la couleur appartient à la rampe."""
        m = (self.m_all() if mask is None else mask) & self.solid
        index = {c: i for i, c in enumerate(ramp)}
        for idx in zip(*np.nonzero(m)):
            c = tuple(int(v) for v in self.data[idx])
            if c in index:
                self.data[idx] = ramp.step(index[c] + steps)
        return self

    # ------------------------------------------------------------------ générateurs
    def noise(self, ramp: Ramp, *, cells=4, octaves: int = 2, seed: int = 0, mask: np.ndarray | None = None,
              weights="bell", persistence: float = 0.5) -> Volume:
        """Colore avec un bruit 3D périodique quantifié sur la rampe.

        Les proportions de chaque ton (weights) sont calculées sur les voxels VISIBLES du masque :
        c'est ce que l'on verra sur les faces. cells=(cx,cy,cz) étire le motif (ex. fibres de bois).
        Sans masque : tout le volume (rempli s'il était vide).
        """
        m = self.m_all() if mask is None else mask
        n = perlin(self.shape, cells, seed=seed, octaves=octaves, persistence=persistence)
        tmp_solid = self.solid.copy()
        if mask is None and not tmp_solid.any():
            vis = self.m_shell(1)
        else:
            vis = m & self.m_surface() if (m & self.solid).any() else m & self.m_shell(1)
            if not vis.any():
                vis = m
        t = equalize(n, vis)
        w = bell_weights(len(ramp)) if weights == "bell" else ([1] * len(ramp) if weights == "flat" else weights)
        lv = quantize_levels(t, w)
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        self.data[m] = cols[lv[m]]
        return self

    def cells(self, ramp: Ramp, *, count: int = 14, seed: int = 0, mask: np.ndarray | None = None,
              mortar=None, mortar_width: float = 0.9, light=(-0.45, 1.0, -0.35), relief: float = 0.55,
              tone_range=(0.3, 0.7), edge_shadow: float = 0.0) -> np.ndarray:
        """Pierres / cellules 3D (Worley) avec joints et relief éclairé de façon cohérente en 3D.

        Chaque cellule reçoit un ton de base ; le côté tourné vers `light` est éclairci, l'autre
        assombri. `mortar` (couleur ou None = ton le plus sombre de la rampe) remplit les joints.
        edge_shadow (0–0.4) assombrit le pourtour des pierres : elles paraissent bombées, moins
        « dalles ». Retourne le masque des JOINTS (pour y faire pousser mousse, lave, cristaux…).
        """
        m = self.m_all() if mask is None else mask
        mortar_width = mortar_width * self.vpu                    # unités de conception -> voxels
        F1, F2, idx, pts = worley(self.shape, count, seed=seed)
        rng = np.random.default_rng(seed + 7919)
        base = rng.uniform(tone_range[0], tone_range[1], len(pts))
        cx, cy, cz = self._centers()
        L = _norm(light)
        delta = []
        for k, g in enumerate((cx, cy, cz)):
            n = self.shape[k]
            d = g - pts[idx, k]
            delta.append((d + n / 2.0) % n - n / 2.0)
        scale = np.maximum(F2, 1e-6)
        dot = (delta[0] * L[0] + delta[1] * L[1] + delta[2] * L[2]) / scale
        tone = base[idx] + relief * dot
        if edge_shadow:
            tone = tone - edge_shadow * np.clip(1.0 - (F2 - F1 - mortar_width) / (1.5 * self.vpu), 0.0, 1.0)
        lv = np.clip(np.round(tone * (len(ramp) - 1)), 1 if mortar is None else 0, len(ramp) - 1).astype(int)
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        out = cols[lv]
        border = (F2 - F1) < mortar_width
        out[border] = rgba(ramp[0] if mortar is None else mortar)
        self.data[m] = out[m]
        return border & m

    def blobs(self, ramp: Ramp, *, count: int = 6, radius=(1.4, 2.4), seed: int = 0,
              mask: np.ndarray | None = None, light=(-0.35, 1.0, -0.45), on_edges: int = 1, on_corners: int = 0,
              wrap: bool = True, rim: float = 0.78, depth=(0.0, 0.9), bumpiness: float = 0.25,
              rim_color=None) -> np.ndarray:
        """Amas (minerai, cristaux, taches) en 3D, posés près de la surface.

        - `on_edges` / `on_corners` : nombre d'amas centrés sur une arête / un coin : ils s'enroulent
          autour du bloc et apparaissent sur 2 ou 3 faces, de façon cohérente.
        - Ombrage 3D : côté `light` clair, contour (rim) le plus sombre de la rampe.
        - wrap=True : un amas qui dépasse d'un côté réapparaît de l'autre (raccord entre blocs voisins).
        Retourne le masque des voxels peints (pratique pour assombrir le contour avec m_dilate).
        """
        rng = np.random.default_rng(seed)
        S = np.array(self.shape, dtype=float) / self.vpu        # étendue en unités de conception
        target = self.m_all() if mask is None else mask
        L = _norm(light)
        bump = perlin(self.shape, 4, seed=seed + 101, octaves=1)
        centers = []
        for _ in range(on_corners):
            c = np.array([rng.choice([0.0, s]) for s in S])
            c += np.where(c == 0, 1, -1) * rng.uniform(0.0, 0.7, 3)
            centers.append(c)
        for _ in range(on_edges):
            a = int(rng.integers(0, 3))
            c = np.array([rng.choice([0.0, s]) for s in S])
            c[a] = rng.uniform(2.5, S[a] - 2.5)
            others = [k for k in range(3) if k != a]
            for k in others:
                c[k] += (1 if c[k] == 0 else -1) * rng.uniform(0.2, 0.8)
            centers.append(c)
        areas = np.array([S[0] * S[2], S[0] * S[2], S[0] * S[1], S[0] * S[1], S[1] * S[2], S[1] * S[2]])
        while len(centers) < count + on_edges + on_corners:
            f = FACES[int(rng.choice(6, p=areas / areas.sum()))]
            lax, lside, *_ = FACE_AXES[f]
            a = AXIS[lax]
            c = rng.uniform(1.5, S - 1.5)
            d = rng.uniform(*depth)
            c[a] = (S[a] - d) if lside > 0 else d
            centers.append(c)
        out = []
        painted = np.zeros(self.shape, bool)
        for c in centers:
            r = float(rng.uniform(*radius))
            aniso = rng.uniform(0.85, 1.15, 3)
            dx, dy, dz = self._delta(c, wrap)
            rr = r * (1.0 + bumpiness * bump)
            rho = np.sqrt((dx / aniso[0]) ** 2 + (dy / aniso[1]) ** 2 + (dz / aniso[2]) ** 2) / rr
            inside = (rho <= 1.0) & target
            if not inside.any():
                continue
            tone = 0.5 + 0.5 * (dx * L[0] + dy * L[1] + dz * L[2]) / r
            n = len(ramp)
            lv = np.clip(1 + np.round(np.clip(tone, 0, 1) * (n - 2)), 1, n - 1).astype(int)
            lv[rho > rim] = 0
            cols = np.array([rgba(col) for col in ramp], dtype=np.uint8)
            out_col = cols[lv]
            if rim_color is not None:
                out_col[rho > rim] = rgba(rim_color)
            self.data[inside] = out_col[inside]
            painted |= inside
            out.append((tuple(float(x) for x in np.round(c, 1)), round(r, 2)))
        self.log.append(f"blobs: {len(out)} amas posés (centre, rayon) : {out}")
        return painted

    def m_dilate(self, mask: np.ndarray, steps: int = 1, wrap: bool = False, diagonal: bool = False) -> np.ndarray:
        """Agrandit un masque d'un voxel par pas (voisinage 6, ou 26 si diagonal)."""
        m = mask.copy()
        if diagonal:
            offs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)]
        else:
            offs = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        for _ in range(steps):
            cur = m.copy()
            for d in offs:
                if wrap:
                    m |= np.roll(cur, d, axis=(0, 1, 2))
                else:
                    sh = np.zeros_like(cur)
                    src = cur[max(0, -d[0]):cur.shape[0] - max(0, d[0]), max(0, -d[1]):cur.shape[1] - max(0, d[1]),
                              max(0, -d[2]):cur.shape[2] - max(0, d[2])]
                    sh[max(0, d[0]):cur.shape[0] - max(0, -d[0]), max(0, d[1]):cur.shape[1] - max(0, -d[1]),
                       max(0, d[2]):cur.shape[2] - max(0, -d[2])] = src
                    m |= sh
        return m

    def occupancy(self, radius: int = 2) -> np.ndarray:
        """Occupation lissée (0–1) : ≈0.5 sur une surface plane, plus dans les creux, moins sur les
        arêtes saillantes. Sert aux normales et à l'occlusion ambiante."""
        occ = self.solid.astype(float)
        k = np.array([1.0])
        for _ in range(max(1, int(radius))):                      # binomiale de rayon `radius` voxels
            k = np.convolve(k, [1.0, 2.0, 1.0])
        k = np.array(k, float) / sum(k)
        r = len(k) // 2
        for ax in range(3):
            pad = [(0, 0)] * 3
            pad[ax] = (r, r)
            p = np.pad(occ, pad)
            acc = np.zeros_like(occ)
            for i, w in enumerate(k):
                sl = [slice(None)] * 3
                sl[ax] = slice(i, i + occ.shape[ax])
                acc += w * p[tuple(sl)]
            occ = acc
        return occ

    def normals(self, smooth: int = 2) -> np.ndarray:
        """Normales 3D estimées (gradient de l'occupation lissée, rayon `smooth` voxels), (sx, sy, sz, 3)."""
        occ = self.occupancy(max(1, int(smooth)))
        g = np.stack(np.gradient(occ), -1)
        n = -g
        return n / (np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9)

    def shade(self, mask, ramp: Ramp, *, light=(-0.4, 1.0, -0.3), contrast: float = 1.0, bias: float = 0.0,
              smooth: int = 2, noise: float = 0.0, seed: int = 0, ao: float = 0.0) -> Volume:
        """Colore `mask` selon l'éclairage d'une lumière 3D sur la forme (normales automatiques).

        Idéal pour les modèles organiques (champignon, rocher, statue) : le modelé est cohérent sous
        tous les angles. contrast > 1 durcit, bias décale vers le clair (+) ou le sombre (-),
        noise ajoute un léger grain (0.1–0.3) pour casser les dégradés trop réguliers.
        ao (0.3–1) : occlusion ambiante — creux et plis assombris, arêtes saillantes éclaircies ; donne
        du relief aux formes sculptées (bras contre le corps, plis, dessous des ailes).
        """
        m = mask & self.solid
        n = self.normals(max(1, int(round(smooth * self.vpu))))
        L = _norm(light)
        tone = 0.5 + 0.5 * (n @ L)
        if ao:
            tone = tone - ao * (self.occupancy(max(1, int(round(3 * self.vpu)))) - 0.5) * 2.0
        if noise:
            tone = tone + noise * perlin(self.shape, 4, seed=seed, octaves=2)
        k = len(ramp) - 1
        lv = np.clip(np.round((tone - 0.5) * contrast * k + k / 2 + bias), 0, k).astype(int)
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        self.data[m] = cols[lv[m]]
        return self

    def cap(self, ramp: Ramp, *, depth=(1, 4), seed: int = 0, cells=4, octaves: int = 2,
            color_cells=4, mask: np.ndarray | None = None, shadow: bool = True) -> np.ndarray:
        """Couche de dessus d'épaisseur irrégulière (herbe, mousse, neige) qui déborde sur les côtés.

        L'épaisseur varie en (x, z) : sur les faces latérales elle dessine des « coulures »
        irrégulières, identiques de part et d'autre de chaque arête. Retourne le masque posé.
        """
        sx, sy, sz = self.shape
        n2 = perlin((sx, sz), cells, seed=seed, octaves=octaves)
        t = equalize(n2)
        lo, hi = depth[0] * self.vpu, depth[1] * self.vpu            # unités de conception -> voxels
        d = np.maximum(1, np.floor(lo + t * (hi - lo + 0.999))).astype(int)        # (sx, sz)
        D = d[:, None, :]
        capm = (self.Y >= sy - D) & self.solid
        if mask is not None:
            capm &= mask
        n3 = perlin(self.shape, color_cells, seed=seed + 1, octaves=2)
        vis = capm & self.m_surface()
        tt = equalize(n3, vis if vis.any() else capm)
        lv = quantize_levels(tt, bell_weights(len(ramp)))
        lv = np.clip(lv, 1 if shadow else 0, len(ramp) - 1)
        if shadow:
            tip = capm & (self.Y == sy - D)                           # pointe des coulures : ombre
            lv = np.where(tip & (D > 1), np.maximum(lv - 1, 0), lv)
            lv = np.where(tip & (D > 1) & (t[:, None, :] > 0.85), 0, lv)
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        self.data[capm] = cols[lv[capm]]
        return capm

    def paint_face(self, face: str, sprite: Sprite, inset: int = 0, at=(0, 0)) -> dict:
        """Peint un sprite 2D sur une face, dans l'orientation EXACTE où il apparaîtra en jeu.

        Les pixels transparents du sprite ne peignent rien. Les pixels posés sur le bord de la face
        modifient aussi les faces voisines (c'est le même voxel) : le nombre de voxels partagés
        touchés est renvoyé et noté dans le journal du volume.
        """
        X, Y, Z = face_coords(face, (0, 0, 0), self.shape)
        n = NORMALS[face]
        X, Y, Z = X - n[0] * inset, Y - n[1] * inset, Z - n[2] * inset
        H, W = X.shape
        ox, oy = at
        sx, sy, sz = self.shape
        touched = Counter()
        painted = 0
        for v in range(sprite.h):
            for u in range(sprite.w):
                c = sprite.data[v, u]
                tu, tv = u + ox, v + oy
                if c[3] == 0 or not (0 <= tu < W and 0 <= tv < H):
                    continue
                x, y, z = int(X[tv, tu]), int(Y[tv, tu]), int(Z[tv, tu])
                self.data[x, y, z] = c
                painted += 1
                for f2, hit in (("west", x == 0), ("east", x == sx - 1), ("down", y == 0),
                                ("up", y == sy - 1), ("north", z == 0), ("south", z == sz - 1)):
                    if hit and f2 != face and inset == 0:
                        touched[f2] += 1
        if touched:
            self.log.append(f"paint_face({face}): {painted} px, dont voxels d'arête partagés avec "
                            + ", ".join(f"{k} ({v})" for k, v in touched.items()))
        else:
            self.log.append(f"paint_face({face}): {painted} px, aucun voxel d'arête touché")
        return dict(touched)

    # ------------------------------------------------------------------ lecture
    def face(self, face: str) -> Sprite:
        """Texture d'une face d'un bloc plein (couche extérieure, orientation Minecraft)."""
        X, Y, Z = face_coords(face, (0, 0, 0), self.shape)
        return Sprite(data=self.data[X, Y, Z])

    def faces(self) -> dict:
        return {f: self.face(f) for f in FACES}

    @classmethod
    def from_faces(cls, faces: dict, resolve: str = "priority", priority=("up", "north", "south", "east",
                                                                          "west", "down")):
        """Construit la peau d'un bloc depuis 6 textures (Sprites, tableaux ou chemins PNG).

        Retourne (volume, conflits). Un conflit = un voxel d'arête/coin qui reçoit des couleurs
        différentes selon la face (exactement l'erreur classique). resolve='priority' garde la
        couleur de la première face de `priority` ; 'majority' la plus fréquente.
        """
        sp = {}
        for f, s in faces.items():
            if s is None:
                continue
            if isinstance(s, Sprite):
                sp[f] = s
            elif isinstance(s, np.ndarray):
                sp[f] = Sprite(data=s)
            else:
                sp[f] = Sprite.load(s)
        sx = sp.get("up", sp.get("down", sp.get("north", sp.get("south")))).w
        sy = sp.get("north", sp.get("south", sp.get("west", sp.get("east", Sprite(sx))))).h
        sz = sp.get("west", sp.get("east", Sprite(sx))).w if ("west" in sp or "east" in sp) else \
            sp.get("up", sp.get("down", Sprite(sx))).h
        vol = cls(sx, sy, sz)
        contrib: dict = {}
        for f, s in sp.items():
            X, Y, Z = face_coords(f, (0, 0, 0), (sx, sy, sz))
            for v in range(s.h):
                for u in range(s.w):
                    key = (int(X[v, u]), int(Y[v, u]), int(Z[v, u]))
                    contrib.setdefault(key, []).append((f, u, v, tuple(int(c) for c in s.data[v, u])))
        conflicts = []
        rank = {f: i for i, f in enumerate(priority)}
        for key, lst in contrib.items():
            cols = [c for *_, c in lst]
            if len(set(cols)) > 1:
                conflicts.append({"voxel": key, "faces": [(f, u, v, hexa(c)) for f, u, v, c in lst]})
            if resolve == "majority":
                chosen = Counter(cols).most_common(1)[0][0]
            else:
                chosen = sorted(lst, key=lambda e: rank.get(e[0], 99))[0][3]
            vol.data[key] = chosen
        vol.log.append(f"from_faces: {len(conflicts)} voxels d'arête en conflit (résolution : {resolve})")
        return vol, conflicts

    @classmethod
    def from_slices(cls, slices: list, legend: dict, transparent: str = ". ") -> Volume:
        """Volume depuis des tranches horizontales ASCII, de BAS en HAUT (slices[0] = y=0).

        Dans chaque tranche : ligne = z (ligne 0 = nord), colonne = x (colonne 0 = ouest),
        c'est-à-dire une vue de dessus, nord en haut — la même orientation que la texture 'up'.
        """
        sl = [Sprite.from_ascii(s, legend, transparent) for s in slices]
        sx = max(s.w for s in sl)
        sz = max(s.h for s in sl)
        vol = cls(sx, len(sl), sz)
        for y, s in enumerate(sl):
            vol.data[:s.w, y, :s.h] = np.transpose(s.data, (1, 0, 2))
        return vol

    def to_slices_ascii(self) -> str:
        cols = self.colors()
        ordered = sorted(cols, key=lambda c: (lightness(c), c))
        legend = {c: ASCII_CHARS[i % len(ASCII_CHARS)] for i, c in enumerate(ordered)}
        out = []
        for y in range(self.shape[1]):
            out.append(f"-- y={y} (ligne = z nord->sud, colonne = x ouest->est)")
            for z in range(self.shape[2]):
                row = ""
                for x in range(self.shape[0]):
                    c = tuple(int(v) for v in self.data[x, y, z])
                    row += "." if c[3] == 0 else legend[c]
                out.append(row)
        out.append("légende :")
        out += [f"  {ch} = {hexa(c)} ({cols[c]})" for c, ch in legend.items()]
        return "\n".join(out)

    # ------------------------------------------------------------------ transformations
    def resample(self, shape=None, factor: float | None = None, threshold: float = 0.5,
                 prefer_surface: bool = True) -> Volume:
        """Change la résolution d'un volume existant (réduction : couleur majoritaire, un voxel est plein
        si au moins `threshold` de sa zone l'est ; agrandissement : plus proche voisin).
        prefer_surface : la couleur majoritaire est prise parmi les voxels VISIBLES de la zone (mousse,
        dorure, liseré) plutôt que parmi l'intérieur caché.

        resample(factor=0.5)   -> deux fois moins de voxels par côté (statue -> figurine)
        resample((14, 16, 5))  -> taille exacte
        Pour garder tous les détails, mieux vaut re-voxeliser la description (Volume.design) quand elle
        existe ; resample() sert aux volumes dessinés à la main (tranches ASCII, imports).
        """
        src = np.array(self.shape)
        if shape is None:
            if factor is None:
                raise ValueError("donner shape ou factor")
            shape = tuple(max(1, int(round(n * factor))) for n in src)
        shape = tuple(int(n) for n in shape)
        out = Volume(*shape, res=max(1, int(round(self.res * shape[0] / src[0]))))
        out.vpu = self.vpu * shape[0] / src[0]
        edges = [np.round(np.linspace(0, src[k], shape[k] + 1)).astype(int) for k in range(3)]
        solid = self.solid
        surf = self.m_surface() if prefer_surface else solid
        flat = self.data.reshape(-1, 4)
        for i in range(shape[0]):
            x0, x1 = edges[0][i], max(edges[0][i + 1], edges[0][i] + 1)
            for j in range(shape[1]):
                y0, y1 = edges[1][j], max(edges[1][j + 1], edges[1][j] + 1)
                for k in range(shape[2]):
                    z0, z1 = edges[2][k], max(edges[2][k + 1], edges[2][k] + 1)
                    sub = solid[x0:x1, y0:y1, z0:z1]
                    if sub.size == 0 or sub.mean() < threshold:
                        continue
                    vis = surf[x0:x1, y0:y1, z0:z1]
                    cols = self.data[x0:x1, y0:y1, z0:z1][vis if vis.any() else sub]
                    vals, counts = np.unique(cols, axis=0, return_counts=True)
                    out.data[i, j, k] = vals[np.argmax(counts)]
        del flat
        out.log = list(self.log) + [f"resample : {tuple(int(n) for n in src)} -> {shape}"]
        return out

    def rotate_y(self, k: int = 1) -> Volume:
        """Rotation de k*90° dans le sens horaire vu de dessus (nord -> est), comme Minecraft."""
        v = self.copy()
        v.data = np.ascontiguousarray(np.rot90(self.data, k, axes=(0, 2)))
        return v

    def mirror(self, axis: str = "x") -> Volume:
        v = self.copy()
        v.data = np.ascontiguousarray(np.flip(self.data, AXIS[axis]))
        return v

    def __repr__(self) -> str:
        return f"Volume{self.shape} ({int(self.solid.sum())} voxels pleins, {len(self.colors())} couleurs)"
