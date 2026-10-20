# Contribuer à pixvox

Merci ! Humains et agents suivent les mêmes règles : elles sont détaillées dans [`AGENTS.md`](AGENTS.md).

## Installation de développement

```bash
git clone https://github.com/nicolas-goyon/PixVox && cd PixVox
python -m pip install -e ".[dev]"      # Python ≥ 3.10
pixvox doctor                          # auto-test ; dit si un JDK 25 est disponible pour les mods
```

## Vérifications locales (les mêmes que la CI)

```bash
ruff check .                     # lint
python -m pytest -q              # tests (ou python tests/run.py, sans pytest)
pixvox export examples/*.py --pack out/pack --json > export.json       # "ok": true
pixvox mod examples/*.py --modid pixvox_demo --build                 # facultatif : JDK 25 + réseau Maven
```

Variable utile : `PYTHONWARNDEFAULTENCODING=1` fait échouer les tests si pixvox ouvre un fichier sans
encodage explicite (ce qui casserait Windows).

## Ce que fait la CI

| workflow | quand | jobs |
|---|---|---|
| `CI` | chaque PR et `main` | lint ; tests (Linux 3.10 → 3.14, Windows, macOS) ; export vérifié + planches des exemples ; mods Fabric et NeoForge compilés + test JUnit ; action réutilisable ; livrables (wheel, skill, pack) ; image Docker |
| `Aperçu des assets` | PR qui touche `examples/` ou `assets/` | planches + export des assets modifiés, commentaire de PR mis à jour |
| `Release` | lancement manuel (*Run workflow*) ou release publiée sur le site | contrôle du numéro ; release GitHub (wheel, sdist, skill, pack, jars), tag majeur `vX`, image `ghcr.io`, PyPI en option |

Chaque job écrit un résumé lisible (onglet *Summary*) et ses sorties en artefacts, JSON compris.

## Pile de PR

Les évolutions importantes sont découpées en PR empilées : la PR n est basée sur la branche de la
PR n − 1 et ne montre que son propre diff. Fusionner dans l'ordre, avec « Rebase and merge » ou
« Create a merge commit » (GitHub rebascule alors la PR suivante sur `main`). Après un « Squash and
merge », rebaser la suivante : `git rebase --onto origin/main <ancienne-base> <branche>`.

## Proposer un asset

`pixvox new <nom> --kind … --dir examples`, itérer avec `pixvox review`, ouvrir une PR : la CI rend
l'asset, vérifie l'export et commente la PR avec le résumé et les liens des planches.

## Publier une version

Tout peut se faire depuis le site GitHub, sans rien installer.

1. **Préparer**, sur `main` : `pixvox/__init__.py` : `__version__ = "X.Y.Z"` ; `CHANGELOG.md` : la
   section `## [Non publié]` devient `## [X.Y.Z]` (en rouvrir une vide au-dessus). Sur le site : ouvrir
   le fichier, crayon ✎, *Commit changes* (directement sur `main` ou par une PR).
2. **Publier**, au choix :

   | depuis | comment | ce qui se passe |
   |---|---|---|
   | site, onglet *Actions* (recommandé) | *Release* → *Run workflow* → cocher `publish` → *Run workflow* | tout est construit et vérifié, puis la release `vX.Y.Z` apparaît complète (environ 15 min) ; en cas d'échec, rien n'est publié |
   | site, page *Releases* | *Draft a new release* → *Choose a tag* : taper `vX.Y.Z`, *Create new tag on publish*, cible `main` → *Publish release* | la release apparaît tout de suite, ses fichiers environ 15 min plus tard ; description laissée vide : remplie avec la section du CHANGELOG et la liste des PR ; un texte écrit est gardé tel quel |
   | terminal (agent, script) | `gh workflow run release.yml -f publish=true`, suivi avec `gh run watch` ; ou `gh release create vX.Y.Z --target main --notes ""` | comme la ligne correspondante ci-dessus |

   Le tag doit valoir `v` + `__version__` : sinon le workflow s'arrête au premier job, sans rien
   construire (page *Releases* : supprimer la release et son tag, corriger, recommencer). Un tag poussé
   seul (`git push origin vX.Y.Z`) ne publie rien. *Run workflow* sans cocher `publish` construit et
   vérifie tout sans rien publier : une répétition générale.
3. **Ce que publie le workflow « Release »** : la release GitHub et ses fichiers (wheel, sdist,
   `pixvox_skill.zip`, pack de démo, mods de démo), le tag `vX` pour l'action (si le jeton GitHub en a
   le droit), l'image `ghcr.io/nicolas-goyon/pixvox`. Une version de test au sens PEP 440 (`0.2.0rc1`)
   ou une release cochée *Set as a pre-release* est marquée *pre-release* et ne touche ni `:latest`,
   ni `:X.Y`, ni `vX`.
4. **Une seule fois**, après la première version : rendre public le paquet `ghcr.io/nicolas-goyon/pixvox`
   (privé à sa création : *Packages* → `pixvox` → *Package settings* → *Change visibility*). PyPI
   (facultatif, réserver le nom tôt) : créer un *trusted publisher* (dépôt `nicolas-goyon/PixVox`,
   workflow `release.yml`, environnement `pypi`) puis la variable de dépôt `PYPI_PUBLISH=true`. Si les
   releases immuables sont activées dans les réglages du dépôt, publier par *Run workflow* : une release
   déjà publiée ne peut plus recevoir de fichiers.
