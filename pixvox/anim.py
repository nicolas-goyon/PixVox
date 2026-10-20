"""pixvox.anim — textures animées (Minecraft : bande verticale d'images + fichier .png.mcmeta).

Dans Minecraft seule la TEXTURE s'anime : la géométrie d'un modèle est figée. pixvox propose donc :
  - Anim : une suite d'images 2D de même taille (flammes sur des plans, item animé…) ;
  - les volumes animés : Block / Model / MultiBlock acceptent une LISTE de volumes de même forme
    (une par image) — seules les couleurs changent (braises qui palpitent, lave qui coule, runes) ;
  - des générateurs qui bouclent sans à-coup : fire() (flammes 2D), pulse() et flow() (volumes).
Durées en ticks : 20 ticks = 1 seconde ; frametime = durée de chaque image (2 = 10 images/s).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .color import Ramp, rgba
from .noise import equalize, perlin
from .sprite import Sprite

# Rampes de feu (sombre -> clair). Le ton 0 sert au liseré extérieur des flammes.
FIRE = Ramp(["#7a1d08", "#c2410c", "#ec7a14", "#f9ad2a", "#fcd85a", "#fff6c4"])
SOUL_FIRE = Ramp(["#0e3f52", "#147a8f", "#27b4c8", "#5fe0e6", "#b5f8fb", "#f0ffff"])
EMBER = Ramp(["#2a1410", "#5a1d0e", "#922a0c", "#cf4a10", "#f2861c", "#ffc24a"])
SOUL_EMBER = Ramp(["#0f1c24", "#13384a", "#16607a", "#1f93ad", "#45c8db", "#a6f1f6"])


# ============================================================================ minutage
@dataclass
class Timing:
    """Minutage d'une animation, comme la section "animation" d'un .png.mcmeta.

    frametime   : ticks par image (1 tick = 1/20 s)
    interpolate : fondu entre images (Minecraft mélange les pixels) — doux pour une lueur, flou pour du feu
    order       : ordre des images [0, 1, 2, (3, 8), …] ; (index, ticks) donne une durée propre à une image
    """
    frametime: int = 2
    interpolate: bool = False
    order: list | None = None

    def __post_init__(self):
        ft = self.frametime
        if isinstance(ft, bool) or not float(ft).is_integer() or int(ft) < 1:
            raise ValueError(f"frametime = nombre entier de ticks >= 1 (reçu {ft!r}) ; 20 ticks = 1 s")
        self.frametime = int(ft)

    def sequence(self, n: int) -> list:
        """[(index d'image, durée en ticks), …] dans l'ordre de lecture."""
        if self.order is None:
            return [(i, self.frametime) for i in range(n)]
        out = []
        for e in self.order:
            if isinstance(e, dict):
                i, d = e["index"], e.get("time", self.frametime)
            elif isinstance(e, (tuple, list)):
                i, d = e[0], e[1]
            else:
                i, d = e, self.frametime
            for val, what in ((i, "index"), (d, "durée")):
                if isinstance(val, bool) or not float(val).is_integer():
                    raise ValueError(f"order : {what} {val!r} doit être un nombre entier (ticks)")
            i, d = int(i), int(d)
            if not 0 <= i < n:
                raise ValueError(f"image {i} hors de l'animation ({n} images)")
            if d < 1:
                raise ValueError(f"durée {d} pour l'image {i} : au moins 1 tick")
            out.append((i, d))
        if not out:
            raise ValueError("order vide")
        return out

    def period(self, n: int) -> int:
        """Durée d'une boucle complète, en ticks."""
        return sum(d for _, d in self.sequence(n))

    def at(self, n: int, tick: float):
        """(image courante, image suivante, fraction de fondu) au tick donné (boucle)."""
        seq = self.sequence(n)
        t = float(tick) % self.period(n)
        for k, (i, d) in enumerate(seq):
            if t < d:
                j = seq[(k + 1) % len(seq)][0]
                return i, j, (t / d if self.interpolate else 0.0)
            t -= d
        return seq[-1][0], seq[0][0], 0.0

    def starts(self, n: int) -> list:
        """Ticks de début de chaque image dans une boucle."""
        out, t = [], 0
        for _, d in self.sequence(n):
            out.append(t)
            t += d
        return out

    def describe(self, n: int) -> str:
        """« 16 images × 2 ticks = 1.6 s » (ou ordre personnalisé)."""
        if self.order is not None:
            txt = f"{n} images, ordre personnalisé ({len(self.sequence(n))} étapes) = {self.period(n) / 20:g} s"
        else:
            txt = f"{n} images × {self.frametime} tick(s) = {self.period(n) / 20:g} s"
        return txt + (", fondu" if self.interpolate else "")

    def mcmeta(self, n: int) -> dict:
        a: dict = {"frametime": self.frametime}
        if self.interpolate:
            a["interpolate"] = True
        if self.order is not None:
            a["frames"] = [i if d == self.frametime else {"index": i, "time": d} for i, d in self.sequence(n)]
        return {"animation": a}


def blend(a: np.ndarray, b: np.ndarray, f: float) -> np.ndarray:
    """Fondu linéaire entre deux images RGBA (interpolation de Minecraft)."""
    if f <= 0:
        return a
    return np.clip(np.round(a.astype(float) * (1 - f) + b.astype(float) * f), 0, 255).astype(np.uint8)


# ============================================================================ Anim
class Anim:
    """Texture animée : suite d'images (Sprites ou tableaux (h, w, 4)) de même taille.

    Anim(images, frametime=2, interpolate=False, order=None)
    Exportée en bande verticale PNG (image 0 en haut) + <texture>.png.mcmeta.
    """

    def __init__(self, frames, frametime: int = 2, interpolate: bool = False, order=None):
        fr = [f.copy() if isinstance(f, Sprite) else Sprite(data=np.asarray(f)) for f in frames]
        if not fr:
            raise ValueError("une animation a au moins une image")
        if len({(s.w, s.h) for s in fr}) > 1:
            raise ValueError("toutes les images d'une animation ont la même taille")
        self.frames = fr
        self.timing = Timing(frametime, interpolate, order)
        self.timing.sequence(len(fr))                       # valide l'ordre

    # -------------------------------------------------------------- accès
    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, i) -> Sprite:
        return self.frames[i]

    def __iter__(self):
        return iter(self.frames)

    @property
    def n(self) -> int:
        return len(self.frames)

    @property
    def w(self) -> int:
        return self.frames[0].w

    @property
    def h(self) -> int:
        return self.frames[0].h

    @property
    def data(self) -> np.ndarray:
        """Image 0 (compatibilité avec le code qui attend un Sprite)."""
        return self.frames[0].data

    @property
    def frametime(self) -> int:
        return self.timing.frametime

    @property
    def period(self) -> int:
        return self.timing.period(self.n)

    @property
    def duration(self) -> float:
        """Durée d'une boucle en secondes."""
        return self.period / 20.0

    @property
    def static(self) -> bool:
        return all(np.array_equal(f.data, self.frames[0].data) for f in self.frames[1:])

    def at(self, tick: float) -> np.ndarray:
        """Image affichée au tick donné (fondu compris si interpolate)."""
        i, j, f = self.timing.at(self.n, tick)
        return blend(self.frames[i].data, self.frames[j].data, f)

    def strip(self) -> np.ndarray:
        """Bande verticale (n·h, w, 4), image 0 en haut : le PNG exporté."""
        return np.concatenate([f.data for f in self.frames], axis=0)

    def mcmeta(self) -> dict:
        m = self.timing.mcmeta(self.n)
        if self.w != self.h:
            m["animation"]["width"], m["animation"]["height"] = self.w, self.h
        return m

    def map(self, fn) -> Anim:
        """Nouvelle animation : fn(Sprite, index) -> Sprite appliqué à chaque image."""
        return Anim([fn(f.copy(), i) for i, f in enumerate(self.frames)], self.timing.frametime,
                    self.timing.interpolate, self.timing.order)

    @classmethod
    def from_strip(cls, src, frametime: int | None = None, interpolate: bool | None = None,
                   frame_h: int | None = None, order=None) -> Anim:
        """Depuis une bande verticale (chemin PNG, Sprite ou tableau) ; images carrées par défaut.
        Pour un chemin PNG, son .png.mcmeta (s'il existe) donne frametime, interpolate, ordre et taille
        d'image ; les arguments passés explicitement ont priorité."""
        meta = {}
        if isinstance(src, Sprite):
            arr = src.data
        elif isinstance(src, np.ndarray):
            arr = src
        else:
            import json
            from pathlib import Path
            with Image.open(src) as im:
                arr = np.array(im.convert("RGBA"))
            mp = Path(str(src) + ".mcmeta")
            if mp.exists():
                meta = json.loads(mp.read_text(encoding="utf-8")).get("animation", {}) or {}
        fh = frame_h or meta.get("height") or (meta.get("width") if "width" in meta else None) or arr.shape[1]
        fh = int(fh)
        if arr.shape[0] % fh:
            raise ValueError(f"hauteur {arr.shape[0]} non multiple de la hauteur d'image {fh}")
        ft = frametime if frametime is not None else meta.get("frametime", 2)
        it = interpolate if interpolate is not None else bool(meta.get("interpolate", False))
        if order is None and "frames" in meta:
            order = [(f["index"], f.get("time", ft)) if isinstance(f, dict) else f for f in meta["frames"]]
        return cls([arr[k * fh:(k + 1) * fh] for k in range(arr.shape[0] // fh)], ft, it, order)

    # -------------------------------------------------------------- sorties
    def save(self, path) -> None:
        """Écrit la bande PNG et son .png.mcmeta (utilisable tel quel dans un resource pack)."""
        import json
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.strip(), "RGBA").save(p)
        Path(str(p) + ".mcmeta").write_text(json.dumps(self.mcmeta(), indent=2) + "\n", encoding="utf-8")

    def contact(self, scale: int = 6, cols: int | None = None, bg=(24, 26, 32, 255)) -> Image.Image:
        """Planche : toutes les images côte à côte (numérotées de gauche à droite)."""
        cols = cols or min(self.n, 16)
        rows = -(-self.n // cols)
        W, H = self.w * scale, self.h * scale
        im = Image.new("RGBA", (cols * (W + 4) + 4, rows * (H + 4) + 4), bg)
        for k, f in enumerate(self.frames):
            im.alpha_composite(f.to_image(scale), (4 + (k % cols) * (W + 4), 4 + (k // cols) * (H + 4)))
        return im

    def gif(self, path, scale: int = 8, bg=(24, 26, 32)) -> str:
        """GIF animé à la vitesse du jeu (sur fond opaque)."""
        save_gif([np.array(f.to_image(scale)) for f in self._timeline_frames()],
                 [d * 50 for _, d in self._ticks()], path, bg)
        return str(path)

    def _ticks(self):
        return [(t, d) for t, (_, d) in zip(self.timing.starts(self.n), self.timing.sequence(self.n))]

    def _timeline_frames(self):
        return [Sprite(data=self.at(t)) for t, _ in self._ticks()]

    def __repr__(self) -> str:
        return (f"Anim({self.n} images {self.w}x{self.h}, {self.frametime} ticks/image, "
                f"boucle {self.duration:g} s{', fondu' if self.timing.interpolate else ''})")


def save_gif(frames, durations_ms, path, bg=(24, 26, 32)) -> None:
    """GIF animé depuis des images RGBA (composées sur `bg`) ; durées en millisecondes."""
    imgs = []
    for f in frames:
        base = Image.new("RGBA", (f.shape[1], f.shape[0]), tuple(bg) + (255,))
        base.alpha_composite(Image.fromarray(np.asarray(f, np.uint8), "RGBA"))
        imgs.append(base.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    dur = [max(20, int(d)) for d in durations_ms]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=dur, loop=0, disposal=1, optimize=False)


# ============================================================================ flammes 2D
def _erode4(m: np.ndarray, bottom_open: bool = True) -> np.ndarray:
    """Érosion 4-voisins d'un masque (..., h, w) indexé [y_haut, x] (ligne 0 = BAS) ; avec bottom_open,
    le dessous de l'image compte comme plein (la flamme sort du foyer : pas de liseré en bas)."""
    p = np.pad(m, [(0, 0)] * (m.ndim - 2) + [(1, 1), (1, 1)])
    if bottom_open:
        p[..., 0, 1:-1] = m[..., 0, :]
    core = p[..., 1:-1, 1:-1].copy()
    core &= p[..., :-2, 1:-1] & p[..., 2:, 1:-1] & p[..., 1:-1, :-2] & p[..., 1:-1, 2:]
    return core


def fire(w: int = 16, *, h: int | None = None, frames: int = 16, seed: int = 0, shape: str = "bush",
         palette=FIRE, height: float = 0.95, width: float = 0.86, tongues: int | None = None, base: float = 0.55,
         turbulence: float = 0.22, cycles: int = 2, puffs: int = 1, sparks: int = 1, frametime: int = 2,
         weights=(3, 3, 2.4, 1.4, 0.6), outline: bool = True) -> Anim:
    """Flammes animées en pixel-art, qui bouclent parfaitement (cutout : alpha 0 ou 255).

    shape     : 'bush' = flambée centrée qui s'effile (feu de camp, brasero, torche) ;
                'sheet' = nappe de flammes sur toute la largeur, raccordable gauche/droite (bloc en feu).
    palette   : rampe sombre -> clair (FIRE, SOUL_FIRE ou la vôtre) ; le ton 0 fait le liseré.
    height / width : hauteur et largeur de la flambée (fractions de l'image) ; base : hauteur du corps.
    tongues   : nombre de langues de feu (défaut 3 pour 'bush', largeur/4 pour 'sheet').
    turbulence: irrégularité du contour (0.1 calme … 0.4 sauvage) ; cycles : vitesse de montée du bruit
                (nombre entier de périodes par boucle).
    puffs     : bouffées détachées qui montent ; sparks : étincelles (pixels isolés) au-dessus.
    weights   : proportions des tons intérieurs (du plus sombre au plus clair, liseré exclu).
    La boucle est exacte : tout mouvement fait un nombre entier de cycles pendant l'animation.
    """
    if shape not in ("bush", "sheet"):
        raise ValueError("shape = 'bush' ou 'sheet'")
    W, H, T = int(w), int(h or w), int(frames)
    TAU = 2 * math.pi
    rng = np.random.default_rng(seed)
    tc = max(1, round(T / 8))
    n1 = perlin((W, H, T), (max(2, round(W / 3)), max(1, round(H / 6)), tc), seed=seed)
    n2 = perlin((W, H, T), (max(2, round(W / 2)), max(2, round(H / 3)), 2 * tc), seed=seed + 1)
    yu = np.arange(H)
    v = ((yu + 0.5) / H)[:, None]                                   # 0 = bas, 1 = haut
    U = ((np.arange(W) + 0.5) / W - 0.5)[None, :]                   # -0.5 .. 0.5
    sheet = shape == "sheet"
    nt = int(tongues if tongues is not None else (max(2, W // 4) if sheet else 3))
    tg = []
    for i in range(nt):
        if sheet:
            c0 = (i + 0.5) / nt - 0.5 + rng.uniform(-0.25, 0.25) / nt
            central = True
        else:
            c0 = (i - (nt - 1) / 2) * width / (nt + 0.6) + rng.uniform(-0.04, 0.04)
            central = abs(c0) < 0.12
        tg.append(dict(c0=c0, w=rng.uniform(0.19, 0.25) * (1.15 if central else 0.9) * (0.8 if sheet else 1.0),
                       h=height * (rng.uniform(0.86, 1.0) if central else rng.uniform(0.6, 0.8)),
                       sh=int(rng.integers(1, 3)), ph=rng.uniform(0, 1), sx=int(rng.integers(1, 3)),
                       px=rng.uniform(0, 1)))
    pf = [dict(c0=rng.uniform(-0.12, 0.12) if not sheet else rng.uniform(-0.5, 0.5), ph=rng.uniform(0, 1),
               r=max(rng.uniform(0.07, 0.1), 2.2 / W)) for _ in range(int(puffs))]

    def dx(c):                                                     # écart horizontal (périodique en nappe)
        d = U - c
        return (d + 0.5) % 1.0 - 0.5 if sheet else d

    heat = np.zeros((T, H, W))
    temp = np.zeros((T, H, W))
    for t in range(T):
        f = t / T
        a = n1[:, (yu - (cycles * H * t) // T) % H, t].T          # bruit qui monte (boucle exacte)
        b = n2[:, (yu - (2 * cycles * H * t) // T) % H, t].T
        if sheet:
            F = 1 - v / (base * height)
        else:
            F = 1 - np.sqrt((U / (0.5 * width)) ** 2 + (v / (base * height)) ** 2)
        for g in tg:
            hh = g["h"] * (0.78 + 0.22 * math.sin(TAU * (g["sh"] * f + g["ph"])))
            cx = g["c0"] + 0.06 * np.sin(TAU * (g["sx"] * f + g["px"]) + 5.0 * v)     # ondule en montant
            hw = g["w"] * np.clip(1 - v / hh, 0, 1) ** 0.55 + 1e-3
            Ft = np.where(v < hh, 1 - np.abs(dx(cx)) / hw, -1.0)
            F = np.maximum(F, np.where(Ft > 0, Ft * np.clip(1.2 - v / hh, 0, 1), Ft))
        puff = np.full_like(F, -1.0)
        for p_ in pf:
            ph = (2 * f + p_["ph"]) % 1.0                           # 2 bouffées par boucle
            if ph > 0.8:
                continue                                            # la bouffée s'éteint avant le haut
            # bouffée ronde qui se détache du sommet en rétrécissant (pas aplatie par le bruit)
            d = np.sqrt(dx(p_["c0"]) ** 2 + ((v - 0.6 - 0.45 * ph) * 1.15) ** 2)
            puff = np.maximum(puff, 1 - d / (p_["r"] * (1.2 - 0.6 * ph)))
        F = F + turbulence * (0.65 * a + 0.35 * b) * (0.4 + v)
        F = np.maximum(F, puff + 0.08 * a)
        heat[t] = F
        temp[t] = np.clip(1 - v / height, 0, 1) ** 0.8 * np.clip(F, 0, 1) + 0.1 * a
    mask = heat > 0.0
    p = np.pad(mask, ((0, 0), (1, 1), (1, 1)))
    if sheet:                                                       # voisinage horizontal périodique
        p[:, 1:-1, 0], p[:, 1:-1, -1] = mask[:, :, -1], mask[:, :, 0]
    mask &= p[:, :-2, 1:-1] | p[:, 2:, 1:-1] | p[:, 1:-1, :-2] | p[:, 1:-1, 2:]    # pas de pixel isolé
    k = len(palette) - 1
    lv = np.zeros((T, H, W), int)
    if mask.any() and k > 1:
        wts = np.asarray(list(weights)[:k] + [1.0] * max(0, k - len(weights)), float)
        q = np.quantile(temp[mask], np.cumsum(wts / wts.sum())[:-1])
        lv[mask] = 1 + np.searchsorted(q, temp[mask])
    elif mask.any():
        lv[mask] = k
    if outline:
        m2 = mask
        if sheet:                                                   # liseré raccordable à gauche/droite
            m2 = np.concatenate([mask[..., -1:], mask, mask[..., :1]], axis=-1)
            edge = (m2 & ~_erode4(m2))[..., 1:-1]
        else:
            edge = mask & ~_erode4(mask)
        lv[edge] = 0
    cols = np.array([rgba(c) for c in palette], np.uint8)
    img = np.zeros((T, H, W, 4), np.uint8)
    img[mask] = cols[np.clip(lv[mask], 0, k)]
    for _ in range(int(sparks)):                                    # étincelles : 1 pixel vif qui s'élève
        x0 = rng.uniform(0.3, 0.7) * W
        ph = rng.uniform(0, 1)
        y0 = rng.uniform(0.5, 0.7) * H
        amp = rng.uniform(0.5, 1.5)
        for t in range(T):
            f = (t / T + ph) % 1.0
            yy = int(y0 + f * (H - y0 + 2))
            xx = int(round(x0 + amp * math.sin(TAU * (t / T + ph)))) % W
            if 0 <= yy < H and not mask[t, yy, xx]:
                img[t, yy, xx] = cols[k - 1 if f < 0.6 else min(k, 2)]
    return Anim([img[t, ::-1] for t in range(T)], frametime)      # ligne 0 du PNG = haut de l'image


# ============================================================================ volumes animés
def _check_args(frames, mask, ramp):
    """Contrôles communs à pulse / flow, avec des messages utiles."""
    from .volume import Volume
    if isinstance(frames, Volume):
        raise TypeError("liste de volumes attendue (images de l'animation) : frames = v.frames(16)")
    _check_frames(list(frames))
    m = np.asarray(mask)
    if m.dtype != bool or m.shape != frames[0].shape:
        raise ValueError(f"masque booléen de forme {frames[0].shape} attendu (reçu {m.dtype} {m.shape})")
    if isinstance(ramp, str) or len(ramp) < 2:
        raise TypeError("rampe de couleurs attendue (au moins 2 tons), ex. ramp('#e06010', 5) ou EMBER")
    return m


def _check_frames(frames):
    if not frames:
        raise ValueError("liste d'images vide")
    s0 = frames[0].solid
    for k, f in enumerate(frames[1:], 1):
        if f.shape != frames[0].shape:
            raise ValueError(f"image {k} : forme {f.shape} ≠ {frames[0].shape}")
        if not np.array_equal(f.solid, s0):
            raise ValueError(f"image {k} : voxels pleins différents de l'image 0. Dans Minecraft seule la "
                             "texture s'anime : gardez la même forme et ne changez que les couleurs")
    return frames


def pulse(frames, mask, ramp, *, seed: int = 0, cells=3, speed: int = 1, amplitude: float = 0.6,
          variation: float = 0.45, bias: float = 0.0):
    """Lueur qui palpite (braises, cristaux, runes, cœur de réacteur) sur une liste de volumes.

    Chaque voxel du masque oscille dans la rampe avec une phase qui dépend de sa position (vague lente,
    pas un clignotement uniforme) ; `variation` garde des voxels plus chauds que d'autres. `speed`
    (entier) = nombre d'oscillations par boucle : la boucle est parfaite. Modifie les volumes en place.
    """
    mask = _check_args(frames, mask, ramp)
    T = len(frames)
    shape = frames[0].shape
    phase = equalize(perlin(shape, cells, seed=seed))
    base = perlin(shape, np.maximum(1, np.asarray(cells) * 2) if not np.isscalar(cells) else cells * 2,
                  seed=seed + 1)
    m = mask & frames[0].solid
    cols = np.array([rgba(c) for c in ramp], np.uint8)
    k = len(ramp) - 1
    for t, f in enumerate(frames):
        s = np.sin(2 * np.pi * (speed * t / T + phase))
        level = (0.5 + bias + 0.5 * (amplitude * s + variation * base * 1.6)) * k
        lv = np.clip(np.round(level), 0, k).astype(int)
        f.data[m] = cols[lv[m]]
    return frames


def flow(frames, mask, ramp, *, cells=4, octaves: int = 2, seed: int = 0, direction=(0, -1, 0),
         cycles: int = 1, morph: int = 1, weights="bell"):
    """Motif qui s'écoule en boucle (lave, eau, énergie, brume) sur une liste de volumes.

    Bruit 3D périodique, translaté de `cycles` périodes entières le long de `direction` (ex. (0,-1,0) =
    descend, (1,0,0) = vers l'est) pendant l'animation, et qui se déforme lentement (`morph` cycles de
    bruit temporel) : boucle parfaite et raccord entre blocs voisins. Modifie les volumes en place.
    """
    from .noise import bell_weights, quantize_levels
    mask = _check_args(frames, mask, ramp)
    T = len(frames)
    sx, sy, sz = frames[0].shape
    c = tuple(int(x) for x in (np.broadcast_to(np.asarray(cells), (3,))))
    n4 = perlin((sx, sy, sz, T), c + (max(1, int(morph)),), seed=seed, octaves=octaves)
    m = mask & frames[0].solid
    vals = np.zeros((T, sx, sy, sz))
    d = [int(np.sign(v)) for v in direction]
    for t in range(T):
        sh = tuple(int(round(cycles * d[k] * (sx, sy, sz)[k] * t / T)) for k in range(3))
        vals[t] = np.roll(n4[..., t], sh, axis=(0, 1, 2))
    vis = np.stack([m & f.m_surface() for f in frames])
    if not vis.any():
        vis = np.stack([m] * T)
    tt = equalize(vals, vis)
    w = bell_weights(len(ramp)) if weights == "bell" else ([1] * len(ramp) if weights == "flat" else weights)
    lv = quantize_levels(tt, w)
    cols = np.array([rgba(cc) for cc in ramp], np.uint8)
    for t, f in enumerate(frames):
        f.data[m] = cols[lv[t][m]]
    return frames


# ============================================================================ outils de minutage
def preview_ticks(timings, max_frames: int = 48, starts_only: bool = False) -> list:
    """Ticks à montrer pour prévisualiser plusieurs animations ensemble (sur leur boucle commune).
    Avec un fondu (interpolate), tous les ticks sont montrés, sauf starts_only=True (débuts d'image)."""
    timings = [(t, n) for t, n in timings if n > 1]
    if not timings:
        return [0]
    period = 1
    for t, n in timings:
        period = period * t.period(n) // math.gcd(period, t.period(n))
    if any(t.interpolate for t, _ in timings) and not starts_only:
        starts = list(range(period))                        # fondu : montrer aussi les instants intermédiaires
    else:
        starts = sorted({s + k * t.period(n) for t, n in timings for k in range(period // t.period(n))
                         for s in t.starts(n)})
    step = max(1, math.ceil(len(starts) / max_frames))
    return starts[::step]


@dataclass
class Clip:
    """Volumes animés d'un asset : images (Volumes) + minutage."""
    frames: list
    timing: Timing = field(default_factory=Timing)

    @property
    def n(self) -> int:
        return len(self.frames)

    def at(self, tick: float):
        i, j, f = self.timing.at(self.n, tick)
        return i, j, f
