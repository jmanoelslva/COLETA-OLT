"""Sobe o coletor apontando para o banco simulado (tools/simular.py) e a OLT de mentira."""

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("COLETOR_DADOS", str(RAIZ / "dados" / "dev"))
os.environ.setdefault("COLETOR_OLTS", str(RAIZ / "olts.dev.toml"))

from coletor.__main__ import main  # noqa: E402

main()
