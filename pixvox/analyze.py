"""pixvox.analyze — diagnostics lisibles (texte) sur un asset : ce que Claude lit après chaque rendu.

Niveaux : OK, INFO, ATTENTION (WARN), ERREUR (ERR).
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

import numpy as np

from .anim import Anim
from .assets import Block, Item, Model, MultiBlock
from .color import delta_e, hexa, lightness, lightness_array, rgb_to_oklab, unique_colors
from .volume import FACES

SLOT_GRAY = (139, 139, 139, 255)


@dataclass
class Finding:
    level: str      # OK | INFO | WARN | ERR
    topic: str
    msg: str

    def line(self) -> str:
        tag = {"OK": "[OK]  ", "INFO": "[INFO]", "WARN": "[ATTN]", "ERR": "[ERR] "}[self.level]
        return f"{tag} {self.topic} : {self.msg}"


# ----------------------------------------------------------------------------- mesures 2D
def _lab(img: np.ndarray) -> np.ndarray:
    return rgb_to_oklab(img[..., :3].astype(float))


def seam_scores(tex: np.ndarray) -> tuple[float, float, float, float]:
    """Raccord de la texture avec elle-même (blocs voisins identiques).

    Une couture = une rupture SYSTÉMATIQUE tout le long du bord, plus forte que les transitions
    voisines. Pour chaque direction : part des paires de pixels (dernière -> première colonne/ligne)
    dont l'écart dépasse le 75e centile des écarts intérieurs. Ramenée à 0.5 au plus si le raccord
    n.est pas plus abrupt que ses voisines immédiates (×1.5) et que toute transition intérieure (×1.2) de la
    texture : un trait (joint, rayure) qui tombe pile au bord n'est pas une couture.
    Retourne (part_h, part_v, ΔE moyen au raccord h, v)."""
    lab = _lab(tex) * 100
    out = []
    for axis in (1, 0):
        L = np.moveaxis(lab, axis, 0)
        inner = np.linalg.norm(L[1:] - L[:-1], axis=-1)          # (n-1, m)
        wrap = np.linalg.norm(L[0] - L[-1], axis=-1)              # (m,)
        p75 = float(np.percentile(inner, 75))
        frac = float((wrap > max(p75, 1.0)).mean())
        means = inner.mean(axis=1)
        w = float(wrap.mean())
        if not (w >= means.max() * 1.2 and w > 1.5 * max(means[0], means[-1])):
            frac = min(frac, 0.5)
        out.append((frac, w))
    (fh, dh), (fv, dv) = out
    return fh, fv, dh, dv


def isolated_fraction(tex: np.ndarray, opaque: np.ndarray | None = None) -> float:
    """Part des pixels dont la couleur n'apparaît chez aucun de leurs 8 voisins (pixels « orphelins »).
    Les diagonales comptent : une ligne en escalier d'une même couleur n'est pas du bruit."""
    h, w = tex.shape[:2]
    op = tex[..., 3] > 0 if opaque is None else opaque
    same_any = np.zeros((h, w), bool)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        sh = np.roll(tex, (dy, dx), axis=(0, 1))
        same_any |= np.all(sh == tex, axis=-1)
    n = op.sum()
    return float((op & ~same_any).sum() / max(1, n))


def local_contrast(tex: np.ndarray) -> float:
    """Écart moyen de clarté OKLab entre pixels voisins (raccord inclus)."""
    L = lightness_array(tex)
    return float((np.abs(L - np.roll(L, 1, 0)).mean() + np.abs(L - np.roll(L, 1, 1)).mean()) / 2)


def near_duplicates(colors, thr: float = 2.0) -> list:
    cols = [c for c in colors if c[3] > 0]
    if len(cols) < 2:
        return []
    lab = rgb_to_oklab(np.array([c[:3] for c in cols], float)) * 100
    out = []
    for i in range(len(cols)):
        d = np.linalg.norm(lab[i + 1:] - lab[i], axis=1)
        for j in np.nonzero(d < thr)[0]:
            out.append((cols[i], cols[i + 1 + j], float(d[j])))
    return out


def _components(mask: np.ndarray) -> list[int]:
    """Tailles des composantes 6-connexes d'un masque 3D."""
    try:
        from scipy import ndimage  # type: ignore
        lab, n = ndimage.label(mask)
        return sorted([int((lab == i).sum()) for i in range(1, n + 1)], reverse=True)
    except Exception:
        pass
    seen = np.zeros_like(mask)
    sizes = []
    for start in zip(*np.nonzero(mask)):
        if seen[start]:
            continue
        q = deque([start])
        seen[start] = True
        n = 0
        while q:
            x, y, z = q.popleft()
            n += 1
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                p = (x + d[0], y + d[1], z + d[2])
                if all(0 <= p[k] < mask.shape[k] for k in range(3)) and mask[p] and not seen[p]:
                    seen[p] = True
                    q.append(p)
        sizes.append(n)
    return sorted(sizes, reverse=True)


