"""pixvox.assets — les objets que l'on décrit : Block (bloc plein), Model (modèle voxel), Item (sprite plat),
MultiBlock (objet de plusieurs blocs). Tous peuvent être animés (textures animées de Minecraft)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .anim import Anim, Timing, _check_frames
from .sprite import Sprite
from .volume import FACES, Volume, face_coords


def _frames_arg(volume) -> list:
    """Un volume, ou une liste de volumes de même forme (images d'une animation)."""
    if isinstance(volume, (list, tuple)):
        return _check_frames(list(volume))
    if not isinstance(volume, Volume):
        raise TypeError(f"Volume ou liste de Volumes attendu, reçu {type(volume).__name__}")
    return [volume]


def _check_emissive(emissive, volume, emission):
    if not 0 <= int(emission) <= 15:
        raise ValueError("emission entre 0 et 15")
    if emissive is None:
        return None
    em = np.asarray(emissive)
    if em.dtype != bool or em.shape != volume.shape:
        raise ValueError(f"emissive : masque booléen de forme {volume.shape} attendu (reçu {em.dtype} {em.shape})")
    return em if (em & volume.solid).any() else None


class _Animated:
    """Volumes animés : self.frames (liste de Volumes, même forme) + self.timing."""
    frames: list
    timing: Timing

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    def frame_at(self, tick: float):
        """(index d'image, index suivant, fondu) au tick donné."""
        return self.timing.at(len(self.frames), tick)

    @property
    def anims(self) -> list:
        """Animations de l'asset : [(Timing, nb d'images)]."""
        return [(self.timing, len(self.frames))]

    def volume_at(self, tick: float) -> Volume:
        """Volume affiché au tick donné (fondu des couleurs si interpolate)."""
        from .anim import blend
        i, j, f = self.frame_at(tick)
        if f <= 0:
            return self.frames[i]
        v = self.frames[i].copy()
        v.data = blend(self.frames[i].data, self.frames[j].data, f)
        return v


SOUNDS = ("stone", "wood", "metal", "glass", "lantern", "chain", "amethyst", "deepslate", "deepslate_bricks",
          "polished_deepslate", "basalt", "netherrack", "nether_bricks", "bone_block", "calcite", "tuff", "copper",
          "mud_bricks", "gravel", "sand", "grass", "wool", "snow", "moss", "anvil", "netherite_block", "shroomlight",
          "froglight", "candle", "lodestone", "gilded_blackstone", "cherry_wood", "bamboo_wood", "nether_wood",
          "resin_bricks", "iron", "decorated_pot", "heavy_core", "slime_block", "honey_block", "coral_block")
PARTICLES = {"flame": ("FLAME", "SMOKE"), "soul": ("SOUL_FIRE_FLAME", "SMOKE"), "small_flame": ("SMALL_FLAME", None),
             "smoke": ("SMOKE", None), "campfire": ("FLAME", "CAMPFIRE_COSY_SMOKE"), "lava": ("LAVA", "SMOKE"),
             "spark": ("ELECTRIC_SPARK", None), "glow": ("GLOW", None), "end_rod": ("END_ROD", None),
             "portal": ("PORTAL", None), "enchant": ("ENCHANT", None), "ash": ("ASH", None),
             "firefly": ("FIREFLY", None), "copper_flame": ("COPPER_FIRE_FLAME", "SMOKE")}


@dataclass
class Props:
    """Comportement en jeu, pour l'export en MOD (ignoré par le resource pack seul).

    strength : dureté (temps de minage) — terre 0.5, pierre 1.5, fer 5, obsidienne 50
    blast    : résistance aux explosions (défaut : 6 pour un bloc à la pioche, sinon = strength)
    sound    : 'stone', 'wood', 'metal', 'glass', 'lantern', 'chain', 'amethyst', 'deepslate'… (SOUNDS)
    light    : lumière émise 0–15 (torche 14, lanterne 15) — éclaire vraiment le monde autour
    tool     : 'pickaxe' | 'axe' | 'shovel' | 'hoe' | None ; tier : None | 'stone' | 'iron' | 'diamond'
    requires_tool : sans le bon outil, le bloc ne lâche rien (comme la pierre)
    collision: False = on passe au travers (plantes, flammes)
    particles: None ou 'flame', 'soul', 'smoke', 'campfire', 'lava', 'spark', 'glow', 'end_rod', 'portal',
               'enchant', 'ash', 'firefly'… émises à particle_at (unités modèle) avec la probabilité
               particle_rate par tick d'affichage
    names    : {'fr_fr': 'Brasero', 'en_us': 'Brazier'} — noms affichés (défaut : tiré du nom de l'asset)
    """
    strength: float = 1.5
    blast: float | None = None
    sound: str = "stone"
    light: int = 0
    tool: str | None = "pickaxe"
    tier: str | None = None
    requires_tool: bool = False
    collision: bool = True
    particles: str | None = None
    particle_at: tuple = (8.0, 12.0, 8.0)
    particle_rate: float = 0.6
    names: dict | None = None

    def __post_init__(self):
        if self.sound not in SOUNDS:
            raise ValueError(f"sound={self.sound!r} inconnu ; choix : {', '.join(SOUNDS)}")
        if not 0 <= int(self.light) <= 15:
            raise ValueError("light entre 0 et 15")
        if self.tool not in (None, "pickaxe", "axe", "shovel", "hoe"):
            raise ValueError("tool = 'pickaxe', 'axe', 'shovel', 'hoe' ou None")
        if self.tier not in (None, "stone", "iron", "diamond"):
            raise ValueError("tier = None, 'stone', 'iron' ou 'diamond'")
        if self.particles is not None and self.particles not in PARTICLES:
            raise ValueError(f"particles={self.particles!r} inconnu ; choix : {', '.join(PARTICLES)}")


class Asset:
    kind = "asset"

    def __init__(self, name: str, notes: str = ""):
        if not name.replace("_", "").isalnum() or name.lower() != name:
            raise ValueError(f"nom invalide {name!r} : minuscules, chiffres et _ uniquement (identifiant Minecraft)")
        self.name = name
        self.notes = notes
        self.props: Props | None = None        # comportement en jeu (export mod), voir Props


def _check_states(states):
    """None (bloc simple), 'axis' (comme les bûches : axis=x|y|z) ou 'facing' (4 directions, comme un
    four). Le modèle entier est tourné par le blockstate : les arêtes restent cohérentes."""
    if states not in (None, "axis", "facing"):
        raise ValueError("states doit être None, 'axis' ou 'facing'")
    return states


class Block(Asset, _Animated):
    """Bloc plein 16x16x16. Les 6 textures sont lues sur la peau du volume (orientation Minecraft).

    Block(name, volume)                      -> faces dérivées : arêtes cohérentes par construction
    Block.from_faces(name, {face: sprite})   -> textures données face par face : les conflits
                                                d'arêtes sont détectés, listés et marqués sur le patron.
                                                fix=True : textures unifiées (chaque voxel d'arête
                                                prend une seule couleur, cf. `resolve`)
    render_type : 'solid' (défaut), 'cutout' (pixels 100 % transparents) ou 'translucent'.
    states      : None, 'axis' (bûche : le volume est conçu debout, axe y) ou 'facing' (le volume est
                  conçu face avant au NORD) -> variantes de blockstate par rotation du modèle entier.
    seamless    : True (défaut) si le bloc doit se raccorder sans couture avec ses voisins (pierre,
                  terre…) ; 'horizontal' si seul l'empilement vertical montre une bordure voulue
                  (herbe, mousse, neige) ; False pour un objet « encadré » (caisse, machine).
    Animation   : passer une LISTE de volumes (même forme, seules les couleurs changent) ; frametime
                  (ticks par image), interpolate, order comme dans un .png.mcmeta. Chaque face qui
                  change devient une texture animée ; les faces fixes restent des PNG simples.
    emissive    : masque des voxels lumineux (cristaux d'un minerai, runes) : exportés dans une
                  surcouche (light_emission = emission) qui reste claire dans le noir.
    """
    kind = "cube"

    def __init__(self, name: str, volume, render_type: str | None = None, seamless=True,
                 states: str | None = None, notes: str = "", frametime: int = 2, interpolate: bool = False,
                 order=None, emissive=None, emission: int = 15):
        super().__init__(name, notes)
        self.seamless = seamless
        self.states = _check_states(states)
        self.frames = _frames_arg(volume)
        self.timing = Timing(frametime, interpolate, order)
        volume = self.frames[0]
        self.emissive = _check_emissive(emissive, volume, emission)
        self.emission = int(emission)
        n = volume.shape[0]
        if volume.shape != (n, n, n) or n not in (8, 16, 32, 64, 128):
            raise ValueError(f"un Block est un cube de N³ voxels, N = 16 (vanilla), 32, 64… (reçu {volume.shape}) ;"
                             " utilisez Model ou MultiBlock pour les autres formes")
        self.volume = volume
        self.conflicts: list = []
        self.source = "volume"
        self.fixed = False
        self.given_faces: dict | None = None
        self.render_type = render_type

    @classmethod
    def from_faces(cls, name: str, faces: dict, fix: bool = False, resolve: str = "priority", **kw) -> Block:
        """Bloc depuis 6 textures (Sprite, tableau ou chemin PNG). Les faces absentes sont remplies
        par la face 'north'. fix=False : textures gardées telles quelles (conflits signalés) ;
        fix=True : textures unifiées sur la peau du volume."""
        given = {}
        for f in FACES:
            s = faces.get(f, faces.get("north"))
            if s is None:
                raise ValueError(f"face {f} manquante")
            given[f] = s if isinstance(s, Sprite) else (Sprite(data=np.asarray(s)) if isinstance(s, np.ndarray)
                                                        else Sprite.load(s))
        vol, conflicts = Volume.from_faces(given, resolve=resolve)
        if kw.get("emissive") is not None:
            raise ValueError("emissive n'est pas pris en charge avec from_faces (textures fournies) : "
                             "construire le bloc depuis un volume")
        b = cls(name, vol, **kw)
        b.conflicts = conflicts
        b.source = "faces"
        b.fixed = fix
        b.given_faces = None if fix else given
        return b

    @classmethod
    def from_textures(cls, name: str, all=None, side=None, top=None, bottom=None, end=None, **faces) -> Block:
        """Raccourci façon Minecraft : all / side+end (colonne) / side+top+bottom, ou faces nommées."""
        f = {}
        if all is not None:
            f = {k: all for k in FACES}
        if side is not None:
            f.update({k: side for k in ("north", "south", "west", "east")})
        if end is not None:
            f.update(up=end, down=end)
        if top is not None:
            f["up"] = top
        if bottom is not None:
            f["down"] = bottom
        f.update({k: v for k, v in faces.items() if k in FACES})
        opts = {k: v for k, v in faces.items() if k not in FACES}
        return cls.from_faces(name, f, **opts)

    def faces(self, frame: int = 0) -> dict:
        """Les 6 textures exportées (celles fournies si from_faces sans fix, sinon la peau du volume) ;
        frame = index d'image pour un bloc animé."""
        if self.given_faces is not None:
            return dict(self.given_faces)
        return self.frames[frame % len(self.frames)].faces()

    def faces_at(self, tick: float) -> dict:
        """Textures affichées au tick donné (fondu compris)."""
        if self.given_faces is not None:
            return dict(self.given_faces)
        return self.volume_at(tick).faces()

    def glow_faces(self, frame: int = 0, vol=None) -> dict:
        """{face: Sprite} de la surcouche lumineuse (pixels emissive, le reste transparent) ;
        les faces sans pixel lumineux sont absentes."""
        if self.emissive is None or self.given_faces is not None:
            return {}
        vol = vol if vol is not None else self.frames[frame % len(self.frames)]
        out = {}
        for f in FACES:
            X, Y, Z = face_coords(f, (0, 0, 0), vol.shape)
            m = self.emissive[X, Y, Z] & vol.solid[X, Y, Z]
            if m.any():
                d = vol.data[X, Y, Z].copy()
                d[~m, 3] = 0              # transparent, mais garde la couleur de base (rendu sûr partout)
                out[f] = Sprite(data=d)
        return out

    def glow_anims(self) -> dict:
        """{face: Sprite ou Anim} de la surcouche lumineuse."""
        fr = [self.glow_faces(k) for k in range(len(self.frames))]
        out = {}
        for f in fr[0]:
            seq = [x[f] for x in fr]
            same = all(np.array_equal(x.data, seq[0].data) for x in seq[1:])
            out[f] = seq[0] if same else Anim(seq, self.timing.frametime, self.timing.interpolate, self.timing.order)
        return out

    def quads(self, tick: float = 0) -> list:
        """Géométrie de rendu au tick donné (les 6 faces du cube, + surcouche lumineuse)."""
        from .render import cube_quads
        q = cube_quads(self.faces_at(tick))
        if self.emissive is not None:
            for gq in cube_quads(self.glow_faces(vol=self.volume_at(tick))):
                gq.emission = self.emission
                q.append(gq)
        return q

    def face_anims(self) -> dict:
        """{face: Sprite (fixe) ou Anim (animée)}."""
        out = {}
        for f in FACES:
            fr = [self.faces(k)[f] for k in range(len(self.frames))]
            same = all(np.array_equal(x.data, fr[0].data) for x in fr[1:])
            out[f] = fr[0] if same else Anim(fr, self.timing.frametime, self.timing.interpolate, self.timing.order)
        return out

    def effective_render_type(self) -> str:
        if self.render_type:
            return self.render_type
        a = np.concatenate([s.data[..., 3].ravel() for k in range(len(self.frames))
                            for s in self.faces(k).values()])
        if ((a > 0) & (a < 255)).any():
            return "translucent"
        if (a == 0).any():
            return "cutout"
        return "solid"


LEGACY_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)     # rotations d'élément acceptées avant 1.21.11


