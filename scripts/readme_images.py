"""Régénère les images du README (docs/images/) à partir des exemples — rendu déterministe.

    python scripts/readme_images.py                    # toutes
    python scripts/readme_images.py --only materiaux   # catalogue des matériaux seulement
    python scripts/readme_images.py --check            # le catalogue est-il à jour ? (CI)
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
from pixvox.png import save_png  # noqa: E402
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


def materials_catalog(size: int = 300, path: Path | None = None) -> Path:
    """Planche « catalogue » des matériaux de pixvox.materials : chaque exemple en mur de 3 × 3 × 3 blocs,
    ombrage en jeu, nom et recette dessous. Vérifiée octet pour octet par la CI (rendu et PNG déterministes)."""
    blocks = example("materials")
    recipes = {"oak_boards": "planks(wood=\"oak\")", "red_bricks": "bricks()", "cut_stone_blocks": "cut_stone()",
               "amber_ore": "ore(crystal=…)", "iron_plates": "metal()", "weathered_copper_plates": "metal(patina=0.45)"}
    cols, pad = 3, 14
    rows = (len(blocks) + cols - 1) // cols
    W, H = cols * (size + pad) + pad, rows * (size + 52) + pad
    cv = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(cv)
    for i, b in enumerate(blocks):
        x, y = pad + (i % cols) * (size + pad), pad + (i // cols) * (size + 52)
        d.rounded_rectangle((x, y, x + size, y + size + 38), 8, fill=PANEL)
        q = tiled_cube_quads(b.faces())
        img = _img(render(q, fit_camera(q, INVENTORY, size - 16, size - 16, 0.04), shading="world"))
        cv.alpha_composite(img, (x + 8, y + 8))
        d.text((x + 10, y + size - 4), b.name, font=font(14), fill=TEXT)
        d.text((x + 10, y + size + 14), recipes.get(b.name, ""), font=font(12, mono=True), fill=MUTED)
    p = path or OUT / "materiaux.png"
    save_png(p, cv)
    return p


def check_catalog() -> int:
    """Code 1 si docs/images/materiaux.png n'est plus à jour (la CI le vérifie sous Linux : rendu et PNG
    déterministes ; les polices des étiquettes diffèrent d'un système à l'autre)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fresh = materials_catalog(path=Path(d) / "materiaux.png").read_bytes()
    current = (OUT / "materiaux.png").read_bytes() if (OUT / "materiaux.png").is_file() else b""
    if fresh != current:
        print("docs/images/materiaux.png n'est plus à jour : python scripts/readme_images.py --only materiaux")
        return 1
    print("docs/images/materiaux.png à jour")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        return check_catalog()
    OUT.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ["--only"] and argv[1:2] == ["materiaux"]:
        print(materials_catalog().relative_to(ROOT))
        return 0
    made = [before_after(), brazier_gif(), materials_catalog(),
            compare_sheet(example("angel_statue"), OUT / "resolutions.png", 300)]
    gallery = [a for n in ("lumenite_ore", "reinforced_crate", "ashen_log", "glowcap", "magma_core") for a in example(n)]
    gallery += [example("mossy_stone")[2], example("lumenite_shard")[0]]
    made.append(compare_sheet(gallery, OUT / "galerie.png", 240))
    for p in made:
        print(f"{p.relative_to(ROOT)} ({Path(p).stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
