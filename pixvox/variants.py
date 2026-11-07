"""pixvox.variants — variantes de construction d'un bloc plein : dalle, escalier, mur, barrière, portillon,
bouton, plaque de pression (#22).

Une variante reprend les textures du bloc plein, lues sur la peau de son volume (règle 1). Chaque face
d'élément montre ce que le bloc plein montrerait à cet endroit, dans la direction où elle regarde
dans le monde : c'est la projection de Minecraft (UV par défaut d'un élément), appliquée après
orientation. Les modèles sont donc écrits déjà orientés (un modèle par géométrie, sans rotation de
blockstate ni `uvlock`) : un escalier tourné vers l'est montre la texture « est » du bloc, même quand
les six faces du volume diffèrent, et une dalle posée sur le bloc plein se raccorde sans couture.

    pierre = Block("mossy_stone", volume)
    famille = pierre.variants("slab", "stairs", "wall")          # [Variant, …] : mossy_stone_slab, …
    export_pack([pierre, *famille], "out/pack")

Les géométries sont celles de Minecraft (dalle de 8, marche de 8, poteau de mur de 8 × 8, côtés bas
de 14, barrière de 4 × 4…). Les propriétés suivent les blocs vanilla, sans `waterlogged` ni `powered`
du portillon (elles ne changent pas le modèle).
"""
from __future__ import annotations

import itertools

import numpy as np

from .assets import Asset, Block

__all__ = ["SHAPES", "Variant"]

SHAPES = ("slab", "stairs", "wall", "fence", "fence_gate", "button", "pressure_plate")
DIRS = ("north", "east", "south", "west")
_TURNS = {"north": 0, "east": 1, "south": 2, "west": 3}       # quarts de tour (horaire vu du dessus) depuis le nord
_RIGHT = {"north": "east", "east": "south", "south": "west", "west": "north"}
_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
LABELS = {"slab": "dalle", "stairs": "escalier", "wall": "mur", "fence": "barrière", "fence_gate": "portillon",
          "button": "bouton", "pressure_plate": "plaque de pression"}

# Propriétés de chaque variante, dans l'ordre du jeu ; valeurs en chaînes, comme dans un blockstate.
PROPERTIES = {
    "slab": {"type": ("bottom", "top", "double")},
    "stairs": {"facing": DIRS, "half": ("bottom", "top"),
               "shape": ("straight", "inner_left", "inner_right", "outer_left", "outer_right")},
    "wall": {"up": ("true", "false"), **{d: ("none", "low", "tall") for d in DIRS}},
    "fence": {d: ("true", "false") for d in DIRS},
    "fence_gate": {"facing": DIRS, "in_wall": ("false", "true"), "open": ("false", "true")},
    "button": {"face": ("floor", "wall", "ceiling"), "facing": DIRS, "powered": ("false", "true")},
    "pressure_plate": {"powered": ("false", "true")},
}
MULTIPART = ("wall", "fence")                 # blockstate « multipart » (parties selon les côtés raccordés)


# ----------------------------------------------------------------------------------------- géométrie
Box = tuple   # ((x0, y0, z0), (x1, y1, z1)) en unités modèle (1/16 de bloc)


def _box(lo, hi) -> Box:
    return (tuple(float(v) for v in lo), tuple(float(v) for v in hi))


def _turn(box: Box, turns: int) -> Box:
    """Boîte tournée de `turns` quarts de tour, sens horaire vu du dessus, autour du centre du bloc
    (le nord devient l'est) : (x, z) → (16 − z, x)."""
    (x0, y0, z0), (x1, y1, z1) = box
    for _ in range(turns % 4):
        x0, z0, x1, z1 = 16 - z1, x0, 16 - z0, x1
    return _box((x0, y0, z0), (x1, y1, z1))


def _toward(box_north: Box, facing: str) -> Box:
    """Boîte dessinée pour le nord, tournée vers `facing`."""
    return _turn(box_north, _TURNS[facing])


_QUAD = {("north", "west"): (0, 0), ("north", "east"): (8, 0), ("south", "west"): (0, 8), ("south", "east"): (8, 8)}


def _quadrants(dirs) -> set:
    """Quarts du plan (x, z) du côté de toutes les directions données (une : moitié, deux : quart)."""
    out = set()
    for (ns, ew) in _QUAD:
        if all(d in (ns, ew) for d in dirs):
            out.add((ns, ew))
    return out


