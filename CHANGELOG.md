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
- `pixvox.mcmodel` lit les fichiers comme 1.21.1 (`ModelLoader(mc="1.21.1")`, `render-model --mc 1.21.1`) :
  `neoforge_data`, couche de rendu de `render_type`, champs inconnus de 1.21.1 ignorés comme le fait le
  jeu, modèles que le jeu refuse (`forge_data`, rotation interdite) signalés.

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
