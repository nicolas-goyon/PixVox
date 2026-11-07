"""Fondations : couleurs, sprites, volumes (peinture des faces, générateurs, résolution)."""
import numpy as np

from pixvox import FACES, Sprite, Volume, delta_e, ramp
from testkit import design_shape


def test_paint_face_roundtrip():
    v = Volume(16, fill="#808080")
    for i, f in enumerate(FACES):
        s = Sprite(16)
        s.noise(ramp(["#aa3333", "#33aa33", "#3333aa", "#aaaa33", "#aa33aa", "#33aaaa"][i], 4), seed=i)
        v.paint_face(f, s)
        assert np.array_equal(v.face(f).data, s.data), f   # dernier peint : identique au sprite
    fresh = Volume(16, fill="#808080")
    s = Sprite(16)
    s.rect(2, 2, 13, 13, "#ff0000")
    fresh.paint_face("north", s)
    op = s.data[..., 3] > 0
    assert np.array_equal(fresh.face("north").data[op], s.data[op])
    assert (fresh.face("north").data[~op] == (128, 128, 128, 255)).all()   # transparent = non peint


def test_edge_voxel_has_one_color_on_both_faces():
    """Le principe de pixvox : le voxel d'arête appartient aux deux faces, avec UNE seule couleur."""
    v = Volume(16, fill="#808080")
    v.set(v.m_box(15, 15, 0, 15, 15, 0), "#ff0000")          # coin haut, est, nord
    up, north, east = v.face("up").data, v.face("north").data, v.face("east").data
    red = (255, 0, 0, 255)
    assert tuple(up[0, 15]) == red          # dessus : x croissant à droite, nord en haut
    assert tuple(north[0, 0]) == red        # nord : est à gauche, haut en haut
    assert tuple(east[0, 15]) == red        # est : sud à gauche -> nord à droite


def test_keyword_only_generators_and_ascii_rows():
    v = Volume(16)
    for call in (lambda: v.cells(ramp("#777777"), 12, 3), lambda: v.blobs(ramp("#33aaaa"), 5, (1.5, 2.3)),
                 lambda: v.noise(ramp("#777777"), 4, 2), lambda: v.m_noise(0.5, 4, 2, 7)):
        try:
            call()
            raise AssertionError("argument positionnel accepté")
        except TypeError:
            pass
    try:
        Sprite.from_ascii("..o.\n..o..\n", {"o": "#000"})
        raise AssertionError("lignes de longueurs différentes acceptées")
    except ValueError:
        pass
    joints = Volume(16).cells(ramp("#777777"), count=10, seed=1)
    assert joints.dtype == bool and 0 < joints.mean() < 0.6


def test_ramp_is_continuous_for_greys():
    a, b = ramp("#8a8680", 5), ramp("#8b857c", 5)
    assert max(delta_e(x, y) for x, y in zip(a, b)) < 6


def test_design_units_give_the_same_object_at_any_resolution():
    v16, v32 = design_shape(16), design_shape(32)
    assert v16.shape == (24, 32, 12) and v32.shape == (48, 64, 24)
    f16, f32 = v16.solid.mean(), v32.solid.mean()
    assert abs(f16 - f32) / f16 < 0.15, (f16, f32)                     # même volume relatif
    assert design_shape(16, scale=0.5).shape == (12, 16, 6)             # figurine moitié plus petite


