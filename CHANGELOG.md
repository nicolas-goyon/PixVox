# Journal des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions
[SemVer](https://semver.org/lang/fr/). Le workflow « Release » reprend la section de la version publiée.

## [Non publié]

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
  La vérification relit le blockstate pour chaque ensemble de parties et chaque direction ; la planche les
  montre. Nouveau `kind` JSON : `multipart`. `pixvox mod` refuse ce type d'asset (code 1).
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
