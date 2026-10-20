"""Lance tous les tests sans pytest : python tests/run.py [filtre…]

Pratique là où pytest n'est pas installé (skill Claude, poste neuf). Avec pytest : python -m pytest.
Un filtre ne garde que les tests dont le nom de fichier ou de fonction contient ce texte.
Code de sortie : 0 si tout passe, 1 sinon.
"""
from __future__ import annotations

import importlib
import sys
import time
import traceback
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):        # console Windows redirigée : jamais d'erreur d'encodage
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    filters = [a for a in argv if not a.startswith("-")]
    verbose = "-v" in argv
    fails, count, skipped, t0 = 0, 0, 0, time.time()
    for path in sorted(HERE.glob("test_*.py")):
        selected = not filters or any(k in path.stem for k in filters)
        try:
            mod = importlib.import_module(path.stem)
        except Exception as e:  # noqa: BLE001 - un module cassé est un échec s'il est demandé
            if selected:
                fails += 1
                count += 1
                print(f"ÉCHEC  {path.stem} (import) : {type(e).__name__} {e}")
            continue
        tests = [(n, f) for n, f in vars(mod).items() if n.startswith("test_") and callable(f)]
        for name, fn in tests:                      # ordre de définition dans le fichier
            if filters and not any(k in path.stem or k in name for k in filters):
                continue
            count += 1
            t = time.time()
            try:
                fn()
                print(f"ok     {path.stem}::{name}  ({time.time() - t:.1f} s)")
            except unittest.SkipTest as e:
                skipped += 1
                print(f"ignoré {path.stem}::{name} : {e}")
            except Exception as e:  # noqa: BLE001 - on rapporte tout échec de test
                fails += 1
                print(f"ÉCHEC  {path.stem}::{name} : {type(e).__name__} {e}")
                if verbose:
                    traceback.print_exc()
    print(f"{count - fails - skipped}/{count} tests passent en {time.time() - t0:.0f} s"
          + (f", {skipped} ignoré(s)" if skipped else "")
          + ("" if not fails else f" — {fails} échec(s) (relancer avec -v pour la trace)"))
    return 1 if fails or not count else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