def test_resample_majority_and_thin_parts():
    v = Volume(16)
    v.set(v.m_box(0, 0, 0, 15, 7, 15), "#ff0000")
    v.set(v.m_box(0, 8, 0, 15, 15, 15), "#0000ff")
    v.set(v.m_box(0, 0, 0, 0, 15, 15), "#00ff00")                      # couche fine d'un voxel
    r = v.resample(factor=0.5)
    assert r.shape == (8, 8, 8) and r.res == 8
    assert tuple(r.data[4, 1, 4]) == (255, 0, 0, 255) and tuple(r.data[4, 6, 4]) == (0, 0, 255, 255)
    q = v.resample(factor=0.25, prefer_surface=False)                    # cellule x=0 : 1/4 vert, 3/4 rouge
    assert tuple(q.data[0, 0, 1]) == (255, 0, 0, 255)                    # couleur minoritaire absorbée
    q = v.resample(factor=0.25)                                          # défaut : la peau visible l'emporte
    assert tuple(q.data[0, 0, 1]) == (0, 255, 0, 255)
    up = r.resample((16, 16, 16))
    assert up.shape == (16, 16, 16) and tuple(up.data[9, 3, 9]) == (255, 0, 0, 255)
    # min_radius : un détail fin ne disparaît pas quand on réduit la description
    tiny = Volume.design((32, 32, 32), res=16, scale=0.25)
    thin = tiny.m_segment((4, 4, 16), (28, 28, 16), 0.3)
    assert thin.sum() >= 6


def test_frames_are_independent_copies():
    v = Volume(4, fill="#808080")
    a, b = v.frames(2)
    a.set(a.m_box(0, 0, 0, 0, 0, 0), "#ff0000")
    assert tuple(b.data[0, 0, 0]) == (128, 128, 128, 255) and tuple(v.data[0, 0, 0]) == (128, 128, 128, 255)


def _png_reference_image():
    """Image de référence de l'encodeur PNG : arithmétique entière seulement, identique partout."""
    y, x = np.mgrid[0:24, 0:20]
    a = np.zeros((24, 20, 4), np.uint8)
    a[..., 0] = (x * 13) % 256
    a[..., 1] = (y * 11) % 256
    a[..., 2] = ((x ^ y) * 7) % 256
    a[..., 3] = np.where((x + y) % 5 == 0, 0, 255)
    a[8:16, 4:12] = (200, 50, 30, 255)
    return a


def test_png_encoder_roundtrips_every_color_type():
    import io
    import zlib

    from PIL import Image

    from pixvox.png import encode_png
    rng = np.random.default_rng(7)
    noisy = rng.integers(0, 256, (37, 29, 4), dtype=np.uint8)
    flat = np.zeros((300, 300, 4), np.uint8)                        # longues séries : correspondances de 258
    cases = [noisy, noisy[..., :3], noisy[..., :2], noisy[..., 0], noisy[..., :1], flat,
             np.full((1, 1, 4), 9, np.uint8), np.tile(noisy[:3, :5], (40, 60, 1)),
             _png_reference_image(), Sprite(16).data]
    real_compress, real_compressobj = zlib.compress, zlib.compressobj

    def forbidden(*a, **k):
        raise AssertionError("l'encodeur ne doit pas passer par le zlib de la machine")
    zlib.compress, zlib.compressobj = forbidden, forbidden
    try:
        encoded = [encode_png(a) for a in cases]
    finally:
        zlib.compress, zlib.compressobj = real_compress, real_compressobj
    for a, b in zip(cases, encoded):
        back = np.asarray(Image.open(io.BytesIO(b)))
        assert np.array_equal(back.reshape(a.shape), a), a.shape
        assert encode_png(a) == b                                     # même appel → mêmes octets
    img = Image.fromarray(noisy).convert("P")                          # mode sans équivalent : passe en RGBA
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(encode_png(img)))), np.asarray(img.convert("RGBA")))


def test_png_reference_bytes():
    """Mêmes pixels → mêmes octets, sur toutes les machines (#41). Si ce test échoue après une
    modification voulue de pixvox/png.py, mettre à jour l'empreinte et le dire dans le CHANGELOG : les
    projets qui versionnent des textures pixvox verront tous leurs PNG changer."""
    import hashlib

    from pixvox.png import encode_png
    got = hashlib.sha256(encode_png(_png_reference_image())).hexdigest()
    assert got == "07651084be952252b77a7f7f6cb6a58fee169b41f68927c0ab32e8966feb3ead", got
