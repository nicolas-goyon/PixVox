# Journal des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions
[SemVer](https://semver.org/lang/fr/). Le workflow « Release » reprend la section de la version publiée.

## [Non publié]

## [0.3.0]

### Ajouté

- Variantes de construction (#22) : `bloc.variants("slab", "stairs", "wall", "fence", "fence_gate", "button",
  "pressure_plate")` (toutes si rien n'est donné), classe `Variant`, liste `SHAPES`. Géométries et propriétés
  des blocs vanilla (escalier : `facing`, `half`, `shape` ; mur : côtés `none`/`low`/`tall` et `up`…). Les
  textures sont celles du bloc plein, projetées : chaque élément montre ce que le bloc plein montre à cet
  endroit, dans la direction où il regarde. Les modèles sont donc écrits déjà orientés (un par géométrie,
  sans rotation de blockstate ni `uvlock`) : la bonne face du volume dans chaque orientation, même quand ses
  six faces diffèrent. Blockstates à variantes, multipart pour le mur et la barrière ; objets sur les modèles
  d'inventaire. Les deux cibles (`1.21.4+`, `1.21.1`). La vérification relit chaque état du blockstate (17
  configurations pour le mur) en plus de l'objet ; un test compare la géométrie de l'escalier et du bouton
  aux blockstates vanilla. Planche : objet, scène posée sur le bloc plein, états caractéristiques. Nouveau
  `kind` JSON : `variant` (`details.shape`, `base`, `models`, `states`). `--replace` refuse les variantes
  (code 1) ; un bloc à surcouche lumineuse ne se décline pas. Exemple : `examples/mossy_stone_family.py`.
- Variantes dans les mods (#22) : vrais blocs vanilla (`SlabBlock`, `StairBlock`, `WallBlock`, `FenceBlock`,
  `FenceGateBlock`, `ButtonBlock`, `PressurePlateBlock` ; sous-classes générées pour les constructeurs
  protégés), Fabric et NeoForge 26.3, NeoForge 1.21.1. Tags de blocs et d'objets (`slabs`, `stairs`, `walls`,
  `fences`… et `wooden_*` pour un bloc qui sonne comme du bois : le mur et la barrière ne se raccordent qu'aux
  blocs de leur tag). Dalle double : 2 dalles (table de butin au format de chaque version). Recettes de
  taille depuis le bloc plein s'il est dans le mod (dalle × 2). Escalier : état du bloc plein, ou de la
  pierre s'il est absent. Bouton et plaque : sans collision, résistance 0,5 ; bois : déclenchés par tout et
  30 ticks, sinon par les créatures seulement et 20 ticks. Noms affichés tirés du bloc plein (« Dalle de … »).
  Le test JUnit vérifie chaque variante : classe vanilla, et chaque propriété du blockstate écrit existe dans
  le jeu avec les mêmes valeurs. Géométrie des 263 états comparée aux blocs vanilla du jar 1.21.1 : identique
  (l'objet de la barrière garde ses traverses dans le bloc).
- `ModelLoader.blockstate_quads` lit aussi les blockstates à variantes.
- Teinte de biome (#23) : `tint="grass" | "foliage" | "water"` et `tinted=masque` (tout le volume sinon) sur
  `Block` et `Model`, module `pixvox.tint` (couleurs de référence de 8 biomes, `apply_tint`). Les voxels teintés
  se peignent en gris. Bloc : `tintindex` sur une face entièrement teintée, surcouche teintée (pixels teintés
  seulement) sur une face mixte, comme le liseré de l'herbe vanilla (`render_type` cutout en 1.21.1). Modèle :
  éléments teintés à part. Objet : `tints` de la définition d'item (1.21.4+), comme le bloc d'herbe et les
  feuilles vanilla. `ModelLoader(tint=…)` applique la couleur aux faces à `tintindex` : la vérification
  compare à la couleur de la plaine (et voit une teinte oubliée). Planche du bloc dans trois biomes, vues et
  taille réelle teintées, analyse (voxels teintés gris et assez clairs), `pixvox view --biome`. JSON :
  `details.tint`, `tint_faces` / `tinted_elements`. Sans mod, l'export rappelle que seul `--replace` sur un
  bloc vanilla teinté affiche la couleur ; les variantes d'un bloc teinté sont refusées. Exemples :
  `examples/meadow_grass.py` (herbe), `examples/willow_leaves.py` (feuillage).
- Textures vanilla de référence (#24) : `pixvox vanilla [--mc 26.3|1.21.1]` télécharge le jar client de la
  version (manifeste piston-meta de Mojang, SHA-1 vérifié), en garde les textures de blocs dans un cache local
  (`$PIXVOX_CACHE`, sinon le cache de l'utilisateur) et supprime le jar ; ensuite tout marche hors ligne. Les
  matériaux sont les textures que le jeu pose sur un cube plein (lues dans ses modèles). Analyse : matériaux
  vanilla les plus proches, et « N % plus clair / plus saturé que stone » face aux voisins (`--neighbors`, sinon
  les deux plus proches pour un bloc). Planche : rangée « dans le monde », l'asset posé entre deux blocs du
  jeu. `ramp_from_vanilla("stone")` : rampe tirée d'une texture du jeu. Sans cache, rien ne change (aucun
  téléchargement implicite) ; les textures ne vont jamais dans un pack ou un mod (droits de Mojang). Tests
  sur un faux serveur Mojang local, plus un test du vrai manifeste (sauté sans réseau).
- Couleurs de biome dans les mods (#23), côté client seulement : 26.3, `BlockTintSources.grass()` / `foliage()` /
  `water()` enregistrées par `BlockColorRegistry` (Fabric, point d'entrée `client`) ou
  `RegisterColorHandlersEvent.BlockTintSources` (NeoForge), la teinte des objets venant de `items/<nom>.json` ;
  1.21.1, `BlockColor` (`BiomeColors.getAverage…Color`, couleur par défaut hors du monde) et `ItemColor`. Le
  point d'entrée NeoForge reçoit `Dist` et n'appelle le code client que sur le client. Noms vérifiés par
  javap dans les jars des deux versions ; un mod sans bloc teinté ne change pas.

## [0.2.0]

### Ajouté

- Cible d'export Minecraft 1.21.1 (NeoForge 21.1) : `pixvox export … --mc 1.21.1`, `export_pack(…, mc="1.21.1")`
  (#18). `pack.mcmeta` au format 34 (datapack 48), `models/item/<nom>.json` au lieu du dossier `items/`,
  lumière des éléments en `neoforge_data`, plus de `shade_direction_override`, `render_type` dès qu'une
  face a de la transparence (surcouche lumineuse comprise), plan dont l'angle n'est pas multiple de 22,5°
  refusé (code 1), tests sans mod par le papier et `custom_model_data`, `--replace` adapté.
- API publique `pixvox.verified(info)` : vrai si un asset rendu par `export_pack` est fidèle (#32).
- Rangement des textures de blocs : `pixvox export … --textures folders`, `export_pack(…, textures="folders")`
  (#31). Un dossier par modèle (`textures/block/<modèle>/atlas.png`, `glow.png`…) ; le champ JSON `textures`
  indique le rangement. Le rangement par défaut ne change pas.
- Blockstates `multipart` : `Multipart` et `Part` (#33). Parties selon les propriétés (valeur, liste, `OR`),
  rotation de `facing` sur chaque partie, modèle vide (`Part.empty`), modèle d'objet choisi avec `display`.
  La vérification relit le blockstate (jusqu'à 16 ensembles de parties, le plus grand dans chaque
  direction) ; la planche les montre. Nouveau `kind` JSON : `multipart`. `pixvox mod` refuse ce type d'asset (code 1).
- Mods NeoForge pour Minecraft 1.21.1 : `pixvox mod … --loader neoforge --mc 1.21.1`, `export_mod(…, mc="1.21.1")`
  (#20). NeoForge 21.1, JDK 21, ressources et tables de butin au format 1.21.1, mêmes fonctions qu'en 26.3.
  Le résultat JSON indique `mc` ; `pixvox doctor` dit dans `mod_build.targets` quel JDK chaque cible exige.
- `pixvox.mcmodel` lit les fichiers comme 1.21.1 (`ModelLoader(mc="1.21.1")`, `render-model --mc 1.21.1`) :
  `neoforge_data`, couche de rendu de `render_type`, champs inconnus de 1.21.1 ignorés comme le fait le
  jeu, modèles que le jeu refuse (`forge_data`, rotation interdite) signalés.

### Corrigé

- Un volume qui mélange voxels semi-transparents et opaques se vérifie à 0 px (`Model`, `MultiBlock` et sa
  miniature, les deux cibles) (#21). Un voxel opaque se voit à travers un voxel semi-transparent
  (`Volume.m_visible`), une boîte ne réunit plus les deux opacités, une face translucide ne montre plus sa
  partie cachée, et le rendu mélange les faces translucides pixel par pixel : l'image ne dépend plus du
  découpage en quads. Les fichiers d'un volume opaque ne changent pas.
- Les PNG livrés (textures, `pack.png`, icône du mod, `Anim.save`, `Sprite.save` en `.png`) sont identiques
  octet pour octet sur toutes les machines (#41). pixvox les encode lui-même (`pixvox.png`, numpy seul) au
  lieu de passer par le zlib de la machine, qui changeait les octets à pixels identiques (zlib-ng, par
  exemple). Taille comparable. **Tous les PNG exportés changent une fois** : un projet qui versionne ses
  textures pixvox doit les régénérer en passant à cette version. Les planches de revue ne changent pas.

### Modifié

- Contrat JSON `pixvox.result/2` : `export` indique la version visée (`mc`).
- La vérification d'export compare aussi deux vues de nuit (lumière des éléments, ombrage, couche de
  rendu) : `views` passe de 6 à 8 au premier instant. Les fichiers de la cible par défaut ne changent pas.

## [0.1.0]

Première version publique.

### Ajouté

- Moteur voxel-first : blocs pleins dont les 6 textures sont lues sur un volume (arêtes cohérentes par
  construction), modèles libres optimisés en éléments + atlas, objets de plusieurs blocs, items ASCII.
- Résolution libre : unités de conception (`Volume.design`), 16 / 32 / 64 voxels par bloc, mise à l'échelle,
  ré-échantillonnage.
- Animation : `Timing`, `Anim`, `fire`, `pulse`, `flow`, plans croisés, parties lumineuses (`light_emission`).
- Rendu « comme le jeu », lecteur de modèles Minecraft, planches de revue PNG / GIF, analyse.
- Export resource pack Java (1.21.4 → 26.3) vérifié par re-rendu, datapack de placement des multiblocs.
- Export en mod Minecraft 26.3 (Fabric ou NeoForge) avec test JUnit généré.
- Ligne de commande `pixvox` : `--json` (contrat `pixvox.result/1`), codes de sortie 0/1/2/3, `new`,
  `doctor`, `summary`.
- Action GitHub réutilisable, aperçu automatique des assets dans les PR, image Docker, skill Claude.
- Publication des versions depuis le site GitHub (Actions → Release → Run workflow, ou page Releases) ou
  `gh` : le numéro est contrôlé avant toute publication, les fichiers sont joints automatiquement.
- Licence MIT, déclarée dans les métadonnées du paquet (PEP 639) et du plugin Claude Code.
