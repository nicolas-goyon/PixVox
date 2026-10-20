"""pixvox — atelier pixel-art / voxel-art pour Minecraft, piloté par code (humains, agents, logiciels)."""
from .anim import EMBER, FIRE, SOUL_EMBER, SOUL_FIRE, Anim, Timing, fire, flow, pulse
from .assets import Block, Item, Model, MultiBlock, Plane, Props
from .color import (
    Ramp,
    adjust,
    darken,
    delta_e,
    hexa,
    lighten,
    lightness,
    luminance,
    mix,
    nearest,
    ramp,
    ramp_between,
    rgba,
    shade,
)
from .noise import equalize, perlin, worley
from .sprite import Sprite
from .volume import FACE_AXES, FACES, NORMALS, Volume, face_coords

__version__ = "0.1.0"


__all__ = ["Block", "Item", "Model", "MultiBlock", "Plane", "Props", "Anim", "Timing", "fire", "pulse",
           "flow", "FIRE", "SOUL_FIRE", "EMBER", "SOUL_EMBER", "Volume", "Sprite", "Ramp", "ramp",
           "ramp_between", "rgba", "hexa", "mix", "adjust", "lighten", "darken", "shade", "lightness",
           "luminance", "delta_e", "nearest", "perlin", "worley", "equalize", "FACES", "NORMALS",
           "FACE_AXES", "face_coords"]
