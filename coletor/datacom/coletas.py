"""Coletas da Datacom (DmOS). Mesmas tabelas da C-DATA, comandos diferentes.

Diferenças de estratégia (ver NOTAS_DATACOM.md):
- Não há histórico de alarmes na OLT. Quedas de ONU vêm do "Last down
  reason/time" do detalhe da ONU; os demais alarmes, da diferença entre
  duas leituras de `show alarm`.
- RX na OLT (RSSI) é por ONU (~2 s): roda em rodízio, uma ONU por vez, junto
  com o detalhe (`coletar_onu`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from .. import alarmes as cat
from ..coletas import EstadoOlt, _gravar_sfp
from ..config import OltConfig
from ..db import Banco, agora_utc, iso
from . import parsers as p
from .sessao import SessaoDatacom

log = logging.getLogger(__name__)

# Códigos de queda de ONU: o histórico deles vem dos dados da ONU, não do diff de `show alarm`.
_QUEDA = {"dgi", "losi", "lofi"}


def _chave(data_olt: str, porta, onu, nome: str) -> str:
    return f"{data_olt}|{porta if porta is not None else ''}|{onu if onu is not None else ''}||{nome}"


def _inserir_evento(c, olt_id: str, chave: str, data_olt: str, data_utc: datetime | None, estimada: bool,
                    porta, onu, mensagem: str, acao: str | None = None) -> int:
    cl = cat.classificar(mensagem)
    return c.execute(
        """INSERT OR IGNORE INTO alarmes_eventos
           (olt_id, chave, data_olt, data_utc, data_estimada, porta, onu_id, uni, mensagem, codigo, acao,
            severidade, visto_em)
           VALUES (?,?,?,?,?,?,?,NULL,?,?,?,?,?)""",
        (olt_id, chave, data_olt, iso(data_utc), int(estimada), porta, onu, mensagem, cl.codigo,
         acao or cl.acao, "info" if (acao or cl.acao) == "normalizou" else cl.severidade, iso(agora_utc())),
    ).rowcount


# ------------------------------------------------------------------ alarmes


def coletar_alarmes(s: SessaoDatacom, olt: OltConfig, banco: Banco, estado: EstadoOlt) -> dict:
    lista = p.alarmes(s.executar("show alarm"))
    agora = agora_utc()
    agora_s = iso(agora)
    novos = normalizados = 0
    with banco.conexao() as c:
        anteriores = {r["chave"]: dict(r) for r in c.execute(
            "SELECT * FROM alarmes_ativos WHERE olt_id = ?", (olt.id,))}
        atuais = {}
        for a in lista:
            mensagem = f"{a['nome']} {a['descricao']}".strip()
            cl = cat.classificar(mensagem)
            chave = _chave(a["data_olt"], a["porta"], a["onu_id"], a["nome"])
            sev = cat.SEVERIDADE_DATACOM.get(a["severidade_olt"], cl.severidade)
            atuais[chave] = (a, mensagem, cl, sev)
        c.execute("DELETE FROM alarmes_ativos WHERE olt_id = ?", (olt.id,))
        for chave, (a, mensagem, cl, sev) in atuais.items():
            c.execute(
                """INSERT INTO alarmes_ativos (olt_id, chave, data_olt, data_utc, data_estimada, porta, onu_id, uni,
                       mensagem, codigo, severidade, primeiro_visto, ultimo_visto)
                   VALUES (?,?,?,?,0,?,?,NULL,?,?,?,?,?)""",
                (olt.id, chave, a["data_olt"], iso(a["data"]), a["porta"], a["onu_id"], mensagem, cl.codigo, sev,
                 anteriores.get(chave, {}).get("primeiro_visto", agora_s), agora_s),
            )
            if cl.codigo not in _QUEDA:
                novos += _inserir_evento(c, olt.id, chave, a["data_olt"], a["data"], False, a["porta"],
                                         a["onu_id"], mensagem)
        # O que sumiu da lista normalizou em algum momento desde a última leitura.
        for chave, r in anteriores.items():
            if chave not in atuais and r["codigo"] not in _QUEDA:
                normalizados += _inserir_evento(
                    c, olt.id, chave + "|normalizou", r["data_olt"], agora, True, r["porta"], r["onu_id"],
                    f"{r['mensagem']} (normalizou)", acao="normalizou")
    return {"ativos": len(lista), "eventos_novos": novos, "normalizados": normalizados}


# ------------------------------------------------------------------ equipamento


def coletar_sistema(s: SessaoDatacom, olt: OltConfig, banco: Banco, estado: EstadoOlt) -> dict:
    cpu = p.cpu(s.executar("show system cpu"))
    mem = p.memoria(s.executar("show system memory"))
    amb = p.ambiente(s.executar("show environment"))
    plat = p.plataforma(s.executar("show platform"))
    sfps = p.transceivers(s.executar("show interface transceivers"))
    for porta, est in p.portas_gpon(s.executar("show interface gpon")).items():
        sfp = sfps.setdefault(porta, {"temp": None, "tensao": None, "bias": None, "tx": None, "rx": None,
                                      "vendor": None, "produto": None, "serial": None})
        sfp.update(produto=est["transceiver"], admin=est["admin"], link=est["link"])
    fw = p.firmware(s.executar("show firmware"))
    up = p.uptime(s.executar("show system uptime"))
    estado.hostname = s.hostname

    agora = agora_utc()
    uptime_s = up["uptime_s"] or cpu["uptime_s"]
    boot = agora - timedelta(seconds=uptime_s) if uptime_s else None
    estado.boot_utc = boot
    card = next((x for x in amb["sensores"] if (x["nome"] or "").lower() == "card"), None)
    ventoinhas = [{"id": v["id"], "status": "Normal" if (v["status"] or "").upper() == "NORMAL" else v["status"],
                   "rpm": v["rpm"]} for v in amb["ventoinhas"]]
    fontes = [{"slot": f["slot"], "status": "working" if (f["status"] or "").upper() == "OK" else (f["status"] or "").lower()}
              for f in amb["fontes"]]
    chassi = next((x for x in plat if x["slot"] and "/" not in x["slot"]), None)
    versao = {"hardware": chassi["modelo"] if chassi else None, "firmware": fw["boot"], "web": None}
    agora_s = iso(agora)
    with banco.conexao() as c:
        c.execute(
            """INSERT INTO olt_status
               (olt_id, coletado_em, cpu, load1, load5, load15, mem_total_mb, mem_livre_mb, mem_uso, temp_placa,
                uptime_s, boot_em, relogio_olt, desvio_relogio_s, ventoinhas, fontes, firmware, versao, sensores,
                plataforma)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?,?,?)""",
            (olt.id, agora_s, cpu["uso"], up["load1"], up["load5"], up["load15"], mem["total_mb"], mem["livre_mb"],
             mem["uso"], card["temp"] if card else None, uptime_s, iso(boot), json.dumps(ventoinhas),
             json.dumps(fontes), json.dumps(fw), json.dumps(versao), json.dumps(amb["sensores"]), json.dumps(plat)),
        )
        for porta, sfp in sfps.items():
            if porta in olt.portas_pon:
                _gravar_sfp(c, olt.id, porta, agora_s, sfp)
        c.execute("UPDATE olts SET hostname = ? WHERE id = ?", (estado.hostname, olt.id))
    return {"portas_sfp": len(sfps), "sensores": len(amb["sensores"])}


# ------------------------------------------------------------------ ONUs


def coletar_onus(s: SessaoDatacom, olt: OltConfig, banco: Banco, estado: EstadoOlt,
                 portas: list[int] | None = None) -> dict:
    total = mudaram = 0
    urgentes: list[dict] = estado.extras.setdefault("urgentes", [])
    for porta in portas or olt.portas_pon:
        lista = p.onus_porta(s.executar(f"show interface gpon 1/1/{porta} onu"))
        agora = iso(agora_utc())
        with banco.conexao() as c:
            antes = {r["onu_id"]: dict(r) for r in c.execute(
                "SELECT onu_id, sn, run_state, last_down_cause FROM onus WHERE olt_id = ? AND porta = ?",
                (olt.id, porta))}
            for o in lista:
                c.execute(
                    """INSERT INTO onus (olt_id, porta, onu_id, sn, descricao, run_state, last_down_cause,
                                         primeiro_visto, visto_em, sn_desde)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(olt_id, porta, onu_id) DO UPDATE SET
                         sn = excluded.sn, descricao = excluded.descricao, run_state = excluded.run_state,
                         last_down_cause = excluded.last_down_cause, visto_em = excluded.visto_em,
                         detalhe_em = CASE WHEN onus.sn = excluded.sn THEN onus.detalhe_em END,
                         sn_desde = CASE WHEN onus.sn = excluded.sn THEN onus.sn_desde ELSE excluded.sn_desde END""",
                    (olt.id, porta, o["onu_id"], o["sn"], o["descricao"], o["run_state"], o["last_down_cause"],
                     agora, agora, agora),
                )
                c.execute("INSERT INTO sinais_onu (olt_id, porta, onu_id, coletado_em, rx, tx) VALUES (?,?,?,?,?,?)",
                          (olt.id, porta, o["onu_id"], agora, o["rx"], o["tx"]))
                a = antes.get(o["onu_id"])
                if a and (a["run_state"] != o["run_state"] or a["last_down_cause"] != o["last_down_cause"]):
                    # Caiu/voltou desde a última leitura: lê o detalhe (hora exata) logo.
                    item = {"porta": porta, "onu_id": o["onu_id"]}
                    if item not in urgentes:
                        urgentes.append(item)
                    mudaram += 1
            c.execute("INSERT INTO pon_resumo (olt_id, porta, coletado_em, total, online) VALUES (?,?,?,?,?)",
                      (olt.id, porta, agora, len(lista), sum(o["run_state"] == "online" for o in lista)))
        total += len(lista)
    return {"onus": total, "mudaram_de_estado": mudaram}


def _local(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def coletar_onu(s: SessaoDatacom, olt: OltConfig, banco: Banco, estado: EstadoOlt, porta: int, onu_id: int) -> dict:
    """Detalhe + RSSI de uma ONU (rodízio e "Ler agora"). Registra a queda se a
    hora da última queda mudou desde a visita anterior."""
    d = p.onu_detalhe(s.executar(f"show interface gpon 1/1/{porta} onu {onu_id}"))
    rx_olt = p.rssi(s.executar(f"show interface gpon 1/1/{porta} onu {onu_id} rssi")) if d["run_state"] == "online" else None
    agora = agora_utc()
    agora_s = iso(agora)
    fuso = d["last_down_dt"].tzinfo if d["last_down_dt"] else timezone(timedelta(hours=-3))
    queda_local = _local(d["last_down_dt"])
    volta_dt = agora - timedelta(seconds=d["online_seg"]) if d["run_state"] == "online" and d["online_seg"] else None
    eventos = 0
    with banco.conexao() as c:
        c.execute(
            """UPDATE onus SET sn = COALESCE(?, sn), descricao = COALESCE(?, descricao), run_state = COALESCE(?, run_state),
                   control_flag = ?, last_down_cause = ?, distancia_m = ?, last_down = ?, last_up = ?, online_seg = ?,
                   line_profile = ?, service_profile = ?, modelo_onu = ?, versao_onu = ?, detalhe_em = ?
               WHERE olt_id = ? AND porta = ? AND onu_id = ?""",
            (d["sn"], d["descricao"], d["run_state"], d["control_flag"], d["last_down_cause"], d["distancia_m"],
             queda_local, _local(volta_dt.astimezone(fuso)) if volta_dt else None, d["online_seg"],
             d["line_profile"], d["service_profile"], d["modelo_onu"], d["versao_onu"], agora_s,
             olt.id, porta, onu_id),
        )
        c.execute("INSERT INTO sinais_onu (olt_id, porta, onu_id, coletado_em, rx, tx) VALUES (?,?,?,?,?,?)",
                  (olt.id, porta, onu_id, agora_s, d["rx"], d["tx"]))
        if rx_olt is not None:
            c.execute("INSERT INTO sinais_olt (olt_id, porta, onu_id, coletado_em, rx_olt) VALUES (?,?,?,?,?)",
                      (olt.id, porta, onu_id, agora_s, rx_olt))
        if d["last_down_dt"]:
            motivo = d["last_down_cause"] or "motivo desconhecido"
            eventos += _inserir_evento(c, olt.id, _chave(queda_local, porta, onu_id, "queda"), queda_local,
                                       d["last_down_dt"], False, porta, onu_id, f"ONU caiu ({motivo})")
            if volta_dt and volta_dt > d["last_down_dt"]:
                # Uptime vem em minutos: a hora da volta é aproximada.
                eventos += _inserir_evento(c, olt.id, _chave(queda_local, porta, onu_id, "volta"),
                                           _local(volta_dt.astimezone(fuso)), volta_dt, True, porta, onu_id,
                                           "ONU voltou", acao="normalizou")
    return {"detalhe": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()},
            "rx_olt": rx_olt, "eventos_novos": eventos}


def itens_rodizio(olt: OltConfig, banco: Banco, estado: EstadoOlt, portas: list[int] | None = None) -> list[dict]:
    """Ordem do rodízio: sem detalhe ainda → sinal fora da faixa boa → o resto,
    do detalhe mais antigo para o mais novo."""
    from ..db import PARAMETROS_PADRAO

    par = banco.parametros()
    limite = par.get("rx_onu_atencao", PARAMETROS_PADRAO["rx_onu_atencao"])
    desde = iso(agora_utc() - timedelta(hours=6))
    with banco.conexao() as c:
        rows = c.execute(
            """SELECT o.porta, o.onu_id, o.detalhe_em, o.run_state,
                      (SELECT rx FROM sinais_onu s WHERE s.olt_id = o.olt_id AND s.porta = o.porta
                         AND s.onu_id = o.onu_id AND s.coletado_em >= ? ORDER BY s.coletado_em DESC LIMIT 1) AS rx
               FROM onus o WHERE o.olt_id = ?""",
            (desde, olt.id),
        ).fetchall()
    sel = [r for r in rows if not portas or r["porta"] in portas]

    def prioridade(r) -> tuple:
        if r["detalhe_em"] is None:
            p_ = 0
        elif r["rx"] is not None and r["rx"] < limite:
            p_ = 1
        else:
            p_ = 2
        return (p_, r["detalhe_em"] or "", r["porta"], r["onu_id"])

    return [{"porta": r["porta"], "onu_id": r["onu_id"]} for r in sorted(sel, key=prioridade)]
