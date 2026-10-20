"""pixvox.sprite — images pixel-art 2D (textures, items, icônes).

Convention : (x, y) = (colonne, ligne), origine en haut à gauche, comme un fichier PNG.
Les données sont un tableau numpy (h, w, 4) uint8 accessible via `sprite.data`.
"""
from __future__ import annotations

import textwrap
from collections import deque

import numpy as np
from PIL import Image

from .color import Ramp, hexa, lightness, rgba, unique_colors
from .noise import bell_weights, equalize, perlin, quantize_levels

ASCII_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ@$%&*+=?!<>^~"


class Sprite:
    def __init__(self, w: int = 16, h: int | None = None, fill=None, data: np.ndarray | None = None):
        if data is not None:
            arr = np.asarray(data)
            if arr.ndim != 3 or arr.shape[2] not in (3, 4):
                raise ValueError("data doit être (h, w, 3|4)")
            if arr.shape[2] == 3:
                arr = np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, arr.dtype)], axis=2)
            self.data = arr.astype(np.uint8).copy()
        else:
            h = w if h is None else h
            self.data = np.zeros((h, w, 4), dtype=np.uint8)
            if fill is not None:
                self.data[...] = rgba(fill)

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_ascii(cls, art: str, legend: dict, transparent: str = ". ", pad: bool = False) -> Sprite:
        """Dessine un sprite depuis une grille de caractères.

        Chaque caractère = un pixel ; `legend` associe caractère -> couleur.
        '.' (et l'espace) = transparent sauf s'ils sont dans la légende.
        Les lignes vides du début/fin et l'indentation commune sont ignorées.
        Toutes les lignes doivent avoir la même longueur (sinon erreur : un caractère en trop donne un
        sprite 17x16) ; pad=True complète les lignes courtes par du transparent.
        """
        lines = textwrap.dedent(art).strip("\n").split("\n")
        lines = [ln.rstrip() for ln in lines]
        h = len(lines)
        w = max(len(ln) for ln in lines)
        lens = [len(ln) for ln in lines]
        if not pad and len(set(lens)) > 1:
            bad = [f"ligne {i}: {n}" for i, n in enumerate(lens) if n != max(set(lens), key=lens.count)]
            raise ValueError(f"lignes ASCII de longueurs différentes ({', '.join(bad[:6])}) ; "
                             "utilisez '.' pour le transparent, ou pad=True")
        s = cls(w, h)
        leg = {k: rgba(v) for k, v in legend.items()}
        for y, ln in enumerate(lines):
            for x, ch in enumerate(ln):
                if ch in leg:
                    s.data[y, x] = leg[ch]
                elif ch in transparent:
                    continue
                else:
                    raise ValueError(f"caractère {ch!r} (x={x}, y={y}) absent de la légende")
        return s

    @classmethod
    def from_levels(cls, levels: np.ndarray, ramp) -> Sprite:
        """Sprite depuis un tableau d'index (h, w) dans une rampe ; -1 = transparent.
        Les index sont bornés à la rampe (pratique pour décaler +1/-1 sans déborder)."""
        lv = np.asarray(levels)
        s = cls(lv.shape[1], lv.shape[0])
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        m = lv >= 0
        s.data[m] = cols[np.clip(lv[m], 0, len(cols) - 1)]
        return s

    @classmethod
    def load(cls, path) -> Sprite:
        with Image.open(path) as im:
            return cls(data=np.array(im.convert("RGBA")))

    def copy(self) -> Sprite:
        return Sprite(data=self.data)

    # ------------------------------------------------------------------ accès
    @property
    def w(self) -> int:
        return self.data.shape[1]

    @property
    def h(self) -> int:
        return self.data.shape[0]

    @property
    def X(self) -> np.ndarray:
        return np.broadcast_to(np.arange(self.w)[None, :], (self.h, self.w))

    @property
    def Y(self) -> np.ndarray:
        return np.broadcast_to(np.arange(self.h)[:, None], (self.h, self.w))

    def __getitem__(self, xy):
        x, y = xy
        return tuple(int(v) for v in self.data[y, x])

    def __setitem__(self, xy, c):
        x, y = xy
        self.data[y, x] = rgba(c)

    def opaque(self) -> np.ndarray:
        """Masque (h, w) des pixels non transparents."""
        return self.data[..., 3] > 0

    def colors(self) -> dict:
        return unique_colors(self.data)

    # ------------------------------------------------------------------ dessin
    def fill(self, c, mask: np.ndarray | None = None) -> Sprite:
        if mask is None:
            self.data[...] = rgba(c)
        else:
            self.data[mask] = rgba(c)
        return self

    def set(self, mask: np.ndarray, colors) -> Sprite:
        """Écrit une couleur (ou un tableau (h,w,4)) là où mask est vrai."""
        if isinstance(colors, np.ndarray) and colors.shape[:2] == self.data.shape[:2]:
            self.data[mask] = colors[mask]
        else:
            self.data[mask] = rgba(colors)
        return self

    def rect(self, x0, y0, x1, y1, c, fill: bool = True) -> Sprite:
        """Rectangle, bornes incluses."""
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        col = rgba(c)
        if fill:
            self.data[max(0, y0):y1 + 1, max(0, x0):x1 + 1] = col
        else:
            self.line(x0, y0, x1, y0, col).line(x0, y1, x1, y1, col)
            self.line(x0, y0, x0, y1, col).line(x1, y0, x1, y1, col)
        return self

    def line(self, x0, y0, x1, y1, c) -> Sprite:
        """Ligne de Bresenham (pixels nets, sans anti-crénelage)."""
        col = rgba(c)
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            if 0 <= x0 < self.w and 0 <= y0 < self.h:
                self.data[y0, x0] = col
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
        return self

    def ellipse(self, cx, cy, rx, ry, c, fill: bool = True) -> Sprite:
        """Ellipse centrée en (cx, cy) en coordonnées pixel continues (centre du pixel 3 = 3.5)."""
        X, Y = self.X + 0.5, self.Y + 0.5
        d = ((X - cx) / max(rx, 1e-6)) ** 2 + ((Y - cy) / max(ry, 1e-6)) ** 2
        m = d <= 1.0
        if not fill:
            inner = ((X - cx) / max(rx - 1, 1e-6)) ** 2 + ((Y - cy) / max(ry - 1, 1e-6)) ** 2 <= 1.0
            m = m & ~inner
        self.data[m] = rgba(c)
        return self

    def flood(self, x, y, c, tolerance: int = 0) -> Sprite:
        """Pot de peinture (4-connexe)."""
        target = self.data[y, x].astype(int)
        col = rgba(c)
        seen = np.zeros((self.h, self.w), bool)
        q = deque([(x, y)])
        while q:
            px, py = q.popleft()
            if not (0 <= px < self.w and 0 <= py < self.h) or seen[py, px]:
                continue
            if np.abs(self.data[py, px].astype(int) - target).max() > tolerance:
                continue
            seen[py, px] = True
            q.extend(((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)))
        self.data[seen] = col
        return self

    def outline(self, c, diagonal: bool = False, inner: bool = False) -> Sprite:
        """Contour autour (ou à l'intérieur, inner=True) de la silhouette opaque."""
        op = self.opaque()
        pad = np.pad(op, 1)
        nb = np.zeros_like(op)
        shifts = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        if diagonal:
            shifts += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dy, dx in shifts:
            sl = pad[1 + dy:1 + dy + self.h, 1 + dx:1 + dx + self.w]
            nb |= sl if not inner else ~sl
        m = (op & nb) if inner else (~op & nb)
        self.data[m] = rgba(c)
        return self

    def bevel(self, hi=None, lo=None, light=(-1, -1), mask: np.ndarray | None = None) -> Sprite:
        """Éclaircit les bords tournés vers la lumière, assombrit les bords opposés.

        `hi` / `lo` : couleurs (ou fonctions couleur -> couleur) ; light=(-1,-1) = lumière en haut à gauche.
        """
        op = self.opaque() if mask is None else mask
        pad = np.pad(op, 1)
        lx, ly = int(np.sign(light[0])), int(np.sign(light[1]))

        def empty(dx, dy):  # voisin (x+dx, y+dy) vide ou hors image
            return ~pad[1 + dy:1 + dy + self.h, 1 + dx:1 + dx + self.w]

        toward = np.zeros_like(op)
        away = np.zeros_like(op)
        if lx:
            toward |= empty(lx, 0)
            away |= empty(-lx, 0)
        if ly:
            toward |= empty(0, ly)
            away |= empty(0, -ly)
        for m, c in ((op & toward & ~away, hi), (op & away & ~toward, lo)):
            if c is None:
                continue
            if callable(c):
                ys, xs = np.nonzero(m)
                for y, x in zip(ys, xs):
                    self.data[y, x] = rgba(c(tuple(self.data[y, x])))
            else:
                self.data[m] = rgba(c)
        return self

    def noise(self, ramp: Ramp, *, cells=4, octaves: int = 2, seed: int = 0, mask: np.ndarray | None = None,
              weights="bell", persistence: float = 0.5) -> Sprite:
        """Remplit (dans `mask`) avec un bruit périodique quantifié sur la rampe.

        cells peut être un tuple (cx, cy) pour étirer (ex. (2, 8) = veines horizontales).
        weights : 'bell' (majorité de tons moyens), 'flat', ou liste de proportions par niveau.
        """
        n = perlin((self.w, self.h), cells, seed=seed, octaves=octaves, persistence=persistence).T  # -> (h, w)
        m = np.ones((self.h, self.w), bool) if mask is None else mask
        t = equalize(n, m)
        w = bell_weights(len(ramp)) if weights == "bell" else ([1] * len(ramp) if weights == "flat" else weights)
        lv = quantize_levels(t, w)
        cols = np.array([rgba(c) for c in ramp], dtype=np.uint8)
        self.data[m] = cols[lv[m]]
        return self

    def paste(self, other: Sprite, x: int = 0, y: int = 0) -> Sprite:
        """Colle `other` (pixels opaques uniquement) en (x, y)."""
        for oy in range(other.h):
            for ox in range(other.w):
                c = other.data[oy, ox]
                tx, ty = x + ox, y + oy
                if c[3] > 0 and 0 <= tx < self.w and 0 <= ty < self.h:
                    self.data[ty, tx] = c
        return self

    def replace(self, old, new) -> Sprite:
        o = np.array(rgba(old), np.uint8)
        m = np.all(self.data == o, axis=-1)
        self.data[m] = rgba(new)
        return self

    def recolor(self, mapping: dict) -> Sprite:
        src = self.data.copy()
        for old, new in mapping.items():
            m = np.all(src == np.array(rgba(old), np.uint8), axis=-1)
            self.data[m] = rgba(new)
        return self

    def flip_h(self) -> Sprite:
        return Sprite(data=self.data[:, ::-1])

    def flip_v(self) -> Sprite:
        return Sprite(data=self.data[::-1])

    def rot90(self, k: int = 1) -> Sprite:
        """Rotation de k*90° dans le sens antihoraire."""
        return Sprite(data=np.rot90(self.data, k))

    # ------------------------------------------------------------------ sorties
    def to_image(self, scale: int = 1) -> Image.Image:
        img = Image.fromarray(self.data, "RGBA")
        if scale != 1:
            img = img.resize((self.w * scale, self.h * scale), Image.NEAREST)
        return img

    def save(self, path, scale: int = 1) -> None:
        self.to_image(scale).save(path)

    def to_ascii(self, legend: dict | None = None) -> str:
        """Grille texte + légende (pour relire les pixels exacts)."""
        cols = self.colors()
        if legend is None:
            ordered = sorted(cols, key=lambda c: (lightness(c), c))
            legend = {c: ASCII_CHARS[i % len(ASCII_CHARS)] for i, c in enumerate(ordered)}
        else:
            legend = {rgba(v): k for k, v in legend.items()}
        rows = []
        for y in range(self.h):
            row = []
            for x in range(self.w):
                c = tuple(int(v) for v in self.data[y, x])
                row.append("." if c[3] == 0 else legend.get(c, "?"))
            rows.append("".join(row))
        leg = [f"  {ch} = {hexa(c)}  ({cols.get(c, 0)} px)" for c, ch in legend.items() if c in cols]
        head = "    " + "".join(str(i % 10) for i in range(self.w))
        body = [f"{y:>3} {r}" for y, r in enumerate(rows)]
        return "\n".join([head] + body + ["légende ('.' = transparent) :"] + leg)

    def __repr__(self) -> str:
        return f"Sprite({self.w}x{self.h}, {len(self.colors())} couleurs)"