@dataclass
class Plane:
    """Plan texturé vertical, visible des deux côtés (flammes, herbes, toiles, hologrammes).

    center = (x, z) et y en unités modèle (1/16 de bloc) ; width x height = taille du plan ;
    angle  = rotation autour de la verticale en degrés (0 = plan face au nord/sud, 90 = face est/ouest).
    emission = luminosité propre 0–15 (light_emission : 15 = pleinement éclairé même la nuit) ;
    shade=False : pas d'ombrage directionnel (comme le feu vanilla).
    La texture (Sprite ou Anim) couvre tout le plan, haut de l'image en haut, non inversée des 2 côtés.
    """
    texture: object
    center: tuple = (8.0, 8.0)
    y: float = 0.0
    width: float = 16.0
    height: float = 16.0
    angle: float = 0.0
    emission: int = 0
    shade: bool = False

    def norm_angle(self) -> float:
        """Angle ramené dans ]-90, 90] (un plan tourné de 180° est le même plan)."""
        a = (float(self.angle) + 90.0) % 180.0 - 90.0
        return 90.0 if a == -90.0 else a

    def axes(self):
        """(d, n) : direction horizontale du plan (sens des u, vu de l'avant) et normale avant."""
        a = math.radians(self.norm_angle())
        return np.array([math.cos(a), 0.0, -math.sin(a)]), np.array([math.sin(a), 0.0, math.cos(a)])

    def bounds(self):
        d, _ = self.axes()
        cx, cz = self.center
        ex = abs(d[0]) * self.width / 2
        ez = abs(d[2]) * self.width / 2
        return (np.array([cx - ex, self.y, cz - ez]), np.array([cx + ex, self.y + self.height, cz + ez]))

    def texture_at(self, tick: float) -> np.ndarray:
        t = self.texture
        return t.at(tick) if isinstance(t, Anim) else np.asarray(t.data)


