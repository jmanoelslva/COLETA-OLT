"""Classificação de sinal e diagnóstico (por ONU e por porta PON).

Ideias inspiradas no SignalHunter (atenuação, degradação vs. histórico,
correlação por PON), reescritas para os dados que a CLI da C-DATA dá — em
especial RX na ONU *e* RX na OLT, e o motivo da queda (LOS × dying gasp).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def classe_rx(v: float | None, saturado: float, atencao: float, critico: float) -> str:
    if v is None:
        return "sem_leitura"
    if v > saturado:
        return "saturado"
    if v < critico:
        return "critico"
    if v < atencao:
        return "atencao"
    return "bom"


_PESO = {"critico": 3, "saturado": 2, "atencao": 2, "bom": 0, "sem_leitura": 0}


def motivo_offline(causa: str | None) -> str:
    """Motivo da última queda → categoria comum aos fabricantes.
    C-DATA: "dying-gasp", "LOS", "--"; Datacom: "Dying gasp", "LOS", "OMCC problem", "N/A"."""
    c = (causa or "").strip().lower().replace(" ", "-")
    if c == "dying-gasp":
        return "energia"
    if c in ("los", "losi"):
        return "sinal"
    if c.startswith("omcc"):
        return "gerencia"
    if c.startswith("ranging"):
        return "ranging"
    if c in ("", "--", "n/a"):
        return "sem_registro"
    return "outro"


# Diferença de perda entre descida e subida que aponta um lado do enlace.
DIF_SENTIDO_DB = 3.0


def avaliar_onu(o: dict, par: dict[str, Any]) -> dict:
    """Recebe a linha da ONU (com rx, rx_olt, rx_media_7d, eventos_1h...) e
    devolve classes + um diagnóstico curto para o técnico."""
    online = o.get("run_state") == "online"
    c_onu = classe_rx(o.get("rx"), par["rx_onu_saturado"], par["rx_onu_atencao"], par["rx_onu_critico"]) if online else "sem_leitura"
    c_olt = classe_rx(o.get("rx_olt"), par["rx_olt_saturado"], par["rx_olt_atencao"], par["rx_olt_critico"]) if online else "sem_leitura"

    delta = None
    if online and o.get("rx") is not None and o.get("rx_media_7d") is not None:
        delta = round(o["rx"] - o["rx_media_7d"], 2)
    degradada = delta is not None and delta <= -abs(par["degradacao_db"])
    oscilando = (o.get("eventos_1h") or 0) >= par["oscilacao_eventos_1h"]

    atenuacao = None
    if online and o.get("rx") is not None and o.get("sfp_tx") is not None:
        atenuacao = round(o["sfp_tx"] - o["rx"], 2)

    alertas: list[str] = []
    # C-DATA: "dying-gasp", "LOS"; Datacom: "Dying gasp", "LOS", "OMCC problem".
    causa = (o.get("last_down_cause") or "").strip().lower().replace(" ", "-")
    if not online:
        if causa == "dying-gasp":
            alertas.append("Offline por falta de energia no cliente (dying gasp)")
        elif causa in ("los", "losi"):
            alertas.append("Offline sem sinal (LOS): verificar drop, conector e CTO")
        elif causa.startswith("ranging"):
            alertas.append("Offline por falha de ranging: sinal instável ou fraco, distância acima do alcance ou ONU incompatível")
        elif causa.startswith("omcc"):
            alertas.append("Offline por falha de gerência (OMCC): ONU travada ou com firmware/perfil incompatível")
        elif not causa or causa in ("--", "n/a"):
            alertas.append("Offline sem queda registrada: não subiu desde que a OLT ligou (cliente desligado ou equipamento recolhido?)")
        else:
            alertas.append(f"Offline ({o['last_down_cause']})")
    else:
        ruim = ("atencao", "critico")
        # Perda em cada sentido: descida = TX do SFP − RX na ONU; subida = TX da ONU − RX na OLT.
        # Na mesma fibra elas ficam próximas; diferença grande aponta o lado do problema.
        dif = None
        if None not in (o.get("sfp_tx"), o.get("rx"), o.get("tx"), o.get("rx_olt")):
            dif = (o["sfp_tx"] - o["rx"]) - (o["tx"] - o["rx_olt"])
        if dif is not None and dif <= -DIF_SENTIDO_DB and c_olt in ruim:
            alertas.append(f"RX OLT perde {abs(dif):.1f} dB a mais que o RX ONU: laser da ONU fraco "
                           "ou conector do lado do cliente")
        elif dif is not None and dif >= DIF_SENTIDO_DB and c_onu in ruim:
            # 1490 nm (descida) sofre mais com curvatura que 1310 nm (subida).
            alertas.append(f"RX ONU perde {dif:.1f} dB a mais que o RX OLT: possível curvatura "
                           "(macrobend) na fibra")
        elif c_onu in ruim and c_olt in ruim:
            alertas.append("RX ONU e RX OLT ruins: atenuação no enlace (drop, conector ou emenda)")
        elif dif is None and c_olt == "critico" and c_onu == "bom":
            alertas.append("Só o RX OLT está ruim: laser da ONU ou conector do lado do cliente")
        elif dif is None and c_onu == "critico" and c_olt == "bom":
            alertas.append("Só o RX ONU está ruim: possível curvatura (macrobend) na fibra")
        elif c_onu in ruim:
            alertas.append("RX ONU fora da faixa boa")
        elif c_olt in ruim:
            alertas.append("RX OLT fora da faixa boa")
        if "saturado" in (c_onu, c_olt):
            alertas.append("Sinal forte demais: avaliar atenuador")
        if degradada:
            alertas.append(f"RX ONU caiu {abs(delta):.1f} dB em relação à média de 7 dias")
        if o.get("temp") is not None and o["temp"] >= par["temp_onu_atencao"]:
            alertas.append(f"ONU quente ({o['temp']:.0f} °C)")
    if oscilando:
        alertas.append(f"Oscilando: {o['eventos_1h']} alarmes na última hora")

    gravidade = max(_PESO[c_onu], _PESO[c_olt])
    if not online and causa in ("los", "losi"):
        gravidade = 3
    if degradada or oscilando:
        gravidade = max(gravidade, 2)
    return {
        "online": online,
        "classe_rx": c_onu,
        "classe_rx_olt": c_olt,
        "delta_7d": delta,
        "degradada": degradada,
        "oscilando": oscilando,
        "atenuacao_db": atenuacao,
        "alertas": alertas,
        "gravidade": gravidade,
    }


def diagnosticar_olt(onus: list[dict], ativos: list[dict], quedas_15min: list[dict],
                     status: dict | None, par: dict[str, Any], portas: list[dict] | None = None) -> list[dict]:
    """Incidentes que valem uma olhada, do mais grave ao menos grave.

    `onus` já vem com o resultado de `avaliar_onu` mesclado.
    `quedas_15min`: eventos LOSi/DGi (alarme) dos últimos 15 min.
    """
    inc: list[dict] = []
    por_porta: dict[int, list[dict]] = defaultdict(list)
    for o in onus:
        por_porta[o["porta"]].append(o)

    # Porta PON inteira sem sinal.
    for a in ativos:
        if a["codigo"] == "los_pon":
            inc.append(_inc("critico", "pon_sem_sinal", f"PON {a['porta']} sem sinal",
                            "A porta PON inteira perdeu sinal: SFP da OLT, cordão no DIO ou rompimento do tronco.",
                            porta=a["porta"]))
        elif a["codigo"] == "sfp_incompativel":
            inc.append(_inc("maior", "sfp", f"SFP da PON {a['porta']} não suportado",
                            "A OLT não reconhece o módulo SFP desta porta. Confirmar modelo/compatibilidade.",
                            porta=a["porta"]))

    # Porta sem link: Datacom informa ("show interface gpon"); C-DATA é inferido pelo RX do SFP sem luz
    # ou por nenhuma ONU online. Se a OLT já acusa LOS na PON, o incidente acima basta.
    com_los = {a["porta"] for a in ativos if a["codigo"] == "los_pon"}
    for pt in portas or []:
        if pt.get("admin") != "disabled" and pt.get("link") == "down" and pt["porta"] not in com_los:
            inc.append(_inc("critico", "pon_sem_link", f"PON {pt['porta']} sem link",
                            "Porta habilitada sem link físico: SFP da OLT, cordão no DIO ou rompimento do tronco.",
                            porta=pt["porta"]))

    # Várias ONUs da mesma porta caindo juntas.
    quedas: dict[int, dict[str, set[int]]] = defaultdict(lambda: {"losi": set(), "dgi": set()})
    for ev in quedas_15min:
        if ev["porta"] is not None and ev["onu_id"] is not None:
            quedas[ev["porta"]][ev["codigo"]].add(ev["onu_id"])
    for porta, q in quedas.items():
        afetadas = q["losi"] | q["dgi"]
        total = len(por_porta.get(porta, [])) or len(afetadas)
        if len(afetadas) >= 3 and len(afetadas) >= 0.3 * total:
            if len(q["dgi"]) >= 0.6 * len(afetadas):
                inc.append(_inc("maior", "queda_energia", f"Queda de energia na região da PON {porta}",
                                f"{len(afetadas)} ONUs caíram juntas com dying gasp nos últimos 15 min: falta de "
                                "energia no bairro, não problema de fibra.", porta=porta, onus=sorted(afetadas)))
            else:
                inc.append(_inc("critico", "queda_fibra", f"Queda em massa por LOS na PON {porta}",
                                f"{len(afetadas)} ONUs perderam sinal juntas nos últimos 15 min sem dying gasp: "
                                "provável rompimento ou problema em CTO/splitter comum.", porta=porta,
                                onus=sorted(afetadas)))

    for porta, lista in sorted(por_porta.items()):
        online = [o for o in lista if o["online"]]
        if not online:
            continue
        criticas = [o for o in online if o["classe_rx"] == "critico"]
        ruins = [o for o in online if o["classe_rx"] in ("atencao", "critico")]
        degradadas = [o for o in online if o["degradada"]]
        # "Atenção" sozinho é comum em rede longa: só vira problema da porta se for quase todo mundo.
        if len(criticas) >= 3 and len(criticas) >= 0.3 * len(online):
            sev = "critico"
        elif len(ruins) >= 3 and len(ruins) >= 0.6 * len(online):
            sev = "maior"
        else:
            sev = None
        if sev:
            inc.append(_inc(sev, "pon_coletiva", f"Sinal ruim generalizado na PON {porta}",
                            f"{len(ruins)} de {len(online)} ONUs online com sinal fora da faixa boa "
                            f"({len(criticas)} em nível crítico). Comum a todas: SFP da OLT, cordão/conector no DIO "
                            "ou splitter primário.",
                            porta=porta, onus=[o["onu_id"] for o in ruins]))
        if (len(degradadas) >= 2 and len(degradadas) >= 0.15 * len(online)) or len(degradadas) >= 5:
            inc.append(_inc("maior", "pon_degradacao", f"Sinal piorando em várias ONUs da PON {porta}",
                            f"{len(degradadas)} ONUs perderam {par['degradacao_db']:.0f} dB ou mais em relação à "
                            "média de 7 dias: possível tração/curvatura no cabo ou emenda (CEO) comum.",
                            porta=porta, onus=[o["onu_id"] for o in degradadas]))

    # ONUs individuais graves (sem repetir as que já entraram num incidente coletivo).
    ja = {(i.get("porta"), x) for i in inc for x in i.get("onus", [])}
    for o in onus:
        if (o["porta"], o["onu_id"]) in ja:
            continue
        if o["online"] and (o["classe_rx"] == "critico" or o["classe_rx_olt"] == "critico"):
            inc.append(_inc("maior", "onu_critica", f"Sinal crítico na ONU {o['porta']}/{o['onu_id']}",
                            "; ".join(o["alertas"]) or "Sinal abaixo do limite crítico.", porta=o["porta"],
                            onus=[o["onu_id"]], descricao=o.get("descricao")))
        elif o["oscilando"]:
            inc.append(_inc("menor", "onu_oscilando", f"ONU {o['porta']}/{o['onu_id']} oscilando",
                            f"{o['eventos_1h']} alarmes na última hora.", porta=o["porta"], onus=[o["onu_id"]],
                            descricao=o.get("descricao")))

    # Mesmo serial em mais de uma posição.
    sns = Counter(o["sn"] for o in onus if o.get("sn"))
    for sn, n in sns.items():
        if n > 1:
            pos = [f"{o['porta']}/{o['onu_id']}" for o in onus if o.get("sn") == sn]
            inc.append(_inc("menor", "sn_duplicado", f"Serial {sn} cadastrado {n} vezes",
                            f"Posições: {', '.join(pos)}. Remover o cadastro que sobrou."))

    if status:
        if status.get("desvio_relogio_s") is not None and abs(status["desvio_relogio_s"]) > 300:
            inc.append(_inc("menor", "relogio", "Relógio da OLT errado",
                            f"Diferença de {status['desvio_relogio_s'] / 60:.0f} min para o servidor. "
                            "Datas de alarmes ficam erradas — configurar NTP."))
        for f in status.get("ventoinhas") or []:
            if str(f.get("status", "")).lower() != "normal":
                inc.append(_inc("maior", "ventoinha", f"Ventoinha {f['id']}: {f['status']}",
                                "Ventoinha fora do normal: risco de superaquecimento."))

    ordem = {"critico": 0, "maior": 1, "menor": 2, "info": 3}
    inc.sort(key=lambda i: ordem.get(i["severidade"], 9))
    return inc


def _inc(sev: str, categoria: str, titulo: str, texto: str, **extra) -> dict:
    return {"severidade": sev, "categoria": categoria, "titulo": titulo, "texto": texto, **extra}


def agrupar_eventos(eventos: list[dict], janela_s: int = 2) -> list[dict]:
    """Junta o trio DGi + LOSi + LOFi da mesma ONU no mesmo instante num evento
    só ("ONU caiu"), com a causa provável. Espera eventos ordenados por data desc."""
    out: list[dict] = []
    grupo: dict | None = None

    def fecha():
        if grupo:
            out.append(grupo)

    for ev in eventos:
        cod = ev["codigo"]
        queda = cod in ("dgi", "losi", "lofi")
        if (grupo and queda and ev["acao"] == grupo["acao"] and ev["porta"] == grupo["porta"]
                and ev["onu_id"] == grupo["onu_id"] and _perto(ev, grupo, janela_s)):
            grupo["codigos"].append(cod)
            grupo["ids"].append(ev["id"])
            _rotular_queda(grupo)
            continue
        fecha()
        grupo = None
        if queda and ev["onu_id"] is not None:
            grupo = {**ev, "codigos": [cod], "ids": [ev["id"]], "agrupado": True}
            _rotular_queda(grupo)
        else:
            out.append({**ev, "codigos": [cod], "ids": [ev["id"]], "agrupado": False})
    fecha()
    return out


def _perto(a: dict, b: dict, janela_s: int) -> bool:
    from .db import de_iso
    da, db_ = de_iso(a.get("data_utc")), de_iso(b.get("data_utc"))
    if da is None or db_ is None:
        return a["data_olt"] == b["data_olt"]
    return abs((da - db_).total_seconds()) <= janela_s


def _rotular_queda(g: dict) -> None:
    cods = set(g["codigos"])
    if g["acao"] == "normalizou":
        g["rotulo"] = "ONU voltou"
        g["severidade"] = "info"
    elif "dgi" in cods:
        g["rotulo"] = "ONU caiu: falta de energia (dying gasp)"
        g["severidade"] = "maior"
    else:
        g["rotulo"] = "ONU caiu: sem sinal (LOS) — fibra/conector"
        g["severidade"] = "critico"
