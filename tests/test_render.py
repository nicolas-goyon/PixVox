"""Rendu « comme le jeu » et lecteur de modèles Minecraft : la référence de toute vérification.

Ces tests prouvent que le rendu d'un volume et le rendu du modèle JSON vanilla relu comme le jeu
coïncident pixel pour pixel, et qu'une vraie erreur (faces échangées, UV tourné) est bien détectée.
"""
import numpy as np

from pixvox import FACES
from pixvox.mcmodel import ModelLoader
from pixvox.render import Camera, compare, face_quad, fit_camera, quads_from_volume, render, rot_matrix
from testkit import JITTER, cube_model_quads, diff, marked_volume


def test_cube_faces_match_minecraft_model():
    v = marked_volume()
    assert diff(quads_from_volume(v), cube_model_quads(v.faces())) == 0


def test_verification_catches_swapped_faces():
    v = marked_volume()
    tex = {f: f"t:block/{f}" for f in FACES}
    tex["north"], tex["south"] = tex["south"], tex["north"]
    assert diff(quads_from_volume(v), cube_model_quads(v.faces(), tex)) > 500


def test_verification_catches_rotated_uv():
    v = marked_volume()
    faces = v.faces()
    loader = ModelLoader(extra_textures={f"t:block/{f}": faces[f] for f in FACES})
    el = {"from": [0, 0, 0], "to": [16, 16, 16],
          "faces": {f: {"texture": "#" + f, "uv": [0, 0, 16, 16], **({"rotation": 90} if f == "up" else {})}
                    for f in FACES}}
    qm = loader.quads({"textures": {f: f"t:block/{f}" for f in FACES}, "elements": [el]})
    assert diff(quads_from_volume(v), qm) > 300


def test_perspective_matches_minecraft_model():
    v = marked_volume(3)
    qm = cube_model_quads(v.faces())
    qv = quads_from_volume(v)
    for view in ((45, -30), (200, 10), (300, 50)):
        cam = fit_camera(qv, view, 220, 220, jitter=JITTER, persp=1.8)
        n, _ = compare(render(qv, cam, shading="flat"), render(qm, cam, shading="flat"))
        assert n == 0, (view, n)


def test_render_edge_ties_do_not_depend_on_draw_order():
    """Deux faces coplanaires voisines : un pixel dont le centre est (à 1e-4 px près) dans B ne doit
    jamais prendre la couleur de A, quel que soit l'ordre de dessin (la tolérance anti-trous de A ne doit
    pas écraser B). Sinon le modèle exporté (autre découpage en quads) diffère du volume de référence."""
    red = np.zeros((16, 8, 4), np.uint8)
    red[...] = (255, 0, 0, 255)
    blue = np.zeros((16, 8, 4), np.uint8)
    blue[...] = (0, 0, 255, 255)
    qa = face_quad("south", (0, 0, 0), (8, 16, 16), red)
    qb = face_quad("south", (8, 0, 0), (16, 16, 16), blue)
    cam = Camera(rot_matrix(0, 0), 10.0, 8 - 0.4999 / 10.0, 8.0, 160, 160)   # x=8 -> 80.5 - 1e-4 px
    ab, ba = render([qa, qb], cam, shading="flat"), render([qb, qa], cam, shading="flat")
    assert tuple(ab[40, 80, :3]) == (0, 0, 255) and tuple(ba[40, 80, :3]) == (0, 0, 255)
    assert (ab == ba).all()
    hole = render([qa, qb], Camera(rot_matrix(0, 0), 10.0, 8 - 0.5 / 10.0, 8.0, 160, 160), shading="flat")
    assert (hole[:, 80, 3] == 255).sum() >= 159                          # pile sur l'arête : pas de trou


def test_missing_texture_is_reported():
    loader = ModelLoader()
    q = loader.quads({"textures": {"all": "t:block/nope"}, "elements": [
        {"from": [0, 0, 0], "to": [16, 16, 16], "faces": {"up": {"texture": "#all"}}}]})
    assert len(q) == 1 and "t:block/nope" in loader.missing


def test_model_loader_reads_like_1_21_1():
    """Lecture « 1.21.1 » (NeoForge 21.1) : couche de rendu de render_type (seuils des shaders du jar),
    neoforge_data de la face puis de l'élément, light_emission ignoré, modèles que le jeu refuse."""
    import numpy as np

    from pixvox.mcmodel import layer_texture, render_layer
    texels = np.array([[[9, 9, 9, al] for al in (0, 20, 100, 200, 255)]], np.uint8)

    def alpha(layer):
        return layer_texture(texels, layer)[0, :, 3].tolist()

    assert (render_layer(None), render_layer("cutout"), render_layer("neoforge:autre")) == ("solid", "cutout", "solid")
    assert alpha("solid") == [255] * 5                                      # l'alpha ne compte pas
    assert alpha("cutout") == [0, 0, 255, 255, 255]                          # jeté sous 0,1
    assert alpha("cutout_mipped") == [0, 0, 0, 255, 255]                     # jeté sous 0,5
    assert alpha("translucent") == [0, 20, 100, 200, 255]
    assert alpha("tripwire") == [0, 0, 100, 200, 255]
    tex = {"t:block/t": np.full((16, 16, 4), 255, np.uint8)}
    el = {"from": [0, 0, 0], "to": [16, 16, 16], "light_emission": 9, "neoforge_data": {"block_light": 12},
          "faces": {"up": {"texture": "#t"}, "down": {"texture": "#t", "neoforge_data": {}}}}

    def quads(element, mc):
        return ModelLoader(extra_textures=tex, mc=mc).quads({"textures": {"t": "t:block/t"}, "elements": [element]})

    assert {q.face: q.emission for q in quads(el, "1.21.1")} == {"up": 12, "down": 0}
    assert {q.face: q.emission for q in quads(el, "1.21.4+")} == {"up": 12, "down": 9}
    rot = {"origin": [8, 8, 8], "axis": "y"}
    for bad in ({**el, "forge_data": {}}, {**el, "rotation": {**rot, "angle": 30}}, {**el, "rotation": rot}):
        assert quads(bad, "1.21.4+")                                        # accepté par la lecture 1.21.4+
        try:
            quads(bad, "1.21.1")
            raise AssertionError(f"modèle refusé par 1.21.1 accepté : {set(bad) - set(el)}")
        except ValueError:
            pass
