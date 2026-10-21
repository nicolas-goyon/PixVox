---
name: pixvox
description: "Atelier pixel-art et voxel-art pour Minecraft Java (1.21.4 → 26.3, et 1.21.1 NeoForge avec --mc 1.21.1), piloté par code. Blocs pleins dont les 6 textures sont lues sur un volume (arêtes cohérentes par construction), modèles voxel exportés en éléments optimisés, objets de plusieurs blocs (statues), résolution libre (16, 32, 64 voxels par bloc, objets décrits une fois puis mis à l'échelle), textures animées (feu, lave, braises, plans de flammes, parties lumineuses), items 16x16 en ASCII. Rendu (inventaire, dessous, monde 3x3x3, nuit, GIF), analyse texte, export resource pack vérifié par re-rendu, et export en MOD Fabric ou NeoForge 26.3 (vrais blocs : formes, lumière, particules, multiblocs posables, compilés et testés). À utiliser pour créer, corriger ou vérifier une texture, un bloc, un item, une icône, un modèle ou un mod de blocs Minecraft."
---
<!-- Fichier généré par scripts/sync_plugin_skill.py depuis SKILL.md : modifier SKILL.md, puis relancer le script. -->

# pixvox — mode d'emploi pour Claude

pixvox me donne des yeux : je décris un asset en Python, l'outil le rend comme le jeu l'affiche,
l'analyse, puis l'exporte (resource pack ou mod). Règles d'or :
- **ne jamais affirmer qu'un asset est réussi sans avoir ouvert (Read) sa planche PNG** — le rapport
  texte ne juge pas le goût, la planche si ; pour une animation, ouvrir aussi `<nom>.anim.png` ;
- **passer tous les réglages des générateurs par mot-clé** (keyword-only : un appel positionnel lève une
  TypeError au lieu de mal interpréter un nombre) ;
- exiger `vérification … : OK` à l'export (en JSON : `"verified": true`), et pour un mod
  `"build": {"ok": true, "tests": {"passed": true}}` ; un code de sortie 1 = à corriger, pas à ignorer.

## Mise en route (une fois par machine)

```bash
python -m pip install "pixvox @ git+https://github.com/nicolas-goyon/PixVox"
python -m pixvox doctor          # auto-test d'export ; dit si les mods sont compilables (JDK 25 + Maven)
```
Installé ainsi avec pip, `pixvox` et `python -m pixvox` sont équivalents (avec pipx ou `uv tool`, seule la
commande `pixvox` marche). Les fichiers d'assets et les sorties (`out/`) vont dans le projet courant.
Sources, exemples, CI : https://github.com/nicolas-goyon/PixVox (consignes : AGENTS.md).

## La boucle de travail

1. Écrire `assets/<nom>.py` qui définit `build()` → un asset ou une liste (variantes). Point de départ
   commenté : `python -m pixvox new <nom> --kind block|model|multiblock|item|animated --dir assets`.
   Noms : minuscules, chiffres et `_` (identifiants Minecraft).
