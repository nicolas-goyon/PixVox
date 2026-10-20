"""Régénère les images du README (docs/images/) à partir des exemples — rendu déterministe.

    python scripts/readme_images.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pixvox.anim import save_gif  # noqa: E402
from pixvox.render import INVENTORY, cube_quads, fit_camera, render, tiled_cube_quads  # noqa: E402
from pixvox.review import BG, GAME_VIEW, MUTED, PANEL, TEXT, _img, compare_sheet, font  # noqa: E402

OUT = ROOT / "docs" / "images"
NIGHT_BG = (10, 12, 20, 255)


def example(name: str):
    res = runpy.run_path(str(ROOT / "examples" / f"{name}.py"))["build"]()
    return res if isinstance(res, list) else [res]


def before_after() -> Path:
    naive, _fixed, vox = example("mossy_stone")

    def corner_zoom(block, size=1400, crop=360):
        q = cube_quads(block.faces())
        cam = fit_camera(q, INVENTORY, size, size, 0.05)
        img = render(q, cam, shading="gui")
        cx, cy, _ = cam.project(np.array([16.0, 16.0, 0.0]))       # coin haut est-nord (le plus proche)
        x0, y0 = int(cx) - crop // 2, int(cy) - int(crop * 0.35)
        return _img(img[y0:y0 + crop, x0:x0 + crop])

    W, H = 1180, 700
    cv = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(cv)
    d.text((24, 16), "L'erreur des arêtes à deux couleurs — et sa correction par construction",
           font=font(22, bold=True), fill=TEXT)
    for i, (b, title, sub) in enumerate([
            (naive, "Avant : une texture par face", f"{len(naive.conflicts)} mini-cubes d'arête ont 2 ou 3 couleurs"),
            (vox, "Après : un volume 16³, faces lues sur sa peau", "0 conflit possible ; la mousse passe d'une face à l'autre")]):
        x = 24 + i * 578
        d.rounded_rectangle([x, 60, x + 554, H - 20], radius=10, fill=PANEL)
        d.text((x + 16, 72), title, font=font(17, bold=True), fill=TEXT)
        d.text((x + 16, 98), sub, font=font(13), fill=MUTED)
        q = cube_quads(b.faces())
        cv.alpha_composite(_img(render(q, fit_camera(q, INVENTORY, 250, 250, 0.04), shading="gui")), (x + 16, 140))
        cv.alpha_composite(corner_zoom(b).resize((270, 270), Image.NEAREST), (x + 270, 130))
        d.text((x + 274, 405), "zoom sur le coin haut (est | nord)", font=font(12), fill=MUTED)
        wq = tiled_cube_quads(b.faces(), (3, 1, 3))
        cv.alpha_composite(_img(render(wq, fit_camera(wq, INVENTORY, 520, 240, 0.04), shading="world")), (x + 16, 430))
    path = OUT / "avant_apres.png"
    cv.convert("RGB").save(path, optimize=True)
    return path


def brazier_gif(size: int = 260) -> Path:
    brazier, soul = example("brazier")
    cams = [fit_camera(a.quads(0), GAME_VIEW, size, size, 0.06, persp=2.2) for a in (brazier, soul)]
    frames = []
    for t in range(0, 32, 2):                       # 16 images × 2 ticks = la boucle complète
        qb, qs = brazier.quads(t), soul.quads(t)
        frames.append(np.concatenate([render(qb, cams[0], shading="world", bg=BG),
                                      render(qb, cams[0], shading="night", bg=NIGHT_BG),
                                      render(qs, cams[1], shading="night", bg=NIGHT_BG)], axis=1))
    path = OUT / "brasero.gif"
    save_gif(frames, [100] * len(frames), path, BG[:3])
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = [before_after(), brazier_gif(),
            compare_sheet(example("angel_statue"), OUT / "resolutions.png", 300)]
    gallery = [a for n in ("lumenite_ore", "reinforced_crate", "ashen_log", "glowcap", "magma_core") for a in example(n)]
    gallery += [example("mossy_stone")[2], example("lumenite_shard")[0]]
    made.append(compare_sheet(gallery, OUT / "galerie.png", 240))
    for p in made:
        print(f"{p.relative_to(ROOT)} ({Path(p).stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
