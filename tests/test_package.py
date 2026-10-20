"""Le paquet s'importe et annonce une version lisible par pip (PEP 440)."""
import re

import pixvox
import testkit  # noqa: F401 - met la racine du dépôt dans sys.path


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", pixvox.__version__), pixvox.__version__