def _palette_findings(all_px: np.ndarray, topic="Palette", soft: int = 32, hard: int = 64) -> list:
    cols = unique_colors(all_px)
    n = len(cols)
    out = []
    Ls = sorted(lightness(c) for c in cols) if cols else [0]
    msg = f"{n} couleurs, clarté OKLab {Ls[0]:.2f}–{Ls[-1]:.2f}"
    if n > hard:
        out.append(Finding("WARN", topic, msg + f" — beaucoup trop (> {hard}) : aspect bruité, peu « vanilla »"))
    elif n > soft:
        out.append(Finding("WARN", topic, msg + " — un peu élevé (vanilla : ~8–24) ; regroupez en rampes"))
    else:
        out.append(Finding("OK", topic, msg))
    dups = near_duplicates(list(cols.keys()))
    if dups:
        ex = ", ".join(f"{hexa(a)}≈{hexa(b)}" for a, b, _ in dups[:4])
        out.append(Finding("INFO", topic, f"{len(dups)} paires quasi identiques (ΔE<2) : {ex}"
                                         + (" …" if len(dups) > 4 else "") + " — fusionnables"))
    return out


# ----------------------------------------------------------------------------- animation
def anim_findings(label: str, stack: np.ndarray, timing) -> list:
    """Diagnostic d'une animation. stack : (T, N, 4) — couleurs des N pixels/voxels visibles à chaque
    image. Vérifie la boucle (pas d'à-coup entre la dernière et la première image) et le rythme."""
    T = stack.shape[0]
    seq = [i for i, _ in timing.sequence(T)]
    st = stack[seq].astype(int)
    frac = [float((np.abs(st[k + 1] - st[k]).max(-1) > 0).mean()) for k in range(len(seq) - 1)]
    f_loop = float((np.abs(st[0] - st[-1]).max(-1) > 0).mean())
    mag = [float(np.abs(st[k + 1] - st[k]).max(-1).mean()) for k in range(len(seq) - 1)]   # ampleur
    m_loop = float(np.abs(st[0] - st[-1]).max(-1).mean())
    out = [Finding("INFO", "Animation", f"{label} : boucle de {timing.describe(T)}")]
    if T < 2:
        return out
    if max(frac + [f_loop]) == 0:
        out.append(Finding("WARN", "Animation", f"{label} : toutes les images sont identiques (rien ne bouge)"))
        return out
    med = float(np.median(frac)) if frac else 0.0
    mmed = float(np.median(mag)) if mag else 0.0
    if f_loop > max(2.0 * med, med + 0.15) or m_loop > max(2.5 * mmed, mmed + 6.0):
        out.append(Finding("WARN", "Animation", f"{label} : à-coup à la boucle — entre la dernière et la première image, "
                                                f"{f_loop:.0%} des pixels changent (écart moyen {m_loop:.0f}) contre "
                                                f"{med:.0%} (écart {mmed:.0f}) d'une image à l'autre. Utilisez des "
                                                "mouvements périodiques : fire/pulse/flow bouclent exactement"))
    else:
        out.append(Finding("OK", "Animation", f"{label} : boucle sans à-coup ({f_loop:.0%} des pixels changent au "
                                              f"raccord, {med:.0%} d'une image à l'autre en moyenne)"))
    if med > 0.65 and not timing.interpolate:
        out.append(Finding("INFO", "Animation", f"{label} : la plupart des pixels changent à chaque image : "
                                                "scintillement ; plus d'images, frametime plus long, ou interpolate=True"))
    return out


