"""Encodeur PNG déterministe : mêmes pixels → mêmes octets, sur toutes les machines.

Pillow et le module `zlib` de Python compressent avec la bibliothèque zlib de la machine (zlib classique,
zlib-ng, Chromium zlib…) : à pixels identiques, les octets du PNG changent d'une machine à l'autre. Un
dépôt qui compare des fichiers générés à ceux qu'il versionne (CI « fichiers générés ») échoue alors sans
raison. Ce module écrit le PNG lui-même, compression comprise, avec numpy seulement :

- un seul bloc IDAT, chunks IHDR / IDAT / IEND, aucune métadonnée (ni date, ni gamma) ;
- filtre de ligne choisi par une règle fixe (plus petite somme des écarts absolus, égalité → plus petit
  numéro de filtre) ;
- DEFLATE en un bloc à codes de Huffman dynamiques (longueurs bornées par package-merge, égalités
  départagées par numéro de symbole) ; correspondances LZ77 cherchées à des distances fixes (pixel
  précédent, ligne précédente…) et aux 8 occurrences précédentes des mêmes 3 octets, analyse paresseuse
  comme zlib, égalité de longueur → plus petite distance.

Taille comparable à celle de Pillow ; quelques dixièmes de seconde pour un atlas de 512 × 512.
Toute modification de ce module change les octets produits : le test `test_png_reference_bytes`
(tests/test_export.py) le signale, et l'entrée du CHANGELOG doit le dire.

Les sommes de contrôle (CRC-32, Adler-32) sont des fonctions mathématiques : celles de `zlib` donnent le
même résultat partout. Le format produit se relit avec n'importe quel décodeur PNG.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

__all__ = ["encode_png", "save_png"]

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_COLOR_TYPE = {1: 0, 2: 4, 3: 2, 4: 6}          # canaux → type de couleur PNG (L, LA, RGB, RGBA)
_MODE_CHANNELS = {"L": 1, "LA": 2, "RGB": 3, "RGBA": 4}

_MAX_MATCH = 258
_MAX_DIST = 32768

# Longueurs 3..258 → (symbole 257..285, bits supplémentaires, base)
_LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115,
             131, 163, 195, 227, 258]
_LEN_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0]
_DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
              2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
_DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]


def _rev(code: np.ndarray, nbits: np.ndarray) -> np.ndarray:
    """Inverse l'ordre des `nbits` bits de poids faible (les codes de Huffman s'écrivent bit fort d'abord)."""
    out = np.zeros_like(code)
    c = code.copy()
    for k in range(int(nbits.max())):
        live = k < nbits
        out = np.where(live, (out << 1) | (c & 1), out)
        c = np.where(live, c >> 1, c)
    return out


def _code_lengths(freq: np.ndarray, limit: int) -> np.ndarray:
    """Longueurs de code de Huffman optimales bornées à `limit` bits (algorithme package-merge).
    Déterministe : les égalités de poids se départagent par numéro de symbole."""
    out = np.zeros(freq.size, np.int64)
    used = [(int(f), s) for s, f in enumerate(freq) if f > 0]
    if len(used) == 1:
        out[used[0][1]] = 1
        return out
    leaves = sorted(used)
    # Chaque élément : (poids, numéro d'ordre, symboles qu'il contient) ; le numéro rend le tri total.
    items = [(f, k, (s,)) for k, (f, s) in enumerate(leaves)]
    cur = items
    for _ in range(limit - 1):
        packs = [(cur[i][0] + cur[i + 1][0], len(items) + i, cur[i][2] + cur[i + 1][2])
                 for i in range(0, len(cur) - 1, 2)]
        cur = sorted(items + packs, key=lambda t: (t[0], t[1]))
    for _, _, syms in cur[: 2 * (len(leaves) - 1)]:
        for s in syms:
            out[s] += 1
    return out


def _canonical(lengths: np.ndarray) -> np.ndarray:
    """Codes canoniques DEFLATE (RFC 1951, 3.2.2) à partir des longueurs."""
    bl_count = np.bincount(lengths, minlength=16)
    bl_count[0] = 0
    nxt = [0] * 17
    code = 0
    for bits in range(1, 16):
        code = (code + int(bl_count[bits - 1])) << 1
        nxt[bits] = code
    out = np.zeros(lengths.size, np.int64)
    for s, ln in enumerate(lengths.tolist()):
        if ln:
            out[s] = nxt[ln]
            nxt[ln] += 1
    return out


_CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]


def _tree_header(lit_len: np.ndarray, dist_len: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Champs (valeurs, nombres de bits) de l'en-tête d'un bloc à codes dynamiques."""
    hlit = max(257, int(np.flatnonzero(lit_len).max()) + 1)
    hdist = max(1, int(np.flatnonzero(dist_len).max()) + 1)
    seq = lit_len[:hlit].tolist() + dist_len[:hdist].tolist()
    # Codage par séries des longueurs : 16 = répéter la précédente 3–6 fois, 17/18 = 3–10 / 11–138 zéros.
    ops: list[tuple[int, int, int]] = []              # (symbole, valeur suppl., bits suppl.)
    i = 0
    while i < len(seq):
        x = seq[i]
        run = 1
        while i + run < len(seq) and seq[i + run] == x:
            run += 1
        i += run
        if x == 0:
            while run >= 11:
                k = min(run, 138)
                ops.append((18, k - 11, 7))
                run -= k
            if run >= 3:
                ops.append((17, run - 3, 3))
                run = 0
            ops.extend((0, 0, 0) for _ in range(run))
        else:
            ops.append((x, 0, 0))
            run -= 1
            while run >= 3:
                k = min(run, 6)
                ops.append((16, k - 3, 2))
                run -= k
            ops.extend((x, 0, 0) for _ in range(run))
    cl_freq = np.bincount([o[0] for o in ops], minlength=19)
    cl_len = _code_lengths(cl_freq, 7)
    cl_code = _rev(_canonical(cl_len), cl_len)
    hclen = max(4, max(k + 1 for k, s in enumerate(_CL_ORDER) if cl_len[s]))
    vals = [hlit - 257, hdist - 1, hclen - 4] + [int(cl_len[s]) for s in _CL_ORDER[:hclen]]
    bits = [5, 5, 4] + [3] * hclen
    for s, ev, eb in ops:
        vals += [int(cl_code[s]), ev]
        bits += [int(cl_len[s]), eb]
    return np.array(vals, np.int64), np.array(bits, np.int64)

# Tables directes : longueur → symbole, distance → symbole
_LEN_SYM = np.zeros(_MAX_MATCH + 1, np.int64)
for _i, _b in enumerate(_LEN_BASE):
    _LEN_SYM[_b:] = _i
_DIST_SYM = np.zeros(_MAX_DIST + 1, np.int64)
for _i, _b in enumerate(_DIST_BASE):
    _DIST_SYM[_b:] = _i
_LEN_BASE_A = np.array(_LEN_BASE, np.int64)
_LEN_EXTRA_A = np.array(_LEN_EXTRA, np.int64)
_DIST_BASE_A = np.array(_DIST_BASE, np.int64)
_DIST_EXTRA_A = np.array(_DIST_EXTRA, np.int64)


def _pixels(img) -> np.ndarray:
    """Tableau (h, w, c) uint8, c ∈ {1, 2, 3, 4}, depuis un tableau numpy ou une image Pillow."""
    if not isinstance(img, np.ndarray):
        mode = getattr(img, "mode", None)
        if mode is None:
            raise TypeError(f"image attendue (tableau numpy ou image Pillow), reçu {type(img).__name__}")
        if mode not in _MODE_CHANNELS:
            img = img.convert("RGBA")
        img = np.asarray(img)
    a = np.asarray(img)
    if a.dtype != np.uint8:
        if a.dtype == bool:
            a = a.astype(np.uint8) * 255
        else:
            a = a.astype(np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3 or a.shape[2] not in _COLOR_TYPE or a.shape[0] < 1 or a.shape[1] < 1:
        raise ValueError(f"image PNG : forme (h, w) ou (h, w, 1|2|3|4) attendue, reçu {a.shape}")
    return np.ascontiguousarray(a)


def _filter(a: np.ndarray) -> np.ndarray:
    """Lignes filtrées, préfixées de leur type de filtre : tableau (h, 1 + w*c) uint8, aplati."""
    h, w, c = a.shape
    x = a.reshape(h, w * c).astype(np.int16)
    left = np.zeros_like(x)
    left[:, c:] = x[:, :-c]
    up = np.zeros_like(x)
    up[1:] = x[:-1]
    ul = np.zeros_like(x)
    ul[1:, c:] = x[:-1, :-c]
    p = left + up - ul
    pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - ul)
    paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, ul))
    cand = np.stack([x, x - left, x - up, x - (left + up) // 2, x - paeth]) & 0xFF   # (5, h, w*c)
    signed = np.where(cand > 127, 256 - cand, cand)
    kind = np.argmin(signed.sum(axis=2), axis=0)                                     # premier minimum
    rows = cand[kind, np.arange(h)]
    return np.concatenate([kind[:, None], rows], axis=1).astype(np.uint8).ravel()


def _run_lengths(eq: np.ndarray) -> np.ndarray:
    """r[i] = nombre de vrais consécutifs à partir de i."""
    n = eq.size
    idx = np.arange(n, dtype=np.int64)
    stop = np.where(eq, n, idx)                       # premier faux à partir de i
    stop = np.minimum.accumulate(stop[::-1])[::-1]
    return stop - idx


_CHAIN = 8                                            # occurrences précédentes essayées par position
_NICE = 32                                            # longueur jugée suffisante : on ne cherche pas mieux


def _hash_matches(data: np.ndarray, best_len: np.ndarray, best_dist: np.ndarray) -> None:
    """Complète (en place) les meilleures correspondances par les `_CHAIN` occurrences précédentes des
    3 mêmes octets. Égalité de longueur → plus petite distance (la plus récente l'emporte)."""
    n = data.size
    if n < 4:
        return
    d = data.astype(np.int64)
    key = (d[:-2] << 16) | (d[1:-1] << 8) | d[2:]             # positions 0 .. n-3
    m = key.size
    order = np.argsort(key, kind="stable")                    # même clé → positions croissantes
    prev = np.full(m, -1, np.int64)
    same = key[order[1:]] == key[order[:-1]]
    prev[order[1:][same]] = order[:-1][same]
    pos = np.arange(m, dtype=np.int64)
    cand = prev.copy()
    for _ in range(_CHAIN):
        dist = pos - cand
        ok = (cand >= 0) & (dist <= _MAX_DIST) & (best_len[:m] < _NICE)
        if not ok.any():
            break
        idx = pos[ok]
        dd = dist[ok]
        ln = np.full(idx.size, 3, np.int64)
        live = np.arange(idx.size)
        while live.size:
            k = ln[live]
            j = idx[live] + k
            go = (k < _MAX_MATCH) & (j < n)
            go[go] = data[j[go]] == data[j[go] - dd[live][go]]
            live = live[go]
            ln[live] += 1
        better = (ln > best_len[idx]) | ((ln == best_len[idx]) & (dd < best_dist[idx]))
        best_len[idx[better]] = ln[better]
        best_dist[idx[better]] = dd[better]
        cand = np.where(cand >= 0, prev[np.maximum(cand, 0)], -1)


def _deflate(data: np.ndarray, distances: list[int]) -> bytes:
    """Flux DEFLATE (un bloc à codes fixes) de `data`, correspondances aux distances données."""
    n = data.size
    best_len = np.zeros(n, np.int64)
    best_dist = np.zeros(n, np.int64)
    for d in distances:                               # ordre croissant : égalité → plus petite distance
        if d >= n:
            break
        r = np.zeros(n, np.int64)
        r[d:] = _run_lengths(data[d:] == data[:-d])
        r = np.minimum(r, _MAX_MATCH)
        better = r > best_len
        best_len = np.where(better, r, best_len)
        best_dist = np.where(better, d, best_dist)
    _hash_matches(data, best_len, best_dist)
    usable = best_len >= 3
    # Prochaine position (≥ i) où une correspondance commence ; n s'il n'y en a plus.
    nxt = np.where(usable, np.arange(n), n)
    nxt = np.minimum.accumulate(nxt[::-1])[::-1] if n else nxt

    lit_runs = []                                     # (début, fin) de littéraux
    m_pos = []                                        # positions des correspondances
    bl, nx = best_len.tolist(), nxt.tolist()
    i = 0
    lit_start = None
    while i < n:
        j = nx[i]
        if j > i:                                     # série de littéraux jusqu'à la prochaine correspondance
            if lit_start is None:
                lit_start = i
            i = j
            continue
        # Analyse paresseuse : si la position suivante offre mieux, i reste un littéral.
        if i + 1 < n and bl[i + 1] > bl[i]:
            if lit_start is None:
                lit_start = i
            i += 1
            continue
        if lit_start is not None:
            lit_runs.append((lit_start, i))
            lit_start = None
        m_pos.append(i)
        i += bl[i]
    if lit_start is not None:
        lit_runs.append((lit_start, n))

    # Jetons dans l'ordre : chaque jeton = (position de départ, est-ce une correspondance)
    starts = np.array([s for s, _ in lit_runs] + m_pos, np.int64)
    is_match = np.array([False] * len(lit_runs) + [True] * len(m_pos))
    order = np.argsort(starts, kind="stable")
    starts, is_match = starts[order], is_match[order]

    # Développe les séries de littéraux en un jeton par octet.
    ends = np.array([e for _, e in lit_runs] + [0] * len(m_pos), np.int64)[order]
    count = np.where(is_match, 1, ends - starts)
    tok = np.repeat(np.arange(starts.size), count)
    off = np.arange(tok.size) - np.repeat(np.cumsum(count) - count, count)
    pos = starts[tok] + np.where(is_match[tok], 0, off)
    mt = is_match[tok]

    # Quatre champs par jeton : symbole lit/long, bits suppl. de longueur, symbole distance, bits suppl.
    lit = data[pos].astype(np.int64)
    length = best_len[pos]
    dist = best_dist[pos]
    lsym = _LEN_SYM[length]
    dsym = _DIST_SYM[dist]
    sym = np.where(mt, 257 + lsym, lit)

    # Codes de Huffman propres au bloc (BTYPE=10), construits de façon déterministe.
    lit_freq = np.bincount(np.append(sym, 256), minlength=286)
    dist_freq = np.bincount(dsym[mt], minlength=30)
    if not dist_freq.any():
        dist_freq[0] = 1                              # au moins un code de distance (lu par tous les décodeurs)
    lit_len = _code_lengths(lit_freq, 15)
    dist_len = _code_lengths(dist_freq, 15)
    lit_code = _rev(_canonical(lit_len), lit_len)
    dist_code = _rev(_canonical(dist_len), dist_len)
    head_v, head_b = _tree_header(lit_len, dist_len)

    v = np.stack([
        lit_code[sym],
        np.where(mt, length - _LEN_BASE_A[lsym], 0),
        np.where(mt, dist_code[dsym], 0),
        np.where(mt, dist - _DIST_BASE_A[dsym], 0),
    ], axis=1)
    b = np.stack([
        lit_len[sym],
        np.where(mt, _LEN_EXTRA_A[lsym], 0),
        np.where(mt, dist_len[dsym], 0),
        np.where(mt, _DIST_EXTRA_A[dsym], 0),
    ], axis=1)
    # En-tête du bloc (BFINAL=1, BTYPE=10), arbres, jetons, symbole de fin (256).
    vals = np.concatenate([[1, 2], head_v, v.ravel(), [lit_code[256]]])
    bits = np.concatenate([[1, 2], head_b, b.ravel(), [lit_len[256]]])
    keep = bits > 0
    vals, bits = vals[keep], bits[keep]
    field = np.repeat(np.arange(vals.size), bits)
    shift = np.arange(field.size) - np.repeat(np.cumsum(bits) - bits, bits)
    stream = ((vals[field] >> shift) & 1).astype(np.uint8)
    return np.packbits(stream, bitorder="little").tobytes()


def _zlib(raw: np.ndarray, bpp: int, stride: int) -> bytes:
    cands = {1, 2, 3, bpp, 2 * bpp, 3 * bpp, 4 * bpp, 8 * bpp, stride, 2 * stride, 4 * stride}
    dists = sorted(d for d in cands if 1 <= d <= _MAX_DIST)
    body = _deflate(raw, dists)
    return b"\x78\x01" + body + struct.pack(">I", zlib.adler32(raw.tobytes()) & 0xFFFFFFFF)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(img) -> bytes:
    """Octets PNG de `img` (tableau (h, w[, c]) uint8 ou image Pillow), identiques sur toutes les machines."""
    a = _pixels(img)
    h, w, c = a.shape
    raw = _filter(a)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, _COLOR_TYPE[c], 0, 0, 0)
    return _PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", _zlib(raw, c, 1 + w * c)) + _chunk(b"IEND", b"")


def save_png(path, img) -> None:
    """Écrit `img` en PNG déterministe (voir `encode_png`)."""
    Path(path).write_bytes(encode_png(img))
