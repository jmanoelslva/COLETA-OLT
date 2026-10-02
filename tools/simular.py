"""Popula um banco de desenvolvimento rodando as coletas de verdade contra uma
OLT falsa que responde com as fixtures (tests/fixtures). Gera alguns dias de
histórico com variação de sinal para testar gráficos e diagnóstico sem OLT.

    python tools/simular.py            # cria dados/dev.sqlite3
    COLETOR_DADOS=dados/dev python -m coletor   (com olts.dev.toml)
"""

from __future__ import annotations

import random
import re
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from coletor import coletas, db  # noqa: E402
from coletor.config import OltConfig  # noqa: E402

FIX = RAIZ / "tests" / "fixtures"
COMANDOS = [
    (r"show ont info \d+ all", "ont_info_todas.txt"),
    (r"show ont info \d+ (\d+)", None),
    (r"show ont optical-info \d+ all", "optical_todas.txt"),
    (r"show port ddm-info \d+ with-onu-optical", "ddm_com_onus.txt"),
    (r"show port ddm-info \d+", "ddm_porta.txt"),
    (r"show alarm active all", "alarmes_ativos.txt"),
    (r"show alarm history all", "alarmes_historico.txt"),
    (r"show firmware info", "firmware.txt"),
    (r"show cpu", "cpu.txt"),
    (r"show fan", "fan.txt"),
    (r"show power state", "power.txt"),
    (r"show memory", "memoria.txt"),
    (r"show temperature", "temperatura.txt"),
    (r"show version", "versao.txt"),
    (r"show uptime", "uptime.txt"),
    (r"show time", "time.txt"),
]


class OltFalsa:
    hostname = "OLT-SIMULADA"
    conectada = True
    ultimo_uso = 0.0

    def __init__(self, ruido: float = 0.0):
        self.ruido = ruido

    def executar(self, comando: str, view: str, timeout: float = 60) -> str:
        for padrao, arq in COMANDOS:
            m = re.fullmatch(padrao, comando)
            if not m:
                continue
            if arq is None:  # detalhe de uma ONU: usa o modelo e troca o ID
                base = (FIX / "ont_info_online.txt").read_text(encoding="utf-8")
                base = re.sub(r"^\s*SN\s*:.*$", "", base, flags=re.M)  # não sobrescreve o SN da lista
                return re.sub(r"(ONT-ID\s*:\s*)\d+", rf"\g<1>{m[1]}", base).replace(
                    "CLIENTE-001", f"CLIENTE-{int(m[1]):03d}")
            texto = (FIX / arq).read_text(encoding="utf-8")
            if re.match(r"show ont info 2 ", comando):  # porta 2 = cópia da 1 com outros seriais
                texto = texto.replace("TEST", "SIM2")
            if self.ruido and ("optical" in comando or "with-onu" in comando):
                texto = re.sub(r"(?<=\s)(-\d+\.\d\d)(?=\s|$)",
                               lambda x: f"{float(x[1]) + random.uniform(-self.ruido, self.ruido):.2f}", texto)
            return texto
        raise AssertionError(f"comando sem fixture: {comando}")


def main() -> None:
    destino = RAIZ / "dados" / "dev" / "coletor.sqlite3"
    destino.unlink(missing_ok=True)
    banco = db.Banco(destino)
    olt = OltConfig(id="simulada", nome="OLT Simulada", host="127.0.0.1", usuario="-", senha="-",
                    portas_pon=(1, 2), ativa=False)
    with banco.conexao() as c:
        c.execute("INSERT INTO olts (id, nome, modelo, host, portas_pon, ativa) VALUES (?,?,?,?,?,0)",
                  (olt.id, olt.nome, olt.modelo, olt.host, "[1, 2]"))
    estado = coletas.EstadoOlt()
    agora_real = db.agora_utc()
    random.seed(1)
    # 3 dias, de hora em hora; a porta 2 "degrada" 4 dB nas últimas 6 h.
    for h in range(72, -1, -1):
        instante = agora_real - timedelta(hours=h)
        falsa = OltFalsa(ruido=0.4)
        with mock.patch.object(coletas, "agora_utc", lambda: instante):
            coletas.coletar_onus(falsa, olt, banco, estado)
            coletas.coletar_rx_olt(falsa, olt, banco, estado)
        if h <= 6:
            with banco.conexao() as c:
                c.execute("UPDATE sinais_onu SET rx = rx - 4 WHERE porta = 2 AND coletado_em = ?", (db.iso(instante),))
    coletas.coletar_sistema(OltFalsa(), olt, banco, estado)
    coletas.coletar_alarmes(OltFalsa(), olt, banco, estado)
    print(f"ok: {destino}")


if __name__ == "__main__":
    main()
