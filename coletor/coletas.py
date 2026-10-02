"""Rotinas de coleta: rodam comandos na OLT e gravam no SQLite."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import alarmes as cat
from .cdata import parsers as p
from .cdata.sessao import VIEW_CONFIG, VIEW_GPON, SessaoCData
from .config import OltConfig
from .db import Banco, agora_utc, iso

log = logging.getLogger(__name__)

# "show port ddm-info <porta> with-onu-optical" passa de 1 min em porta cheia.
TIMEOUT_DDM_ONUS = 420


@dataclass
class EstadoOlt:
    """O que precisamos lembrar entre coletas para interpretar as datas da OLT."""
    fuso: timezone | None = None
    boot_utc: datetime | None = None
    desvio_s: float | None = None
    hostname: str | None = None
    extras: dict = field(default_factory=dict)


def _relogio_e_boot(s: SessaoCData, estado: EstadoOlt) -> dict:
    agora = agora_utc()
    rel = p.relogio(s.executar("show time", VIEW_CONFIG))
    up = p.uptime(s.executar("show uptime", VIEW_CONFIG))
    if rel is not None:
        estado.fuso = rel.tzinfo  # type: ignore[assignment]
        estado.desvio_s = (rel - agora).total_seconds()
    if up["boot_local"] is not None and estado.fuso is not None:
        estado.boot_utc = up["boot_local"].replace(tzinfo=estado.fuso).astimezone(timezone.utc)
    estado.hostname = s.hostname
    return {"relogio": rel, "uptime_s": up["uptime_s"]}


# ------------------------------------------------------------------ alarmes


def coletar_alarmes(s: SessaoCData, olt: OltConfig, banco: Banco, estado: EstadoOlt) -> dict:
    _relogio_e_boot(s, estado)
    ativos = p.alarmes(s.executar("show alarm active all", VIEW_CONFIG))
    historico = p.alarmes(s.executar("show alarm history all", VIEW_CONFIG))
    agora = agora_utc()
    agora_s = iso(agora)

    def preparar(ev: dict) -> dict:
        data_utc, estimada = cat.converter_data(ev["data_olt"], estado.fuso, estado.boot_utc, agora)
        c = cat.classificar(ev["mensagem"])
        return {**ev, "chave": cat.chave_evento(ev), "data_utc": iso(data_utc), "data_estimada": int(estimada),
                "codigo": c.codigo, "acao": c.acao, "severidade": c.severidade}

    novos = 0
    with banco.conexao() as c:
        for ev in map(preparar, historico):
            cur = c.execute(
                """INSERT OR IGNORE INTO alarmes_eventos
                   (olt_id, chave, data_olt, data_utc, data_estimada, porta, onu_id, uni, mensagem,
                    codigo, acao, severidade, visto_em)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (olt.id, ev["chave"], ev["data_olt"], ev["data_utc"], ev["data_estimada"], ev["porta"],
                 ev["onu_id"], ev["uni"], ev["mensagem"], ev["codigo"], ev["acao"], ev["severidade"], agora_s),
            )
            novos += cur.rowcount

        anteriores = {
            r["chave"]: r["primeiro_visto"]
            for r in c.execute("SELECT chave, primeiro_visto FROM alarmes_ativos WHERE olt_id = ?", (olt.id,))
        }
        c.execute("DELETE FROM alarmes_ativos WHERE olt_id = ?", (olt.id,))
        for ev in map(preparar, ativos):
            c.execute(
                """INSERT OR REPLACE INTO alarmes_ativos
                   (olt_id, chave, data_olt, data_utc, data_estimada, porta, onu_id, uni, mensagem,
                    codigo, severidade, primeiro_visto, ultimo_visto)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (olt.id, ev["chave"], ev["data_olt"], ev["data_utc"], ev["data_estimada"], ev["porta"],
                 ev["onu_id"], ev["uni"], ev["mensagem"], ev["codigo"], ev["severidade"],
                 anteriores.get(ev["chave"], agora_s), agora_s),
            )
    # Se nenhum evento do buffer era conhecido, pode ter havido perda entre coletas.
    perda_possivel = bool(historico) and novos == len(historico)
    return {"ativos": len(ativos), "historico_lido": len(historico), "eventos_novos": novos,
            "perda_possivel": perda_possivel}


# ------------------------------------------------------------------ sistema


def coletar_sistema(s: SessaoCData, olt: OltConfig, banco: Banco, estado: EstadoOlt) -> dict:
    tempo = _relogio_e_boot(s, estado)
    st = {
        **p.cpu(s.executar("show cpu", VIEW_CONFIG)),
        **{f"mem_{k}": v for k, v in p.memoria(s.executar("show memory", VIEW_CONFIG)).items()},
        "temp_placa": p.temperatura(s.executar("show temperature", VIEW_CONFIG)),
        "ventoinhas": p.ventoinhas(s.executar("show fan", VIEW_CONFIG)),
        "fontes": p.fontes(s.executar("show power state", VIEW_CONFIG)),
        "firmware": p.firmware(s.executar("show firmware info", VIEW_CONFIG)),
        "versao": p.versao(s.executar("show version", VIEW_CONFIG)),
    }
    sfps = {}
    erros = {}
    for porta in olt.portas_pon:
        try:
            sfps[porta] = p.ddm_porta(s.executar(f"show port ddm-info {porta}", VIEW_GPON))["sfp"]
        except p.ErroCli as e:  # porta sem SFP, por exemplo
            erros[porta] = str(e)

    agora = iso(agora_utc())
    with banco.conexao() as c:
        c.execute(
            """INSERT INTO olt_status
               (olt_id, coletado_em, cpu, load1, load5, load15, mem_total_mb, mem_livre_mb, mem_uso,
                temp_placa, uptime_s, boot_em, relogio_olt, desvio_relogio_s, ventoinhas, fontes, firmware, versao)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (olt.id, agora, st["uso"], st["load1"], st["load5"], st["load15"], st["mem_total_mb"],
             st["mem_livre_mb"], st["mem_uso"], st["temp_placa"], tempo["uptime_s"], iso(estado.boot_utc),
             tempo["relogio"].isoformat() if tempo["relogio"] else None, estado.desvio_s,
             json.dumps(st["ventoinhas"]), json.dumps(st["fontes"]), json.dumps(st["firmware"]),
             json.dumps(st["versao"])),
        )
        for porta, sfp in sfps.items():
            _gravar_sfp(c, olt.id, porta, agora, sfp)
        c.execute("UPDATE olts SET hostname = ? WHERE id = ?", (estado.hostname, olt.id))
    return {"portas_sfp": len(sfps), "erros_sfp": erros}


