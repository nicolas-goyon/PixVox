"""Le paquet annonce une version lisible par pip (PEP 440), une licence, et se publie sans surprise :
contrôle du tag avant toute release et notes tirées du CHANGELOG (scripts/release.py)."""
import importlib.util
import json
import re

import pixvox
from testkit import ROOT, require


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", pixvox.__version__), pixvox.__version__


def test_license_is_declared_everywhere():
    require("LICENSE", "pyproject.toml", "claude-plugin/.claude-plugin/plugin.json")
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^license = "MIT"$', pyproject, re.M), "pyproject.toml : license = \"MIT\" (PEP 639)"
    assert not re.search(r"License :: ", pyproject), "PEP 639 : pas de classifieur de licence en plus"
    plugin = json.loads((ROOT / "claude-plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["license"] == "MIT"


def _release():
    require("scripts/release.py")
    spec = importlib.util.spec_from_file_location("pixvox_release", ROOT / "scripts" / "release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _refused(rel, *args) -> str:
    try:
        rel.decide(*args)
    except rel.ReleaseError as e:
        return str(e)
    raise AssertionError(f"publication acceptée à tort : {args[:3]}")


def test_release_check_decides_from_the_event():
    rel = _release()

    def free(tag):
        return False

    # release publiée sur le site (ou gh release create) : le tag doit être v + __version__
    site = {"release": {"tag_name": "v0.2.0", "prerelease": False}}
    assert rel.decide("release", site, "refs/tags/v0.2.0", "0.2.0", free) == \
        {"version": "0.2.0", "tag": "v0.2.0", "prerelease": False, "publish": True}
    assert "0.1.0" in _refused(rel, "release", site, "refs/tags/v0.2.0", "0.1.0", free)
    # pré-version : case « pre-release » cochée, ou numéro de test PEP 440
    ticked = {"release": {"tag_name": "v0.2.0", "prerelease": True}}
    assert rel.decide("release", ticked, "", "0.2.0", free)["prerelease"] is True
    assert rel.decide("release", {"release": {"tag_name": "v0.2.0rc1"}}, "", "0.2.0rc1", free)["prerelease"] is True

    # lancement manuel : rien n'est publié sans « publish »
    repo = {"repository": {"default_branch": "main"}}
    dry = rel.decide("workflow_dispatch", {"inputs": {"publish": "false"}, **repo}, "refs/heads/dev", "0.2.0", free)
    assert dry["publish"] is False and dry["tag"] == "v0.2.0"
    run = {"inputs": {"publish": "true"}, **repo}                # les entrées arrivent en texte dans l'événement
    assert rel.decide("workflow_dispatch", run, "refs/heads/main", "0.2.0", free)["publish"] is True
    assert "main" in _refused(rel, "workflow_dispatch", run, "refs/heads/dev", "0.2.0", free)
    assert "existe déjà" in _refused(rel, "workflow_dispatch", run, "refs/heads/main", "0.2.0", lambda tag: True)
    # tout autre événement (CI) : jamais de publication
    assert rel.decide("push", {}, "refs/heads/main", "0.2.0", free)["publish"] is False
    # numéro illisible par pip : refus, quel que soit l'événement
    assert "PEP 440" in _refused(rel, "workflow_dispatch", run, "refs/heads/main", "0.2", free)
    assert rel.is_prerelease("1.0.0.dev3") and not rel.is_prerelease("1.0.0.post1")


def test_release_notes_come_from_the_changelog():
    rel = _release()
    changelog = ("# Journal\n\n## [Non publié]\n\n- à venir\n\n## [0.2.0rc1]\n\n- essai\n\n"
                 "## [0.2.0] - 2026-11-02\n\n- nouveau\n\n## [0.1.0]\n\nPremière.\n")
    assert rel.section("0.2.0", changelog) == "- nouveau"            # pas la section 0.2.0rc1 qui précède
    assert rel.section("0.2.0rc1", changelog) == "- essai"
    assert rel.section("0.1.0", changelog) == "Première."
    assert rel.section("0.3.0", changelog) is None
    text = rel.notes("v0.2.0", changelog)
    assert text.startswith("- nouveau\n\nInstallation") and "PixVox@v0.2.0" in text
    assert rel.notes("v0.3.0", changelog).startswith("Version 0.3.0.")
    # le dépôt lui-même : la version courante a sa section (sinon la release n'aurait pas de notes)
    require("CHANGELOG.md")
    current = rel.package_version()
    assert current == pixvox.__version__
    assert rel.section(current, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")), \
        f"CHANGELOG.md : ajouter une section ## [{current}]"
