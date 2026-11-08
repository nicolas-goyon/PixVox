"""pixvox.mcp_server — serveur MCP (stdio) : pixvox pour tout agent compatible (#28).

    pip install "pixvox[mcp]"
    pixvox mcp                      # à déclarer dans Claude Desktop, Claude Code, Cursor… (docs/integration.md)

Outils : review, view, export, mod, render_model, doctor. Chacun appelle la commande du même nom avec
`--json` (pixvox.cli.run) : mêmes paramètres, même contrat (docs/cli.md). La réponse contient d'abord ce
document JSON, puis les images produites (planches de revue, planches d'animation, vues), pour que l'agent
les regarde dans la conversation (règle 2 : regarder avant d'affirmer). `is_error` est vrai quand le code
de sortie n'est pas 0 (export non vérifié, fichier introuvable…) ; le JSON dit pourquoi.

Garde-fous : ceux de la ligne de commande (dossiers de sortie protégés par le fichier `.pixvox`, jamais
d'écrasement d'un dossier qui n'est pas à pixvox) ; aucun outil ne lance Minecraft (règle 7) : `mod`
génère et, avec build=True, compile le mod et son test JUnit, sans ouvrir le jeu. Les chemins sont relatifs
au dossier où le client démarre le serveur (le projet, pour Claude Code).

La dépendance `mcp` est optionnelle : le cœur de pixvox reste numpy + Pillow.
"""
# pas de « from __future__ import annotations » : le SDK évalue les annotations des outils, et `types` (mcp,
# paquet optionnel) n'est importé que dans build_server.
import json
import threading
from pathlib import Path
from typing import Literal

__all__ = ["build_server", "main", "MCP_HINT"]

MCP_HINT = 'le serveur MCP demande le paquet optionnel « mcp » : pip install "pixvox[mcp]"'
_LOCK = threading.Lock()          # la ligne de commande redirige sys.stdout : un appel à la fois
Shading = Literal["gui", "world", "night", "flat"]


def _run(argv: list, images: bool):
    """Exécute la commande pixvox, renvoie le CallToolResult : JSON du contrat + images."""
    from mcp import types

    from .cli import _jsonable, run
    with _LOCK:
        code, out = run([*argv, "--json"])
    doc = _jsonable(out)
    content = [types.TextContent(type="text", text=json.dumps(doc, ensure_ascii=False, indent=2))]
    if images:
        for p in _image_paths(doc):
            try:
                data = Path(p).read_bytes()
            except OSError:
                continue
            content.append(types.ImageContent(type="image", data=_b64(data), mime_type="image/png"))
    return types.CallToolResult(content=content, is_error=code != 0)


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


def _image_paths(doc: dict) -> list:
    """Images PNG citées par un résultat : planches, planches d'animation, vues (dans l'ordre, sans doublon)."""
    out = []
    for a in doc.get("assets") or []:
        for k in ("sheet", "anim_sheet", "image"):
            if a.get(k) and str(a[k]).endswith(".png"):
                out.append(a[k])
    if doc.get("image") and str(doc["image"]).endswith(".png"):
        out.append(doc["image"])
    return list(dict.fromkeys(out))