def _clip_findings(asset, label: str) -> list:
    """Animation d'un asset fait de volumes : couleurs des voxels visibles à chaque image."""
    frames = getattr(asset, "frames", [])
    if len(frames) < 2:
        return []
    surf = asset.volume.m_surface()
    stack = np.stack([f.data[surf] for f in frames])
    out = anim_findings(label, stack, asset.timing)
    moving = int((np.abs(stack.astype(int) - stack[:1].astype(int)).max(-1) > 0).any(0).sum())
    out.append(Finding("INFO", "Animation", f"{label} : {moving} voxels visibles sur {int(surf.sum())} changent de "
                                            "couleur (le reste reste fixe dans l'export)"))
    return out


def _anim_tex_findings(anim: Anim, label: str) -> list:
    stack = np.stack([f.data.reshape(-1, 4) for f in anim.frames])
    out = anim_findings(label, stack, anim.timing)
    a = stack[..., 3]
    if ((a > 0) & (a < 255)).any():
        out.append(Finding("WARN", "Transparence", f"{label} : pixels semi-transparents (translucent) ; le feu vanilla "
                                                   "est en cutout (alpha 0 ou 255)"))
    return out


# ----------------------------------------------------------------------------- blocs
def analyze_block(b: Block) -> list:
    out = []
    faces = b.faces()
    if b.source == "volume":
        out.append(Finding("OK", "Arêtes", "cohérentes par construction (textures lues sur la peau du volume)"))
    else:
        conf = b.conflicts
        if not conf:
            out.append(Finding("OK", "Arêtes", "aucun conflit entre les textures fournies"))
        else:
            per_edge = Counter()
            visible = 0
            examples = []
            for c in conf:
                fs = sorted({f for f, *_ in c["faces"]})
                per_edge["/".join(fs)] += 1
                cols = [h for *_, h in c["faces"]]
                d = max(delta_e(cols[i], cols[j]) for i in range(len(cols)) for j in range(i + 1, len(cols)))
                visible += d > 5
                if len(examples) < 4:
                    examples.append(" vs ".join(f"{f}({u},{v})={h}" for f, u, v, h in c["faces"]))
            edges = ", ".join(f"{k}: {v}" for k, v in per_edge.most_common(6))
            out.append(Finding("WARN", "Arêtes",
                               f"{len(conf)} voxels d'arête ont 2-3 couleurs selon la face ({visible} nettement "
                               f"visibles, ΔE>5). Par arête : {edges}"))
            for e in examples:
                out.append(Finding("INFO", "Arêtes", "ex. " + e))
            if b.fixed:
                out[-len(examples) - 1] = Finding("OK", "Arêtes", f"{len(conf)} conflits d'arête CORRIGÉS (fix=True) : "
                                                                    f"chaque voxel d'arête n'a plus qu'une couleur ({edges})")
            else:
                out.append(Finding("INFO", "Arêtes", "conflits marqués en magenta sur le patron ; Block.from_faces(…, "
                                                      "fix=True) unifie (priorité up > north > south > east > west > down)"))
    # raccords
    bad, expected = [], []
    parts = []
    mode = getattr(b, "seamless", True)
    for f in FACES:
        rh, rv, dh, dv = seam_scores(faces[f].data)
        parts.append(f"{f[0].upper()} {max(rh, rv):.0%}")
        for direction, r, dd in (("horizontal", rh, dh), ("vertical", rv, dv)):
            if r > 0.6 and dd > 6:
                txt = f"{f} ({direction}, {r:.0%} du bord en rupture, ΔE {dd:.0f})"
                side = f not in ("up", "down")
                if mode is False or (mode == "horizontal" and side and direction == "vertical"):
                    expected.append(txt)
                else:
                    bad.append(txt)
    if expected:
        why = "seamless=False" if mode is False else "seamless='horizontal' : empilement vertical"
        out.append(Finding("INFO", "Raccords", f"bordure voulue ({why}) : " + "; ".join(expected)))
    if bad:
        out.append(Finding("WARN", "Raccords", "couture probable quand on pose des blocs côte à côte : "
                                               + "; ".join(bad) + " — vérifiez la vue Monde 3×3×3. Motif non périodique : "
                                               "utilisez wrap=True / les bruits pixvox ; motif déjà périodique dont la "
                                               "transition la plus nette tombe pile au bord : changez la graine (seed) ; "
                                               "bordure voulue : seamless=False / 'horizontal'"))
    elif not expected:
        out.append(Finding("OK", "Raccords", "pas de couture (part du bord en rupture : " + ", ".join(parts)
                           + " ; alerte au-delà de 60 % et ΔE > 6)"))
    else:
        out.append(Finding("OK", "Raccords", "aucune autre couture"))
    # palette
    all_px = np.concatenate([faces[f].data.reshape(-1, 4) for f in FACES])
    out += _palette_findings(all_px)
    # bruit / contraste
    iso = {f: isolated_fraction(faces[f].data) for f in FACES}
    lc = {f: local_contrast(faces[f].data) for f in FACES}
    worst = max(iso, key=iso.get)
    msg = (f"pixels orphelins {min(iso.values()):.0%}–{max(iso.values()):.0%}, contraste local "
           f"{min(lc.values()):.3f}–{max(lc.values()):.3f}")
    if iso[worst] > 0.40 or max(lc.values()) > 0.11:
        out.append(Finding("WARN", "Texture", msg + f" — granuleux (pire : {worst}). Moins d'octaves, rampe plus "
                                                   "serrée (spread), ou weights en cloche"))
    elif max(lc.values()) < 0.012:
        out.append(Finding("WARN", "Texture", msg + " — très plat : ajoutez du relief ou du bruit doux"))
    else:
        out.append(Finding("OK", "Texture", msg))
    # transparence
    a = all_px[:, 3]
    rt = b.effective_render_type()
    if rt == "translucent":
        out.append(Finding("WARN", "Transparence", f"{int(((a > 0) & (a < 255)).sum())} px semi-transparents : "
                                                   "rendu 'translucent' requis (ordre de tri, coût)"))
    elif rt == "cutout":
        out.append(Finding("INFO", "Transparence", f"{int((a == 0).sum())} px transparents : rendu 'cutout'"))
    else:
        out.append(Finding("OK", "Transparence", "opaque (rendu 'solid')"))
    # faces identiques
    groups = Counter(faces[f].data.tobytes() for f in FACES)
    out.append(Finding("INFO", "Export", f"{len(groups)} texture(s) distincte(s) sur 6 faces"))
    if b.emissive is not None:
        gl = b.glow_faces()
        n = sum(int((g.data[..., 3] > 0).sum()) for g in gl.values())
        out.append(Finding("INFO", "Lumière", f"{n} pixels lumineux sur {len(gl)} face(s) : surcouche light_emission "
                                              f"{b.emission} (visible dans le noir, n'éclaire pas le monde sans mod)"))
    if b.animated and b.given_faces is None:
        fa = b.face_anims()
        anim_faces = [f for f in FACES if isinstance(fa[f], Anim)]
        fixed = [f for f in FACES if f not in anim_faces]
        out.append(Finding("INFO", "Animation", (f"faces animées : {', '.join(anim_faces)}" if anim_faces else
                                                 "aucune face ne change") +
                           (f" ; fixes (PNG simples) : {', '.join(fixed)}" if fixed and anim_faces else "")))
        out += _clip_findings(b, "bloc")
    out += _journal(b.volume.log)
    return out


