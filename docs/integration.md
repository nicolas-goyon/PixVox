# Intégrer pixvox ailleurs : action GitHub, Docker, autres CI, Python

pixvox est utilisable sans agent : tout passe par la commande `pixvox` (contrat JSON et codes de
sortie dans [cli.md](cli.md)). Cette page montre les intégrations prêtes à l'emploi.

## Action GitHub (`uses: nicolas-goyon/PixVox@main`)

L'action installe pixvox, lance une commande en `--json`, écrit un résumé lisible dans le job,
téléverse les sorties en artefact et expose le résultat aux étapes suivantes. Elle marche sur les
runners Linux, macOS et Windows. Référence : `@main` (dernière version), `@v0.1.0` (version figée,
recommandé ; dependabot sait la mettre à jour) ; `@v0` suit la dernière 0.x quand la release a pu
déplacer ce tag.

Dépôt d'assets : vérifier chaque PR et publier le resource pack sur `main` :

```yaml
name: assets
on: [push, pull_request]
jobs:
  pack:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: nicolas-goyon/PixVox@main        # ou un tag de version : @v0.1.0
        with:
          command: export
          files: assets/**/*.py
          args: --pack out/pack --zip out/mon_pack.zip --ns mon_pack
```

Mod compilé (JDK 25 installé par l'action) :

```yaml
      - uses: nicolas-goyon/PixVox@main
        with:
          command: mod
          files: assets/*.py
          args: --modid mon_mod --name "Mon mod" --loader fabric --build
          java: "true"
```

Revue de qualité bloquante (code 1 si l'analyse signale une alerte) :

```yaml
      - uses: nicolas-goyon/PixVox@main
        with:
          command: review
          files: assets/*.py
          args: --out out/review --fail-on warn
```

| entrée | défaut | rôle |
|---|---|---|
| `command` | `export` | commande pixvox (`review`, `export`, `mod`, `anim`, `compare`, `view`, `doctor`…) |
| `files` | — | fichiers `.py`, motifs glob acceptés (`assets/**/*.py`) |
| `args` | — | arguments supplémentaires (découpés comme un shell, guillemets acceptés) |
| `working-directory` | `.` | dossier où lancer pixvox |
| `python-version` | `3.13` | vide = utiliser le Python d'une étape `actions/setup-python` précédente |
| `java` | `false` | `true` : JDK 25 + cache Gradle (pour `mod --build`) |
| `pixvox-spec` | code de l'action | ce que pip installe (un chemin, `pixvox @ git+…@v0.1.0`) |
| `upload` / `upload-path` / `artifact-name` | `true` / `out/` / `pixvox-<commande>-<job>-<suffixe>` | artefact (nom unique par défaut, même dans une matrice) |
| `summary` | `true` | résumé Markdown dans le job |
| `fail` | `true` | faire échouer l'étape si le code n'est pas 0 |

Sorties : `ok`, `exit-code`, `result` (chemin du JSON), `summary` (chemin du Markdown),
`artifact-name`, `artifact-url`. Pour réagir soi-même à un échec, mettre `fail: "false"` puis tester
`if: steps.pixvox.outputs.ok == 'false'` (avec `fail: "true"`, l'étape échoue d'abord). Les fichiers
sont séparés par des espaces : pas d'espace dans leurs noms.

Dans ce dépôt, le workflow « Aperçu des assets » utilise l'action sur chaque PR qui touche
`examples/` ou `assets/` et publie un commentaire avec le résumé et les liens des planches (sauf pour
une PR venant d'un fork : son jeton ne peut pas commenter ; résumé et artefacts restent disponibles).

## Docker

L'image contient Python, pixvox et un JDK 25 : rien d'autre à installer, même pour compiler un mod.

```bash
docker run --rm -v "$PWD:/work" ghcr.io/nicolas-goyon/pixvox doctor
docker run --rm -v "$PWD:/work" ghcr.io/nicolas-goyon/pixvox export assets/*.py --pack out/pack --json
docker run --rm -v "$PWD:/work" ghcr.io/nicolas-goyon/pixvox mod assets/*.py --modid mon_mod --build
```

Les fichiers produits arrivent dans le dossier monté (`/work`). L'image est publiée à chaque
version (`:latest`, `:0.1.0`, `:0.1`) ; `docker build -t pixvox .` la construit localement. Le paquet
ghcr.io est privé à sa création : le rendre public une fois (réglages du paquet sur GitHub).

## Autres CI (GitLab, Jenkins…)

```yaml
# .gitlab-ci.yml
pack:
  image:
    name: ghcr.io/nicolas-goyon/pixvox:latest
    entrypoint: [""]                  # l'image lance pixvox par défaut ; GitLab a besoin d'un shell
  script:
    - pixvox export assets/*.py --pack out/pack --zip out/pack.zip --json > result.json
    - pixvox summary result.json --format text
  artifacts:
    paths: [out/pack.zip, result.json]
```

Le code de sortie suffit à faire échouer le job : `1` pour un asset non fidèle ou refusé,
`2` pour une erreur d'utilisation.

## Python

```python
from pixvox import Block, Volume, ramp, export_pack
from pixvox.cli import run                           # même contrat que la ligne de commande

v = Volume(16)
v.noise(ramp("#7b7d83", 4), cells=3, seed=1)
infos = export_pack([Block("ma_pierre", v)], "out/pack")  # lève ExportError si un asset est refusé
assert all(i["verify"]["diff_px"] == 0 for i in infos)

code, result = run(["review", "assets/ore.py", "--json"])
```

## Agents

- **Claude (claude.ai)** : téléverser `pixvox_skill.zip` (fichier de chaque release) dans
  *Customize → Skills* (selon le compte : *Settings → Capabilities*, section Skills) ; l'exécution de
  code doit être activée. Le zip contient un dossier `pixvox/` avec `SKILL.md`, le paquet et les exemples.
- **Claude Code, dans n'importe quel projet** : `/plugin marketplace add nicolas-goyon/PixVox` puis
  `/plugin install pixvox@pixvox` (en ligne de commande : `claude plugin marketplace add …` et
  `claude plugin install pixvox@pixvox`). Le skill installe pixvox avec pip à la première utilisation.
- **Claude Code et autres agents de code, dans ce dépôt** : les consignes sont dans
  [`AGENTS.md`](../AGENTS.md) (importé par `CLAUDE.md`) et le skill de projet `.claude/skills/pixvox` se
  charge tout seul. Un agent qui contribue un asset ouvre une PR : la CI rend les planches, vérifie
  l'export et commente la PR.
- **Demandes d'asset traitées par un agent depuis les issues** (facultatif) : l'action officielle
  `anthropics/claude-code-action@v1` répond aux mentions `@claude` dans les issues et les PR ; elle se
  configure avec `/install-github-app` depuis Claude Code (secret `ANTHROPIC_API_KEY` ou jeton
  d'abonnement). Le formulaire « Demande d'asset » donne alors une consigne directement exploitable.
- **Tout agent capable de lancer des commandes** : `pixvox doctor --json` dit ce qui est possible
  (mods compilables ou non), `pixvox new` donne un point de départ, `--json` donne un résultat
  exploitable sans analyser du texte.
