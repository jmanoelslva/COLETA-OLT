"""O que muda por fabricante: classe de sessão, rotinas de coleta e como o
"sinal na OLT" é dividido em pedaços pequenos (para não travar a fila)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import coletas as cdata
from .cdata.sessao import SessaoCData
from .datacom import coletas as datacom
from .datacom.sessao import SessaoDatacom

Rotina = Callable[..., dict]


@dataclass(frozen=True)
class Driver:
    sessao: type
    # tipo → (prioridade, parâmetro de intervalo, função). Menor prioridade roda antes.
    tipos: dict[str, tuple[int, str, Rotina]]
    # Pedaços de uma volta de "sinal na OLT" (kwargs para funcao_rx).
    itens_rx: Callable[..., list[dict]]
    funcao_rx: Rotina
    consultar_onu: Rotina
    # Ciclo próprio de "RX OLT" ligado? (C-DATA: desligado, ver abaixo)
    coleta_rx_olt: bool = True


CDATA = Driver(
    sessao=SessaoCData,
    tipos={
        "alarmes": (0, "intervalo_alarmes_s", cdata.coletar_alarmes),
        "sistema": (1, "intervalo_sistema_s", cdata.coletar_sistema),
        "onus": (2, "intervalo_onus_s", cdata.coletar_onus),
    },
    # Uma porta por vez (~1 min cada).
    itens_rx=lambda olt, banco, estado, portas=None: [{"portas": [p]} for p in (portas or olt.portas_pon)],
    funcao_rx=cdata.coletar_rx_olt,
    consultar_onu=cdata.consultar_onu,
    # Desligado: na V1.x o `ddm-info ... with-onu-optical` sobrecarrega a CPU
    # da OLT. Na V3.x o RX OLT já vem no ciclo de ONUs (`optical-info ... all`),
    # e o SFP da PON é lido no ciclo de equipamento.
    coleta_rx_olt=False,
)

DATACOM = Driver(
    sessao=SessaoDatacom,
    tipos={
        "alarmes": (0, "intervalo_alarmes_s", datacom.coletar_alarmes),
        "sistema": (1, "intervalo_sistema_s", datacom.coletar_sistema),
        "onus": (2, "intervalo_onus_s", datacom.coletar_onus),
    },
    # Uma ONU por vez (~3 s: detalhe + RSSI).
    itens_rx=datacom.itens_rodizio,
    funcao_rx=datacom.coletar_onu,
    consultar_onu=datacom.coletar_onu,
)

DRIVERS: dict[str, Driver] = {"cdata": CDATA, "datacom": DATACOM}
