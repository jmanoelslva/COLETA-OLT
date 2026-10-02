"""Consulta de uma ONU pelo serial, para o backend do app técnico.

O app técnico acha a ONU do cliente no Controllr (serial, OLT, porta e
posição) e pede aqui o que o Controllr não guarda: histórico de sinal, quedas
com motivo e hora, alarmes ativos e a situação da PON. O serial do Controllr é
igual ao da OLT (12 caracteres, prefixo do fabricante + hexa, maiúsculas).
"""

from __future__ import annotations

from datetime import datetime

from . import alarmes as cat
from . import analise
from .db import de_iso

# Códigos que significam "a ONU caiu" (C-DATA: trio DGi/LOSi/LOFi; Datacom:
# quedas detectadas pelo "Last down reason" — ver alarmes._CATALOGO).
CODIGOS_QUEDA = ("dgi", "losi", "lofi", "omcc", "ranging", "queda")


class NaoEncontrada(LookupError):
    pass


def normalizar_sn(sn: str) -> str:
    return "".join(sn.split()).upper()


def localizar(c, sn: str | None = None, olt: str | None = None, porta: int | None = None,
              onu_id: int | None = None) -> dict:
    """Linha da ONU em `onus` + `olt_nome`/`fabricante`.

    Pelo serial (preferido): se a mesma ONU aparecer em duas posições (mudou de
    porta e a antiga ainda não expirou), vale a vista por último. Sem serial,
    pela posição: `olt` aceita o id do cadastro ou o nome (o `olt_name` do
    Controllr)."""
    base = ("SELECT o.*, t.nome AS olt_nome, t.fabricante FROM onus o JOIN olts t ON t.id = o.olt_id ")
    if sn:
        r = c.execute(base + "WHERE o.sn = ? ORDER BY o.visto_em DESC LIMIT 1", (normalizar_sn(sn),)).fetchone()
        if not r:
            raise NaoEncontrada(f"nenhuma OLT coletada tem a ONU {normalizar_sn(sn)}")
        return dict(r)
    if olt is None or porta is None or onu_id is None:
        raise ValueError("informe o serial ou a OLT, a porta e a posição da ONU")
    r = c.execute(base + "WHERE (t.id = ? OR UPPER(t.nome) = UPPER(?)) AND o.porta = ? AND o.onu_id = ?",
                  (olt, olt, porta, onu_id)).fetchone()
    if not r:
        raise NaoEncontrada(f"nenhuma ONU em {olt} PON {porta} posição {onu_id}")
    return dict(r)


def eventos_da_onu(c, olt_id: str, porta: int, onu_id: int, desde: str) -> list[dict]:
    """Eventos de alarme da ONU desde `desde` (mais recentes primeiro), com o
    trio DGi/LOSi/LOFi agrupado numa queda só."""
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM alarmes_eventos WHERE olt_id = ? AND porta = ? AND onu_id = ? "
        "AND COALESCE(data_utc, visto_em) >= ? ORDER BY COALESCE(data_utc, visto_em) DESC, id DESC LIMIT 2000",
        (olt_id, porta, onu_id, desde))]
    return analise.agrupar_eventos([{**r, "rotulo": cat.classificar(r["mensagem"]).rotulo} for r in rows])


def quedas(eventos: list[dict]) -> list[dict]:
    """Cada queda com o motivo, a hora e quando a ONU voltou (se voltou).

    `eventos` vem de eventos_da_onu (mais recentes primeiro); a volta é o
    primeiro "normalizou" de queda depois da queda."""
    linha = [e for e in reversed(eventos) if set(e["codigos"]) & set(CODIGOS_QUEDA)]
    out = []
    for i, e in enumerate(linha):
        if e["acao"] != "alarme":
            continue
        volta = next((v for v in linha[i + 1:] if v["acao"] == "normalizou"), None)
        # Outra queda antes da volta: a ONU já tinha voltado sem o evento chegar.
        proxima = next((v for v in linha[i + 1:] if v["acao"] == "alarme"), None)
        if volta and proxima and _quando(proxima) < _quando(volta):
            volta = None
        inicio, fim = _quando(e), _quando(volta) if volta else None
        out.append({
            "caiu_em": e.get("data_utc") or e["visto_em"],
            "hora_estimada": bool(e.get("data_estimada")) or not e.get("data_utc"),
            "motivo": e["rotulo"],
            "codigos": e["codigos"],
            "severidade": e["severidade"],
            "voltou_em": (volta.get("data_utc") or volta["visto_em"]) if volta else None,
            "duracao_s": int((fim - inicio).total_seconds()) if inicio and fim else None,
        })
    out.reverse()
    return out


def _quando(e: dict | None) -> datetime | None:
    if not e:
        return None
    return de_iso(e.get("data_utc") or e.get("visto_em"))


def situacao_pon(c, olt_id: str, porta: int, desde_15min: str) -> dict:
    """A PON da ONU agora: quantas estão online e quantas caíram nos últimos
    15 minutos — muitas caindo juntas é problema da rede, não do cliente."""
    r = c.execute("SELECT COUNT(*) total, SUM(run_state = 'online') online FROM onus WHERE olt_id = ? AND porta = ?",
                  (olt_id, porta)).fetchone()
    caidas = c.execute(
        "SELECT COUNT(DISTINCT onu_id) n FROM alarmes_eventos WHERE olt_id = ? AND porta = ? AND acao = 'alarme' "
        f"AND codigo IN ({','.join('?' * len(CODIGOS_QUEDA))}) AND data_utc >= ?",
        (olt_id, porta, *CODIGOS_QUEDA, desde_15min)).fetchone()
    sfp = c.execute("SELECT link, admin FROM pon_sfp WHERE olt_id = ? AND porta = ? ORDER BY coletado_em DESC LIMIT 1",
                    (olt_id, porta)).fetchone()
    return {"porta": porta, "total": r["total"] or 0, "online": r["online"] or 0, "caidas_15min": caidas["n"] or 0,
            "link": sfp["link"] if sfp else None, "admin": sfp["admin"] if sfp else None}
