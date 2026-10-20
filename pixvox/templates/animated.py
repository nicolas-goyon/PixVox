"""Bloc animé « __TITLE__ » (__NAME__) : de la lave coule dans les joints, créé par `pixvox new`.

Minecraft n'anime que les textures : on donne une LISTE de volumes de même forme (16 images ici).
flow() fait couler un bruit périodique (boucle sans à-coup, raccord entre blocs voisins).
    pixvox review __FILE__        # + planche d'animation et GIF
    pixvox export __FILE__        # bandes PNG + .png.mcmeta, vérifiées à chaque image
"""
from pixvox import Block, Props, Ramp, Volume, flow, ramp

BASALT = ramp("#3a3337", n=5, spread=0.20, hue_shift=10)
LAVA = Ramp(["#5c1a08", "#a8300b", "#e2600f", "#f99a22", "#ffd85e"])     # croûte sombre -> jaune vif


def build():
    v = Volume(16)
    joints = v.cells(BASALT, count=8, seed=3, mortar_width=0.95, edge_shadow=0.25, relief=0.5)
    frames = flow(v.frames(16), joints, LAVA, cells=4, octaves=2, seed=2, direction=(0, -1, 0))
    b = Block("__NAME__", frames, frametime=3, emissive=joints, emission=12)   # la lave brille la nuit
    b.props = Props(strength=2.5, sound="basalt", light=9, tool="pickaxe", particles="lava",
                    particle_at=(8, 16, 8), particle_rate=0.08,
                    names={"fr_fr": "__TITLE__", "en_us": "__TITLE__"})
    return b
