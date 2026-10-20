"""Cœur de magma : bloc plein animé. Pierre volcanique en dalles, la lave s'écoule dans les joints.

- Les dalles sont fixes ; seuls les joints changent de couleur (flow : bruit qui descend en boucle).
- Le bruit est périodique en x, y, z ET dans le temps : les blocs voisins se raccordent à chaque image
  et la boucle n'a pas d'à-coup.
- À l'export, seules les faces qui changent deviennent des textures animées (ici les 6, car les joints
  passent partout ; chaque face = bande 16x256 + .png.mcmeta).
"""
from pixvox import Block, Props, Ramp, Volume, flow, ramp

BASALT = ramp("#3a3337", n=5, spread=0.20, hue_shift=10, tint=0.01)
LAVA = Ramp(["#5c1a08", "#a8300b", "#e2600f", "#f99a22", "#ffd85e"])     # croûte sombre -> jaune vif


def build():
    v = Volume(16)
    joints = v.cells(BASALT, count=8, seed=3, mortar_width=0.95, edge_shadow=0.25, relief=0.5)
    frames = v.frames(16)
    flow(frames, joints, LAVA, cells=4, octaves=2, seed=2, direction=(0, -1, 0), cycles=1, morph=1,
         weights=(1, 2, 3, 2, 1))
    b = Block("magma_core", frames, frametime=3)
    b.props = Props(strength=2.5, sound="basalt", light=9, tool="pickaxe", requires_tool=True, particles="lava",
                    particle_at=(8, 16, 8), particle_rate=0.08,
                    names={"fr_fr": "Cœur de magma", "en_us": "Magma Core"})  # export mod
    return b
