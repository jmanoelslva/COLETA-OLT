"""Manda comandos de leitura numa OLT cadastrada e mostra o que chega, cru,
por alguns segundos — para ver paginação, prompts e confirmações novas.

    python tools/sonda_bruta.py <id> <host> <porta> "cmd1" "cmd2" ...

Só aceita comandos show/enable/config/interface/exit. Senha vem do cadastro.
"""

import dataclasses
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import paramiko  # noqa: E402

from coletor import inventario  # noqa: E402
from coletor.cofre import Cofre  # noqa: E402
from coletor.config import carregar_settings  # noqa: E402
from coletor.db import Banco  # noqa: E402

PERMITIDO = re.compile(r"^(show .*|enable|config|exit|interface gpon \d+/\d+|terminal length 0|)$")


def ler(canal, segundos):
    buf, fim = b"", time.monotonic() + segundos
    while time.monotonic() < fim:
        if canal.recv_ready():
            buf += canal.recv(65535)
            fim = max(fim, time.monotonic() + 1.5)
        else:
            time.sleep(0.1)
    return buf.decode("utf-8", "replace")


st = carregar_settings()
olt = inventario.obter(Banco(st.banco), Cofre(st.dados), sys.argv[1])
olt = dataclasses.replace(olt, host=sys.argv[2], porta_ssh=int(sys.argv[3]))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(olt.host, port=olt.porta_ssh, username=olt.usuario, password=olt.senha,
          look_for_keys=False, allow_agent=False, timeout=15)
ch = c.invoke_shell(width=512, height=2000)
inicio = ler(ch, 4)
print("=== LOGIN (últimos 300) ===", repr(inicio[-300:]))
if re.search(r"(user ?name|login)\s*:\s*$", inicio, re.I):
    ch.send(olt.usuario + "\n"); ler(ch, 2); ch.send(olt.senha + "\n"); print("=== 2º login ===", repr(ler(ch, 3)[-200:]))
for cmd in sys.argv[4:]:
    assert PERMITIDO.match(cmd), cmd
    ch.send(cmd + "\n")
    saida = ler(ch, 6)
    print(f"=== {cmd!r}: {len(saida)} bytes ===")
    print("INÍCIO:", repr(saida[:300]))
    print("FIM:   ", repr(saida[-300:]))
ch.send("q"); time.sleep(0.5); c.close()