class Model(Asset, _Animated):
    """Modèle voxel (forme libre) exporté en éléments Minecraft optimisés + texture atlas.

    voxel_size : unités de modèle par voxel ; par défaut 16 / volume.res (1 = densité vanilla,
                 0.5 = volume à 32 voxels par bloc, deux fois plus fin).
    Le volume est centré horizontalement et posé au sol (y=0) sauf si `origin` est donné.
    Animation  : une LISTE de volumes (même forme) ; frametime / interpolate / order.
    emissive   : masque des voxels qui brillent (braises, yeux, cristaux) : exportés dans des éléments
                 à part avec light_emission = emission (0–15), visibles même dans le noir.
    Plans      : add_plane() / add_cross() ajoutent des plans texturés (flammes animées…).
    """
    kind = "model"

    def __init__(self, name: str, volume, voxel_size: float | None = None, origin=None,
                 ambient_occlusion: bool = True, states: str | None = None, inventory_scale: float | None = None,
                 inventory_center: bool = False, notes: str = "", frametime: int = 2, interpolate: bool = False,
                 order=None, emissive=None, emission: int = 15):
        super().__init__(name, notes)
        self.states = _check_states(states)
        self.inventory_scale = inventory_scale
        self.inventory_center = inventory_center
        self.frames = _frames_arg(volume)
        self.timing = Timing(frametime, interpolate, order)
        volume = self.frames[0]
        self.volume = volume
        self.planes: list[Plane] = []
        self.emissive = _check_emissive(emissive, volume, emission)
        self.emission = int(emission)
        self.voxel_size = float(voxel_size) if voxel_size else 16.0 / volume.res   # unités modèle par voxel
        sx, sy, sz = volume.shape
        if origin is None:
            origin = ((16 - sx * self.voxel_size) / 2.0, 0.0, (16 - sz * self.voxel_size) / 2.0)
        self.origin = tuple(float(o) for o in origin)
        self.ambient_occlusion = ambient_occlusion


    def add_plane(self, texture, *, center=(8, 8), y: float = 0, width: float = 16, height: float = 16,
                  angle: float = 0, emission: int = 0, shade: bool = False) -> Plane:
        """Ajoute un plan texturé (voir Plane). texture : Sprite ou Anim (animée)."""
        if not isinstance(texture, (Sprite, Anim)):
            texture = Sprite(data=np.asarray(texture))
        p = Plane(texture, tuple(float(c) for c in center), float(y), float(width), float(height), float(angle),
                  int(emission), bool(shade))
        if not 0 <= p.emission <= 15:
            raise ValueError("emission entre 0 et 15")
        self.planes.append(p)
        return p

    def add_cross(self, texture, *, center=(8, 8), y: float = 0, width: float = 16, height: float = 16,
                  planes: int = 2, angle: float = 45, emission: int = 0, shade: bool = False) -> list:
        """Plans croisés autour d'un axe vertical (feu de camp, plantes) : planes=2 -> X (angle ±45°),
        planes=4 -> X + croix droite (0° et 90°), plus plein vu de partout."""
        angs = [angle, angle - 90] if planes == 2 else [angle, angle - 90, angle - 45, angle + 45]
        if planes not in (2, 4):
            raise ValueError("planes = 2 ou 4")
        return [self.add_plane(texture, center=center, y=y, width=width, height=height, angle=a,
                               emission=emission, shade=shade) for a in angs]

    def bounds(self):
        """Boîte englobante des voxels pleins (et des plans), en unités modèle : (min, max)."""
        xs, ys, zs = np.nonzero(self.volume.solid)
        lo = np.array([xs.min(), ys.min(), zs.min()], float) * self.voxel_size + np.array(self.origin)
        hi = np.array([xs.max() + 1, ys.max() + 1, zs.max() + 1], float) * self.voxel_size + np.array(self.origin)
        for p in self.planes:
            a, b = p.bounds()
            lo, hi = np.minimum(lo, a), np.maximum(hi, b)
        return lo, hi

    def quads(self, tick: float = 0) -> list:
        """Géométrie de rendu au tick donné : faces des voxels (+ émission) et plans texturés."""
        from .render import plane_quads, quads_from_volume
        q = quads_from_volume(self.volume_at(tick), offset=self.origin, voxel_size=self.voxel_size,
                              emissive=self.emissive, emission=self.emission)
        for p in self.planes:
            q += plane_quads(p.center, p.y, p.width, p.height, p.angle, p.texture_at(tick), p.emission, p.shade)
        return q

    @property
    def anims(self) -> list:
        """Toutes les animations du modèle : (Timing, nb d'images) — volumes et plans."""
        out = [(self.timing, len(self.frames))]
        out += [(p.texture.timing, p.texture.n) for p in self.planes if isinstance(p.texture, Anim)]
        return out

    def gui_transform(self):
        """(échelle, centre) de l'icône d'inventaire : vanilla = (0.625, (8, 8, 8)).
        inventory_scale multiplie l'échelle ; inventory_center recentre la case sur le modèle."""
        s = 0.625 * (self.inventory_scale or 1.0)
        if self.inventory_center:
            lo, hi = self.bounds()
            c = tuple(float(x) for x in (lo + hi) / 2)
        else:
            c = (8.0, 8.0, 8.0)
        return s, c