def _journal(log) -> list:
    """Résume le journal du volume (les peintures sans contact d'arête sont regroupées)."""
    out = []
    quiet = [ln for ln in log if ln.startswith("paint_face(") and "aucun voxel d'arête" in ln]
    if quiet:
        names = ", ".join(ln.split("(")[1].split(")")[0] for ln in quiet)
        out.append(Finding("INFO", "Journal", f"paint_face sur {names} : aucun voxel d'arête touché"))
    for ln in log:
        if ln not in quiet:
            out.append(Finding("INFO", "Journal", ln))
    return out


# ----------------------------------------------------------------------------- modèles
def analyze_model(m: Model) -> list:
    from .export import optimize_model
    out = []
    v = m.volume
    solid = v.solid
    n = int(solid.sum())
    if n == 0:
        return [Finding("ERR", "Volume", "vide")]
    xs, ys, zs = np.nonzero(solid)
    bb = (xs.min(), ys.min(), zs.min(), xs.max() + 1, ys.max() + 1, zs.max() + 1)
    vs = m.voxel_size
    lo = [round(float(m.origin[k] + bb[k] * vs), 2) for k in range(3)]
    hi = [round(float(m.origin[k] + bb[k + 3] * vs), 2) for k in range(3)]
    out.append(Finding("INFO", "Volume", f"{n} voxels pleins, boîte {int(bb[3] - bb[0])}x{int(bb[4] - bb[1])}x{int(bb[5] - bb[2])}"
                                         f" ; en unités modèle de {lo} à {hi}"))
    if min(lo) < -16 or max(hi) > 32:
        out.append(Finding("ERR", "Volume", "hors des limites Minecraft [-16, 32] : réduisez ou changez voxel_size"))
    elif max(hi) > 16 or min(lo) < 0:
        out.append(Finding("INFO", "Volume", "dépasse du bloc [0,16] (autorisé jusqu'à [-16,32], hitbox inchangée)"))
    comps = _components(solid)
    if len(comps) > 1:
        out.append(Finding("WARN", "Volume", f"{len(comps)} morceaux séparés (tailles {comps[:6]}) : "
                                             "parties flottantes ?"))
    else:
        out.append(Finding("OK", "Volume", "un seul morceau connexe"))
    ext = max(hi[k] - lo[k] for k in range(3))
    if ext < 11 and not m.inventory_scale:
        sug = min(2.0, max(1.2, round(13.0 / max(ext, 1), 1)))
        out.append(Finding("INFO", "Inventaire", f"petit dans la case ({ext:g} unités sur 16) : "
                                                 f"Model(…, inventory_scale={sug}, inventory_center=True)"))
    hidden = int(v.m_hidden().sum())
    if hidden:
        out.append(Finding("INFO", "Volume", f"{hidden} voxels cachés (couleur sans importance, servent de jokers)"))
    out += _palette_findings(v.data[v.m_surface()])
    opt = optimize_model(m)
    alt = "; ".join(f"{k}: {d['elements']} éléments, texture {d['texture']}px" for k, d in opt.alternatives.items())
    level = "WARN" if len(opt.elements) > 150 else "OK"
    sz = opt.texture_size
    out.append(Finding(level, "Export", f"stratégie '{opt.strategy}' → {len(opt.elements)} éléments, "
                                        f"{opt.n_faces} faces, atlas {sz}x{sz} ({alt})"
                       + (" — lourd pour un bloc très répété" if level == "WARN" else "")))
    if opt.anim_atlas is not None:
        out.append(Finding("INFO", "Export", f"atlas animé {opt.anim_atlas.size}px × {len(opt.anim_atlas.frames)} images "
                                             "(faces qui changent) + atlas fixe pour le reste"))
    if m.emissive is not None:
        ne = sum(1 for e in opt.elements if e.get("light_emission"))
        out.append(Finding("INFO", "Lumière", f"{int((m.emissive & solid).sum())} voxels lumineux → {ne} éléments "
                                              f"light_emission {m.emission} (restent clairs dans le noir)"))
    out += _plane_findings(m)
    out += _clip_findings(m, "volume")
    out += _journal(v.log)
    return out


