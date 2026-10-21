# Ligne de commande et contrat JSON

`pixvox` s'utilise de la même façon par un humain, un agent ou un autre programme. Ce document est le
**contrat** sur lequel un programme peut s'appuyer : format de sortie `--json`, codes de sortie, et
emplacement des fichiers produits. Toute rupture de ce contrat change la valeur de `schema`.

## Installation et lancement

```bash
pip install "pixvox @ git+https://github.com/nicolas-goyon/PixVox"   # @v0.1.0 pour une version précise
pixvox --version
python -m pixvox …        # équivalent, utile sans installation (depuis un clone ou le skill)
```

## Commandes

| commande | rôle | sorties |
|---|---|---|
| `pixvox new NOM [--kind block\|model\|multiblock\|item\|animated] [--dir D]` | fichier d'asset de départ, prêt à modifier | `D/NOM.py` |
| `pixvox review F.py… [--out D] [--only NOM] [--fail-on never\|warn\|err]` | planche de revue + rapport (+ planche d'animation et GIF) | `D/<nom>.review.png`, `.report.txt`, `.anim.png`, `.anim.gif` |
| `pixvox export F.py… [--pack D] [--ns NS] [--zip Z] [--replace nom=minecraft:bloc] [--mc 1.21.4+\|1.21.1]` | resource pack Java vérifié par re-rendu, pour 1.21.4 → 26.3 (défaut) ou 1.21.1 (NeoForge 21.1) | `D/` (+ `Z`, `D_datapack/` pour les multiblocs) |
| `pixvox mod F.py… --modid ID [--loader fabric\|neoforge] [--build] [--java-home J] [--zip Z]` | projet de mod Minecraft 26.3 (+ `.jar` avec `--build`) | `out/mod_ID_LOADER/` |
| `pixvox view F.py --yaw Y --pitch P [--persp 2] [--shading gui\|world\|night\|flat] [--tick T]` | rendu à un angle libre | `out/<nom>.view_Y_P.png` |
| `pixvox anim F.py…` | images d'une animation + GIF | `out/<nom>.anim.png`, `.anim.gif` |
| `pixvox compare F.py… [--out IMG]` | variantes côte à côte | `IMG` |
| `pixvox ascii F.py [--face up\|…]` | pixels exacts en texte | (sortie standard) |
| `pixvox render-model PACK ns:block/nom [--out IMG] [--mc 1.21.4+\|1.21.1]` | aperçu d'un modèle JSON quelconque (pack fait main, Blockbench…), lu comme la version choisie | `IMG` |
| `pixvox doctor [--java-home J]` | Python, dépendances, JDK, export de test | — |
| `pixvox summary RESULT.json [--format markdown\|text]` | résumé lisible d'un résultat `--json` | (sortie standard) |

Un fichier d'asset est un script Python qui définit `build()` et renvoie un asset ou une liste
d'assets (`Block`, `Model`, `MultiBlock`, `Item`). Noms : minuscules, chiffres et `_`.

Le contrat change de numéro (`schema`) quand ses champs changent : `pixvox.result/1` pour la version
0.1.0, `pixvox.result/2` ensuite (champ `mc` du résultat d'`export`).

## Codes de sortie

| code | signification | exemples |
|---|---|---|
| `0` | réussi | tout est exporté et vérifié |
| `1` | **vérification échouée** : le travail est fait mais n'est pas bon | écart de rendu après export, asset refusé par les limites du jeu, compilation ou test JUnit du mod en échec, `--fail-on` atteint, textures manquantes (`render-model`) |
| `2` | **utilisation ou environnement** : rien n'a pu être évalué | fichier absent, `build()` qui lève une exception (ou appelle `sys.exit`), argument invalide (`--ns` hors `[a-z0-9_.-]`, taille ≤ 0…), nom introuvable avec `--only`, dossier de sortie refusé, JDK 25 absent pour `--build` |
| `3` | erreur interne de pixvox (bogue : la trace est sur la sortie d'erreur) | — |

## Mode `--json`

Avec `--json` (avant ou après la commande), la **sortie standard contient un seul document JSON** ;
le journal lisible (rapports, lignes `[export] …`) part sur la **sortie d'erreur**. Le document existe
aussi en cas d'erreur d'utilisation (code 2).

Champs communs :

```json
{
  "schema": "pixvox.result/2",
  "pixvox": "0.2.0",
  "command": "export",
  "ok": true,
  "exit_code": 0,
  "errors": [],
  "warnings": [],
  "seconds": 3.42
}
```

- `errors[]` : `{"type", "message", …}` avec `type` parmi `usage`, `input`, `asset_code`, `output_dir`,
  `refused`, `verification`, `quality`, `build`, `environment`, `missing_texture`, `selftest`, `internal` ;
  selon le cas `file`, `asset`, `log`.
- Dossiers de sortie : un dossier de pack ou de mod est **recréé** à chaque export ; pixvox ne vide qu'un
  dossier vide ou qu'il a lui-même créé (fichier `.pixvox`), sinon erreur `output_dir` (code 2) : `--pack .`
  ne peut pas effacer votre dossier de travail.
- Les chemins sont écrits avec des `/`, relatifs au dossier courant si on les a donnés ainsi.
- `kind` d'un asset : `block`, `model`, `multiblock` ou `item` (identifiants stables, en anglais).

### `export`

```json
{
  "pack": "out/pack", "zip": "out/pack.zip", "datapack": null, "datapack_zip": null, "namespace": "pixvox",
  "mc": "1.21.4+",
  "assets": [
    {"name": "lumenite_ore", "kind": "block", "file": "examples/lumenite_ore.py",
     "model": "pixvox:block/lumenite_ore", "verified": true,
     "verify": {"diff_px": 0, "views": 8, "ticks": 1, "missing": []},
     "warnings": ["…"], "details": {"elements": 2, "layout": "…", "glow_faces": 6}}
  ],
  "refused": [{"name": "trop_grand", "file": "…", "message": "… hors des limites [-16, 32] …"}]
}
```

`verified` est vrai quand le modèle et les textures **relus sur disque** et rendus comme le jeu
donnent exactement l'image de l'asset (0 pixel d'écart : 6 angles et 2 vues de nuit, puis 3 angles à
chaque image d'animation). `views` compte les vues comparées.

`mc` : version de Minecraft visée (`--mc`). `1.21.4+` (défaut) : formats 46 → 97, définitions d'items
(`items/`), `light_emission`. `1.21.1` (NeoForge 21.1) : format 34 (datapack 48), `models/item/<nom>.json`
au lieu de `items/`, lumière des éléments en `neoforge_data`, `render_type` dès qu'une face a de la
transparence, rotations limitées à -45 … 45° par pas de 22,5 (plan dont l'angle n'est pas multiple de
22,5° : asset refusé, code 1), et
`assets/minecraft/models/item/paper.json` qui porte chaque modèle par `custom_model_data` (tests sans mod ;
`details.custom_model_data`). Dans les deux cas, la vérification relit les fichiers comme la version
visée les lit.

### `review`

```json
{"assets": [{"name": "brazier", "kind": "model", "file": "examples/brazier.py", "animated": true,
             "sheet": "out/brazier.review.png", "report_file": "out/brazier.report.txt",
             "anim_sheet": "out/brazier.anim.png", "anim_gif": "out/brazier.anim.gif",
             "counts": {"OK": 9, "INFO": 7, "WARN": 0, "ERR": 0},
             "findings": [{"level": "OK", "topic": "Export", "message": "…"}]}]}
```

`level` : `OK`, `INFO`, `WARN`, `ERR`. Par défaut les alertes ne changent pas le code de sortie ;
`--fail-on warn` (ou `err`) les transforme en échec (code 1), utile en CI.

### `mod`

```json
{"project": "out/mod_demo_fabric", "loader": "fabric", "modid": "demo", "zip": null,
 "jar": "out/mod_demo_fabric/build/libs/demo-1.0.0.jar",
 "build": {"java_home": "…", "java_version": 25, "ok": true, "log": "…/build_log.txt",
           "tests": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0, "passed": true}},
 "assets": [ … comme pour export … ]}
```

Sans `--build`, `jar` et `build` valent `null`. Le test JUnit généré démarre les registres de
Minecraft avec le mod (sans ouvrir le jeu) et vérifie chaque bloc.

### `doctor`

```json
{"python": {"version": "3.13.1", "ok": true, "required": ">=3.10"},
 "packages": {"pixvox": "0.1.0", "numpy": "2.3.0", "pillow": "11.2.0"},
 "java": {"home": "/opt/java", "version": 25, "required": 25, "ok": true},
 "mod_build": {"possible": true, "reason": "JDK trouvé"},
 "selftest": {"ok": true, "diff_px": 0, "seconds": 0.5}}
```

### Autres commandes

`view`, `anim`, `compare` : `assets[]` avec le chemin produit (`image`, `sheet`, `gif`) ;
`ascii` : `faces` (bloc), `ascii` (item) ou `slices` (modèle) ; `render-model` : `image`, `quads`,
`missing` ; `new` : `file`, `kind`, `next` (commandes suivantes) ; `summary` : `text`.

## Exemples d'intégration

Shell :

```bash
pixvox export assets/*.py --pack out/pack --json > result.json
status=$?
jq -r '.assets[] | "\(.name)\t\(.verified)"' result.json
[ $status -eq 0 ] || pixvox summary result.json --format text
```

Python (sans sous-processus) :

```python
from pixvox.cli import run
code, result = run(["export", "assets/ore.py", "--pack", "out/pack", "--json"])
bad = [a["name"] for a in result["assets"] if not a["verified"]]
```

Node.js :

```js
const { spawnSync } = require("node:child_process");
const r = spawnSync("pixvox", ["review", "assets/ore.py", "--json"], { encoding: "utf8" });
const result = JSON.parse(r.stdout);   // r.status : 0, 1, 2 ou 3
```
