# Consignes pour les agents (et pour les humains pressés)

Ce fichier est lu par les agents de code (Claude Code via `CLAUDE.md`, Codex, Copilot, Cursor…).
Il décrit comment travailler **sur** ce dépôt et comment **utiliser** pixvox de façon fiable.

## En une phrase

pixvox décrit des assets Minecraft en Python (volumes de voxels, sprites), les rend comme le jeu,
les analyse, puis les exporte en resource pack **vérifié par re-rendu** ou en mod Fabric / NeoForge.

## Installer et vérifier l'environnement

```bash
python -m pip install -e ".[dev]"     # Python ≥ 3.10 ; numpy et Pillow seulement
pixvox doctor --json                  # selftest.ok doit être vrai ; mod_build.possible dit si --build marche
```

Sans installation (skill Claude, clone en lecture seule) : `python -m pixvox …` depuis la racine.

## Avant d'ouvrir une PR

```bash
ruff check .                                        # style (config dans pyproject.toml)
python -m pytest -q                                 # ou : python tests/run.py (sans pytest)
pixvox export examples/*.py --pack out/pack --json  # "ok": true, chaque asset "verified": true
```

La CI refait tout cela : tests sur Linux (Python 3.10 → 3.14), Windows et macOS (3.13) ; lint, export
des exemples, mods de démo compilés (Fabric et NeoForge, JDK 25, test JUnit), action, image Docker et
livrables sur Linux. Lire les résultats : `gh pr checks <n>`,
l'onglet *Summary* de chaque job, ou les fichiers `*.json` des artefacts (contrat : `docs/cli.md`).

## Carte du code

| module | rôle |
|---|---|
| `pixvox/color.py`, `noise.py` | rampes OKLab, bruits périodiques (raccords sans couture) |
| `pixvox/sprite.py`, `volume.py` | images 2D et volumes de voxels ; les faces d'un bloc sont lues sur la peau du volume |
| `pixvox/render.py`, `mcmodel.py` | rendu « comme le jeu » et lecteur de modèles JSON Minecraft (référence de toute vérification) |
| `pixvox/anim.py`, `assets.py` | animation (Timing, fire, pulse, flow) ; Block, Model, MultiBlock, Item, Props |
| `pixvox/export.py` | resource pack : optimisation en éléments, atlas, `.mcmeta`, vérification par re-rendu |
| `pixvox/analyze.py`, `review.py` | analyse (raccords, palette, boucles…) et planches de revue PNG / GIF |
| `pixvox/mod.py`, `mod_templates/` | projet de mod Gradle (Java, données 26.3, test JUnit) |
| `pixvox/cli.py`, `summary.py`, `templates/` | ligne de commande, résumés Markdown, gabarits de `pixvox new` |
| `tests/test_<couche>.py` | un fichier par couche, `testkit.py` pour les outils communs |
| `examples/` | assets de démonstration (exportés et compilés en mod par la CI) |
| `SKILL.md` | mode d'emploi de l'outil pour Claude ; copie générée pour le plugin Claude Code : `python scripts/sync_plugin_skill.py` (vérifié en CI) |

## Règles du projet

1. **Voxel d'abord.** Un bloc est un volume ; ses textures sont lues sur sa peau. Ne jamais peindre
   les 6 faces séparément (le voxel d'arête aurait deux couleurs) : `Block.from_faces(…)` détecte ces
   conflits, `fix=True` les corrige.
2. **Regarder avant d'affirmer.** Un asset n'est « réussi » qu'après lecture de sa planche
   (`pixvox review` → `out/<nom>.review.png`). Le rapport texte ne juge pas l'esthétique.
3. **Un export non vérifié est un échec.** `verified: false` ou un code de sortie 1 se corrige, il ne
   s'ignore pas.
4. **Arguments par mot-clé** pour les générateurs (`noise`, `cells`, `blobs`, `fire`…) : ils sont
   keyword-only, un appel positionnel lève `TypeError`.
5. **Contrat stable.** Les champs JSON (`docs/cli.md`) et les codes de sortie (0/1/2/3) sont une API :
   ne pas les changer sans incrémenter `schema` et mettre à jour `docs/cli.md` et les tests.
6. **Langue.** Messages, docs et commentaires en français ; identifiants JSON et noms d'assets en anglais.
7. **Ne jamais lancer Minecraft** (`runClient`, `runServer`, serveur dédié) : cela suppose d'accepter
   le CLUF de Mojang, ce qui revient à l'humain. La CI compile les mods et lance un test JUnit qui
   charge les registres du jeu sans l'ouvrir : c'est suffisant pour valider.
8. **Versions de Minecraft.** Elles sont regroupées dans `pixvox/mod.py` (`FABRIC`, `NEOFORGE`). Avant
   de les changer, vérifier les noms d'API dans le jar du jeu (`javap`) puis faire passer le job `mods`.
9. **Tests par couche.** Un test ne dépend que de ce qu'il teste (imports dans `testkit.py` paresseux) ;
   tout nouveau comportement arrive avec son test, qui doit aussi passer via `python tests/run.py`.

## Contribuer un asset

```bash
pixvox new ma_lanterne --kind model --dir examples   # block | model | multiblock | item | animated
pixvox review examples/ma_lanterne.py                # lire la planche, corriger, recommencer
pixvox export examples/ma_lanterne.py --json         # "ok": true attendu
```

Les assets du dépôt vivent dans `examples/` (un fichier par asset ou par famille, docstring qui
explique la technique). Ouvrir une PR : le workflow « Aperçu des assets » rend les planches, vérifie
l'export et publie un commentaire (mis à jour à chaque poussée) avec le résumé et les liens des
artefacts ; le job `exemples` de la CI ré-exporte toute la galerie.

## Pile de PR et fusion

Les grosses évolutions arrivent en PR empilées (chacune basée sur la précédente). Fusionner dans
l'ordre avec « Rebase and merge » ou « Create a merge commit » ; après un « Squash and merge », rebaser
la PR suivante : `git rebase --onto origin/main <ancienne-base> <branche>`.

## Publier une version

1. Mettre à jour `pixvox/__init__.py` (`__version__`) et `CHANGELOG.md` (section `## [X.Y.Z]`), sur `main`.
2. `gh workflow run release.yml -f publish=true` (sur le site : Actions → Release → Run workflow →
   cocher `publish`). Le workflow « Release » vérifie le numéro, construit et teste tout, puis crée la
   release `vX.Y.Z` avec ses fichiers. Un tag poussé seul ne publie rien. Autres façons, dont la page
   Releases du site : `CONTRIBUTING.md`.
