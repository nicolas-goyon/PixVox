"""pixvox.vanilla — textures de blocs du jeu, en cache local, pour juger un asset à côté du vanilla (#24).

`pixvox vanilla --mc 26.3` (ou `fetch("26.3")`) télécharge le jar client de cette version depuis les
serveurs de Mojang (manifeste piston-meta, empreinte SHA-1 vérifiée), en extrait les textures de blocs
(`assets/minecraft/textures/block/*.png`) dans un cache de l'utilisateur, puis supprime le jar. Ensuite
tout fonctionne sans réseau : analyse (couleur moyenne comparée aux matériaux vanilla proches), rangée
« dans le monde » de la planche (l'asset posé entre des blocs du jeu), `ramp_from_vanilla("stone")`.

Droits : ces textures appartiennent à Mojang. Elles restent dans le cache local (hors du dépôt) et ne
sont jamais copiées dans un pack, un mod ou un livrable ; seules les planches de revue, locales, les
montrent. Cache : $PIXVOX_CACHE/vanilla, sinon le dossier de cache de l'utilisateur (~/.cache/pixvox,
%LOCALAPPDATA%\\pixvox, ~/Library/Caches/pixvox).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from .color import Ramp, rgb_to_oklab

__all__ = ["VanillaUnavailable", "fetch", "available", "texture", "texture_names", "materials", "ramp_from_vanilla",
           "nearest_materials", "material_delta", "block_faces", "cache_dir", "MANIFEST", "VERSIONS"]

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
VERSIONS = ("26.3", "1.21.1")                 # versions visées par pixvox ; --mc accepte aussi une autre
DEFAULT_MC = "26.3"
_PREFIX = "assets/minecraft/textures/block/"
_MODELS = "assets/minecraft/models/block/"
# Matériaux : textures que le jeu pose sur un cube plein (modèles de ces parents), sauf les gris teintés
_CUBE_PARENTS = {"block/cube_all", "block/cube_column", "block/cube_column_horizontal", "block/cube_bottom_top"}
_TINTED_GREY = re.compile(r"(grass|leaves|fern|vine|lily_pad|sugar_cane|_overlay)")


class VanillaUnavailable(RuntimeError):
    """Textures vanilla absentes du cache et téléchargement impossible (code de sortie 2)."""


def _user_cache() -> Path:
    if os.environ.get("PIXVOX_CACHE"):
        return Path(os.environ["PIXVOX_CACHE"])
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "pixvox"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "pixvox"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pixvox"


def cache_dir(mc: str = DEFAULT_MC) -> Path:
    """Dossier du cache des textures de la version `mc`."""
    if not re.fullmatch(r"[0-9a-z._-]+", mc):
        raise ValueError(f"version {mc!r} invalide")
    return _user_cache() / "vanilla" / mc


def available(mc: str = DEFAULT_MC) -> bool:
    """Vrai si les textures de la version `mc` sont déjà dans le cache (aucun accès réseau)."""
    return (cache_dir(mc) / "meta.json").is_file()


def cached_version(prefer=VERSIONS) -> str | None:
    """Première version de `prefer` présente dans le cache, sinon None."""
    return next((v for v in prefer if available(v)), None)


def _get(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pixvox"})
    with urllib.request.urlopen(req, timeout=timeout) as r:                    # noqa: S310 - URL de Mojang
        return r.read()


def fetch(mc: str = DEFAULT_MC, *, force: bool = False, manifest_url: str | None = None, log=None) -> dict:
    """Télécharge (si besoin) le jar client de `mc`, vérifie son SHA-1 et met en cache ses textures de blocs.
    Renvoie {mc, cache, textures, sha1, downloaded}. VanillaUnavailable si le réseau ou la version manque."""
    d = cache_dir(mc)
    if available(mc) and (d / "ids.json").is_file() and not force:       # cache d'avant 0.5.1 : complété
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return {**meta, "cache": d, "downloaded": False}
    say = log or (lambda *_: None)
    manifest_url = manifest_url or os.environ.get("PIXVOX_VANILLA_MANIFEST", MANIFEST)   # miroir, tests
    try:
        manifest = json.loads(_get(manifest_url))
        entry = next((v for v in manifest.get("versions", []) if v.get("id") == mc), None)
        if entry is None:
            raise VanillaUnavailable(f"version {mc!r} inconnue du manifeste de Mojang")
        client = json.loads(_get(entry["url"]))["downloads"]["client"]
        say(f"[vanilla] téléchargement du jar client {mc} ({client.get('size', 0) // 1_000_000} Mo)…")
        data = _get(client["url"], timeout=600.0)
    except VanillaUnavailable:
        raise
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        raise VanillaUnavailable(f"textures vanilla {mc} absentes du cache et téléchargement impossible ({e}) ; "
                                 "relancer `pixvox vanilla` avec un accès réseau") from e
    sha1 = hashlib.sha1(data).hexdigest()                                      # noqa: S324 - empreinte publiée
    if sha1 != client["sha1"]:
        raise VanillaUnavailable(f"jar client {mc} corrompu (SHA-1 {sha1} au lieu de {client['sha1']})")
    tmp = Path(tempfile.mkdtemp(prefix="pixvox_vanilla_"))
    try:
        out = tmp / "textures"
        out.mkdir()
        n = 0
        materials = set()
        ids = {"blocks": set(), "items": set()}
        with zipfile.ZipFile(_bytes_file(tmp, data)) as z:
            for name in z.namelist():
                if name.startswith(_PREFIX) and name.endswith(".png") and "/" not in name[len(_PREFIX):]:
                    (out / Path(name).name).write_bytes(z.read(name))
                    n += 1
                elif name.startswith(_MODELS) and name.endswith(".json"):
                    materials |= _cube_textures(z.read(name))
                for kind, prefix in (("blocks", "assets/minecraft/blockstates/"), ("items", "assets/minecraft/items/"),
                                     ("items", "assets/minecraft/models/item/")):      # items/ : 1.21.4+ ; 1.21.1
                    if name.startswith(prefix) and name.endswith(".json") and "/" not in name[len(prefix):]:
                        ids[kind].add(Path(name).stem)
        if not n:
            raise VanillaUnavailable(f"aucune texture de bloc dans le jar client {mc}")
        materials = sorted(m for m in materials if (out / f"{m}.png").is_file() and not _TINTED_GREY.search(m))
        meta = {"mc": mc, "sha1": sha1, "textures": n, "materials": len(materials), "source": client["url"]}
        (tmp / "materials.txt").write_text("\n".join(materials) + "\n", encoding="utf-8")
        (tmp / "ids.json").write_text(json.dumps({k: sorted(v) for k, v in ids.items()}) + "\n", encoding="utf-8")
        (tmp / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        (tmp / "jar").unlink()
        if d.exists():
            shutil.rmtree(d)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(d))                                          # cache complet ou rien
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say(f"[vanilla] {n} textures de blocs {mc} en cache : {d}")
    return {**meta, "cache": d, "downloaded": True}


def _cube_textures(raw: bytes) -> set:
    """Textures d'un modèle de bloc vanilla dont le parent est un cube plein (cube_all, cube_column…)."""
    try:
        m = json.loads(raw)
    except ValueError:
        return set()
    if str(m.get("parent", "")).removeprefix("minecraft:") not in _CUBE_PARENTS:
        return set()
    return {str(t).removeprefix("minecraft:").removeprefix("block/") for t in (m.get("textures") or {}).values()
            if "block/" in str(t)}


