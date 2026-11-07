"""Textures vanilla en cache (#24) : téléchargement depuis un faux serveur Mojang local (manifeste, version, jar
factice), hors ligne ensuite, refus, rampe, analyse et rangée « dans le monde ». Aucun jar de Mojang n'est
utilisé ; un test d'intégration facultatif lit le vrai manifeste (sauté sans réseau)."""
import hashlib
import io
import json
import os
import threading
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from testkit import tmpdir


def _png(arr) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.asarray(arr, np.uint8), "RGBA").save(buf, "PNG")
    return buf.getvalue()


def _tex(rgb, seed, h=16):
    rng = np.random.default_rng(seed)
    a = np.zeros((h, 16, 4), np.uint8)
    a[..., :3] = np.clip(np.array(rgb) + rng.integers(-12, 13, (h, 16, 1)), 0, 255)
    a[..., 3] = 255
    return a


def _fake_jar() -> bytes:
    """Jar client factice : textures de blocs, modèles (cubes pleins ou non), et un fichier hors sujet."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        t = "assets/minecraft/textures/block/"
        z.writestr(t + "stone.png", _png(_tex((125, 125, 125), 1)))
        z.writestr(t + "oak_planks.png", _png(_tex((162, 130, 78), 2)))
        z.writestr(t + "oak_log.png", _png(_tex((109, 85, 50), 3)))
        z.writestr(t + "oak_log_top.png", _png(_tex((150, 120, 70), 4)))
        z.writestr(t + "grass_block_top.png", _png(_tex((150, 150, 150), 5)))         # gris teinté : exclu
        z.writestr(t + "magma.png", _png(_tex((160, 60, 20), 6, h=48)))               # animée : 3 images
        z.writestr(t + "red_bed_head.png", _png(_tex((160, 30, 30), 7)))              # pas un cube : exclu
        z.writestr(t + "sub/deep.png", _png(_tex((0, 0, 0), 8)))                     # sous-dossier : ignoré
        m = "assets/minecraft/models/block/"
        z.writestr(m + "stone.json", json.dumps({"parent": "minecraft:block/cube_all",
                                                 "textures": {"all": "minecraft:block/stone"}}))
        z.writestr(m + "oak_planks.json", json.dumps({"parent": "block/cube_all",
                                                      "textures": {"all": "block/oak_planks"}}))
        z.writestr(m + "oak_log.json", json.dumps({"parent": "block/cube_column", "textures": {
            "end": "block/oak_log_top", "side": "block/oak_log"}}))
        z.writestr(m + "magma_block.json", json.dumps({"parent": "block/cube_all", "textures": {"all": "block/magma"}}))
        z.writestr(m + "grass_block.json", json.dumps({"parent": "block/cube_bottom_top", "textures": {
            "top": "block/grass_block_top", "side": "block/stone", "bottom": "block/stone"}}))
        z.writestr(m + "red_bed.json", json.dumps({"parent": "block/bed", "textures": {"bed": "block/red_bed_head"}}))
        z.writestr("data/minecraft/recipe/x.json", "{}")
    return buf.getvalue()


@contextmanager
def fake_mojang(jar: bytes, sha1: str | None = None, versions=("26.3",)):
    """Serveur HTTP local qui imite piston-meta : manifeste -> JSON de version -> jar client."""
    routes = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - API de http.server
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            if body is not None:
                self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    routes["/manifest.json"] = json.dumps({"versions": [{"id": v, "url": f"{base}/{v}.json"} for v in versions]}).encode()
    for v in versions:
        routes[f"/{v}.json"] = json.dumps({"downloads": {"client": {
            "url": f"{base}/client.jar", "sha1": sha1 or hashlib.sha1(jar).hexdigest(), "size": len(jar)}}}).encode()
    routes["/client.jar"] = jar
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    old = {k: os.environ.get(k) for k in ("no_proxy", "NO_PROXY")}
    os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    try:
        yield f"{base}/manifest.json"
    finally:
        srv.shutdown()
        srv.server_close()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def cache_in(path):
    old = os.environ.get("PIXVOX_CACHE")
    os.environ["PIXVOX_CACHE"] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PIXVOX_CACHE", None)
        else:
            os.environ["PIXVOX_CACHE"] = old


def _raises(exc, text: str, fn) -> None:
    try:
        fn()
    except exc as e:
        assert text in str(e), str(e)
    else:
        raise AssertionError(f"{exc.__name__} attendue ({text})")


def test_fetch_caches_block_textures_then_works_offline():
    from pixvox import vanilla as V
    jar = _fake_jar()
    with tmpdir() as tmp, cache_in(tmp / "cache"):
        assert not V.available("26.3") and V.cached_version() is None
        with fake_mojang(jar) as url:
            info = V.fetch("26.3", manifest_url=url)
        assert info["downloaded"] and info["textures"] == 7 and info["sha1"] == hashlib.sha1(jar).hexdigest()
        d = V.cache_dir("26.3")
        assert d.is_relative_to(tmp / "cache") and not (d / "jar").exists()           # le jar n'est pas gardé
        assert V.materials("26.3") == ["magma", "oak_log", "oak_log_top", "oak_planks", "stone"]
        assert "red_bed_head" in V.texture_names() and "deep" not in V.texture_names()
        assert V.texture("magma").shape == (16, 16, 4)                                  # 1re image d'une bande
        faces = V.block_faces("oak_log")
        assert np.array_equal(faces["up"], V.texture("oak_log_top")) and np.array_equal(faces["north"], V.texture("oak_log"))
        # hors ligne : le cache suffit, aucun accès réseau
        again = V.fetch("26.3", manifest_url="http://127.0.0.1:9/inaccessible")
        assert not again["downloaded"] and V.cached_version() == "26.3"
        r = V.ramp_from_vanilla("stone", n=5)
        assert len(set(r)) == len(r) >= 3
        L = [sum(c[:3]) for c in r]
        assert L == sorted(L)
        near = V.nearest_materials(V.texture("oak_planks").reshape(-1, 4), k=2)
        assert near[0]["name"] == "oak_planks" and near[0]["delta_e"] == 0


def test_fetch_refusals_leave_no_cache():
    from pixvox import vanilla as V
    jar = _fake_jar()
    with tmpdir() as tmp, cache_in(tmp / "cache"):
        with fake_mojang(jar, sha1="0" * 40) as url:
            _raises(V.VanillaUnavailable, "corrompu", lambda: V.fetch("26.3", manifest_url=url))
        with fake_mojang(jar) as url:
            _raises(V.VanillaUnavailable, "inconnue", lambda: V.fetch("9.9", manifest_url=url))
        _raises(V.VanillaUnavailable, "téléchargement impossible",
                lambda: V.fetch("26.3", manifest_url="http://127.0.0.1:9/inaccessible"))
        assert not V.available("26.3")
        _raises(V.VanillaUnavailable, "pixvox vanilla", lambda: V.texture("stone"))
        _raises(ValueError, "invalide", lambda: V.cache_dir("../x"))


def test_vanilla_analysis_review_row_and_cli():
    from pixvox import Block, Item, Sprite, Volume, ramp
    from pixvox.analyze import analyze
    from pixvox.review import review_data
    from test_cli import _cli
    grey = Volume(16)
    grey.noise(ramp("#7f7f7f", 4, spread=0.12, hue_shift=0, tint=0), cells=4, seed=1)
    loud = Volume(16, fill="#3fd0c8")                                      # cyan franc : bien plus saturé
    with tmpdir() as tmp, cache_in(tmp / "cache"):
        assert not [f for f in analyze(Block("g", grey)) if f.topic == "Vanilla"]   # cache vide : rien
        os.environ["PIXVOX_VANILLA_MANIFEST"] = "http://127.0.0.1:9/inaccessible"     # pas de réseau : code 2
        try:
            rc, data = _cli("vanilla", "--mc", "26.3", cwd=tmp)
        finally:
            del os.environ["PIXVOX_VANILLA_MANIFEST"]
        assert rc == 2 and data["errors"][0]["type"] == "environment", data
        size_without = review_data(Block("g", grey), tmp / "a")["sheet"]
        with fake_mojang(_fake_jar()) as url:
            os.environ["PIXVOX_VANILLA_MANIFEST"] = url
            try:
                rc, data = _cli("vanilla", cwd=tmp)
            finally:
                del os.environ["PIXVOX_VANILLA_MANIFEST"]
        assert rc == 0 and data["downloaded"] and data["textures"] == 7 and data["materials"] == 5, data
        f = [x for x in analyze(Block("g", grey)) if x.topic == "Vanilla"]
        assert f[0].level == "INFO" and "stone" in f[0].msg and any(x.level == "OK" for x in f)
        f = [x for x in analyze(Block("loud", loud), neighbors=["stone"]) if x.topic == "Vanilla"]
        assert any(x.level == "WARN" and "plus saturé" in x.msg and "stone" in x.msg for x in f), f
        assert not [x for x in analyze(Item("i", Sprite(16))) if x.topic == "Vanilla"]
        from PIL import Image
        r = review_data(Block("g", grey), tmp / "b", neighbors=["stone", "oak_log"])
        assert Image.open(r["sheet"]).height > Image.open(size_without).height       # rangée « dans le monde »


def test_mojang_manifest_lists_pixvox_versions():
    """Intégration (réseau) : les versions visées par pixvox existent dans le vrai manifeste de Mojang."""
    import unittest
    import urllib.request

    from pixvox import vanilla as V
    try:
        with urllib.request.urlopen(V.MANIFEST, timeout=10) as r:                    # noqa: S310
            manifest = json.loads(r.read())
    except OSError as e:
        raise unittest.SkipTest(f"pas de réseau ({e})") from e
    ids = {v["id"]: v["url"] for v in manifest["versions"]}
    for mc in V.VERSIONS:
        assert mc in ids, mc