2. `python -m pixvox review assets/<nom>.py` → rapport + `out/<nom>.review.png` ; **Read** la planche.
   Asset animé : aussi `out/<nom>.anim.png` (une colonne par instant, vues inventaire / en jeu / nuit) et
   `out/<nom>.anim.gif` (à donner à l'utilisateur ; je ne vois pas l'animation d'un GIF).
3. Variantes : plusieurs assets dans `build()` puis `python -m pixvox compare assets/<nom>.py --out out/cmp.png`.
4. Pixels exacts : `python -m pixvox ascii assets/<nom>.py --only <asset> --face north` (alias top/bottom).
5. Angle libre : `python -m pixvox view assets/<nom>.py --yaw 135 --pitch 20 [--shading world|night]
   [--persp 2] [--tick 6]`. Par DESSOUS toujours `--persp 1.5–2.5` (sinon illusion de Necker : l'objet
   paraît creux, « déformé »). `--shading night` : seules les faces à light_emission restent claires.
6. Resource pack : `python -m pixvox export assets/*.py --pack out/pack --zip out/pack.zip`. Un modèle que le
   jeu refuserait (élément hors de [-16, 32]) est REFUSÉ (ExportError, code de sortie 1), pas exporté.
   Pour Minecraft 1.21.1 (mod NeoForge 21.1) : `--mc 1.21.1` (`export_pack(…, mc="1.21.1")`) — fichiers
   chargés tels quels par 1.21.1 et vérifiés comme 1.21.1 les lit (voir « Pièges connus »).
7. Mod : `python -m pixvox mod assets/*.py --modid mon_mod [--loader fabric|neoforge] --build
   --java-home <JDK 25> --zip out/mon_mod_src.zip` → `out/mod_<modid>_<loader>/build/libs/<modid>-1.0.0.jar`.
8. Livrer les zips / le jar + la planche (et le GIF). `README_pixvox.txt` (pack) et `README.md` (mod)
   expliquent l'installation.

Options utiles : `--only NOM` ; `review --out DOSSIER` ; `view --size N` ; `compare --size N` ;
`export --ns NAMESPACE --replace nom=minecraft:bloc` ; `anim fichier.py` (planche + GIF seuls) ;
`render-model DOSSIER_PACK ns:block/nom [--tick T] [--shading night] [--persp 2]` relit un modèle JSON.

Résultats exploitables : ajouter `--json` à n'importe quelle commande → un seul document JSON sur la
sortie standard (journal sur stderr), codes de sortie 0 réussi / 1 vérification échouée / 2 utilisation
ou environnement / 3 interne (contrat : `docs/cli.md`). `python -m pixvox summary result.json` le résume.

## Repères à connaître par cœur

- Repère = repère des modèles : **x ouest→est, y bas→haut, z nord→sud**. `Volume(16)` : le voxel i
  occupe [i, i+1] ; primitives en coordonnées continues (centre du bloc (8, 8, 8)) ; `m_box` bornes incluses.
- Orientation des textures (= Minecraft, vue de l'extérieur, jamais en miroir) :

  | face  | colonne u (gauche→droite)    | ligne v (haut→bas)          |
  |-------|------------------------------|-----------------------------|
  | up    | x croissant (ouest à gauche) | z croissant (nord en haut)  |
  | down  | x croissant                  | z décroissant (SUD en haut) |
  | north | x décroissant (est à gauche) | y décroissant               |
  | south | x croissant (ouest à gauche) | y décroissant               |
  | west  | z croissant (nord à gauche)  | y décroissant               |
  | east  | z décroissant (sud à gauche) | y décroissant               |

- Icône d'inventaire (`display.gui` [30, 225, 0], échelle 0.625) : dessus, **EST à gauche**, **NORD à
  droite**. Dans le monde : dessus 1.0, N/S 0.8, E/O 0.6, dessous 0.5 — ne pas peindre ces ombres.
- Face avant d'un objet orienté ou d'un multibloc = côté **NORD** du volume (z = 0).
- Sprites et tranches ASCII : (x, y) = (colonne, ligne), origine en haut à gauche ; lignes de même longueur.

## Choisir la bonne construction

| besoin | outil |
|---|---|
| bloc plein (pierre, minerai, caisse, bûche, herbe) | `Block(name, Volume(16) …)` — faces lues sur la peau |
| bloc plein HD (textures 32×32) | `Block(name, Volume(32, res=32))` |
| textures existantes à vérifier / corriger | `Block.from_faces(name, {face: Sprite ou .png})`, puis `fix=True` |
| forme libre (champignon, brasero, lanterne) | `Model(name, volume)` → éléments + atlas (limite [-16, 32]) |
| objet de plusieurs blocs (statue, arbre, machine) | `MultiBlock(name, volume)` : sans limite de taille |
| même objet à plusieurs tailles / finesses | décrire en unités de conception : `Volume.design(extent, res=, scale=)` |
| animation (feu, lave, braises, runes) | liste de volumes (`v.frames(n)` + `pulse` / `flow`), `fire()` + `add_cross` |
| partie qui brille la nuit | `emissive=masque, emission=12` sur Block / Model / MultiBlock ; plans `emission=15` |
| vrai bloc (lumière, collision, particules) | `asset.props = Props(...)` puis `export_mod` |
| petit modèle perdu / trop grand dans la case | `Model(…, inventory_scale=1.6 ou 0.8, inventory_center=True)` |
| item plat / icône (animé : `Anim`) | `Item(name, Sprite.from_ascii(ART, LEGEND))` |
| bloc orientable | `states="axis"` (volume conçu debout) ou `"facing"` (face avant au NORD) |
| bordure voulue entre blocs | `seamless=False` (caisse) ou `"horizontal"` (herbe, mousse) |

## Résolution libre (« vectorisation »)

- `Volume.design(extent, res=16, scale=1.0, min_radius=0.75)` : on décrit l'objet en **unités de
  conception** (16 unités = 1 bloc à l'échelle 1) ; le même code produit l'objet à n'importe quelle
  finesse (`res` = voxels par bloc : 16 vanilla, 32/64 HD, 8 gros pixels) ou taille (`scale`). Toutes les
  primitives (`m_segment`, `m_sphere`, `m_box`, rayons, `shade(smooth=…)`, `cells(mortar_width=…)`…)
  prennent alors des unités de conception. Pour les motifs de détail : `v.DX, v.DY, v.DZ` (centres des
  voxels en unités) ; un trait d'un voxel quelle que soit la résolution : épaisseur `1 / v.vpu`.
- `min_radius` (voxels) : un doigt, une auréole ne disparaissent pas quand on réduit (figurine).
- Boîtes : en unités continues, `v.m_cuboid(lo, hi)` = [lo, hi[ (garde au moins un voxel d'épaisseur) ;
  `m_box(x0, y0, z0, x1, y1, z1)` a des bornes INCLUSES (« pixels » : couvre [x0, x1 + 1[).
- Les plans (`add_plane`, `add_cross`) sont en **unités modèle** (1/16 de bloc), pas en unités de
  conception : avec `Volume.design(…, scale=s)`, multiplier soi-même centre, y, largeur et hauteur par s.
- `v.resample(factor=0.5)` / `v.resample((sx, sy, sz))` : change la résolution d'un volume dessiné à la
  main (couleur majoritaire parmi les voxels VISIBLES de chaque zone ; `prefer_surface=False` : tous).
  Re-voxeliser la description (design) garde plus de détails.
- `Model` et `MultiBlock` prennent la résolution du volume (`voxel_size = 16 / res`). Coût : à 32 par
  bloc, ~4× plus d'éléments (la statue HD : 1209 éléments, jusqu'à 367 par partie — lourd). La miniature
  d'inventaire d'un multibloc est ré-échantillonnée à 16³ (légère). HD conseillé pour des pièces uniques.

## Animation

Minecraft n'anime que les **textures** (bande verticale d'images + `.png.mcmeta`) : la forme reste fixe.
- Volumes animés : `frames = v.frames(16)` (16 copies), modifier les couleurs image par image, puis
  `Block(name, frames, frametime=2)` / `Model(…)` / `MultiBlock(…)` ; `interpolate=True` (fondu, pour les
  lueurs lentes), `order=[0, 1, (2, 10)]` (ordre et durées). Changer la forme entre images est refusé.
- Générateurs qui bouclent exactement (mouvements entiers sur la boucle) :
  `pulse(frames, mask, ramp, *, seed, cells=3, speed=1, amplitude=0.6, variation=0.45, bias=0)` braises,
  cristaux, runes ; `flow(frames, mask, ramp, *, cells=4, octaves=2, seed, direction=(0,-1,0), cycles=1,
  morph=1, weights="bell")` lave, eau, énergie (raccord entre blocs conservé).
- Flammes 2D : `fire(16, *, h=None, frames=16, seed=0, shape="bush"|"sheet", palette=FIRE|SOUL_FIRE,
  height=0.95, width=0.86, tongues=None, base=0.55, turbulence=0.22, cycles=2, puffs=1, sparks=1,
  frametime=2)` → `Anim` cutout (alpha 0/255), liseré sombre, cœur clair en bas. `Anim(images, frametime,
  interpolate, order)`, `anim.contact()`, `anim.gif(path)`, `anim.save(png)` (bande + mcmeta),
  `Anim.from_strip(png)` (relit le .mcmeta s'il existe). frametime = entier de ticks ≥ 1.
- Plans texturés (flammes, plantes) : `m.add_cross(anim, center=(8, 8), y=8, width=12, height=15,
  planes=2|4, angle=45, emission=15)` ou `m.add_plane(…, angle=…)`. Deux faces, texture non inversée de
  chaque côté, `shade_direction_override: "up"`. Angles multiples de 22,5° (sinon 1.21.11+ seulement).
  Garder le pied des flammes DANS la vasque (sinon les coins du plan dépassent sous le bord).
- Émission : `emissive=mask, emission=12` → Model / MultiBlock : éléments séparés avec `light_emission` ;
  Block : surcouche aux mêmes coordonnées (comme le liseré de l'herbe vanilla) ne contenant que les pixels
  lumineux. Visibles la nuit (vue `night`), mais n'éclairent pas le monde : pour cela `Props(light=…)`.
- L'analyse vérifie la boucle (à-coup entre dernière et première image), le rythme, la transparence.
- Export : faces fixes → atlas `#0`, faces animées → atlas animé `#1`, plans → `#p0, #p1…` ; vérification
  à chaque début d'image (relit le `.mcmeta`).

## Export en mod (Fabric ou NeoForge, Minecraft 26.3, Java 25)

```python
m.props = Props(strength=3.5, sound="lantern", light=15, tool="pickaxe", tier=None, requires_tool=False,
                collision=True, particles="flame", particle_at=(8, 12, 8), particle_rate=0.5,
                names={"fr_fr": "Brasero", "en_us": "Brazier"})
export_mod([…], "out/mod_x", modid="mon_mod", name="Mon mod", loader="fabric"|"neoforge",
           build=True, java_home="/chemin/jdk-25", zip_path="out/mon_mod_src.zip")
```
- `Props` : `sound` parmi stone, wood, metal, glass, lantern, chain, amethyst, deepslate, deepslate_bricks,
  polished_deepslate, basalt, netherrack, nether_bricks, bone_block, calcite, tuff, copper, mud_bricks,
  gravel, sand, grass, wool, snow, moss, anvil, netherite_block, shroomlight, froglight, candle, lodestone,
  gilded_blackstone, cherry_wood, bamboo_wood, nether_wood, resin_bricks, iron, decorated_pot, heavy_core,
  slime_block, honey_block, coral_block ; `tool` : pickaxe | axe | shovel | hoe | None ; `tier` : None |
  stone | iron | diamond ; `strength` 0 = cassé d'un coup (plante).
- Block → bloc plein (`axis` : RotatedPillarBlock, `facing` : orienté) ; Model → bloc à forme libre
  (contour/collision calculés depuis les voxels, ≤ 24 boîtes, coupés à la hauteur du bloc : au-delà
  d'un bloc de haut, faire un MultiBlock ; les plans n'ont pas de forme), lumière,
  particules (`flame`, `soul`, `smoke`, `campfire`, `lava`, `spark`, `glow`, `end_rod`, `portal`,
  `enchant`, `ash`, `firefly`, `small_flame`, `copper_flame`) ; MultiBlock → UN bloc à propriétés
  `facing` + `part` : posé d'un coup si la place est libre (face avant vers le joueur), retiré d'un coup,
  un seul objet lâché (par la partie d'ancrage, en bas au centre), immobile pour les pistons ; Item → item.
- Généré : code Java (`ModContent.java` + classes de blocs), ressources du pack (mêmes fichiers, vérifiés),
  tables de butin au **format 26.3** (`"condition": {"type": …}`, `minecraft:match_block`), tags d'outil,
  noms en_us/fr_fr, onglet créatif, icône, Gradle wrapper, README, **test JUnit** qui charge les registres
  du jeu avec le mod (sans ouvrir le jeu) et vérifie chaque bloc, lumière, formes et géométrie des multiblocs.
- `build=True` exige un JDK 25 et le réseau (Maven Fabric/NeoForge/Central). Première construction
  NeoForge : décompilation de Minecraft (~5 min, ~4 Go de RAM). Sans JDK 25 ou sans accès à ces dépôts :
  livrer le zip des sources (`--zip`) ; l'utilisateur compile chez lui avec `./gradlew build` (README). Ne jamais lancer `runClient` / `runServer`
  moi-même (CLUF de Minecraft : c'est à l'utilisateur de lancer le jeu).
- Versions figées dans `pixvox/mod.py` (`FABRIC`, `NEOFORGE`) ; pour une autre version de Minecraft,
  les mettre à jour et vérifier les noms d'API dans le jar (javap). modid réservés refusés (minecraft,
  fabric, neoforge…). Le projet est recréé à chaque export : un dossier par chargeur.

## Aide-mémoire API (signatures réelles ; `*` = la suite est keyword-only)

```python
from pixvox import *     # Volume, Sprite, Block, Model, Item, MultiBlock, Props, Anim, fire, pulse, flow…

ramp(base, n=5, spread=0.4, hue_shift=16, tint=0.012, base_index=None, warm=85, cool=268,
     dark_chroma=-0.25, light_chroma=-0.35)           # sombre -> clair ; ombres froides, lumières chaudes
Ramp([...])  ramp_between(c1, c2, n)   R[0] R.mid R[-1] R.at(t) R.step(i)   FIRE SOUL_FIRE EMBER SOUL_EMBER
mix(a, b, t)  adjust(c, dL=0, dC=0, dh=0, mulC=1)  lighten(c, x)  darken(c, x)  delta_e(a, b)  hexa(c)

v = Volume(sx=16, sy=None, sz=None, fill=None, res=16)   # v.data (sx, sy, sz, 4) uint8 ; alpha 0 = vide
v = Volume.design(extent, res=16, scale=1.0, fill=None, min_radius=0.75)   # unités de conception
# --- masques (booléens, combinables & | ~)
v.m_box(x0,y0,z0, x1,y1,z1)  v.m_cuboid(lo, hi)  v.m_sphere(c, r)  v.m_ellipsoid(c, radii, wrap=False, rotation=(yaw,pitch,roll))
v.m_cylinder(center2d, r, lo, hi, axis="y")  v.m_segment(a, b, r0, r1=None)  v.m_tube([p…], radii)
v.m_torus(c, R, r, axis="y")  v.m_shell(depth=1)  v.m_layer(face, depth=1, offset=0)  v.m_edges(width=1)
v.m_corners(size=1)  v.m_surface()  v.m_exposed(face)  v.m_hidden()  v.m_dilate(mask, steps=1, wrap=False)
v.m_noise(threshold=0.5, *, cells=4, octaves=2, seed=0, mask=None)
v.X v.Y v.Z (indices)  v.DX v.DY v.DZ (unités de conception)  v.solid  v.vpu  v.res
# --- écriture
v.set(mask, couleur | tableau)  v.fill(c)  v.clear(mask)  v.box(…, c)  v.sphere(c, r, col)
v.tint(mask, color, t=0.5)  v.adjust(mask, dL=0, dC=0, dh=0, mulC=1)  v.shift_ramp(mask, R, steps)
# --- générateurs (périodiques sur la taille du volume)
v.noise(R, *, cells=4 | (cx,cy,cz), octaves=2, seed=0, mask=None, weights="bell"|"flat"|[..], persistence=0.5)
joints = v.cells(R, *, count=14, seed=0, mask=None, mortar=None, mortar_width=0.9, light=…, relief=0.55,
                 tone_range=(0.3,0.7), edge_shadow=0.0)            # pavés 3D -> masque des JOINTS
ore = v.blobs(R, *, count=6, radius=(1.4,2.4), seed=0, mask=None, on_edges=1, on_corners=0, wrap=True,
              rim=0.78, depth=(0,0.9), bumpiness=0.25, rim_color=None)   # -> masque peint
top = v.cap(R, *, depth=(1,4), seed=0, cells=4, octaves=2, color_cells=4, mask=None, shadow=True)
v.shade(mask, R, *, light=(-0.4,1,-0.3), contrast=1.0, bias=0.0, smooth=2, noise=0.0, seed=0, ao=0.0)
v.paint_face(face, sprite, inset=0, at=(0, 0))   v.face(f)  v.faces()  v.frames(n)  v.resample(...)
Volume.from_slices([ascii bas -> haut], legend)  v.to_slices_ascii()  v.rotate_y(k)  v.mirror("x")  v.copy()

s = Sprite(w=16, h=None, fill=None)     Sprite.from_ascii(art, legend, transparent=". ", pad=False)
Sprite.from_levels(levels, R)  s.rect  s.line  s.ellipse  s.flood  s.outline(c)  s.bevel(hi, lo)  s.noise(R, *, …)

Block(name, volume | [volumes], render_type=None, seamless=True, states=None, frametime=2, interpolate=False,
      order=None, emissive=None, emission=15)
Block.from_faces(name, {face: Sprite|ndarray|png}, fix=False, …)   Block.from_textures(name, all=… | side=…, end=…)
Model(name, volume | [volumes], voxel_size=None, origin=None, ambient_occlusion=True, states=None,
      inventory_scale=None, inventory_center=False, frametime=2, interpolate=False, order=None,
      emissive=None, emission=15)       m.add_plane(tex, *, center, y, width, height, angle, emission, shade)
                                        m.add_cross(tex, *, center, y, width, height, planes=2, angle=45, emission)
MultiBlock(name, volume | [volumes], ambient_occlusion=True, frametime=2, …, emissive=None, emission=15)
Item(name, Sprite | Anim)
asset.props = Props(...)   asset.quads(tick)   asset.volume_at(tick)

review(asset, out_dir="out")   animate(asset, out_dir)   compare([a, b], "out/cmp.png", size=300)
view(asset, yaw, pitch, size=600, shading="gui"|"world"|"night"|"flat", out_dir="out", persp=0.0, tick=0)
export_pack([...], root="out/pack", namespace="pixvox", zip_path=None, replace={"nom": "minecraft:stone"})
export_mod([...], out, modid, name=None, *, loader="fabric", build=False, java_home=None, zip_path=None)
perlin(shape, cells=4, seed=0, octaves=1)   # shape 2D, 3D… ou 4D (x, y, z, temps) : périodique partout
```

## Recettes éprouvées (voir examples/)

- **Minerai** (`lumenite_ore.py`) : `noise(STONE, cells=3, octaves=3)` + `blobs(ORE, count=5, on_edges=1)`
  + `tint(v.m_dilate(ore, wrap=True) & ~ore, ORE[1], 0.3)`.
- **Caisse / machine** (`reinforced_crate.py`) : panneaux `paint_face(f, sp, at=(2,2))`, cadre éclairé en
  3D, `seamless=False`.
- **Herbe / mousse** (`mossy_stone.py`) : `cap(MOSS, depth=(1,4))` + `seamless="horizontal"`.
- **Bûche** (`ashen_log.py`) : cernes + écorce `noise(cells=(6,1,6))`, `states="axis"`.
- **Modèle organique** (`glowcap.py`) : ellipsoïdes, `shade(noise=0.1–0.2)`.
- **Item** (`lumenite_shard.py`) : ASCII, contour très sombre teinté, lumière haut-gauche.
- **Statue** (`angel_statue.py`) : décrite une fois en unités (48 × 56 × 16) → `MultiBlock` 3 × 3,5 × 1
  blocs à res 16 et 32, et figurine d'un bloc (`scale=16/56`) ; cônes/capsules, ailes en ellipsoïdes
  inclinés, auréole reliée par une tige, `shade(ao=0.7)`.
- **Brasero animé** (`brazier.py`) : vasque évasée + 4 pieds (`m_tube`), braises `pulse` lumineuses
  (`emissive`, `emission=12`), flammes `fire()` sur 4 plans (`add_cross` X puis +, deux graines),
  `Props(light=15, particles="flame")` ; variante âmes (SOUL_FIRE).
- **Bloc de lave animé** (`magma_core.py`) : `cells` (dalles) puis `flow` dans les joints, 16 images.

## Qualité pixel-art (ce que l'analyse vérifie, et ce qu'elle ne voit pas)

- Palettes : 8–24 couleurs par bloc, rampes de 4–5 tons ; fusionner les quasi-doublons signalés.
- Bruit en amas : `octaves` 2–3, `weights="bell"`, `spread` 0.12–0.2 pour une pierre.
- Raccords : alerte si > 60 % du bord rompt ET la rupture dépasse les transitions voisines. Motif déjà
  périodique mais alerte quand même = la transition la plus nette tombe pile au bord : changer `seed`.
- Feu / lave : fort contraste voulu ; l'alerte « granuleux » peut alors être ignorée après avoir regardé.
- Items : contour sombre continu, lumière haut-gauche, rien de semi-transparent, lisible sur #8b8b8b.

## Pièges connus (vérifiés dans le jar de 26.3)

- Élément de modèle : `light_emission` (0–15, depuis 1.21.2), rotation d'angle libre depuis 1.21.11
  (avant : -45/-22,5/0/22,5/45), `shade` remplacé en 26.3 par `shade_direction_override` (l'export écrit
  les deux, les versions ignorent ce qu'elles ne connaissent pas).
- 26.x : la couche de rendu (solide/cutout/translucide) est déduite **par face** de la transparence des
  textures ; plus de `render_type` ni de BlockRenderLayerMap à déclarer. Conséquence : la surcouche
  lumineuse d'un `Block(…, emissive=…)` s'affiche bien en 26.x ; avant 26.x il faut un bloc en rendu
  cutout (sinon toute la face paraît éclairée) — l'export l'annonce par une ligne ATTENTION.
- Une source de lumière entièrement enfermée (cage pleine) n'a aucune face visible : l'analyse dit
  « 0 éléments light_emission » et « rien ne bouge » — ouvrir la cage (barreaux, vitre).
- Tables de butin 26.3 : `"condition": {"type": "minecraft:survives_explosion"}` (plus de liste
  `conditions`), état de bloc par `minecraft:match_block`.
- `item_display` (tests sans mod, datapack des multiblocs) : modèle tourné de 180° autour de y depuis
  1.20 ; les commandes générées compensent avec `Rotation:[180f,0f]` — la garder.
- `pack.mcmeta` : min 46 (1.21.4) → max 97 (26.3).
- Un `Model` doit tenir dans [-16, 32] ; au-delà, `MultiBlock`. Une partie > 150 éléments est lourde.
- `--replace` : seulement des blocs vanilla sans propriétés. Pour tester un modèle lumineux sans mod :
  `--replace nom=minecraft:torch` (sans propriétés, lumière 14, rendu cutout) ; un vrai bloc = un mod.

## Repères 1.21.1 (`--mc 1.21.1`, vérifiés dans le jar 1.21.1 et les sources de NeoForge 21.1)

- `pack.mcmeta` : format 34 (datapack 48, dossier `function/`). Pas de dossier `items/` ni de composant
  `item_model` : un item = `models/item/<nom>.json` (parent : le modèle du bloc) ; `custom_model_data` est
  un entier et sert aux `overrides`.
- Élément : `from`, `to`, `rotation`, `faces`, `shade` (vanilla) + `neoforge_data` (NeoForge). Ni
  `light_emission` ni `shade_direction_override` : la lumière devient `"neoforge_data": {"block_light": n,
  "sky_light": n}` (lue par NeoForge seulement : vanilla et Fabric affichent sans lueur, l'export le dit
  par une ligne ATTENTION). `forge_data` fait échouer le chargement : ne jamais l'écrire.
- Rotation d'élément : -45, -22,5, 0, 22,5 ou 45° seulement ; un plan à un autre angle refuse l'export.
- Couche de rendu : `render_type` (NeoForge ; absent = solide, l'alpha ne compte pas), écrit dès qu'une
  face a de la transparence, surcouche lumineuse d'un `Block` comprise (`minecraft:cutout`). Sous
  Fabric, la couche se déclare dans le mod.
- Tests sans mod : le papier porte chaque modèle (`assets/minecraft/models/item/paper.json`),
  `/give @s minecraft:paper[minecraft:custom_model_data=N]`, N stable (tiré du nom) et listé dans
  `README_pixvox.txt` ; `--replace` écrit `models/item/<bloc>.json`.
- Dans un mod NeoForge 1.21.1 : copier `assets/<ns>/` (modèles, textures, blockstates, `models/item`) dans
  les ressources du mod. `pixvox mod` produit des mods 26.3.

## Tester en jeu

Sans mod (1.21.4+ ; en 1.21.1 : `/give @s minecraft:paper[minecraft:custom_model_data=N]`, voir le
`README_pixvox.txt` du pack) :
```
/give @s minecraft:stone[minecraft:item_model="pixvox:<nom>"]
/execute align xyz run summon minecraft:item_display ~0.5 ~0.5 ~0.5 {Rotation:[180f,0f],item:{id:"minecraft:stone",count:1,components:{"minecraft:item_model":"pixvox:<nom>"}}}
```
Multibloc sans mod : copier `<pack>_datapack` dans `saves/<monde>/datapacks/`, `/reload`, puis
`/function pixvox:place/<nom>` / `/function pixvox:remove/<nom>`.
Avec le mod : jar dans `mods/` (+ Fabric API pour Fabric), blocs dans l'onglet créatif du mod ou
`/give @s <modid>:<nom>`.
