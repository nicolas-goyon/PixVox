# Claude Code — PixVox

Les consignes du dépôt sont dans AGENTS.md (communes à tous les agents) :

@AGENTS.md

Mode d'emploi détaillé de l'outil (repères d'orientation, API, recettes, pièges vérifiés dans le jar
de Minecraft 26.3) : `SKILL.md`, à lire avant de dessiner un asset. Le skill de projet
`.claude/skills/pixvox` y renvoie automatiquement quand la tâche concerne des assets Minecraft.

Rappels propres à Claude :
- en début de session : `python -m pip install -e ".[dev]"` puis `pixvox doctor --json` ;
- un asset n'est réussi qu'après lecture de sa planche avec l'outil Read (`out/<nom>.review.png`) ;
- un GIF ne se lit pas : regarder la planche d'animation `out/<nom>.anim.png`, livrer le GIF à l'humain.