class Item(Asset):
    """Item plat (sprite carré, 16x16 en vanilla), exporté avec item/generated.
    sprite : Sprite, ou Anim pour un item animé (bande + .png.mcmeta)."""
    kind = "sprite"

    def __init__(self, name: str, sprite, notes: str = ""):
        super().__init__(name, notes)
        if sprite.w != sprite.h:
            raise ValueError(f"sprite {sprite.w}x{sprite.h} non carré pour l'item {name!r} "
                             "(une ligne ASCII trop longue ou trop courte ?)")
        self.anim = sprite if isinstance(sprite, Anim) else None
        self.sprite = sprite.frames[0] if isinstance(sprite, Anim) else sprite

    @property
    def animated(self) -> bool:
        return self.anim is not None and self.anim.n > 1

    def sprite_at(self, tick: float) -> np.ndarray:
        return self.anim.at(tick) if self.anim is not None else self.sprite.data

    @property
    def anims(self) -> list:
        return [(self.anim.timing, self.anim.n)] if self.anim is not None else []

    def quads(self, tick: float = 0) -> list:
        """Item extrudé (comme tenu en main / au sol)."""
        from .render import item_quads
        return item_quads(self.sprite_at(tick))


class MultiBlock(Asset, _Animated):
    """Objet de plusieurs blocs (statue, grande machine, arbre…) à la résolution vanilla (16 voxels
    par bloc), sans limite de taille.

    Le volume est découpé en cellules de res³ voxels (16³ à la résolution vanilla, 32³ en HD…) ; chaque
    cellule non vide devient un modèle de bloc
    (une « partie »). Repère : la cellule (0, 0, 0) est le bloc de départ, x vers l'est, y vers le
    haut, z vers le sud ; la face AVANT de l'objet est le côté NORD du volume (z = 0).
    Export : un modèle par partie + un atlas partagé, une miniature d'inventaire (l'objet entier dans
    une case), et un datapack dont la fonction pose l'objet en jeu avec des item_display (sans mod).
    Animation : une LISTE de volumes (même forme) ; frametime / interpolate / order.
    emissive  : masque des voxels lumineux (éléments à part avec light_emission = emission).
    """
    kind = "multi"

    def __init__(self, name: str, volume, ambient_occlusion: bool = True, notes: str = "",
                 frametime: int = 2, interpolate: bool = False, order=None, emissive=None, emission: int = 15):
        super().__init__(name, notes)
        self.frames = _frames_arg(volume)
        self.timing = Timing(frametime, interpolate, order)
        volume = self.frames[0]
        if not volume.solid.any():
            raise ValueError("volume vide")
        self.volume = volume
        self.emissive = _check_emissive(emissive, volume, emission)
        self.emission = int(emission)
        self.ambient_occlusion = ambient_occlusion
        self.res = volume.res                       # voxels par bloc (16 vanilla, 32 HD…)
        r = self.res
        sx, sy, sz = volume.shape
        self.blocks = (-(-sx // r), -(-sy // r), -(-sz // r))

    @property
    def voxel_size(self) -> float:
        return 16.0 / self.res

    def quads(self, tick: float = 0) -> list:
        """Géométrie de rendu de l'objet entier au tick donné."""
        from .render import quads_from_volume
        return quads_from_volume(self.volume_at(tick), voxel_size=self.voxel_size, emissive=self.emissive,
                                 emission=self.emission)

    def cells(self) -> list:
        """Cellules (bx, by, bz) contenant au moins un voxel plein."""
        solid = self.volume.solid
        r = self.res
        out = []
        nx, ny, nz = self.blocks
        for bx in range(nx):
            for by in range(ny):
                for bz in range(nz):
                    if solid[bx * r:(bx + 1) * r, by * r:(by + 1) * r, bz * r:(bz + 1) * r].any():
                        out.append((bx, by, bz))
        return out

    def miniature(self):
        """(taille de voxel, origine) de la miniature, en unités modèle : l'objet entier réduit pour
        tenir dans un bloc, centré, au milieu de la case d'inventaire."""
        sx, sy, sz = self.volume.shape
        vs = self.voxel_size * min(1.0, 16.0 / (max(sx, sy, sz) * self.voxel_size))
        origin = ((16 - sx * vs) / 2, (16 - sy * vs) / 2, (16 - sz * vs) / 2)
        return vs, origin

    def gui_transform(self):
        return 0.625, (8.0, 8.0, 8.0)
