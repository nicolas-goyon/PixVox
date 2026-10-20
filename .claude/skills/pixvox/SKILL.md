---
name: pixvox
description: Créer, corriger ou vérifier des assets Minecraft Java (blocs, modèles, objets de plusieurs blocs, items, textures animées) avec pixvox dans ce dépôt, puis les exporter en resource pack vérifié ou en mod Fabric / NeoForge. À utiliser dès qu'une tâche touche examples/, des textures, des blocs, des icônes ou un mod Minecraft.
---

# pixvox dans ce dépôt

1. Environnement : `python -m pip install -e ".[dev]"` puis `pixvox doctor --json` (`selftest.ok` vrai ;
   `mod_build.possible` dit si `pixvox mod --build` marchera ici).
2. Lire **`SKILL.md` à la racine du dépôt** : orientation des faces, unités, API, recettes éprouvées, pièges.
3. Boucle de travail :
   - `pixvox new <nom> --kind block|model|multiblock|item|animated --dir examples` (point de départ) ;
   - modifier le fichier, puis `pixvox review examples/<nom>.py` et **lire la planche** `out/<nom>.review.png`
     (et `out/<nom>.anim.png` si animé) avant de juger ;
   - `pixvox export examples/<nom>.py --json` : `"ok": true` et chaque asset `"verified": true` ;
   - mod : `pixvox mod examples/<nom>.py --modid <id> [--loader neoforge] --build --json`.
4. Règles du dépôt : `AGENTS.md` (ne jamais lancer Minecraft, contrat JSON stable, tests par couche).
5. Avant de rendre la main : `ruff check .` et `python -m pytest -q`.