def _plane_findings(m: Model) -> list:
    out = []
    if not m.planes:
        return out
    angles = sorted({round(p.norm_angle(), 3) for p in m.planes})
    out.append(Finding("INFO", "Plans", f"{len(m.planes)} plan(s) texturé(s), angles {angles}, "
                                        f"{sum(1 for p in m.planes if p.emission)} lumineux"))
    odd = [a for a in angles if abs(a / 22.5 - round(a / 22.5)) > 1e-6]     # export : rotation dans [-45, 45]
    if odd:
        out.append(Finding("WARN", "Plans", f"angle(s) {odd} : acceptés seulement depuis 1.21.11 (avant : multiples "
                                            "de 22,5° — sinon le modèle ne charge pas)"))
    for p in m.planes:
        lo, hi = p.bounds()
        if lo.min() < -16 or hi.max() > 32:
            out.append(Finding("ERR", "Plans", f"plan hors des limites [-16, 32] : {lo.round(2).tolist()} → "
                                               f"{hi.round(2).tolist()}"))
            break
    seen = set()
    for k, p in enumerate(m.planes):
        if id(p.texture) in seen:
            continue
        seen.add(id(p.texture))
        if isinstance(p.texture, Anim):
            out += _anim_tex_findings(p.texture, f"plan {k} ({p.texture.w}×{p.texture.h})")
        else:
            a = np.asarray(p.texture.data)[..., 3]
            if ((a > 0) & (a < 255)).any():
                out.append(Finding("WARN", "Transparence", f"plan {k} : pixels semi-transparents (rendu translucide, "
                                                           "tri imparfait) ; préférer alpha 0 ou 255 (cutout)"))
    if any(p.emission for p in m.planes):
        out.append(Finding("INFO", "Lumière", "plans light_emission : pleinement éclairés même la nuit. Le bloc "
                                              "n'éclaire pas ses voisins sans mod (luminance) — voir l'export mod"))
    return out


