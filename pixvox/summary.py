"""Résumés lisibles d'un résultat `pixvox … --json` : Markdown (résumé de CI, commentaire de PR) ou texte.

    pixvox export assets/*.py --json > result.json
    pixvox summary result.json >> "$GITHUB_STEP_SUMMARY"
"""
from __future__ import annotations

OK, KO, WARN = "✅", "❌", "⚠️"


def _code(p) -> str:
    return f"`{p}`" if p else "—"


def _status(data: dict) -> str:
    return f"{OK} réussi" if data.get("ok") else f"{KO} échec (code {data.get('exit_code')})"


def _details(e: dict) -> str:
    d = e.get("details") or {}
    parts = []
    if e.get("kind") == "multiblock" and d.get("blocks"):
        b = d["blocks"]
        parts.append(f"{b[0]}×{b[1]}×{b[2]} blocs, {d.get('parts')} parties")
    if d.get("elements") is not None and e.get("kind") != "block":
        parts.append(f"{d['elements']} éléments")
    if d.get("texture_size"):
        parts.append(f"atlas {d['texture_size']} px")
    if d.get("planes"):
        parts.append(f"{d['planes']} plans")
    if d.get("animated"):
        parts.append(f"{d['animated']} texture(s) animée(s)")
    return ", ".join(parts) or "—"


def _verify_cell(e: dict) -> str:
    v = e.get("verify") or {}
    ticks = f" × {v['ticks']} instants" if v.get("ticks", 1) > 1 else ""
    mark = OK if e.get("verified") else KO
    return f"{mark} {v.get('diff_px', '?')} px ({v.get('views', '?')} vues{ticks})"


def _errors_md(data: dict) -> list:
    lines = []
    if data.get("errors"):
        lines += ["", "**Erreurs**", ""]
        lines += [f"- {KO} `{e.get('type')}`" + (f" **{e['asset']}**" if e.get("asset") else "")
                  + f" : {e.get('message')}" for e in data["errors"]]
    if data.get("warnings"):
        lines += ["", "<details><summary>Avertissements</summary>", ""]
        lines += [f"- {WARN} {w}" for w in data["warnings"]]
        lines += ["", "</details>"]
    return lines


def _assets_table(assets: list) -> list:
    lines = ["| Asset | Type | Vérification de l'export | Détails |", "|---|---|---|---|"]
    lines += [f"| `{e['name']}` | {e['kind']} | {_verify_cell(e)} | {_details(e)} |" for e in assets]
    return lines


def to_markdown(data: dict) -> str:
    cmd = data.get("command") or "?"
    lines = [f"### pixvox {cmd} — {_status(data)}", ""]
    if cmd == "export":
        lines.append(f"Pack {_code(data.get('pack'))} · zip {_code(data.get('zip'))} · datapack "
                     f"{_code(data.get('datapack'))} · namespace `{data.get('namespace')}`"
                     + (f" · Minecraft `{data['mc']}`" if data.get("mc") else ""))
        lines += [""] + _assets_table(data.get("assets", []))
    elif cmd == "mod":
        b = data.get("build") or {}
        t = b.get("tests") or {}
        lines.append(f"Projet {_code(data.get('project'))} ({data.get('loader')}, modid `{data.get('modid')}`) · "
                     f"jar {_code(data.get('jar'))}")
        if b:
            tests = f"{t['tests'] - t['failures'] - t['errors']}/{t['tests']} {OK if t.get('passed') else KO}" \
                if t else "non exécutés"
            lines.append(f"Compilation : {OK if b.get('ok') else KO} (JDK {b.get('java_version')}) · "
                         f"tests JUnit : {tests}")
        lines += [""] + _assets_table(data.get("assets", []))
    elif cmd == "review":
        lines += ["| Asset | Type | ERR | WARN | Planche | Animation |", "|---|---|---|---|---|---|"]
        for e in data.get("assets", []):
            c = e.get("counts", {})
            lines.append(f"| `{e['name']}` | {e['kind']} | {c.get('ERR', 0)} | {c.get('WARN', 0)} | "
                         f"{_code(e.get('sheet'))} | {_code(e.get('anim_gif'))} |")
        alerts = [(e["name"], f) for e in data.get("assets", []) for f in e.get("findings", [])
                  if f["level"] in ("WARN", "ERR")]
        if alerts:
            lines += ["", "<details><summary>Alertes de l'analyse</summary>", ""]
            lines += [f"- **{n}** · {f['level']} · {f['topic']} : {f['message']}" for n, f in alerts]
            lines += ["", "</details>"]
    elif cmd == "doctor":
        py, pk, j, st = (data.get(k, {}) for k in ("python", "packages", "java", "selftest"))
        lines += ["| | |", "|---|---|",
                  f"| pixvox | {pk.get('pixvox')} |",
                  f"| Python | {py.get('version')} ({(data.get('platform') or {}).get('system')}) |",
                  f"| numpy / Pillow | {pk.get('numpy')} / {pk.get('pillow')} |",
                  f"| JDK | {j.get('version') or 'absent'} {_code(j.get('home'))} → mods "
                  f"{'compilables' if j.get('ok') else 'non compilables ici'} |",
                  f"| Auto-test d'export | {OK if st.get('ok') else KO} {st.get('diff_px')} px "
                  f"({st.get('seconds')} s) |"]
    else:
        outputs = [(e.get("name"), e.get("image") or e.get("gif") or e.get("sheet") or e.get("file"))
                   for e in data.get("assets", [])]
        for key in ("image", "file"):
            if data.get(key):
                outputs.append((key, data[key]))
        lines += [f"- {n} : {_code(p)}" for n, p in outputs] or ["(aucune sortie)"]
    lines += _errors_md(data)
    return "\n".join(lines) + "\n"


def to_text(data: dict) -> str:
    cmd = data.get("command") or "?"
    lines = [f"pixvox {cmd} : {'OK' if data.get('ok') else 'ÉCHEC'} (code {data.get('exit_code')})"]
    for e in data.get("assets", []):
        if "verified" in e:
            lines.append(f"  {e['name']} ({e['kind']}) : {'OK' if e['verified'] else 'ÉCART'} "
                         f"{e['verify'].get('diff_px')} px")
        elif "counts" in e:
            c = e["counts"]
            lines.append(f"  {e['name']} ({e['kind']}) : {c.get('ERR', 0)} ERR, {c.get('WARN', 0)} WARN")
        else:
            lines.append(f"  {e.get('name')} ({e.get('kind')})")
    lines += [f"  erreur [{e.get('type')}] {e.get('message')}" for e in data.get("errors", [])]
    lines += [f"  attention : {w}" for w in data.get("warnings", [])]
    return "\n".join(lines) + "\n"