def _bytes_file(tmp: Path, data: bytes) -> Path:
    p = tmp / "jar"
    p.write_bytes(data)
    return p


def _require(mc: str | None) -> str:
    mc = mc or cached_version()
    if mc is None or not available(mc):
        raise VanillaUnavailable(f"textures vanilla {mc or DEFAULT_MC} absentes du cache : lancer "
                                 f"`pixvox vanilla --mc {mc or DEFAULT_MC}` (une fois, avec un accès réseau)")
    return mc


def texture_names(mc: str | None = None) -> list:
    """Noms des textures de blocs en cache (sans .png), triés."""
    return sorted(p.stem for p in (cache_dir(_require(mc)) / "textures").glob("*.png"))


def texture(name: str, mc: str | None = None) -> np.ndarray:
    """Texture vanilla (h, w, 4) uint8 ; première image d'une texture animée (bande verticale)."""
    p = cache_dir(_require(mc)) / "textures" / f"{name}.png"
    if not p.is_file():
        raise KeyError(f"texture vanilla {name!r} introuvable (voir texture_names())")
    with Image.open(p) as im:
        a = np.asarray(im.convert("RGBA"))
    return a[: a.shape[1]].copy()


def block_faces(name: str, mc: str | None = None) -> dict:
    """{face: texture} d'un bloc vanilla simple : <nom>, <nom>_top / _bottom / _side s'ils existent."""
    names = set(texture_names(mc))
    side = name if name in names else f"{name}_side"
    top = f"{name}_top" if f"{name}_top" in names else side
    bottom = f"{name}_bottom" if f"{name}_bottom" in names else top
    return {"up": texture(top, mc), "down": texture(bottom, mc),
            **{f: texture(side, mc) for f in ("north", "south", "west", "east")}}