def build_server():
    """Serveur MCPServer avec les six outils de pixvox (importe `mcp` : paquet optionnel)."""
    try:
        from mcp import types
        from mcp.server.mcpserver import MCPServer
    except ImportError as e:                                   # pragma: no cover - dépend de l'installation
        raise ImportError(MCP_HINT) from e
    from . import __version__

    srv = MCPServer(
        "pixvox", version=__version__,
        instructions=("pixvox décrit des assets Minecraft Java en Python (volumes de voxels, sprites), les rend comme "
                      "le jeu, les analyse et les exporte en resource pack vérifié par re-rendu ou en mod Fabric / "
                      "NeoForge. Regarder les planches renvoyées avant de juger un asset ; un export n'est réussi que "
                      "si chaque asset a \"verified\": true. Ne jamais lancer Minecraft."))

    @srv.tool(description="Planche de revue PNG (renvoyée comme image) + rapport d'analyse de fichiers d'assets "
                          "pixvox (.py). Même contrat que `pixvox review --json`.")
    def review(files: list[str], out: str = "out", only: str | None = None,
               neighbors: list[str] | None = None, images: bool = True) -> types.CallToolResult:
        argv = ["review", *files, "--out", out]
        argv += ["--only", only] if only else []
        argv += ["--neighbors", ",".join(neighbors)] if neighbors else []
        return _run(argv, images)

    @srv.tool(description="Rendu d'un asset à un angle libre (yaw, pitch en degrés), renvoyé comme image. Même "
                          "contrat que `pixvox view --json`.")
    def view(file: str, yaw: float = 225, pitch: float = 30, size: int = 700, shading: Shading = "gui",
             tick: float = 0, biome: str | None = None, persp: float = 0.0, only: str | None = None,
             out: str = "out", images: bool = True) -> types.CallToolResult:
        argv = ["view", file, "--yaw", str(yaw), "--pitch", str(pitch), "--size", str(size), "--shading", shading,
                "--tick", str(tick), "--persp", str(persp), "--out", out]
        argv += ["--biome", biome] if biome else []
        argv += ["--only", only] if only else []
        return _run(argv, images)

    @srv.tool(description="Resource pack Java vérifié par re-rendu (chaque asset relu du disque et comparé au "
                          "pixel près). mc : \"1.21.4+\" ou \"1.21.1\". replace : {\"nom\": \"minecraft:bloc\"}. Même "
                          "contrat que `pixvox export --json` ; is_error si un asset n'est pas vérifié.")
    def export(files: list[str], pack: str = "out/pack", mc: Literal["1.21.4+", "1.21.1"] = "1.21.4+",
               ns: str = "pixvox", zip: str | None = None, replace: dict[str, str] | None = None,  # noqa: A002
               textures: Literal["flat", "folders"] = "flat") -> types.CallToolResult:
        argv = ["export", *files, "--pack", pack, "--mc", mc, "--ns", ns, "--textures", textures]
        argv += ["--zip", zip] if zip else []
        for k, v in (replace or {}).items():
            argv += ["--replace", f"{k}={v}"]
        return _run(argv, images=False)

    @srv.tool(description="Projet de mod Gradle Fabric ou NeoForge (vrais blocs). build=True compile le .jar et "
                          "lance le test JUnit (JDK 25 pour 26.3, 21 pour 1.21.1) ; Minecraft n'est jamais lancé. "
                          "Même contrat que `pixvox mod --json`.")
    def mod(files: list[str], modid: str = "pixvox_mod", loader: Literal["fabric", "neoforge"] = "fabric",
            mc: Literal["26.3", "1.21.1"] = "26.3", name: str | None = None, out: str | None = None,
            version: str = "1.0.0", zip: str | None = None, build: bool = False,  # noqa: A002
            java_home: str | None = None) -> types.CallToolResult:
        argv = ["mod", *files, "--modid", modid, "--loader", loader, "--mc", mc, "--version", version]
        for flag, val in (("--name", name), ("--out", out), ("--zip", zip), ("--java-home", java_home)):
            argv += [flag, val] if val else []
        argv += ["--build"] if build else []
        return _run(argv, images=False)

    @srv.tool(description="Aperçu d'un modèle JSON d'un resource pack (dossier ou .zip ; fait main, Blockbench…), "
                          "renvoyé comme image. model : \"ns:block/nom\". Même contrat que `pixvox render-model --json`.")
    def render_model(pack: str, model: str, out: str = "out/model_preview.png", yaw: float = 225,
                     pitch: float = 30, size: int = 600, shading: Shading = "gui", tick: float = 0,
                     persp: float = 0.0, mc: Literal["1.21.4+", "1.21.1"] = "1.21.4+",
                     images: bool = True) -> types.CallToolResult:
        argv = ["render-model", pack, model, "--out", out, "--yaw", str(yaw), "--pitch", str(pitch),
                "--size", str(size), "--shading", shading, "--tick", str(tick), "--persp", str(persp), "--mc", mc]
        return _run(argv, images)

    @srv.tool(description="Vérifie l'installation : Python, dépendances, export de test, JDK pour compiler les "
                          "mods. Même contrat que `pixvox doctor --json`.")
    def doctor(java_home: str | None = None) -> types.CallToolResult:
        return _run(["doctor", *(["--java-home", java_home] if java_home else [])], images=False)

    return srv


def main() -> None:
    """Serveur MCP sur stdin / stdout (le journal de pixvox va sur stderr)."""
    build_server().run("stdio")
