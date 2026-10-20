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
| `Release` | tag `vX.Y.Z` | release GitHub (wheel, sdist, skill, pack, jars), tag majeur `vX`, image `ghcr.io`, PyPI en option |

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

1. `pixvox/__init__.py` : `__version__ = "X.Y.Z"` ; `CHANGELOG.md` : nouvelle section `## [X.Y.Z]`.
2. Fusionner sur `main`, puis `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. Le workflow « Release » publie : release GitHub et ses fichiers, tag `vX` pour l'action (si le jeton
   GitHub en a le droit), image `ghcr.io/nicolas-goyon/pixvox`. Une version de test au sens PEP 440
   (`0.2.0rc1`, tag `v0.2.0rc1`) est marquée *pre-release* et ne touche ni `:latest` ni `vX`.
4. Une seule fois : rendre public le paquet `ghcr.io/nicolas-goyon/pixvox` (privé à sa création).
   PyPI (facultatif, réserver le nom tôt) : créer un *trusted publisher* (dépôt `nicolas-goyon/PixVox`,
   workflow `release.yml`, environnement `pypi`) puis la variable de dépôt `PYPI_PUBLISH=true`.
