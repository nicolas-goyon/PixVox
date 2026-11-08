"""Serveur MCP (#28) : chaque outil appelé par un client MCP en mémoire (JSON du contrat + images), erreurs,
refus, et un vrai serveur stdio en sous-processus (le protocole n'est jamais pollué par le journal)."""
import asyncio
import json
import os
import sys

from testkit import ROOT, tmpdir

ASSET = '''from pixvox import Block, Model, Volume, ramp
def build():
    v = Volume(16)
    v.noise(ramp("#8a7a6a", 4), cells=4, seed=1)
    m = Volume(8, 6, 8, fill="#6a7a8a")
    return [Block("bloc_mcp", v), Model("objet_mcp", m)]
'''


def _mcp():
    import unittest
    try:
        import mcp  # noqa: F401
    except ImportError as e:
        raise unittest.SkipTest('paquet optionnel « mcp » absent (pip install "pixvox[mcp]")') from e


def _doc(r) -> dict:
    return json.loads(r.content[0].text)


def _images(r) -> list:
    return [c for c in r.content if type(c).__name__ == "ImageContent"]


def test_every_tool_through_an_in_memory_client():
    _mcp()
    from mcp.client import Client

    from pixvox.mcp_server import build_server
    srv = build_server()

    async def scenario(tmp):
        async with Client(srv) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            assert names == ["doctor", "export", "mod", "render_model", "review", "view"], names
            f = str(tmp / "asset.py")
            r = await c.call_tool("review", {"files": [f], "out": str(tmp / "rev")})
            d = _doc(r)
            assert not r.is_error and d["command"] == "review" and d["schema"] and len(d["assets"]) == 2
            assert len(_images(r)) == 2 and all(i.mime_type == "image/png" for i in _images(r))
            r = await c.call_tool("review", {"files": [f], "out": str(tmp / "rev"), "only": "objet_mcp",
                                             "images": False})
            assert len(_doc(r)["assets"]) == 1 and not _images(r)
            r = await c.call_tool("view", {"file": f, "yaw": 135, "pitch": 20, "only": "bloc_mcp",
                                           "out": str(tmp / "v"), "shading": "night", "size": 200})
            assert not r.is_error and len(_images(r)) == 1
            r = await c.call_tool("export", {"files": [f], "pack": str(tmp / "pack"), "mc": "1.21.1"})
            d = _doc(r)
            assert not r.is_error and d["ok"] and all(a["verified"] for a in d["assets"]) and not _images(r)
            r = await c.call_tool("render_model", {"pack": str(tmp / "pack"), "model": "pixvox:block/objet_mcp",
                                                   "out": str(tmp / "rm.png"), "mc": "1.21.1", "size": 200})
            assert not r.is_error and len(_images(r)) == 1, _doc(r)
            r = await c.call_tool("mod", {"files": [f], "modid": "mcp_test", "out": str(tmp / "mod")})
            d = _doc(r)
            assert not r.is_error and d["ok"] and (tmp / "mod" / "build.gradle").exists(), d["errors"]
            r = await c.call_tool("doctor", {})
            assert _doc(r)["command"] == "doctor"
            # erreurs : JSON du contrat intact, is_error vrai
            r = await c.call_tool("review", {"files": [str(tmp / "absent.py")]})
            d = _doc(r)
            assert r.is_error and d["exit_code"] == 2 and d["errors"], d
            r = await c.call_tool("export", {"files": [str(tmp / "absent.py")], "pack": str(tmp / "pack2")})
            assert r.is_error and _doc(r)["exit_code"] == 2 and _doc(r)["errors"]
            r = await c.call_tool("view", {"file": f, "shading": "plein"})                # hors des choix
            assert r.is_error

    with tmpdir() as tmp:
        (tmp / "asset.py").write_text(ASSET, encoding="utf-8")
        asyncio.run(scenario(tmp))


def test_stdio_server_in_a_subprocess_keeps_the_protocol_clean():
    """`pixvox mcp` démarré comme le ferait Claude Desktop : un export (qui journalise beaucoup) ne doit
    rien écrire d'autre que le protocole sur la sortie standard."""
    _mcp()
    from mcp import StdioServerParameters
    from mcp.client import Client

    async def scenario(tmp):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]))
        params = StdioServerParameters(command=sys.executable, args=["-m", "pixvox", "mcp"], cwd=str(tmp), env=env)
        async with Client(params, read_timeout_seconds=120) as c:
            assert c.server_info.name == "pixvox"
            r = await c.call_tool("export", {"files": ["asset.py"], "pack": "out/pack"})
            d = _doc(r)
            assert not r.is_error and d["ok"] and len(d["assets"]) == 2, d
            r = await c.call_tool("review", {"files": ["asset.py"], "only": "bloc_mcp"})
            assert not r.is_error and len(_images(r)) == 1

    with tmpdir() as tmp:
        (tmp / "asset.py").write_text(ASSET, encoding="utf-8")
        asyncio.run(scenario(tmp))
        assert (tmp / "out" / "pack" / "pack.mcmeta").exists()


def test_mcp_command_refuses_json():
    from test_cli import _cli
    with tmpdir() as tmp:
        rc, data = _cli("mcp", cwd=tmp)                          # _cli ajoute --json : refusé
        assert rc == 2 and "stdin" in data["errors"][0]["message"]


def test_plugin_declares_the_mcp_server():
    """claude-plugin/.mcp.json : format des plugins Claude Code (mcpServers à la racine du plugin)."""
    from testkit import require
    require("claude-plugin/.mcp.json")
    cfg = json.loads((ROOT / "claude-plugin" / ".mcp.json").read_text(encoding="utf-8"))
    assert cfg == {"mcpServers": {"pixvox": {"command": "pixvox", "args": ["mcp"]}}}
