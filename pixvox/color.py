"""pixvox.color — couleurs, rampes perceptuelles (OKLab / OKLCH) et utilitaires.

Toutes les couleurs sont manipulées comme des tuples RGBA (0-255).
Formats acceptés partout : "#rgb", "#rrggbb", "#rrggbbaa", (r,g,b), (r,g,b,a), None (transparent).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

TRANSPARENT = (0, 0, 0, 0)


# ----------------------------------------------------------------------------- parsing
def rgba(c) -> tuple[int, int, int, int]:
    """Convertit n'importe quelle couleur acceptée en tuple RGBA d'entiers."""
    if c is None:
        return TRANSPARENT
    if isinstance(c, str):
        s = c.strip().lower()
        if s in ("", "none", "transparent", "clear"):
            return TRANSPARENT
        if s.startswith("#"):
            s = s[1:]
        if len(s) in (3, 4):
            s = "".join(ch * 2 for ch in s)
        if len(s) == 6:
            s += "ff"
        if len(s) != 8:
            raise ValueError(f"couleur invalide : {c!r}")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    if isinstance(c, (tuple, list, np.ndarray)):
        vals = [int(round(float(x))) for x in c]
        if len(vals) == 3:
            vals.append(255)
        if len(vals) != 4:
            raise ValueError(f"couleur invalide : {c!r}")
        return tuple(max(0, min(255, v)) for v in vals)  # type: ignore[return-value]
    raise TypeError(f"couleur invalide : {c!r}")


def hexa(c) -> str:
    """'#rrggbb' (ou '#rrggbbaa' si alpha < 255)."""
    r, g, b, a = rgba(c)
    return f"#{r:02x}{g:02x}{b:02x}" + ("" if a == 255 else f"{a:02x}")


# ----------------------------------------------------------------------------- OKLab
def _srgb_to_lin(x):
    x = np.asarray(x, dtype=float) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(x):
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055) * 255.0


def rgb_to_oklab(rgb) -> np.ndarray:
    """rgb : tableau (...,3) en 0-255 -> (...,3) OKLab (L dans 0-1)."""
    lin = _srgb_to_lin(rgb)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    lc = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    mc = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    sc = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(lc), np.cbrt(mc), np.cbrt(sc)
    return np.stack([
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    ], axis=-1)


def _oklab_to_lin(lab) -> np.ndarray:
    lab = np.asarray(lab, dtype=float)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    lc, mc, sc = l_ ** 3, m_ ** 3, s_ ** 3
    return np.stack([
        4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
        -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
        -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc,
    ], axis=-1)


def oklab_to_rgb(lab) -> np.ndarray:
    return _lin_to_srgb(_oklab_to_lin(lab))


def oklch(c) -> tuple[float, float, float]:
    """(L 0-1, C ~0-0.37, h degrés) d'une couleur."""
    L, a, b = rgb_to_oklab(np.array(rgba(c)[:3], dtype=float))
    return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360.0)


def from_oklch(L: float, C: float, h: float, alpha: int = 255) -> tuple[int, int, int, int]:
    """Construit une couleur depuis OKLCH en réduisant la chroma si hors gamut sRGB."""
    L = float(np.clip(L, 0.0, 1.0))
    C = max(0.0, float(C))
    for _ in range(40):
        a = C * math.cos(math.radians(h))
        b = C * math.sin(math.radians(h))
        lin = _oklab_to_lin(np.array([L, a, b]))
        if np.all(lin >= -1e-4) and np.all(lin <= 1 + 1e-4):
            break
        C *= 0.9
    rgb = _lin_to_srgb(lin)
    return (int(round(rgb[0])), int(round(rgb[1])), int(round(rgb[2])), int(alpha))


# ----------------------------------------------------------------------------- mesures
def luminance(c) -> float:
    """Luminance relative (WCAG) 0-1."""
    lin = _srgb_to_lin(np.array(rgba(c)[:3], dtype=float))
    return float(0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2])


def lightness(c) -> float:
    """Clarté perceptuelle OKLab L (0-1) — meilleure que la luminance pour comparer des valeurs."""
    return oklch(c)[0]


def delta_e(c1, c2) -> float:
    """Distance perceptuelle OKLab x100 (≈1 = à peine visible, >10 = nettement différent)."""
    a = rgb_to_oklab(np.array(rgba(c1)[:3], dtype=float))
    b = rgb_to_oklab(np.array(rgba(c2)[:3], dtype=float))
    return float(np.linalg.norm(a - b) * 100.0)


def lightness_array(rgba_arr: np.ndarray) -> np.ndarray:
    """Clarté OKLab L pour un tableau (...,4) ou (...,3) uint8."""
    return rgb_to_oklab(np.asarray(rgba_arr)[..., :3].astype(float))[..., 0]


# ----------------------------------------------------------------------------- transformations
def mix(c1, c2, t: float = 0.5):
    """Mélange perceptuel (OKLab) de deux couleurs ; t=0 -> c1, t=1 -> c2."""
    a, b = rgba(c1), rgba(c2)
    la = rgb_to_oklab(np.array(a[:3], dtype=float))
    lb = rgb_to_oklab(np.array(b[:3], dtype=float))
    rgb = oklab_to_rgb(la + (lb - la) * t)
    alpha = a[3] + (b[3] - a[3]) * t
    return rgba((*rgb, alpha))


def adjust(c, dL: float = 0.0, dC: float = 0.0, dh: float = 0.0, mulC: float = 1.0):
    """Ajuste une couleur en OKLCH (clarté, chroma, teinte)."""
    r = rgba(c)
    L, C, h = oklch(r)
    return from_oklch(L + dL, C * mulC + dC, h + dh, r[3])