def _stairs(facing: str, half: str, shape: str) -> list:
    """Dalle + marche. La marche est du côté `facing` (le haut de l'escalier) ; coin extérieur : un quart
    seulement, coin intérieur : la moitié plus un quart du côté opposé ; gauche / droite vues en
    regardant vers `facing`. Escalier du haut (half=top) : même plan, dalle en haut, marche en bas."""
    side = _RIGHT[facing] if shape.endswith("right") else _OPPOSITE[_RIGHT[facing]]
    if shape == "straight":
        quads = _quadrants([facing])
    elif shape.startswith("outer"):
        quads = _quadrants([facing, side])
    else:
        quads = _quadrants([facing]) | _quadrants([_OPPOSITE[facing], side])
    y_slab, y_step = ((0, 8), (8, 16)) if half == "bottom" else ((8, 16), (0, 8))
    boxes = [_box((0, y_slab[0], 0), (16, y_slab[1], 16))]
    for d in DIRS:                                     # moitiés entières d'abord, puis quarts restants
        h = _quadrants([d])
        if h <= quads:
            x0 = min(_QUAD[q][0] for q in h)
            z0 = min(_QUAD[q][1] for q in h)
            x1 = max(_QUAD[q][0] for q in h) + 8
            z1 = max(_QUAD[q][1] for q in h) + 8
            boxes.append(_box((x0, y_step[0], z0), (x1, y_step[1], z1)))
            quads -= h
    for q in sorted(quads):
        x0, z0 = _QUAD[q]
        boxes.append(_box((x0, y_step[0], z0), (x0 + 8, y_step[1], z0 + 8)))
    return boxes


_GATE_CLOSED = [((0, 5, 7), (2, 16, 9)), ((14, 5, 7), (16, 16, 9)), ((6, 6, 7), (8, 15, 9)), ((8, 6, 7), (10, 15, 9)),
                ((2, 6, 7), (6, 9, 9)), ((2, 12, 7), (6, 15, 9)), ((10, 6, 7), (14, 9, 9)), ((10, 12, 7), (14, 15, 9))]
_GATE_OPEN = [((0, 5, 7), (2, 16, 9)), ((14, 5, 7), (16, 16, 9)), ((0, 6, 13), (2, 15, 15)), ((14, 6, 13), (16, 15, 15)),
              ((0, 6, 9), (2, 9, 13)), ((0, 12, 9), (2, 15, 13)), ((14, 6, 9), (16, 9, 13)), ((14, 12, 9), (16, 15, 13))]


def _fence_gate(facing: str, in_wall: str, open_: str) -> list:
    """Portillon dessiné pour le sud (comme le modèle vanilla), ouvert vers `facing`, abaissé de 3 dans un mur."""
    dy = -3 if in_wall == "true" else 0
    turns = (_TURNS[facing] - _TURNS["south"]) % 4
    return [_turn(_box((a[0], a[1] + dy, a[2]), (b[0], b[1] + dy, b[2])), turns)
            for a, b in (_GATE_OPEN if open_ == "true" else _GATE_CLOSED)]


def _button(face: str, facing: str, powered: str) -> list:
    """Bouton de 6 × 4, épais de 2 (1 enfoncé), collé au sol, au plafond ou au mur opposé à `facing`."""
    h = 1 if powered == "true" else 2
    if face in ("floor", "ceiling"):
        y = (0, h) if face == "floor" else (16 - h, 16)
        if facing in ("north", "south"):
            return [_box((5, y[0], 6), (11, y[1], 10))]
        return [_box((6, y[0], 5), (10, y[1], 11))]
    # mur : dessiné pour facing=north (collé au bloc du sud, z 16-h..16), puis tourné
    return [_toward(_box((5, 6, 16 - h), (11, 10, 16)), facing)]


def _plate(powered: str) -> list:
    return [_box((1, 0, 1), (15, 0.5 if powered == "true" else 1, 15))]