# ----------------------------------------------------------------------------- items
def analyze_item(it: Item) -> list:
    out = []
    s = it.sprite
    d = s.data
    op = d[..., 3] > 0
    if not op.any():
        return [Finding("ERR", "Sprite", "entièrement transparent")]
    if (s.w, s.h) == (16, 16):
        pass
    elif s.w == s.h and s.w in (32, 64, 128):
        out.append(Finding("INFO", "Sprite", f"taille {s.w}x{s.h} : haute définition (vanilla : 16x16)"))
    else:
        out.append(Finding("WARN", "Sprite", f"taille inhabituelle {s.w}x{s.h} (vanilla 16x16, HD 32/64)"))
    ys, xs = np.nonzero(op)
    bb = (xs.min(), ys.min(), xs.max(), ys.max())
    cover = op.sum() / op.size
    out.append(Finding("INFO", "Sprite", f"contenu x {bb[0]}–{bb[2]}, y {bb[1]}–{bb[3]} "
                                         f"({bb[2] - bb[0] + 1}x{bb[3] - bb[1] + 1}), remplissage {cover:.0%}"))
    if bb[2] - bb[0] + 1 < 9 and bb[3] - bb[1] + 1 < 9:
        out.append(Finding("WARN", "Sprite", "petit dans la case : l'icône paraîtra minuscule"))
    semi = int(((d[..., 3] > 0) & (d[..., 3] < 255)).sum())
    if semi:
        out.append(Finding("WARN", "Transparence", f"{semi} px semi-transparents (vanilla : alpha 0 ou 255)"))
    # contour
    pad = np.pad(op, 1)
    boundary = np.zeros_like(op)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = pad[1 + dy:1 + dy + s.h, 1 + dx:1 + dx + s.w]
        boundary |= op & ~nb
    L = lightness_array(d)
    thr = min(0.40, np.percentile(L[op], 30))
    dark = boundary & (L <= thr)
    cov = dark.sum() / max(1, boundary.sum())
    gaps = np.argwhere(boundary & ~dark)
    where = ", ".join(f"({x},{y})" for y, x in gaps[:8]) + (" …" if len(gaps) > 8 else "")
    if cov >= 0.999:
        out.append(Finding("OK", "Contour", "bord entièrement sombre (contour net et continu)"))
    elif cov >= 0.75:
        out.append(Finding("INFO", "Contour", f"{cov:.0%} du bord est sombre ; pixels de bord clairs en (x,y) : "
                                              f"{where} — trou dans le contour, ou contour sélectif voulu ?"))
    else:
        out.append(Finding("INFO", "Contour", f"{cov:.0%} du bord est sombre — la plupart des items vanilla ont un "
                                              "contour foncé ; vérifiez la lisibilité sur la case grise"))
    # lumière : intérieur de la silhouette, côté haut-gauche vs bas-droite
    inner = op & ~dark
    yy, xx = np.nonzero(inner)
    if len(yy) > 6:
        Lv = L[inner]
        proj = -(xx - xx.mean()) - (yy - yy.mean())          # >0 vers le haut-gauche
        corr = float(np.corrcoef(proj, Lv)[0, 1]) if np.std(Lv) > 1e-6 else 0.0
        if corr > 0.15:
            out.append(Finding("OK", "Lumière", f"vient du haut-gauche (corrélation {corr:+.2f}), comme vanilla"))
        elif corr < -0.15:
            out.append(Finding("WARN", "Lumière", f"semble venir du bas-droite ({corr:+.2f}) ; vanilla éclaire "
                                                  "en haut à gauche"))
        else:
            out.append(Finding("INFO", "Lumière", f"direction peu marquée ({corr:+.2f})"))
    # orphelins
    iso = isolated_fraction(d, op)
    out.append(Finding("WARN" if iso > 0.30 else "OK", "Pixels", f"{iso:.0%} de pixels orphelins"
                       + (" — dessin bruité, regroupez en amas" if iso > 0.30 else "")))
    # lisibilité sur la case d'inventaire
    blab = rgb_to_oklab(d[boundary][:, :3].astype(float)) * 100
    slab = rgb_to_oklab(np.array(SLOT_GRAY[:3], float)) * 100
    close = float((np.linalg.norm(blab - slab, axis=1) < 12).mean()) if len(blab) else 0.0
    if close > 0.25:
        out.append(Finding("WARN", "Lisibilité", f"{close:.0%} du bord se confond avec le gris des cases (#8b8b8b)"))
    else:
        out.append(Finding("OK", "Lisibilité", "le bord se détache du fond de case"))
    out += _palette_findings(d, soft=24, hard=40)
    if it.anim is not None and it.anim.n > 1:
        out += _anim_tex_findings(it.anim, "item")
    return out