# RX do SFP da PON nessa faixa = sem luz chegando (a C-DATA mostra -40 dBm).
RX_SEM_LUZ_DBM = -35.0


def inferir_link(c, olt_id: str, porta: int, sfp: dict) -> str | None:
    """A CLI da C-DATA não informa o link da PON. Inferimos: porta com ONUs
    cadastradas está sem link se o RX do SFP indica sem luz ou se nenhuma ONU
    está online. Porta sem ONUs cadastradas fica indefinida (None)."""
    r = c.execute(
        "SELECT COUNT(*) total, SUM(run_state = 'online') online FROM onus WHERE olt_id = ? AND porta = ?",
        (olt_id, porta),
    ).fetchone()
    if not r["total"]:
        return None
    if sfp.get("rx") is not None and sfp["rx"] <= RX_SEM_LUZ_DBM:
        return "down"
    return "down" if not r["online"] else "up"


def _gravar_sfp(c, olt_id: str, porta: int, agora: str, sfp: dict) -> None:
    if "link" not in sfp:
        sfp = {**sfp, "link": inferir_link(c, olt_id, porta, sfp)}
    c.execute(
        """INSERT INTO pon_sfp (olt_id, porta, coletado_em, temp, tensao, bias, tx, rx, vendor, produto, serial,
                               admin, link)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (olt_id, porta, agora, sfp["temp"], sfp["tensao"], sfp["bias"], sfp["tx"], sfp["rx"],
         sfp["vendor"], sfp["produto"], sfp["serial"], sfp.get("admin"), sfp.get("link")),
    )


# ------------------------------------------------------------------ ONUs


def coletar_onus(s: SessaoCData, olt: OltConfig, banco: Banco, estado: EstadoOlt,
                 portas: list[int] | None = None) -> dict:
    total = 0
    for porta in portas or olt.portas_pon:
        lista, totais = p.ont_info_todas(s.executar(f"show ont info {porta} all", VIEW_GPON))
        sinais = p.optical_todas(s.executar(f"show ont optical-info {porta} all", VIEW_GPON))
        agora = iso(agora_utc())
        with banco.conexao() as c:
            for o in lista:
                c.execute(
                    """INSERT INTO onus (olt_id, porta, onu_id, sn, control_flag, run_state, config_state,
                                         match_state, last_down_cause, primeiro_visto, visto_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(olt_id, porta, onu_id) DO UPDATE SET
                         sn = excluded.sn, control_flag = excluded.control_flag,
                         run_state = excluded.run_state, config_state = excluded.config_state,
                         match_state = excluded.match_state, last_down_cause = excluded.last_down_cause,
                         visto_em = excluded.visto_em,
                         -- troca de ONU na mesma posição: o detalhe antigo não vale mais
                         descricao = CASE WHEN onus.sn = excluded.sn THEN onus.descricao END,
                         detalhe_em = CASE WHEN onus.sn = excluded.sn THEN onus.detalhe_em END""",
                    (olt.id, porta, o["onu_id"], o["sn"], o["control_flag"], o["run_state"], o["config_state"],
                     o["match_state"], o["last_down_cause"], agora, agora),
                )
            for sg in sinais:
                c.execute(
                    "INSERT INTO sinais_onu (olt_id, porta, onu_id, coletado_em, rx, tx, tensao, bias, temp) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (olt.id, porta, sg["onu_id"], agora, sg["rx"], sg["tx"], sg["tensao"], sg["bias"], sg["temp"]),
                )
            if totais:
                c.execute("INSERT INTO pon_resumo (olt_id, porta, coletado_em, total, online) VALUES (?,?,?,?,?)",
                          (olt.id, porta, agora, totais["total"], totais["online"]))
        total += len(lista)
    _completar_descricoes(s, olt, banco)
    return {"onus": total}


def _completar_descricoes(s: SessaoCData, olt: OltConfig, banco: Banco, limite: int = 40) -> None:
    """A descrição (nome do cliente), distância e horários de queda só vêm no
    detalhe da ONU — busca aos poucos (as sem detalhe primeiro, depois as com
    detalhe de mais de 24 h), para não alongar demais um ciclo."""
    vencido = iso(agora_utc() - timedelta(hours=24))
    with banco.conexao() as c:
        faltando = c.execute(
            "SELECT porta, onu_id FROM onus WHERE olt_id = ? AND (detalhe_em IS NULL OR detalhe_em < ?) "
            "ORDER BY detalhe_em, porta, onu_id LIMIT ?",
            (olt.id, vencido, limite),
        ).fetchall()
    for r in faltando:
        try:
            _gravar_detalhe(banco, olt, p.ont_info_uma(s.executar(f"show ont info {r['porta']} {r['onu_id']}", VIEW_GPON)))
        except p.ErroCli as e:
            log.warning("[%s] detalhe ONU %s/%s: %s", olt.id, r["porta"], r["onu_id"], e)


def _gravar_detalhe(banco: Banco, olt: OltConfig, d: dict) -> None:
    with banco.conexao() as c:
        c.execute(
            """UPDATE onus SET sn = COALESCE(?, sn), descricao = ?, control_flag = COALESCE(?, control_flag),
                   run_state = COALESCE(?, run_state), config_state = COALESCE(?, config_state),
                   match_state = COALESCE(?, match_state), last_down_cause = ?, distancia_m = ?,
                   last_up = ?, last_down = ?, last_dying_gasp = ?, online_seg = ?,
                   line_profile = ?, service_profile = ?, detalhe_em = ?
               WHERE olt_id = ? AND porta = ? AND onu_id = ?""",
            (d["sn"], d["descricao"], d["control_flag"], d["run_state"], d["config_state"], d["match_state"],
             d["last_down_cause"], d["distancia_m"], d["last_up"], d["last_down"], d["last_dying_gasp"],
             d["online_seg"], d["line_profile"], d["service_profile"], iso(agora_utc()),
             olt.id, d["porta"], d["onu_id"]),
        )


def consultar_onu(s: SessaoCData, olt: OltConfig, banco: Banco, estado: EstadoOlt, porta: int, onu_id: int) -> dict:
    """Leitura sob demanda de uma ONU (tela de detalhe → "Atualizar agora")."""
    d = p.ont_info_uma(s.executar(f"show ont info {porta} {onu_id}", VIEW_GPON))
    _gravar_detalhe(banco, olt, d)
    try:
        sg = p.optical_uma(s.executar(f"show ont optical-info {porta} {onu_id}", VIEW_GPON))
    except p.ErroCli:
        sg = {"rx": None, "tx": None, "tensao": None, "bias": None, "temp": None}  # offline
    with banco.conexao() as c:
        c.execute(
            "INSERT INTO sinais_onu (olt_id, porta, onu_id, coletado_em, rx, tx, tensao, bias, temp) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (olt.id, porta, onu_id, iso(agora_utc()), sg["rx"], sg["tx"], sg["tensao"], sg["bias"], sg["temp"]),
        )
    return {"detalhe": d, "sinal": sg}


# ------------------------------------------------------------------ RX na OLT (lento)


def coletar_rx_olt(s: SessaoCData, olt: OltConfig, banco: Banco, estado: EstadoOlt,
                   portas: list[int] | None = None) -> dict:
    lidas = 0
    erros = {}
    for porta in portas or olt.portas_pon:
        try:
            r = p.ddm_porta(s.executar(f"show port ddm-info {porta} with-onu-optical", VIEW_GPON,
                                       timeout=TIMEOUT_DDM_ONUS))
        except p.ErroCli as e:
            erros[porta] = str(e)
            continue
        agora = iso(agora_utc())
        with banco.conexao() as c:
            _gravar_sfp(c, olt.id, porta, agora, r["sfp"])
            c.executemany(
                "INSERT INTO sinais_olt (olt_id, porta, onu_id, coletado_em, rx_olt) VALUES (?,?,?,?,?)",
                [(olt.id, porta, onu, agora, rx) for onu, rx in r["rx_olt"].items()],
            )
        lidas += len(r["rx_olt"])
    return {"leituras": lidas, "erros": erros}