# ----------------------------------------------------------------------------------------- variante
class Variant(Asset):
    """Variante de construction d'un bloc plein (voir le module). Créée par `Block.variants(…)` ou
    `Variant(bloc, "slab", name=…)`. Hérite des `props` du bloc (dureté, son, outil) pour un mod."""
    kind = "variant"

    def __init__(self, base: Block, shape: str, name: str | None = None, notes: str = ""):
        if not isinstance(base, Block):
            raise TypeError(f"variante d'un Block plein attendue, reçu {type(base).__name__}")
        if shape not in SHAPES:
            raise ValueError(f"variante inconnue {shape!r} ; choix : {', '.join(SHAPES)}")
        if base.emissive is not None:
            raise ValueError(f"{base.name} : surcouche lumineuse (emissive) non prise en charge par les variantes ; "
                             "les dériver d'un bloc sans emissive")
        super().__init__(name or f"{base.name}_{shape}", notes)
        self.base = base
        self.shape = shape
        self.props = base.props

    # ---------------------------------------------------------------- propriétés et états
    @property
    def properties(self) -> dict:
        return {k: list(v) for k, v in PROPERTIES[self.shape].items()}

    @property
    def multipart(self) -> bool:
        return self.shape in MULTIPART

    @property
    def volume(self):
        return self.base.volume

    @property
    def frames(self) -> list:
        return self.base.frames

    @property
    def anims(self) -> list:
        return self.base.anims

    @property
    def animated(self) -> bool:
        return self.base.animated

    def all_states(self) -> list:
        """Tous les états du bloc (produit des valeurs de ses propriétés), dans l'ordre du jeu."""
        props = PROPERTIES[self.shape]
        return [dict(zip(props, vals)) for vals in itertools.product(*props.values())]

    def check_states(self) -> list:
        """États relus et comparés à l'export : tous, sauf pour le mur (162 états) où chaque partie est vue
        seule, en ligne, en L, en T et en croix, basse et haute, avec et sans poteau."""
        if self.shape != "wall":
            return self.all_states()
        out = []
        none = {d: "none" for d in DIRS}
        out.append({"up": "true", **none})
        for d in DIRS:
            for h in ("low", "tall"):
                out.append({"up": "false", **none, d: h})
        for h in ("low", "tall"):
            out.append({"up": "false", **none, "north": h, "south": h})              # ligne : sans poteau
            out.append({"up": "true", **none, "north": h, "east": h})               # coin
            out.append({"up": "true", **none, "north": h, "east": h, "west": h})    # T
            out.append({"up": "true", **{d: h for d in DIRS}})                      # croix
        return out

    @staticmethod
    def state_key(state: dict) -> str:
        """Clé de variante de blockstate : propriétés triées par nom, « a=1,b=2 »."""
        return ",".join(f"{k}={state[k]}" for k in sorted(state))

    # ---------------------------------------------------------------- géométrie
    def boxes(self, state: dict) -> list:
        """Boîtes (unités modèle, déjà orientées) du bloc dans l'état donné."""
        s = self.shape
        if s == "slab":
            return {"bottom": [_box((0, 0, 0), (16, 8, 16))], "top": [_box((0, 8, 0), (16, 16, 16))],
                    "double": [_box((0, 0, 0), (16, 16, 16))]}[state["type"]]
        if s == "stairs":
            return _stairs(state["facing"], state["half"], state["shape"])
        if s == "fence_gate":
            return _fence_gate(state["facing"], state["in_wall"], state["open"])
        if s == "button":
            return _button(state["face"], state["facing"], state["powered"])
        if s == "pressure_plate":
            return _plate(state["powered"])
        return [b for _, when, bs in self.parts() if _when_ok(when, state) for b in bs]

    def parts(self) -> list:
        """Mur et barrière : [(suffixe du modèle, condition, boîtes)] dans l'ordre du blockstate multipart."""
        if self.shape == "wall":
            out = [("_post", {"up": "true"}, [_box((4, 0, 4), (12, 16, 12))])]
            for d in DIRS:
                out.append((f"_side_{d}", {d: "low"}, [_toward(_box((5, 0, 0), (11, 14, 8)), d)]))
                out.append((f"_side_tall_{d}", {d: "tall"}, [_toward(_box((5, 0, 0), (11, 16, 8)), d)]))
            return out
        if self.shape == "fence":
            out = [("_post", None, [_box((6, 0, 6), (10, 16, 10))])]
            for d in DIRS:
                out.append((f"_side_{d}", {d: "true"}, [_toward(_box((7, 12, 0), (9, 15, 9)), d),
                                                         _toward(_box((7, 6, 0), (9, 9, 9)), d)]))
            return out
        return []

    def inventory_boxes(self) -> list:
        """Géométrie de l'objet en main / dans l'inventaire (modèles « inventory » de Minecraft)."""
        s = self.shape
        if s == "wall":
            return [_box((4, 0, 4), (12, 16, 12)), _box((5, 0, 0), (11, 13, 16))]
        if s == "fence":
            return [_box((6, 0, 0), (10, 16, 4)), _box((6, 0, 12), (10, 16, 16)),
                    _box((7, 13, 0), (9, 15, 16)), _box((7, 5, 0), (9, 7, 16))]
        if s == "button":
            return [_box((5, 6, 6), (11, 10, 10))]
        return self.boxes(self.item_state())

    def item_state(self) -> dict:
        """État dont le modèle sert d'objet (escalier tourné vers l'est comme en vanilla, dalle du bas…)."""
        return {"slab": {"type": "bottom"}, "stairs": {"facing": "east", "half": "bottom", "shape": "straight"},
                "fence_gate": {"facing": "south", "in_wall": "false", "open": "false"},
                "pressure_plate": {"powered": "false"}}.get(self.shape, {})

    # ---------------------------------------------------------------- modèles écrits
    def _suffix(self, state: dict) -> str:
        """Suffixe lisible d'un état : valeurs dans l'ordre du jeu, « true » → nom de la propriété (open,
        wall pour in_wall, pressed / down pour powered), « false » omis."""
        if state == self.item_state() and self.shape not in ("button",):
            return ""
        words = []
        for k in PROPERTIES[self.shape]:
            v = state[k]
            if v == "true":
                words.append({"in_wall": "wall", "powered": "down" if self.shape == "pressure_plate" else "pressed"}
                             .get(k, k))
            elif v != "false":
                words.append(v)
        return "_" + "_".join(words) if words else ""

    def models(self) -> list:
        """[(nom du modèle, boîtes)] : un modèle par géométrie distincte (le premier état qui la donne le
        nomme), plus le modèle d'inventaire du mur, de la barrière et du bouton."""
        out: dict = {}
        if self.multipart:
            for suffix, _, boxes in self.parts():
                out.setdefault(tuple(boxes), self.name + suffix)
        else:
            for state in self.all_states():
                out.setdefault(tuple(self.boxes(state)), self.name + self._suffix(state))
        if self.shape in ("wall", "fence", "button"):
            out.setdefault(tuple(self.inventory_boxes()), self.name + "_inventory")
        return [(name, list(boxes)) for boxes, name in out.items()]

    def model_name(self, boxes) -> str:
        return {tuple(b): n for n, b in self.models()}[tuple(boxes)]

    def item_model_name(self) -> str:
        return self.model_name(self.inventory_boxes())

    def written_names(self) -> list:
        return [n for n, _ in self.models()]

    # ---------------------------------------------------------------- rendu de référence
    def faces_at(self, tick: float = 0) -> dict:
        return self.base.faces_at(tick)

    def state_quads(self, state: dict, tick: float = 0) -> list:
        from .render import projected_box_quads
        return projected_box_quads(self.boxes(state), self.faces_at(tick))

    def quads(self, tick: float = 0) -> list:
        """Objet d'inventaire (géométrie projetée sur la peau du bloc plein)."""
        from .render import projected_box_quads
        return projected_box_quads(self.inventory_boxes(), self.faces_at(tick))

    def showcase_states(self) -> list:
        """[(libellé, état)] montrés sur la planche de revue (10 au plus)."""
        s = self.shape
        if s == "stairs":
            states = [{"facing": "north", "half": "bottom", "shape": k}
                      for k in ("straight", "inner_left", "inner_right", "outer_left", "outer_right")]
            states += [{"facing": "north", "half": "top", "shape": "straight"},
                       {"facing": "east", "half": "bottom", "shape": "straight"}]
        elif s == "button":
            states = [{"face": f, "facing": "north", "powered": "false"} for f in ("floor", "wall", "ceiling")]
            states += [{"face": "floor", "facing": "north", "powered": "true"},
                       {"face": "wall", "facing": "east", "powered": "false"}]
        elif s == "fence_gate":
            states = [{"facing": "north", "in_wall": w, "open": o} for w in ("false", "true") for o in ("false", "true")]
            states.append({"facing": "east", "in_wall": "false", "open": "true"})
        elif self.shape == "wall":
            n = {d: "none" for d in DIRS}
            states = [{"up": "true", **n}, {"up": "true", **n, "north": "low"}, {"up": "true", **n, "north": "tall"}]
            for h in ("low", "tall"):
                states += [{"up": "false", **n, "north": h, "south": h}, {"up": "true", **n, "north": h, "east": h},
                           {"up": "true", **n, "north": h, "east": h, "west": h}]
            states.append({"up": "true", **{d: "low" for d in DIRS}})
        elif self.shape == "fence":
            f = {d: "false" for d in DIRS}
            states = [f, {**f, "north": "true"}, {**f, "north": "true", "south": "true"},
                      {**f, "north": "true", "east": "true"}, {**f, "north": "true", "east": "true", "west": "true"},
                      {d: "true" for d in DIRS}]
        else:
            states = self.all_states()
        return [(self.state_label(st), st) for st in states[:10]]

    def state_label(self, state: dict) -> str:
        """Libellé court d'un état pour la planche (« north · bottom · outer_left », « poteau · N bas »)."""
        words = []
        for k in PROPERTIES[self.shape]:
            v = state[k]
            if k in DIRS and self.multipart:
                if v in ("low", "true"):
                    words.append(k[0].upper() + (" bas" if v == "low" else ""))
                elif v == "tall":
                    words.append(k[0].upper() + " haut")
            elif v == "true":
                words.append({"up": "poteau", "in_wall": "dans un mur", "open": "ouvert", "powered": "enfoncé"}.get(k, k))
            elif v not in ("false", "none"):
                words.append(v)
        return " · ".join(words) or "seul"

    def scene(self) -> tuple[list, list]:
        """Petite scène « posé dans le monde » pour la planche de revue : (positions du bloc plein,
        [(position, état)]) en blocs, sol de 3 × 3 compris."""
        floor = [(x, -1, z) for x in range(3) for z in range(3)]
        s = self.shape
        if s == "slab":
            return floor + [(0, 0, 0)], [((1, 0, 0), {"type": "bottom"}), ((2, 0, 0), {"type": "double"}),
                                          ((1, 0, 1), {"type": "top"}), ((0, 0, 1), {"type": "bottom"})]
        if s == "stairs":
            return floor, [((0, 0, 0), {"facing": "north", "half": "bottom", "shape": "outer_left"}),
                           ((1, 0, 0), {"facing": "north", "half": "bottom", "shape": "straight"}),
                           ((2, 0, 0), {"facing": "north", "half": "bottom", "shape": "outer_right"}),
                           ((0, 0, 1), {"facing": "west", "half": "bottom", "shape": "straight"}),
                           ((2, 0, 1), {"facing": "east", "half": "top", "shape": "straight"})]
        if s == "wall":
            n = {d: "none" for d in DIRS}
            return floor, [((0, 0, 0), {"up": "true", **n, "east": "low", "south": "low"}),
                           ((1, 0, 0), {"up": "false", **n, "east": "low", "west": "low"}),
                           ((2, 0, 0), {"up": "true", **n, "west": "low"}),
                           ((0, 0, 1), {"up": "false", **n, "north": "tall", "south": "tall"}),
                           ((0, 0, 2), {"up": "true", **n, "north": "tall"})]
        if s == "fence":
            f = {d: "false" for d in DIRS}
            return floor, [((0, 0, 0), {**f, "east": "true", "south": "true"}),
                           ((1, 0, 0), {**f, "east": "true", "west": "true"}),
                           ((2, 0, 0), {**f, "west": "true"}),
                           ((0, 0, 1), {**f, "north": "true", "south": "true"}),
                           ((0, 0, 2), {**f, "north": "true"})]
        if s == "fence_gate":
            return floor, [((0, 0, 0), {"facing": "south", "in_wall": "false", "open": "false"}),
                           ((1, 0, 0), {"facing": "south", "in_wall": "false", "open": "true"}),
                           ((2, 0, 1), {"facing": "east", "in_wall": "false", "open": "false"})]
        if s == "button":
            # bouton mural sur la face nord du bloc (visible sous l'angle d'inventaire), deux au sol devant
            return floor + [(1, 0, 1)], [((1, 0, 0), {"face": "wall", "facing": "north", "powered": "false"}),
                                         ((0, 0, 0), {"face": "floor", "facing": "north", "powered": "false"}),
                                         ((2, 0, 1), {"face": "floor", "facing": "east", "powered": "true"})]
        return floor, [((0, 0, 1), {"powered": "false"}), ((2, 0, 1), {"powered": "true"})]

    def scene_quads(self, tick: float = 0) -> list:
        from .render import cube_quads
        blocks, placed = self.scene()
        faces = self.faces_at(tick)
        q = []
        for pos in blocks:
            q += cube_quads(faces, offset=np.array(pos, float) * 16)
        for pos, state in placed:
            q += [x.translated(np.array(pos, float) * 16) for x in self.state_quads(state, tick)]
        return q


def _when_ok(when, state: dict) -> bool:
    return not when or all(str(state.get(k)) == v for k, v in when.items())