# ----------------------------------------------------------------------------- multiblocs
def analyze_multiblock(mb: MultiBlock) -> list:
    from .export import optimize_multiblock
    out = []
    v = mb.volume
    sx, sy, sz = v.shape
    nx, ny, nz = mb.blocks
    out.append(Finding("INFO", "Taille", f"{nx} x {ny} x {nz} blocs ({sx}x{sy}x{sz} voxels, {mb.res} par bloc), "
                                         f"{int(v.solid.sum())} voxels pleins"))
    if sx % mb.res or sy % mb.res or sz % mb.res:
        out.append(Finding("INFO", "Taille", "dimensions non multiples de 16 : la dernière rangée de blocs est "
                                             "partielle (normal pour 3,5 blocs de haut)"))
    comps = _components(v.solid)
    if len(comps) > 1:
        out.append(Finding("WARN", "Volume", f"{len(comps)} morceaux séparés (tailles {comps[:6]}) : "
                                             "parties flottantes ?"))
    else:
        out.append(Finding("OK", "Volume", "un seul morceau connexe"))
    out += _palette_findings(v.data[v.m_surface()])
    opt = optimize_multiblock(mb)
    st = opt.stats
    lvl = "WARN" if st["elements_max"] > 150 else "OK"
    out.append(Finding(lvl, "Export", f"{st['parts']} parties, {st['elements_total']} éléments au total "
                                      f"({st['elements_min']}–{st['elements_max']} par partie), atlas partagé "
                                      f"{st['texture']}x{st['texture']}"
                       + (" — une partie est lourde : simplifiez le détail de surface" if lvl == "WARN" else "")))
    out.append(Finding("INFO", "Export", f"miniature d'inventaire : volume ré-échantillonné "
                                         f"{'x'.join(str(n) for n in st['mini_shape'])} ({st['mini_elements']} éléments)"))
    out.append(Finding("INFO", "En jeu", f"face avant = côté NORD du volume ; /function <ns>:place/{mb.name} "
                                         "(datapack généré à l'export) pose l'objet centré sur le bloc d'exécution"))
    if mb.emissive is not None:
        out.append(Finding("INFO", "Lumière", f"{int((mb.emissive & v.solid).sum())} voxels lumineux → "
                                              f"{st.get('emissive_elements', 0)} éléments light_emission {mb.emission} "
                                              "(visibles dans le noir ; n'éclairent pas le monde sans mod)"))
    out += _clip_findings(mb, "objet")
    out += _journal(v.log)
    return out


def analyze(asset) -> list:
    if isinstance(asset, MultiBlock):
        return analyze_multiblock(asset)
    if isinstance(asset, Block):
        return analyze_block(asset)
    if isinstance(asset, Model):
        return analyze_model(asset)
    if isinstance(asset, Item):
        return analyze_item(asset)
    raise TypeError(asset)


def format_report(asset, findings: list, extra: list | None = None) -> str:
    kind = {"cube": "bloc plein 16³", "model": "modèle voxel", "sprite": "item plat",
            "multi": "objet multibloc"}[asset.kind]
    head = f"=== {asset.name} ({kind}) ==="
    lines = [head] + [f.line() for f in findings]
    if extra:
        lines += extra
    w = sum(f.level in ("WARN", "ERR") for f in findings)
    lines.append(f"--- {w} point(s) d'attention" if w else "--- rien à signaler")
    return "\n".join(lines)
