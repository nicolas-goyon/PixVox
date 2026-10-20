"""pixvox.noise — bruits périodiques (raccord parfait) en 2D et 3D.

Tous les bruits sont *périodiques sur la taille du tableau* : la colonne 15 « continue » sur la
colonne 0. C'est ce qui garantit qu'une texture se raccorde quand les blocs sont posés côte à côte.
"""
from __future__ import annotations

import itertools

import numpy as np


def _as_tuple(v, d):
    if isinstance(v, (int, float, np.integer, np.floating)):
        return tuple(int(v) for _ in range(d))
    v = tuple(int(x) for x in v)
    if len(v) != d:
        raise ValueError(f"attendu {d} valeurs, reçu {v}")
    return v


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _perlin_once(shape, cells, rng) -> np.ndarray:
    d = len(shape)
    cells = tuple(max(1, c) for c in cells)
    g = rng.normal(size=tuple(cells) + (d,))
    g /= np.linalg.norm(g, axis=-1, keepdims=True) + 1e-12
    coords = [(np.arange(n) + 0.5) * c / n for n, c in zip(shape, cells)]
    grids = np.meshgrid(*coords, indexing="ij")
    i0 = [np.floor(gk).astype(int) for gk in grids]
    f = [gk - ik for gk, ik in zip(grids, i0)]
    w = [_fade(fk) for fk in f]
    out = np.zeros(shape, dtype=float)
    for bits in itertools.product((0, 1), repeat=d):
        idx = tuple((i0[k] + bits[k]) % cells[k] for k in range(d))
        grad = g[idx]
        dot = np.zeros(shape, dtype=float)
        for k in range(d):
            dot += grad[..., k] * (f[k] - bits[k])
        weight = np.ones(shape, dtype=float)
        for k in range(d):
            weight *= w[k] if bits[k] else (1.0 - w[k])
        out += weight * dot
    return out * (2.0 / np.sqrt(d))


def perlin(shape, cells=4, seed: int = 0, octaves: int = 1, persistence: float = 0.5,
           lacunarity: int = 2) -> np.ndarray:
    """Bruit de gradient (Perlin) périodique.

    shape   : (sx, sy) ou (sx, sy, sz)
    cells   : nombre de cellules du réseau sur la période (int, ou un par axe pour étirer :
              ex. (2, 8, 8) = motif allongé le long de x, comme des fibres de bois).
    octaves : couches de détail (chaque octave double la fréquence).
    Retour  : tableau float centré sur 0 (≈ [-1, 1]).
    """
    shape = tuple(int(s) for s in shape)
    d = len(shape)
    base = _as_tuple(cells, d)
    rng = np.random.default_rng(seed)
    total = np.zeros(shape, dtype=float)
    amp, norm = 1.0, 0.0
    for o in range(max(1, octaves)):
        c = tuple(int(b * (lacunarity ** o)) for b in base)
        total += amp * _perlin_once(shape, c, rng)
        norm += amp
        amp *= persistence
    return total / norm


def worley(shape, points: int = 12, seed: int = 0, jitter_points=None):
    """Bruit cellulaire (Worley) périodique.

    Retourne (F1, F2, idx, pts) :
      F1  distance au point le plus proche, F2 au second (en voxels/pixels),
      idx index de la cellule la plus proche, pts positions des points.
    F2 - F1 petit = frontière entre cellules (joints, mortier, fissures).
    """
    shape = tuple(int(s) for s in shape)
    d = len(shape)
    rng = np.random.default_rng(seed)
    if jitter_points is not None:
        pts = np.asarray(jitter_points, dtype=float)
    else:
        pts = rng.random((points, d)) * np.array(shape, dtype=float)
    grids = np.meshgrid(*[np.arange(n) + 0.5 for n in shape], indexing="ij")
    dist2 = np.zeros((len(pts),) + shape, dtype=float)
    for k in range(d):
        delta = np.abs(grids[k][None, ...] - pts[:, k].reshape((-1,) + (1,) * d))
        delta = np.minimum(delta, shape[k] - delta)          # distance périodique
        dist2 += delta ** 2
    dist = np.sqrt(dist2)
    order = np.argsort(dist, axis=0)
    idx = order[0]
    F1 = np.take_along_axis(dist, order[0:1], axis=0)[0]
    F2 = np.take_along_axis(dist, order[1:2], axis=0)[0] if len(pts) > 1 else F1 * 0 + 99.0
    return F1, F2, idx, pts


def equalize(values: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Remplace chaque valeur par son rang normalisé dans [0, 1] (égalisation d'histogramme).

    Si `mask` est donné, les rangs sont calculés sur les valeurs masquées, puis appliqués à tout
    le tableau par interpolation (les valeurs hors masque restent cohérentes).
    """
    v = np.asarray(values, dtype=float)
    ref = v[mask] if mask is not None else v.ravel()
    if ref.size == 0:
        return np.zeros_like(v)
    srt = np.sort(ref)
    ranks = np.searchsorted(srt, v, side="left").astype(float)
    ranks_r = np.searchsorted(srt, v, side="right").astype(float)
    r = (ranks + ranks_r) / 2.0 / max(1, srt.size)
    return np.clip(r, 0.0, 1.0)


def quantize_levels(t: np.ndarray, weights) -> np.ndarray:
    """Découpe t (0-1, typiquement égalisé) en niveaux selon des proportions `weights`.

    weights = [1, 2, 3, 2, 1] -> 5 niveaux, le niveau central occupe 3/9 de la surface.
    """
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    edges = np.cumsum(w)[:-1]
    return np.searchsorted(edges, np.asarray(t, dtype=float), side="right")


def bell_weights(n: int) -> list[float]:
    """Proportions en cloche (majorité de tons moyens, peu d'extrêmes)."""
    if n <= 2:
        return [1.0] * n
    c = (n - 1) / 2.0
    return [float(1.0 + (c - abs(i - c)) * 1.0) for i in range(n)]
