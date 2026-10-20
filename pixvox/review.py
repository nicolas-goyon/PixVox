"""pixvox.review — planche de revue (PNG) + rapport texte pour un asset.

C'est la boucle de travail : décrire l'asset -> review() -> regarder la planche + lire le rapport -> corriger.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ._io import say
from .analyze import analyze, format_report
from .assets import Block, Item, Model, MultiBlock
from .color import hexa, lightness, lightness_array, unique_colors
from .render import (
    BACK,
    FRONT_N,
    INVENTORY,
    SIDE_E,
    TOP,
    cube_quads,
    fit_camera,
    gui_camera,
    item_quads,
    quads_from_volume,
    render,
    tiled_cube_quads,
)

GAME_VIEW = (200, 22)   # vue « en jeu » : un peu de côté, légèrement plongeante

BG = (24, 26, 32, 255)
PANEL = (35, 38, 47, 255)
TEXT = (226, 228, 233, 255)
MUTED = (146, 152, 166, 255)
LEVEL_COL = {"OK": (120, 200, 140, 255), "INFO": (150, 170, 200, 255), "WARN": (240, 190, 90, 255),
             "ERR": (240, 100, 100, 255)}
SLOT = (139, 139, 139, 255)
PERSP_BELOW = 1.8      # vue de dessous en perspective : sans elle, un cube vu d'en bas paraît creux

_FONT_CACHE: dict = {}


def font(size: int = 14, mono: bool = False, bold: bool = False):
    key = (size, mono, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = (["DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf", "consolab.ttf", "consola.ttf", "Menlo.ttc"]
             if mono else ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
                           "arialbd.ttf" if bold else "arial.ttf", "Arial.ttf", "Helvetica.ttc"])
    dirs = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF", "/Library/Fonts",
            "/System/Library/Fonts", "C:/Windows/Fonts", str(Path.home() / ".fonts")]
    f = None
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except OSError:
                    pass
        if f:
            break
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


# ----------------------------------------------------------------------------- briques
def _img(arr) -> Image.Image:
    return Image.fromarray(np.asarray(arr, np.uint8), "RGBA")


def _panel(canvas: Image.Image, x, y, w, h, title: str | None = None):
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=PANEL)
    if title:
        d.text((x + 10, y + 7), title, font=font(13, bold=True), fill=MUTED)
    return (x, y + (26 if title else 0), w, h - (26 if title else 0))


def _paste_center(canvas: Image.Image, img: Image.Image, box):
    x, y, w, h = box
    canvas.alpha_composite(img, (int(x + (w - img.width) / 2), int(y + (h - img.height) / 2)))


def grid_face(tex: np.ndarray, cell: int = 9, major: int = 4, border=(255, 255, 255, 90)) -> Image.Image:
    """Texture agrandie avec grille (fine à chaque texel, marquée tous les `major` texels)."""
    h, w = tex.shape[:2]
    checker = np.zeros((h * cell, w * cell, 4), np.uint8)
    yy, xx = np.mgrid[0:h * cell, 0:w * cell]
    checker[...] = (60, 63, 72, 255)
    checker[((yy // 4) + (xx // 4)) % 2 == 0] = (78, 82, 92, 255)
    base = Image.fromarray(checker, "RGBA")
    base.alpha_composite(_img(tex).resize((w * cell, h * cell), Image.NEAREST))
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(1, w):
        d.line([(i * cell, 0), (i * cell, h * cell)], fill=(0, 0, 0, 95 if i % major == 0 else 30))
    for j in range(1, h):
        d.line([(0, j * cell), (w * cell, j * cell)], fill=(0, 0, 0, 95 if j % major == 0 else 30))
    d.rectangle([0, 0, w * cell - 1, h * cell - 1], outline=border)
    base.alpha_composite(ov)
    return base


def net_image(faces: dict, cell: int = 9, marks: dict | None = None) -> Image.Image:
    """Patron :            [UP]
                [NORTH][WEST][SOUTH][EAST]
                              [DOWN]
    Chaque texture est affichée telle qu'exportée (orientation du PNG = orientation en jeu vue de
    l'extérieur). Les bandes N|W|S|E se touchent par leurs arêtes réelles, UP et DOWN touchent SOUTH."""
    fw = faces["north"].w * cell
    fh = faces["north"].h * cell
    gx, gy = 4, 17
    W = 4 * fw + 3 * gx + 40
    H = 3 * fh + 2 * gy + 34
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ox, oy = 20, 16
    pos = {"north": (ox, oy + fh + gy), "west": (ox + fw + gx, oy + fh + gy),
           "south": (ox + 2 * (fw + gx), oy + fh + gy), "east": (ox + 3 * (fw + gx), oy + fh + gy),
           "up": (ox + 2 * (fw + gx), oy), "down": (ox + 2 * (fw + gx), oy + 2 * (fh + gy))}
    names = {"up": "UP", "down": "DOWN", "north": "NORTH", "south": "SOUTH", "west": "WEST", "east": "EAST"}
    f = font(11)
    fs = font(11, bold=True)
    for k, (x, y) in pos.items():
        im.alpha_composite(grid_face(faces[k].data, cell), (x, y))
        d.text((x + 1, y - 14), names[k], font=fs, fill=TEXT)
        for u, v in (marks or {}).get(k, ()):
            d.rectangle([x + u * cell, y + v * cell, x + (u + 1) * cell - 1, y + (v + 1) * cell - 1],
                        outline=(255, 0, 220, 255), width=2)
    # arêtes non contiguës dans le patron
    ux, uy = pos["up"]
    dx_, dy_ = pos["down"]
    nx, ny = pos["north"]
    ex, ey = pos["east"]
    lab = [((ux + fw - 52, uy - 14), "arête N ↑"), ((ux - 12, uy + fh / 2 - 6), "W"),
           ((ux + fw + 4, uy + fh / 2 - 6), "E"),
           ((dx_ + fw - 52, dy_ + fh + 1), "arête N ↓"), ((dx_ - 12, dy_ + fh / 2 - 6), "W"),
           ((dx_ + fw + 4, dy_ + fh / 2 - 6), "E"),
           ((nx - 12, ny + fh / 2 - 6), "E"), ((ex + fw + 4, ey + fh / 2 - 6), "N")]
    for (x, y), t in lab:
        d.text((x, y), t, font=f, fill=MUTED)
    cap = ["Bande N | W | S | E : les faces", "voisines se touchent par leurs", "vraies arêtes (E revient sur N).",
           "UP et DOWN touchent SOUTH ;", "leurs autres arêtes sont notées", "par une lettre (N, W, E)."]
    for i, t in enumerate(cap):
        d.text((ox, dy_ + 8 + i * 15), t, font=f, fill=MUTED)
    return im