def ramp_from_vanilla(name: str, n: int = 5, mc: str | None = None) -> Ramp:
    """Rampe de `n` couleurs tirée d'une texture du jeu (« stone », « oak_planks »…) : couleurs opaques triées
    par clarté OKLab, prises aux quantiles pondérés par leur fréquence. Pour partir d'une palette qui s'accorde."""
    a = texture(name, mc)
    px = a[a[..., 3] > 0][:, :4]
    if not len(px):
        raise ValueError(f"texture vanilla {name!r} entièrement transparente")
    cols, counts = np.unique(px, axis=0, return_counts=True)
    L = rgb_to_oklab(cols[:, :3])[:, 0]
    order = np.argsort(L, kind="stable")
    cols, counts = cols[order], counts[order]
    cum = np.cumsum(counts) / counts.sum()
    idx = [min(int(np.searchsorted(cum, q)), len(cols) - 1) for q in np.linspace(0.06, 0.94, n)]
    for i in range(1, len(idx)):                       # couleurs distinctes, toujours de plus en plus claires
        if idx[i] <= idx[i - 1]:
            idx[i] = min(idx[i - 1] + 1, len(cols) - 1)
    picks = [cols[i] for i in dict.fromkeys(idx)]
    return Ramp([tuple(int(x) for x in c[:3]) + (255,) for c in picks])


def known_ids(mc: str | None = None):
    """{"mc", "blocks", "items"} : identifiants (sans « minecraft: ») des blocs et des items du jar en cache ;
    None si le cache n'a pas cette liste (fait avant pixvox 0.5.1 : relancer `pixvox vanilla`)."""
    mc = _require(mc)
    f = cache_dir(mc) / "ids.json"
    if not f.is_file():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return {"mc": mc, "blocks": set(d["blocks"]), "items": set(d["items"])}


def materials(mc: str | None = None) -> list:
    """Matériaux vanilla : textures posées sur un cube plein par le jeu (pierre, planches, minerais…)."""
    return (cache_dir(_require(mc)) / "materials.txt").read_text(encoding="utf-8").split()


def _stats(mc: str) -> dict:
    """{nom: (L, a, b, chroma)} moyens des matériaux opaques, calculés une fois puis gardés en cache."""
    d = cache_dir(mc)
    f = d / "stats.json"
    if f.is_file():
        return {k: tuple(v) for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
    out = {}
    for name in materials(mc):
        a = texture(name, mc)
        if a.shape[0] != a.shape[1] or (a[..., 3] < 255).mean() > 0.01:
            continue
        lab = rgb_to_oklab(a[..., :3].reshape(-1, 3)).mean(axis=0)
        out[name] = (float(lab[0]), float(lab[1]), float(lab[2]), float(np.hypot(lab[1], lab[2])))
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def nearest_materials(colors: np.ndarray, mc: str | None = None, k: int = 3) -> list:
    """Matériaux vanilla dont la couleur moyenne est la plus proche de celle de `colors` ((n, 3|4) uint8) :
    [{name, delta_e, lighter, more_saturated}] ; lighter / more_saturated : écarts relatifs (0.12 = +12 %)."""
    mc = _require(mc)
    lab = rgb_to_oklab(np.asarray(colors)[:, :3]).mean(axis=0)
    C = float(np.hypot(lab[1], lab[2]))
    stats = _stats(mc)
    scored = sorted(((float(np.linalg.norm(lab - np.array(s[:3]))) * 100, name, s) for name, s in stats.items()),
                    key=lambda t: (t[0], t[1]))
    return [{"name": name, "delta_e": round(de, 1), "lighter": round(float((lab[0] - s[0]) / max(s[0], 1e-6)), 3),
             "more_saturated": round(float((C - s[3]) / max(s[3], 0.03)), 3)} for de, name, s in scored[:k]]


def material_delta(colors: np.ndarray, name: str, mc: str | None = None) -> dict:
    """Écarts de `colors` à la texture vanilla `name` : {name, delta_e, lighter, more_saturated} (relatifs)."""
    a = texture(name, mc)
    ref = rgb_to_oklab(a[a[..., 3] > 0][:, :3]).mean(axis=0)
    lab = rgb_to_oklab(np.asarray(colors)[:, :3]).mean(axis=0)
    C, Cr = float(np.hypot(lab[1], lab[2])), float(np.hypot(ref[1], ref[2]))
    return {"name": name, "delta_e": round(float(np.linalg.norm(lab - ref)) * 100, 1),
            "lighter": round(float((lab[0] - ref[0]) / max(ref[0], 1e-6)), 3),
            "more_saturated": round((C - Cr) / max(Cr, 0.03), 3)}
