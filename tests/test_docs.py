"""Fichiers lus par des machines : en-têtes YAML des skills, manifestes du plugin Claude Code, liens internes.

Un en-tête de skill invalide ne casse rien de visible : le skill se charge sans description et ne se
déclenche plus. Ce test le voit avant les utilisateurs.
"""
import json
import re

from testkit import ROOT, require

SKILLS = [ROOT / "SKILL.md", ROOT / ".claude" / "skills" / "pixvox" / "SKILL.md",
          ROOT / "claude-plugin" / "skills" / "pixvox" / "SKILL.md"]


def _front_matter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    return text.split("---\n", 2)[1]


def test_skill_front_matter_is_valid_yaml():
    require(*(str(p.relative_to(ROOT)) for p in SKILLS))
    try:
        import yaml
    except ImportError:                       # PyYAML absent (skill décompressé) : contrôle minimal
        for p in SKILLS:
            for line in _front_matter(p).splitlines():
                key, _, value = line.partition(": ")
                assert not (": " in value and not value.startswith('"')), (p, key)
        return
    for p in SKILLS:
        fm = yaml.safe_load(_front_matter(p))
        assert isinstance(fm, dict), p
        assert fm.get("name") == "pixvox", p                       # = nom du dossier du skill
        assert re.fullmatch(r"[a-z0-9-]{1,64}", fm["name"]), p
        assert 20 < len(fm.get("description", "")) <= 1024, p


def test_plugin_skill_is_in_sync_and_manifests_parse():
    require("scripts/sync_plugin_skill.py", ".claude-plugin/marketplace.json", "claude-plugin")
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_plugin_skill", ROOT / "scripts" / "sync_plugin_skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.TARGET.read_text(encoding="utf-8") == mod.render(), "python scripts/sync_plugin_skill.py"
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    plugin = json.loads((ROOT / "claude-plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert market["owner"]["name"] and market["plugins"][0]["name"] == plugin["name"] == "pixvox"
    assert (ROOT / market["plugins"][0]["source"]).resolve() == (ROOT / "claude-plugin").resolve()


def test_relative_links_in_docs_exist():
    require("AGENTS.md", "CONTRIBUTING.md", "docs/integration.md")
    for doc in [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CONTRIBUTING.md", *(ROOT / "docs").glob("*.md")]:
        for target in re.findall(r"\]\((?!https?://|#)([^)#\s]+)", doc.read_text(encoding="utf-8")):
            assert (doc.parent / target).exists(), f"{doc.name} : lien cassé {target}"
