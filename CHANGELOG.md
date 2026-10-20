# Journal des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions
[SemVer](https://semver.org/lang/fr/). Le workflow « Release » reprend la section de la version publiée.

## [Non publié]

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