def slot_icon(icon: np.ndarray, k: int) -> Image.Image:
    """Case d'inventaire Minecraft (18x18 px GUI) à l'échelle k, icône 16k x 16k centrée."""
    s = 18 * k
    im = Image.new("RGBA", (s, s), SLOT)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, s - 1, k - 1], fill=(55, 55, 55, 255))
    d.rectangle([0, 0, k - 1, s - 1], fill=(55, 55, 55, 255))
    d.rectangle([0, s - k, s - 1, s - 1], fill=(255, 255, 255, 255))
    d.rectangle([s - k, 0, s - 1, s - 1], fill=(255, 255, 255, 255))
    ic = _img(icon)
    if ic.width != 16 * k:
        ic = ic.resize((16 * k, 16 * k), Image.NEAREST)
    im.alpha_composite(ic, (k, k))
    return im


def palette_image(arr: np.ndarray, width: int, max_rows: int = 13) -> Image.Image:
    cols = unique_colors(arr)
    items = sorted(cols.items(), key=lambda kv: (lightness(kv[0]), kv[0]))
    ncol = max(1, width // 112)
    rows = min(max_rows, (len(items) + ncol - 1) // ncol)
    shown = items[:rows * ncol]
    im = Image.new("RGBA", (width, rows * 18 + (16 if len(items) > len(shown) else 0)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(11, mono=True)
    for i, (c, n) in enumerate(shown):
        cx, cy = (i // rows) * 112, (i % rows) * 18
        d.rectangle([cx, cy + 1, cx + 14, cy + 15], fill=c, outline=(0, 0, 0, 255))
        d.text((cx + 19, cy + 2), f"{hexa(c)[:7]} {n}", font=f, fill=TEXT)
    if len(items) > len(shown):
        d.text((0, rows * 18 + 1), f"… +{len(items) - len(shown)} couleurs", font=font(11), fill=MUTED)
    return im


def text_block(lines, width: int, size: int = 13, colors=None) -> Image.Image:
    f = font(size)
    out = []
    for i, ln in enumerate(lines):
        col = colors[i] if colors else TEXT
        words = [w_ for w_ in ln.split(" ") if w_]
        cur = ""
        first = True
        for w_ in words:
            trial = f"{cur} {w_}" if cur.strip() else (cur + w_)
            if f.getlength(trial) > width - 8 and cur.strip():
                out.append((cur, col, first))
                cur = "      " + w_
                first = False
            else:
                cur = trial
        out.append((cur, col, first))
    lh = size + 5
    im = Image.new("RGBA", (width, max(lh, len(out) * lh)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, (t, c, _) in enumerate(out):
        d.text((4, i * lh), t, font=f, fill=c)
    return im


def _findings_lines(findings):
    lines, cols = [], []
    for fd in findings:
        lines.append(fd.line())
        cols.append(LEVEL_COL[fd.level])
    return lines, cols


def _header(canvas, title, subtitle):
    d = ImageDraw.Draw(canvas)
    d.text((18, 12), title, font=font(20, bold=True), fill=TEXT)
    d.text((18 + d.textlength(title, font=font(20, bold=True)) + 14, 18), subtitle, font=font(13), fill=MUTED)


def _slots_row(cv, box, quads, gui=(0.625, (8, 8, 8))):
    """Cases d'inventaire aux échelles GUI 1-4 + icône ×4 en niveaux de gris (lisibilité des valeurs).
    gui = (échelle, centre) du display 'gui' du modèle (vanilla : 0.625 centré sur le bloc)."""
    bx, by, bw, bh = box
    sx = bx + 10
    icon4 = None
    for k in (1, 2, 3, 4):
        icon = render(quads, gui_camera(k, center=gui[1], display_scale=gui[0]), shading="gui")
        s = slot_icon(icon, k)
        cv.alpha_composite(s, (sx, by + 8 + (72 - s.height)))
        sx += s.width + 8
        icon4 = icon
    g = icon4.copy()
    L = np.clip(lightness_array(g), 0, 1)
    g[..., :3] = (L * 255).astype(np.uint8)[..., None]
    cv.alpha_composite(slot_icon(g, 4), (sx, by + 8))


def _analysis_panel(cv: Image.Image, x: int, y: int, w: int, findings, size: int = 13) -> Image.Image:
    """Panneau « Analyse » en bas à droite ; agrandit la planche si le texte ne tient pas (rien n'est coupé)."""
    lines, cols = _findings_lines(findings)
    tb = text_block(lines, w - 16, size, cols)
    need = y + 26 + 4 + tb.height + 16 + 8
    if need > cv.height:
        big = Image.new("RGBA", (cv.width, need), BG)
        big.alpha_composite(cv, (0, 0))
        cv = big
    box = _panel(cv, x, y, w, cv.height - y - 16, "Analyse")
    cv.alpha_composite(tb, (box[0] + 8, box[1] + 4))
    return cv


# ----------------------------------------------------------------------------- planches
def _sheet_block(b: Block, findings) -> Image.Image:
    faces = b.faces()
    W, H = 1500, 1000
    cv = Image.new("RGBA", (W, H), BG)
    if b.source == "volume":
        src = "faces lues sur le volume"
    elif b.fixed:
        src = f"textures fournies, {len(b.conflicts)} conflits d'arête unifiés"
    else:
        src = f"textures fournies telles quelles — {len(b.conflicts)} voxels d'arête en conflit (magenta)"
    n = b.volume.shape[0]
    _header(cv, b.name, f"bloc plein {n}³{' (HD)' if n > 16 else ''} · rendu {b.effective_render_type()} · {src}")
    qc = cube_quads(faces)
    P = 360
    x = 16
    glow = b.glow_faces() if b.emissive is not None else {}
    world = ("Monde 3×3×3 (raccords, ombrage en jeu)", INVENTORY, "world", tiled_cube_quads(faces), 0)
    if glow:
        world = ("Monde 3×3×3 la nuit (pixels lumineux)", INVENTORY, "night",
                 tiled_cube_quads(faces, glow=glow, emission=b.emission), 0)
    for title, view, shading, quads, persp in (
            ("Inventaire · EST à g. · NORD à dr.", INVENTORY, "gui", b.quads(0), 0),
            ("Dessous (perspective) · OUEST à g. · SUD à dr.", BACK, "world", qc, PERSP_BELOW),
            world):
        box = _panel(cv, x, 50, P + 10, P + 36, title)
        img = render(quads, fit_camera(quads, view, P, P, 0.06, persp=persp), shading=shading,
                     bg=(10, 12, 20, 255) if shading == "night" else None)
        _paste_center(cv, _img(img), box)
        x += P + 26
    # taille réelle + palette
    box = _panel(cv, x, 50, W - x - 16, P + 36, "Taille réelle ×1 ×2 ×3 ×4 · valeurs")
    _slots_row(cv, box, qc)
    all_px = np.concatenate([faces[f].data.reshape(-1, 4) for f in faces])
    cv.alpha_composite(palette_image(all_px, box[2] - 20, 13), (box[0] + 10, box[1] + 92))
    # patron
    marks: dict = {}
    if b.conflicts and not b.fixed:
        for c in b.conflicts:
            for f, u, v, _ in c["faces"]:
                marks.setdefault(f, []).append((u, v))
    net = net_image(faces, max(2, 128 // faces["north"].w), marks)
    box = _panel(cv, 16, 50 + P + 52, net.width + 20, H - (50 + P + 52) - 16,
                 "Patron — textures telles qu'exportées (PNG = orientation en jeu)")
    cv.alpha_composite(net, (box[0] + 10, box[1] + 4))
    ax = 16 + net.width + 36
    return _analysis_panel(cv, ax, 50 + P + 52, W - ax - 16, findings)


def _sheet_model(m: Model, findings) -> Image.Image:
    from .export import optimize_model
    W, H = 1500, 1000
    cv = Image.new("RGBA", (W, H), BG)
    extra = (f" · {len(m.planes)} plan(s)" if m.planes else "") + (" · animé" if _is_animated(m) else "")
    _header(cv, m.name, f"modèle voxel {m.volume.shape[0]}×{m.volume.shape[1]}×{m.volume.shape[2]} · "
                        f"voxel = {m.voxel_size:g} unité(s){extra}")
    q = m.quads(0)
    P = 360
    x = 16
    for title, view, shading, persp in (("Inventaire · EST à g. · NORD à dr.", INVENTORY, "gui", 0),
                                        ("Dessous (perspective) · OUEST à g. · SUD à dr.", BACK, "world", PERSP_BELOW)):
        box = _panel(cv, x, 50, P + 10, P + 36, title)
        _paste_center(cv, _img(render(q, fit_camera(q, view, P, P, 0.06, persp=persp), shading=shading)), box)
        x += P + 26
    box = _panel(cv, x, 50, P + 10, P + 36, "Dessus (nord en haut, sans ombrage)")
    _paste_center(cv, _img(render(q, fit_camera(q, TOP, P, P, 0.06), shading="flat")), box)
    x += P + 26
    box = _panel(cv, x, 50, W - x - 16, P + 36, "Taille réelle ×1 ×2 ×3 ×4 · valeurs")
    _slots_row(cv, box, q, m.gui_transform())
    cv.alpha_composite(palette_image(m.volume.data[m.volume.m_surface()], box[2] - 20, 13),
                       (box[0] + 10, box[1] + 92))
    y2 = 50 + P + 52
    S = 300
    x = 16
    glow = bool(m.planes and any(p.emission for p in m.planes)) or m.emissive is not None
    panels = (("Face nord (orthogonale)", FRONT_N, "flat", 0), ("Face est (orthogonale)", SIDE_E, "flat", 0))
    if glow:
        panels = (("Face nord (orthogonale)", FRONT_N, "flat", 0),
                  ("La nuit (light_emission seule)", GAME_VIEW, "night", 2.2))
    for title, view, shading, persp in panels:
        box = _panel(cv, x, y2, S + 10, S + 36, title)
        _paste_center(cv, _img(render(q, fit_camera(q, view, S, S, 0.06, persp=persp), shading=shading,
                                      bg=(10, 12, 20, 255) if shading == "night" else None)), box)
        x += S + 26
    opt = optimize_model(m)
    at = opt.main_atlas
    box = _panel(cv, x, y2, S + 10, S + 36, f"Atlas {at.size}px · {len(opt.elements)} élém."
                 + (f" + {len(m.planes)} plans" if m.planes else ""))
    cell = max(1, (S - 10) // at.size)
    _paste_center(cv, grid_face(at.image, cell, major=8), box)
    x += S + 26
    return _analysis_panel(cv, x, y2, W - x - 16, findings)


def _grid_overlay(img: np.ndarray, cam, plane: str, mb: MultiBlock) -> Image.Image:
    """Trace les limites de blocs (tous les 16 voxels) sur une vue orthogonale de face ou de côté."""
    im = _img(img)
    d = ImageDraw.Draw(im)
    sx = mb.volume.shape[0] * mb.voxel_size
    nx, ny, nz = mb.blocks
    col = (255, 210, 80, 150)
    if plane == "north":
        for i in range(nx + 1):
            a, b = cam.project((16 * i, 0, 0)), cam.project((16 * i, 16 * ny, 0))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=col, width=1)
        for j in range(ny + 1):
            a, b = cam.project((0, 16 * j, 0)), cam.project((16 * nx, 16 * j, 0))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=col, width=1)
    else:
        for k in range(nz + 1):
            a, b = cam.project((sx, 0, 16 * k)), cam.project((sx, 16 * ny, 16 * k))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=col, width=1)
        for j in range(ny + 1):
            a, b = cam.project((sx, 16 * j, 0)), cam.project((sx, 16 * j, 16 * nz))
            d.line([(a[0], a[1]), (b[0], b[1])], fill=col, width=1)
    return im


def _mini_quads(mb: MultiBlock):
    """Géométrie de la miniature d'inventaire, telle qu'elle est exportée (volume ré-échantillonné)."""
    from .export import miniature_model
    mm = miniature_model(mb)
    return quads_from_volume(mm.volume, offset=mm.origin, voxel_size=mm.voxel_size)


def _sheet_multi(mb: MultiBlock, findings) -> Image.Image:
    from .export import optimize_multiblock
    W, H = 1500, 1000
    cv = Image.new("RGBA", (W, H), BG)
    nx, ny, nz = mb.blocks
    sx, sy, sz = mb.volume.shape
    _header(cv, mb.name, f"objet multibloc {nx}×{ny}×{nz} blocs ({sx}×{sy}×{sz} voxels, {mb.res} par bloc)"
                         " · face avant = NORD")
    q = mb.quads(0)
    P = 360
    x = 16
    for title, view, shading, persp in (("Objet entier · vue 3/4 (EST à g., NORD à dr.)", INVENTORY, "gui", 0),
                                        ("Dessous (perspective) · OUEST à g. · SUD à dr.", BACK, "world",
                                         PERSP_BELOW)):
        box = _panel(cv, x, 50, P + 10, P + 36, title)
        _paste_center(cv, _img(render(q, fit_camera(q, view, P, P, 0.05, persp=persp), shading=shading)), box)
        x += P + 26
    box = _panel(cv, x, 50, P + 10, P + 36, "Face avant (nord) · limites de blocs")
    cam = fit_camera(q, FRONT_N, P, P, 0.05)
    _paste_center(cv, _grid_overlay(render(q, cam, shading="flat"), cam, "north", mb), box)
    x += P + 26
    box = _panel(cv, x, 50, W - x - 16, P + 36, "Icône d'inventaire réelle (miniature 16³)")
    mq = _mini_quads(mb)
    _slots_row(cv, box, mq)
    big = render(mq, fit_camera(mq, INVENTORY, 150, 150, 0.04), shading="gui")
    cv.alpha_composite(_img(big), (box[0] + 10, box[1] + 92))
    cv.alpha_composite(palette_image(mb.volume.data[mb.volume.m_surface()], box[2] - 180, 8),
                       (box[0] + 170, box[1] + 96))
    y2 = 50 + P + 52
    S = 300
    x = 16
    box = _panel(cv, x, y2, S + 10, S + 36, "Côté (est) · limites de blocs")
    cam = fit_camera(q, SIDE_E, S, S, 0.05)
    _paste_center(cv, _grid_overlay(render(q, cam, shading="flat"), cam, "east", mb), box)
    x += S + 26
    glow = mb.emissive is not None
    box = _panel(cv, x, y2, S + 10, S + 36, "La nuit (light_emission)" if glow else
                 "Vue en jeu (perspective, ombrage monde)")
    _paste_center(cv, _img(render(q, fit_camera(q, (160, 12), S, S, 0.05, persp=2.2),
                                  shading="night" if glow else "world",
                                  bg=(10, 12, 20, 255) if glow else None)), box)
    x += S + 26
    opt = optimize_multiblock(mb)
    at = opt.main_atlas
    box = _panel(cv, x, y2, S + 10, S + 36, f"Atlas partagé {at.size}px · {opt.stats['parts']} parties")
    cell = max(1, (S - 10) // at.size)
    _paste_center(cv, grid_face(at.image, cell, major=8) if cell > 1 else _img(at.image)
                  .resize((S - 10, S - 10), Image.NEAREST), box)
    x += S + 26
    return _analysis_panel(cv, x, y2, W - x - 16, findings, size=12)


def _sheet_item(it: Item, findings) -> Image.Image:
    s = it.sprite
    cell = max(4, 560 // max(s.w, s.h))
    W, H = 1500, max(560, 16 + 50 + max(s.w, s.h) * cell + 66)
    cv = Image.new("RGBA", (W, H), BG)
    _header(cv, it.name, f"item plat {s.w}×{s.h}")
    cell = max(4, 560 // max(s.w, s.h))
    big = grid_face(s.data, cell, major=4)
    box = _panel(cv, 16, 50, big.width + 60, big.height + 66, "Sprite (grille, x → / y ↓)")
    bx, by, bw, bh = box
    d = ImageDraw.Draw(cv)
    f = font(10, mono=True)
    ox, oy = bx + 40, by + 22
    cv.alpha_composite(big, (ox, oy))
    for i in range(s.w):
        d.text((ox + i * cell + cell / 2 - 3, oy - 14), str(i % 10), font=f, fill=MUTED)
    for j in range(s.h):
        d.text((ox - 22, oy + j * cell + cell / 2 - 6), f"{j:>2}", font=f, fill=MUTED)
    x = 16 + big.width + 76
    box = _panel(cv, x, 50, W - x - 16, 250, "Taille réelle : cases ×1 ×2 ×3 ×4, puis fond sombre")
    bx, by, bw, bh = box
    sx = bx + 10
    for k in (1, 2, 3, 4):
        sl = slot_icon(s.data, k)
        cv.alpha_composite(sl, (sx, by + 10 + (72 - sl.height)))
        sx += sl.width + 10
    dark = Image.new("RGBA", (16 * 4 + 8, 16 * 4 + 8), (16, 16, 20, 255))
    dark.alpha_composite(s.to_image(4), (4, 4))
    cv.alpha_composite(dark, (sx + 6, by + 10))
    # silhouette & valeurs
    y3 = by + 100
    sil = np.zeros_like(s.data)
    sil[..., 3] = 255
    sil[..., :3] = 235
    sil[s.data[..., 3] > 0, :3] = 20
    L = lightness_array(s.data)
    val = np.zeros_like(s.data)
    val[..., :3] = (np.clip(L, 0, 1) * 255).astype(np.uint8)[..., None]
    val[..., 3] = s.data[..., 3]
    d.text((bx + 10, y3), "Silhouette", font=font(11), fill=MUTED)
    d.text((bx + 10 + 6 * 16 + 24, y3), "Valeurs (gris)", font=font(11), fill=MUTED)
    cv.alpha_composite(_img(sil).resize((6 * s.w, 6 * s.h), Image.NEAREST), (bx + 10, y3 + 16))
    vb = Image.new("RGBA", (6 * s.w, 6 * s.h), (139, 139, 139, 255))
    vb.alpha_composite(_img(val).resize((6 * s.w, 6 * s.h), Image.NEAREST))
    cv.alpha_composite(vb, (bx + 10 + 6 * 16 + 24, y3 + 16))
    pal = palette_image(s.data, 340, 7)
    cv.alpha_composite(pal, (bx + 10 + 2 * (6 * 16 + 24), y3 + 16))
    return _analysis_panel(cv, x, 50 + 250 + 16, W - x - 16, findings)


def review_data(asset, out_dir="out") -> dict:
    """Planche de revue PNG + rapport texte (+ planche d'animation et GIF), sans rien afficher.

    Renvoie {name, sheet, report_file, report, findings, anim} ; anim = (png, gif) ou None.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    findings = analyze(asset)
    if isinstance(asset, MultiBlock):
        sheet = _sheet_multi(asset, findings)
    elif isinstance(asset, Block):
        sheet = _sheet_block(asset, findings)
    elif isinstance(asset, Model):
        sheet = _sheet_model(asset, findings)
    else:
        sheet = _sheet_item(asset, findings)
    path = out / f"{asset.name}.review.png"
    sheet.convert("RGB").save(path)
    report = format_report(asset, findings)
    report_file = out / f"{asset.name}.report.txt"
    report_file.write_text(report + "\n", encoding="utf-8")
    anim_paths = anim_sheet(asset, out) if _is_animated(asset) else None
    return {"name": asset.name, "sheet": path, "report_file": report_file, "report": report,
            "findings": findings, "anim": anim_paths}


def review(asset, out_dir="out", show_report: bool = True) -> tuple[Path, str]:
    """Rend la planche de revue PNG et renvoie (chemin, rapport texte)."""
    r = review_data(asset, out_dir)
    if show_report:
        say(r["report"])
        say(f"planche : {r['sheet']}")
        if r["anim"]:
            say(f"animation : {r['anim'][0]} (images) | {r['anim'][1]} (GIF)")
    return r["sheet"], r["report"]


# ----------------------------------------------------------------------------- animation
def _is_animated(asset) -> bool:
    return any(n > 1 for _, n in getattr(asset, "anims", []))


def _ticks(asset, max_frames: int):
    from .anim import preview_ticks
    return preview_ticks(getattr(asset, "anims", []), max_frames)


def _views_for(asset):
    """Vues de l'animation : inventaire, en jeu (perspective), et la nuit si quelque chose brille."""
    glow = bool(getattr(asset, "planes", None) and any(p.emission for p in asset.planes)) or \
        getattr(asset, "emissive", None) is not None
    views = [("inventaire", INVENTORY, "gui", 0.0), ("en jeu", GAME_VIEW, "world", 2.2)]
    if glow:
        views.append(("la nuit", GAME_VIEW, "night", 2.2))
    return views


def anim_frames(asset, size: int = 220, max_frames: int = 48):
    """Rendus de l'animation : liste de (tick, [image par vue]) + noms des vues."""
    views = _views_for(asset)
    ticks = _ticks(asset, max_frames)
    q0 = asset.quads(0)
    cams = {name: fit_camera(q0, view, size, size, 0.06, persp=persp) for name, view, _, persp in views}
    out = []
    for t in ticks:
        q = asset.quads(t)
        imgs = []
        for name, _view, shading, _ in views:
            bg = (10, 12, 20, 255) if shading == "night" else BG
            imgs.append(render(q, cams[name], shading=shading, bg=bg))
        out.append((t, imgs))
    return out, [v[0] for v in views]


def anim_sheet(asset, out_dir="out", size: int = 150, gif_size: int = 220, max_frames: int = 16):
    """Planche des images d'une animation (une ligne par vue, une colonne par image) + GIF animé à la
    vitesse du jeu (vues côte à côte). Retourne (chemin PNG, chemin GIF)."""
    from .anim import Anim, save_gif
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames, names = anim_frames(asset, size, max_frames)
    n = len(frames)
    rows = len(names)
    planes = [p for p in getattr(asset, "planes", []) if isinstance(p.texture, Anim)]
    tex_rows = []
    seen = set()
    for p in planes:
        if id(p.texture) not in seen:
            seen.add(id(p.texture))
            tex_rows.append(p.texture)
    W = 16 + n * (size + 6) + 120
    H = 60 + rows * (size + 22) + sum(min(96, t.h * 4) + 30 for t in tex_rows) + 16
    cv = Image.new("RGBA", (max(W, 700), H), BG)
    periods = ", ".join(dict.fromkeys(t.describe(k) for t, k in asset.anims if k > 1))
    _header(cv, asset.name, f"animation · {periods} · {n} instants montrés (ticks : "
                            f"{', '.join(str(int(t)) for t, _ in frames[:8])}{'…' if n > 8 else ''})")
    d = ImageDraw.Draw(cv)
    y = 50
    for r, name in enumerate(names):
        d.text((16, y), name, font=font(13, bold=True), fill=MUTED)
        for k, (t, imgs) in enumerate(frames):
            x = 16 + k * (size + 6)
            cv.alpha_composite(_img(imgs[r]), (x, y + 18))
            d.text((x + 3, y + 20), f"t{int(t)}", font=font(10), fill=MUTED)
        y += size + 22
    for tex in tex_rows:
        d.text((16, y + 4), f"texture du plan : {tex.n} images {tex.w}×{tex.h}", font=font(13, bold=True), fill=MUTED)
        sc = max(1, min(96, tex.h * 4) // tex.h)
        cv.alpha_composite(tex.contact(sc, cols=min(tex.n, 32)), (16, y + 22))
        y += min(96, tex.h * 4) + 30
    png = out / f"{asset.name}.anim.png"
    cv.convert("RGB").save(png)
    gframes, _ = anim_frames(asset, gif_size, 48)
    ticks = [t for t, _ in gframes]
    period = max((tm.period(k) for tm, k in asset.anims if k > 1), default=20)
    from math import gcd
    full = 1
    for tm, k in asset.anims:
        if k > 1:
            full = full * tm.period(k) // gcd(full, tm.period(k))
    durs = [((ticks[i + 1] if i + 1 < len(ticks) else full) - ticks[i]) * 50 for i in range(len(ticks))]
    strips = []
    for _, imgs in gframes:
        strips.append(np.concatenate([np.concatenate([im, np.zeros((im.shape[0], 4, 4), np.uint8)], axis=1)
                                      for im in imgs], axis=1))
    gif = out / f"{asset.name}.anim.gif"
    save_gif(strips, durs, gif, BG[:3])
    del period
    return png, gif

def asset_quads(asset, tick: float = 0) -> list:
    """Géométrie de rendu de n'importe quel asset au tick donné (objet entier pour un multibloc,
    plans texturés compris pour un modèle)."""
    return asset.quads(tick)


def view(asset, yaw: float, pitch: float, size: int = 600, shading: str = "gui", path=None,
         out_dir="out", persp: float = 0.0, tick: float = 0) -> Path:
    """Rendu libre (angle quelconque) pour inspecter un détail. Les items sont montrés extrudés
    comme en main / au sol (item/generated). persp > 0 : perspective (1.5–3 ; conseillé pour les vues
    par dessous). shading='night' : la nuit, seules les faces à light_emission restent claires.
    tick : instant d'une animation. Fichier : <out_dir>/<nom>.view_<yaw>_<pitch>.png."""
    q = asset_quads(asset, tick)
    bg = (10, 12, 20, 255) if shading == "night" else BG
    img = render(q, fit_camera(q, (yaw, pitch), size, size, 0.05, persp=persp), shading=shading, bg=bg)
    p = Path(path) if path else Path(out_dir) / f"{asset.name}.view_{int(yaw)}_{int(pitch)}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    _img(img).convert("RGB").save(p)
    return p


def compare_sheet(assets, path="out/compare.png", size: int = 300) -> Path:
    """Planche côte à côte : vue inventaire, vue opposée et icône ×2 de chaque asset (pour choisir
    entre des variantes : palettes, graines, réglages)."""
    n = len(assets)
    cols = 3 if n in (5, 6, 9) else min(n, 4)
    rows = (n + cols - 1) // cols
    cw, ch = size + 24, size * 2 + 120
    cv = Image.new("RGBA", (cols * cw + 16, rows * ch + 16), BG)
    for i, a in enumerate(assets):
        x = 16 + (i % cols) * cw
        y = 16 + (i // cols) * ch
        box = _panel(cv, x, y, size + 8, ch - 16, a.name)
        if isinstance(a, Item):
            big = a.sprite.to_image(max(1, (size - 20) // max(a.sprite.w, a.sprite.h)))
            _paste_center(cv, big, (box[0], box[1], box[2], size))
            q3 = item_quads(a.sprite.data)
            _paste_center(cv, _img(render(q3, fit_camera(q3, (200, 25), size - 10, size - 10, 0.08),
                                          shading="world")), (box[0], box[1] + size, box[2], size))
            icon = a.sprite.data
        else:
            q = asset_quads(a)
            _paste_center(cv, _img(render(q, fit_camera(q, INVENTORY, size - 10, size - 10, 0.05), shading="gui")),
                          (box[0], box[1], box[2], size))
            _paste_center(cv, _img(render(q, fit_camera(q, BACK, size - 10, size - 10, 0.05, persp=PERSP_BELOW),
                                          shading="world")), (box[0], box[1] + size, box[2], size))
            gs, gc = a.gui_transform() if isinstance(a, (Model, MultiBlock)) else (0.625, (8, 8, 8))
            icon = render(_mini_quads(a) if isinstance(a, MultiBlock) else q,
                          gui_camera(2, center=gc, display_scale=gs), shading="gui")
        cv.alpha_composite(slot_icon(icon, 2), (box[0] + 10, box[1] + 2 * size + 4))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cv.convert("RGB").save(p)
    return p