def lighten(c, amount: float = 0.06):
    return adjust(c, dL=amount)


def darken(c, amount: float = 0.06):
    return adjust(c, dL=-amount)


def shade(c, factor: float):
    """Multiplie le RGB (comme l'ombrage directionnel de Minecraft)."""
    r, g, b, a = rgba(c)
    return rgba((r * factor, g * factor, b * factor, a))


def _toward(h: float, target: float, amount: float) -> float:
    """Tourne la teinte h vers target d'au plus `amount` degrés (chemin le plus court)."""
    d = (target - h + 180.0) % 360.0 - 180.0
    step = max(-abs(amount), min(abs(amount), d))
    return (h + step) % 360.0


# ----------------------------------------------------------------------------- rampes
class Ramp(tuple):
    """Rampe de couleurs, de la plus sombre (index 0) à la plus claire (index -1)."""

    def __new__(cls, colors: Iterable):
        return super().__new__(cls, tuple(rgba(c) for c in colors))

    def at(self, t: float):
        """Couleur à la position t (0 = sombre, 1 = clair), arrondie à l'index le plus proche."""
        i = int(round(float(np.clip(t, 0.0, 1.0)) * (len(self) - 1)))
        return self[i]

    def step(self, i: int):
        """Index borné (i < 0 -> 0, i > n-1 -> n-1)."""
        return self[max(0, min(len(self) - 1, int(i)))]

    @property
    def darkest(self):
        return self[0]

    @property
    def lightest(self):
        return self[-1]

    @property
    def mid(self):
        return self[len(self) // 2]

    def hex(self) -> list[str]:
        return [hexa(c) for c in self]

    def __repr__(self) -> str:
        return "Ramp(" + ", ".join(self.hex()) + ")"


def ramp(base, n: int = 5, spread: float = 0.40, hue_shift: float = 16.0, tint: float = 0.012,
         base_index: float | None = None, warm: float = 85.0, cool: float = 268.0,
         dark_chroma: float = -0.25, light_chroma: float = -0.35) -> Ramp:
    """Génère une rampe « pixel-art » autour d'une couleur de base (sombre -> clair).

    - spread       : écart de clarté OKLab entre la plus sombre et la plus claire (0.12–0.2 pierre,
                     0.3–0.5 objets contrastés).
    - hue_shift    : rotation de teinte (degrés) aux extrémités : ombres vers `cool` (bleu),
                     lumières vers `warm` (jaune). Évite les rampes ternes « + noir / + blanc ».
    - tint         : petite chroma ajoutée aux extrémités dans ces directions (donne vie aux gris).
    - dark_chroma  : variation relative de chroma des ombres (-0.25 = 25 % moins saturées ; positif =
                     ombres plus saturées, à doser : à faible clarté la saturation monte vite).
    - light_chroma : idem pour les lumières (-0.35 = lumières un peu lavées).
    - base_index   : position de la couleur de base dans la rampe (défaut : milieu).
    Le calcul se fait en coordonnées a/b OKLab : deux bases presque identiques donnent toujours
    des rampes presque identiques (pas de saut entre gris chaud et gris froid).
    """
    L0, C0, h0 = oklch(base)
    alpha = rgba(base)[3]
    if n < 1:
        raise ValueError("n >= 1")
    if n == 1:
        return Ramp([base])
    b = (n - 1) / 2.0 if base_index is None else float(base_index)
    out = []
    for i in range(n):
        t = (i - b) / (n - 1)               # négatif = plus sombre
        L = float(np.clip(L0 + spread * t, 0.06, 0.97))
        k = min(1.0, abs(t) * 2.0)          # 0 à la base, 1 aux extrémités
        target = warm if t > 0 else cool
        h = _toward(h0, target, hue_shift * k)
        C = C0 * (1.0 + (dark_chroma if t < 0 else light_chroma) * k)
        a_ = max(C, 0.0) * math.cos(math.radians(h)) + tint * k * math.cos(math.radians(target))
        b_ = max(C, 0.0) * math.sin(math.radians(h)) + tint * k * math.sin(math.radians(target))
        out.append(from_oklch(L, math.hypot(a_, b_), math.degrees(math.atan2(b_, a_)) % 360.0, alpha))
    return Ramp(out)


def ramp_between(c1, c2, n: int = 5) -> Ramp:
    """Rampe par interpolation OKLab entre deux couleurs (c1 sombre -> c2 clair)."""
    return Ramp([mix(c1, c2, i / (n - 1)) for i in range(n)])


def unique_colors(arr: np.ndarray, include_transparent: bool = False) -> dict[tuple, int]:
    """Compte les couleurs RGBA d'un tableau (...,4)."""
    flat = np.asarray(arr).reshape(-1, 4)
    if not include_transparent:
        flat = flat[flat[:, 3] > 0]
    if len(flat) == 0:
        return {}
    cols, counts = np.unique(flat, axis=0, return_counts=True)
    return {tuple(int(v) for v in c): int(n) for c, n in zip(cols, counts)}


def nearest(c, palette: Sequence) -> tuple:
    """Couleur de `palette` la plus proche (OKLab)."""
    target = rgb_to_oklab(np.array(rgba(c)[:3], dtype=float))
    pal = [rgba(p) for p in palette]
    labs = rgb_to_oklab(np.array([p[:3] for p in pal], dtype=float))
    i = int(np.argmin(np.linalg.norm(labs - target, axis=1)))
    return pal[i]
