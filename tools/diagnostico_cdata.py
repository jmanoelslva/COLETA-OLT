"""Roda todos os comandos de leitura que o coletor usa numa C-DATA e confere
cada parser, sem gravar nada no banco. Saídas vão para tools/capturas/.

    python tools/diagnostico_cdata.py <id-do-cadastro> [host] [porta]

host/porta opcionais sobrescrevem os do cadastro (ex.: testar pelo endereço
externo). A senha vem do cadastro e não é exibida.
"""

from __future__ import annotations

import dataclasses
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coletor import inventario  # noqa: E402
from coletor.cdata import parsers as p  # noqa: E402
from coletor.cdata.sessao import VIEW_CONFIG, VIEW_GPON, SessaoCData  # noqa: E402
from coletor.cofre import Cofre  # noqa: E402
from coletor.config import carregar_settings  # noqa: E402
from coletor.db import Banco  # noqa: E402

CAPTURAS = RAIZ / "tools" / "capturas"


def main() -> None:
    olt_id = sys.argv[1]
    st = carregar_settings()
    olt = inventario.obter(Banco(st.banco), Cofre(st.dados), olt_id)
    if not olt:
        sys.exit(f"OLT '{olt_id}' não cadastrada")
    if len(sys.argv) > 2:
        olt = dataclasses.replace(olt, host=sys.argv[2], porta_ssh=int(sys.argv[3]) if len(sys.argv) > 3 else olt.porta_ssh)
    porta = olt.portas_pon[0]
    comandos = [
        ("show time", VIEW_CONFIG, p.relogio),
        ("show uptime", VIEW_CONFIG, p.uptime),
        ("show version", VIEW_CONFIG, p.versao),
        ("show cpu", VIEW_CONFIG, p.cpu),
        ("show memory", VIEW_CONFIG, p.memoria),
        ("show temperature", VIEW_CONFIG, p.temperatura),
        ("show fan", VIEW_CONFIG, p.ventoinhas),
        ("show power state", VIEW_CONFIG, p.fontes),
        ("show firmware info", VIEW_CONFIG, p.firmware),
        ("show alarm active all", VIEW_CONFIG, p.alarmes),
        ("show alarm history all", VIEW_CONFIG, p.alarmes),
        (f"show port ddm-info {porta}", VIEW_GPON, p.ddm_porta),
        (f"show ont info {porta} all", VIEW_GPON, p.ont_info_todas),
        (f"show ont optical-info {porta} all", VIEW_GPON, p.optical_todas),
    ]
    s = SessaoCData(olt, st.known_hosts)
    s.conectar()
    print(f"conectado: {s.hostname}")
    CAPTURAS.mkdir(exist_ok=True)
    primeira_onu = None
    for cmd, view, parser in comandos:
        t0 = time.monotonic()
        try:
            saida = s.executar(cmd, view, timeout=120)
        except Exception as e:  # noqa: BLE001
            print(f"[FALHA CLI] {cmd}: {e}")
            continue
        arq = CAPTURAS / f"{olt_id}_{re.sub(r'[^A-Za-z0-9]+', '_', cmd).strip('_')}.txt"
        arq.write_text(f"# {cmd}\n{saida}", encoding="utf-8")
        try:
            r = parser(saida)
        except Exception as e:  # noqa: BLE001
            print(f"[FALHA PARSER] {cmd}: {type(e).__name__}: {e}")
            continue
        resumo = r
        if isinstance(r, tuple):
            resumo = (len(r[0]), r[1])
            if r[0] and primeira_onu is None:
                primeira_onu = r[0][0]["onu_id"]
        elif isinstance(r, list):
            resumo = f"{len(r)} itens; 1º={r[0] if r else None}"
        elif isinstance(r, dict) and "rx_olt" in r:
            resumo = {"sfp": r["sfp"], "rx_olt": len(r["rx_olt"])}
        vazio = r in (None, [], {}) or (isinstance(r, dict) and all(v in (None, {}, []) for v in r.values()))
        marca = "[VAZIO?]" if vazio else "[ok]"
        print(f"{marca} {cmd} ({time.monotonic() - t0:.1f}s): {str(resumo)[:220]}")
    if primeira_onu is not None:
        for cmd, parser in ((f"show ont info {porta} {primeira_onu}", p.ont_info_uma),
                            (f"show ont optical-info {porta} {primeira_onu}", p.optical_uma)):
            try:
                saida = s.executar(cmd, VIEW_GPON, timeout=60)
                (CAPTURAS / f"{olt_id}_{re.sub(r'[^A-Za-z0-9]+', '_', cmd)}.txt").write_text(f"# {cmd}\n{saida}", encoding="utf-8")
                print(f"[ok] {cmd}: {str(parser(saida))[:220]}")
            except Exception as e:  # noqa: BLE001
                print(f"[FALHA] {cmd}: {type(e).__name__}: {e}")
    s.fechar()


if __name__ == "__main__":
    main()
