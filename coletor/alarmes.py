"""Catálogo de alarmes da C-DATA e conversão das datas da OLT."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# (padrão da mensagem, código, rótulo, severidade). Ordem importa: o primeiro que casar vence.
# Severidades: critico > maior > menor > info.
_CATALOGO: list[tuple[re.Pattern, str, str, str]] = [
    # Quedas detectadas pelos dados da ONU (Datacom: "Last down reason/time").
    (re.compile(r"^ONU caiu \(Dying gasp\)", re.I), "dgi", "ONU caiu: falta de energia (dying gasp)", "maior"),
    (re.compile(r"^ONU caiu \(LOSi?\)", re.I), "losi", "ONU caiu: sem sinal (LOS)", "critico"),
    (re.compile(r"^ONU caiu \(OMCC", re.I), "omcc", "ONU caiu: falha de gerência (OMCC)", "maior"),
    (re.compile(r"^ONU caiu \(Ranging", re.I), "ranging", "ONU caiu: falha de ranging (sinal/distância)", "maior"),
    (re.compile(r"^ONU caiu", re.I), "queda", "ONU caiu", "maior"),
    (re.compile(r"^ONU voltou", re.I), "queda", "ONU voltou", "info"),
    # Nomes de alarme do DmOS (Datacom).
    (re.compile(r"\bGPON_DGi\b"), "dgi", "ONU sem energia (dying gasp)", "maior"),
    (re.compile(r"\bGPON_LOSi\b"), "losi", "ONU sem sinal (LOSi)", "critico"),
    (re.compile(r"\bGPON_LOFi\b"), "lofi", "ONU perdeu quadro (LOFi)", "maior"),
    (re.compile(r"\bGPON_LOAMi\b"), "loami", "ONU perdeu canal de gerência (LOAMi)", "menor"),
    (re.compile(r"\bGPON_DFi\b"), "dfi", "ONU não respondeu após desativar (DFi)", "maior"),
    (re.compile(r"\bGPON_(LOS|LOSS)\b"), "los_pon", "Porta PON sem sinal (LOS)", "critico"),
    (re.compile(r"Loss of signal\(LOS\)", re.I), "los_pon", "Porta PON sem sinal (LOS)", "critico"),
    (re.compile(r"Loss of signal for ONU\(LOSi\)", re.I), "losi", "ONU sem sinal (LOSi)", "critico"),
    (re.compile(r"Loss of frame for ONU\(LOFi\)", re.I), "lofi", "ONU perdeu quadro (LOFi)", "maior"),
    (re.compile(r"Dying gasp\(DGi\)", re.I), "dgi", "ONU sem energia (dying gasp)", "maior"),
    (re.compile(r"\(DFi\)", re.I), "dfi", "ONU não respondeu após desativar (DFi)", "maior"),
    (re.compile(r"ONT Tx power exceeds the high", re.I), "tx_onu", "TX da ONU acima do limite", "menor"),
    (re.compile(r"ONT Tx power exceeds the low", re.I), "tx_onu", "TX da ONU abaixo do limite", "menor"),
    (re.compile(r"ONT Tx power becomes normal", re.I), "tx_onu", "TX da ONU normalizou", "menor"),
    (re.compile(r"ONT Rx power exceeds the high", re.I), "rx_onu", "RX da ONU acima do limite", "menor"),
    (re.compile(r"ONT Rx power exceeds the low", re.I), "rx_onu", "RX da ONU abaixo do limite", "menor"),
    (re.compile(r"ONT Rx power becomes normal", re.I), "rx_onu", "RX da ONU normalizou", "menor"),
    (re.compile(r"Ethernet port link status is (down|up)", re.I), "uni_link", "Porta LAN da ONU", "info"),
    (re.compile(r"not support this trans?ceiver", re.I), "sfp_incompativel", "SFP da PON não suportado", "maior"),
    # Mensagens do firmware V3.x.
    (re.compile(r"trans?ceiver is not adapted", re.I), "sfp_incompativel", "SFP da PON não reconhecido (tipo padrão)", "menor"),
    (re.compile(r"TX output power of the optical port", re.I), "tx_pon", "TX do SFP da PON fora do limite", "maior"),
    (re.compile(r"ONT temperature exceeds the alarm", re.I), "temp_onu", "Temperatura da ONU acima do limite", "menor"),
    (re.compile(r"ONT temperature exceeds the warning", re.I), "temp_onu", "Temperatura da ONU em atenção", "info"),
    (re.compile(r"ONT voltage exceeds", re.I), "tensao_onu", "Tensão da ONU fora do limite", "menor"),
    (re.compile(r"ONT bias current exceeds", re.I), "bias_onu", "Corrente do laser da ONU fora do limite", "menor"),
]

_NORMALIZOU = re.compile(r"(\sclear$|becomes normal|link status is up|^ONU voltou|\(normalizou\)$)", re.I)

# Severidade que o próprio DmOS informa → nossa escala.
SEVERIDADE_DATACOM = {"CRITICAL": "critico", "MAJOR": "maior", "MINOR": "menor", "WARNING": "menor",
                      "INFO": "info", "INDETERMINATE": "info"}

SEVERIDADE_ORDEM = {"critico": 0, "maior": 1, "menor": 2, "info": 3}


@dataclass(frozen=True)
class Classificacao:
    codigo: str
    rotulo: str
    severidade: str
    acao: str  # 'alarme' | 'normalizou'


def classificar(mensagem: str) -> Classificacao:
    acao = "normalizou" if _NORMALIZOU.search(mensagem) else "alarme"
    for padrao, codigo, rotulo, sev in _CATALOGO:
        if padrao.search(mensagem):
            if codigo == "uni_link":
                rotulo = "Porta LAN da ONU caiu" if acao == "alarme" else "Porta LAN da ONU voltou"
            return Classificacao(codigo, rotulo, sev, acao)
    return Classificacao("outro", mensagem, "menor", acao)


def chave_evento(ev: dict) -> str:
    return "|".join(str(ev.get(k) if ev.get(k) is not None else "") for k in ("data_olt", "porta", "onu_id", "uni", "mensagem"))


# ------------------------------------------------------------------ datas

# Sem relógio (OLT desligada), a FD16xx volta a contar de 2000-01-01 00:00 UTC.
EPOCA_SEM_RELOGIO = datetime(2000, 1, 1, tzinfo=timezone.utc)
ANO_MINIMO_VALIDO = 2015


def converter_data(data_olt: str, fuso: timezone | None, boot_utc: datetime | None,
                   agora: datetime) -> tuple[datetime | None, bool]:
    """Data como a OLT mostrou → (UTC, estimada?).

    Datas de antes do relógio ser acertado (ano 1999/2000) são reconstruídas a
    partir do boot: `real ≈ boot + (data_falsa − 2000-01-01 UTC)`. Só vale para
    eventos do boot atual; o que não fizer sentido volta None.
    """
    try:
        ingenua = datetime.strptime(data_olt, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None, False
    fuso = fuso or timezone.utc
    local = ingenua.replace(tzinfo=fuso)
    if local.year >= ANO_MINIMO_VALIDO:
        return local.astimezone(timezone.utc), False
    if boot_utc is None:
        return None, False
    real = boot_utc + (local - EPOCA_SEM_RELOGIO)
    if real < boot_utc or real > agora + timedelta(minutes=5):
        return None, False
    return real.astimezone(timezone.utc), True
