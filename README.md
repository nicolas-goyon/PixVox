# pixvox

Atelier pixel-art / voxel-art pour Minecraft Java, piloté par code : rendu fidèle au jeu, analyse,
resource packs vérifiés pixel par pixel et mods Fabric / NeoForge — utilisable par des agents, des
humains ou d'autres logiciels.

> Ce dépôt se construit par une pile de PR ; la documentation complète arrive dans la PR « Docs ».

## Développement

```bash
python -m pip install -e ".[dev]"     # Python ≥ 3.10 (numpy, Pillow)
ruff check .                          # lint
python -m pytest -q                   # tests (ou python tests/run.py, sans pytest)
```

La CI (`.github/workflows/ci.yml`) relance le lint et les tests sur Linux (Python 3.10 → 3.14),
Windows et macOS à chaque PR.
