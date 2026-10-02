"""Parsers da CLI da C-DATA FD16xx (testados contra saídas reais em tests/fixtures).

Aceitam os dois formatos de firmware vistos na planta: V1.x (FD1616GS,
"interface-gpon", "--More--") e V3.x (V3.3.76: colunas novas nas listas,
alarmes com AlarmId/Level e "(clear)" na linha de baixo, RX OLT junto no
optical-info).

Todos recebem a saída bruta da sessão (com eco do comando e prompt) e
ignoram o que não reconhecem. Valor ausente (`--`, linha vazia) vira None.
"""

from __future__ import annotations

import re
from datetime import datetime


class ErroCli(Exception):
    """A OLT respondeu com erro (`Error:...`, `Unknown command:...`)."""


_ERRO = re.compile(r"^\s*(Error\s*:.*|Unknown command\s*:.*|% ?(Unknown|Invalid|Incomplete).*)$", re.I | re.M)


def checar_erro(saida: str) -> None:
    m = _ERRO.search(saida)
    if m:
        raise ErroCli(m.group(1).strip())


def _num(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if not v or v.startswith("-") and set(v) == {"-"}:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _int(v: str | None) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _texto(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v in ("", "--", "-") else v


def chave_valor(saida: str) -> dict[str, str]:
    """Linhas `Chave : valor` → dict (primeira ocorrência vence)."""
    out: dict[str, str] = {}
    for linha in saida.splitlines():
        if ":" not in linha:
            continue
        k, v = linha.split(":", 1)
        k = re.sub(r"\s+", " ", k).strip()
        if k and k not in out:
            out[k] = v.strip()
    return out


# ---------------------------------------------------------------- ONUs


def _kv(kv: dict[str, str], *chaves: str) -> str | None:
    """Primeiro valor existente entre nomes alternativos (V1 × V3)."""
    for c in chaves:
        if c in kv:
            return kv[c]
    return None


# V1: 10 colunas. V3: + "Desc" (nome do cliente) no fim, que pode ter espaços.
_LINHA_ONT = re.compile(
    r"^\s*(\d+)/(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S.*?))?\s*$"
)
_TOTAL_ONT = re.compile(r"Total:\s*(\d+),\s*online:\s*(\d+)", re.I)


def ont_info_todas(saida: str) -> tuple[list[dict], dict | None]:
    """`show ont info <porta> all` → (onus, totais). Em V3 a descrição já vem aqui."""
    checar_erro(saida)
    onus = []
    for linha in saida.splitlines():
        m = _LINHA_ONT.match(linha)
        if not m:
            continue
        onus.append({
            "porta": int(m[3]),
            "onu_id": int(m[4]),
            "sn": m[5],
            "control_flag": m[6].lower(),
            "run_state": m[7].lower(),
            "config_state": m[8].lower(),
            "match_state": m[9].lower(),
            "last_down_cause": _texto(m[10]),
            "descricao": _texto(m[11]),
        })
    t = _TOTAL_ONT.search(saida)
    totais = None
    if t:
        totais = {"total": int(t[1]), "online": int(t[2])}
        for nome in ("deactive", "failed", "success"):
            x = re.search(rf"{nome}:\s*(\d+)", saida, re.I)
            if x:
                totais[nome] = int(x[1])
    return onus, totais


_ONLINE = re.compile(r"(?:(\d+)\s*days?)?\s*(?:(\d+)h)?:?\s*(?:(\d+)m)?:?\s*(?:(\d+)s)?", re.I)


def duracao_online(v: str | None) -> int | None:
    """`12days 17h:26m:41s` → segundos."""
    v = _texto(v)
    if not v:
        return None
    m = _ONLINE.fullmatch(v.replace(" ", ""))
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def ont_info_uma(saida: str) -> dict:
    """`show ont info <porta> <id>`."""
    checar_erro(saida)
    kv = chave_valor(saida)
    sn = _texto(kv.get("SN"))
    return {
        "porta": _int(kv.get("Port")),
        "onu_id": _int(kv.get("ONT-ID")),
        # V3: "42061D3135A0 (4206-1D3135A0)" — fica só o serial.
        "sn": sn.split()[0] if sn else None,
        "descricao": _texto(kv.get("Description")),
        "control_flag": (_texto(kv.get("Control flag")) or "").lower() or None,
        "run_state": (_texto(kv.get("Run state")) or "").lower() or None,
        "config_state": (_texto(kv.get("Config state")) or "").lower() or None,
        "match_state": (_texto(kv.get("Match state")) or "").lower() or None,
        "distancia_m": _int(kv.get("Distance(m)")),
        "auth_mode": _texto(kv.get("Authentic mode")),
        "last_down_cause": _texto(kv.get("Last down cause")),
        "last_up": _texto(kv.get("Last up time")),
        "last_down": _texto(kv.get("Last down time")),
        "last_dying_gasp": _texto(kv.get("Last dying-gasp")),
        "online_seg": duracao_online(_kv(kv, "On line time", "Online time")),
        "line_profile": _texto(_kv(kv, "Line Profile-name", "Line profile name")),
        "service_profile": _texto(_kv(kv, "Service Profile-name", "Service profile name", "Srv profile name")),
    }


# V1: "0/0 1  1   3.22  2.20  -18.23  19.80  62.49" (tensão, TX, RX, bias, temp).
_LINHA_OPT_V1 = re.compile(
    r"^\s*\d+/\d+\s+(\d+)\s+(\d+)(?:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+))?\s*$"
)
# V3: "1  -15.02  1.77  -23.28  34.90  3.30  12.70" (RX, TX, RX na OLT, temp, tensão, corrente).
_LINHA_OPT_V3 = re.compile(r"^\s*(\d+)(?:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+))?\s*$")


def optical_todas(saida: str, porta: int | None = None) -> list[dict]:
    """`show ont optical-info <porta> all`. ONU offline vem só com o ID (ou "--").
    Em V3 a linha não traz a porta (vem de `porta`) e traz o RX na OLT."""
    checar_erro(saida)
    out = []
    v3 = re.search(r"OLT\s+Rx", saida, re.I) is not None
    for linha in saida.splitlines():
        if v3:
            m = _LINHA_OPT_V3.match(linha)
            if not m:
                continue
            out.append({
                "porta": porta, "onu_id": int(m[1]), "rx": _num(m[2]), "tx": _num(m[3]), "rx_olt": _num(m[4]),
                "temp": _num(m[5]), "tensao": _num(m[6]), "bias": _num(m[7]),
            })
        else:
            m = _LINHA_OPT_V1.match(linha)
            if not m:
                continue
            out.append({
                "porta": int(m[1]), "onu_id": int(m[2]), "tensao": _num(m[3]), "tx": _num(m[4]),
                "rx": _num(m[5]), "bias": _num(m[6]), "temp": _num(m[7]),
            })
    return out


def optical_uma(saida: str) -> dict:
    """`show ont optical-info <porta> <id>` (ONU offline → ErroCli)."""
    checar_erro(saida)
    kv = chave_valor(saida)
    return {
        "porta": _int(kv.get("Port")),
        "onu_id": _int(kv.get("ONT-ID")),
        "tensao": _num(kv.get("Voltage(V)")),
        "tx": _num(kv.get("Tx optical power(dBm)")),
        "rx": _num(kv.get("Rx optical power(dBm)")),
        "bias": _num(kv.get("Laser bias current(mA)")),
        "temp": _num(kv.get("Temperature(C)")),
        "rx_olt": _num(_kv(kv, "OLT Rx ONT optical power(dBm)", "OLT Rx optical power(dBm)")),
    }


_LINHA_RX_OLT = re.compile(r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?|--)\s*$")


def ddm_porta(saida: str) -> dict:
    """`show port ddm-info <porta> [with-onu-optical]` → SFP da PON + RX na OLT por ONU."""
    checar_erro(saida)
    kv = chave_valor(saida)
    sfp = {
        "temp": _num(_kv(kv, "Temperature(C)", "Temp(C)")),
        "tensao": _num(_kv(kv, "Supply Voltage(V)", "Voltage(V)")),
        "bias": _num(_kv(kv, "TX Bias current(mA)", "Bias(mA)")),
        "tx": _num(_kv(kv, "TX power(dBm)", "TX power(dBM)")),
        "rx": _num(_kv(kv, "RX power(dBm)", "RX power(dBM)")),
        "vendor": _texto(_kv(kv, "Vendor", "Vendor Name")),
        "produto": _texto(_kv(kv, "Product name", "Ordering Name")),
        "serial": _texto(_kv(kv, "Serial number", "Serial Number")),
    }
    rx_olt: dict[int, float | None] = {}
    na_tabela = False
    for linha in saida.splitlines():
        if re.match(r"^\s*ONT\s+Rx optical", linha):
            na_tabela = True
            continue
        if na_tabela:
            m = _LINHA_RX_OLT.match(linha)
            if m:
                rx_olt[int(m[1])] = _num(m[2])
    return {"sfp": sfp, "rx_olt": rx_olt}


# ---------------------------------------------------------------- alarmes


# V1: "2026-10-02 13:27:53 PON 0/0/8 ONU 7 [UNI 0/1] mensagem"
_LINHA_ALARME = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+PON\s+(\d+)/(\d+)/(\d+)"
    r"(?:\s+ONU\s+(\d+))?(?:\s+UNI\s+(\d+/\d+))?\s+(.+?)\s*$"
)
_LINHA_ALARME_GENERICA = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(.+?)\s*$")
# V3: "1000501 2026-10-02 19:21:04  Err  PON 0/0/2 ONU: 18 [UNI 1] ONU-SN(SHLN..)   mensagem"
_LINHA_ALARME_V3 = re.compile(
    r"^(\d+)\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(\S+)\s+"
    r"(?:PON\s+(\d+)/(\d+)/(\d+)(?:\s+ONU:\s*(\d+))?(?:\s+UNI\s+(\d+))?(?:\s+ONU-SN\(([^)]*)\))?\s+)?"
    r"(.+?)\s*$"
)
_LINHA_CLEAR_V3 = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+\(clear\)\s*$", re.I)


def alarmes(saida: str) -> list[dict]:
    """`show alarm active all` / `show alarm history all`.

    No histórico V3, "(clear)" vem na linha de baixo do alarme: vira um evento
    de normalização com a mesma origem e a mensagem + " clear" (o mesmo jeito
    que a V1 escreve)."""
    checar_erro(saida)
    out: list[dict] = []
    anterior: dict | None = None
    for linha in saida.splitlines():
        linha = linha.strip()
        c = _LINHA_CLEAR_V3.match(linha)
        if c:
            if anterior:
                out.append({**anterior, "data_olt": c[1], "mensagem": anterior["mensagem"] + " clear"})
            continue
        v3 = _LINHA_ALARME_V3.match(linha)
        if v3:
            anterior = {
                "data_olt": v3[2],
                "porta": int(v3[6]) if v3[6] else None,
                "onu_id": int(v3[7]) if v3[7] else None,
                "uni": f"0/{v3[8]}" if v3[8] else None,  # mesmo formato da V1
                "mensagem": v3[10],
            }
            out.append(anterior)
            continue
        m = _LINHA_ALARME.match(linha)
        if m:
            anterior = None
            out.append({
                "data_olt": m[1],
                "porta": int(m[4]),
                "onu_id": int(m[5]) if m[5] else None,
                "uni": m[6],
                "mensagem": m[7],
            })
            continue
        g = _LINHA_ALARME_GENERICA.match(linha)
        if g:  # alarme sem PON (sistema) — guarda a mensagem inteira
            anterior = None
            out.append({"data_olt": g[1], "porta": None, "onu_id": None, "uni": None, "mensagem": g[2]})
    return out


# ---------------------------------------------------------------- sistema


def firmware(saida: str) -> dict:
    checar_erro(saida)
    bancos: dict[str, dict] = {}
    boot = None
    for linha in saida.splitlines():
        m = re.match(r"^\s*(firmware\d+)\s+(status|version|date|build date|size)\s*:\s*(.*?)\s*$", linha)
        if m:
            bancos.setdefault(m[1], {})[m[2].replace(" ", "_")] = m[3]
            continue
        b = re.match(r"^\s*boot selection\s*:\s*(\S+)", linha)
        if b:
            boot = b[1]
    return {"bancos": bancos, "boot": boot}


def cpu(saida: str) -> dict:
    """V1: "Utilization : 10%" + load average. V3: só "Load Average(1min) : 23.27%"
    (já em %), que vira o uso."""
    checar_erro(saida)
    kv = chave_valor(saida)
    em_pct = "%" in (kv.get("Load Average(1min)") or "")
    uso = _num((kv.get("Utilization") or "").rstrip("%"))
    if uso is None and em_pct:
        uso = _num(kv["Load Average(1min)"].strip().rstrip("%"))
    return {
        "uso": uso,
        "load1": None if em_pct else _num(kv.get("Load Average(1min)")),
        "load5": None if em_pct else _num(kv.get("Load Average(5min)")),
        "load15": None if em_pct else _num(kv.get("Load Average(15min)")),
    }


def ventoinhas(saida: str) -> list[dict]:
    checar_erro(saida)
    out = []
    for m in re.finditer(r"FAN\[(\d+)\]\s*status:\s*(\S+)(?:\s*\((\d+)\s*RPM\))?", saida, re.I):
        out.append({"id": int(m[1]), "status": m[2], "rpm": int(m[3]) if m[3] else None})
    return out


def fontes(saida: str) -> list[dict]:
    """V1: "1  working". V3: "1  YES  ON  Normal  AC" (presença, energia, estado, tipo)
    seguido de uma tabela de tensões por canal, que não é fonte."""
    checar_erro(saida)
    out = []
    if re.search(r"Presence", saida, re.I):
        for m in re.finditer(r"^\s*(\d+)\s+(YES|NO)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", saida, re.M | re.I):
            if m[2].upper() == "NO":
                status = "ausente"
            elif m[4].lower() == "normal":
                status = "working"
            else:
                status = "notworking"
            out.append({"slot": int(m[1]), "status": status})
        return out
    for m in re.finditer(r"^\s*(\d+)\s+(working|notworking)\s*$", saida, re.M | re.I):
        out.append({"slot": int(m[1]), "status": m[2].lower()})
    return out


def memoria(saida: str) -> dict:
    checar_erro(saida)
    kv = chave_valor(saida)
    return {
        "total_mb": _num((kv.get("Total memory") or "").upper().removesuffix("MB")),
        "livre_mb": _num((kv.get("Free memory") or "").upper().removesuffix("MB")),
        "uso": _num((kv.get("Utilization") or "").rstrip("%")),
    }


def temperatura(saida: str) -> float | None:
    """V1: "The temperature of the board: 58.0(C)". V3: tabela "Slot current"."""
    checar_erro(saida)
    m = re.search(r"temperature of the board:\s*(-?\d+(?:\.\d+)?)", saida, re.I)
    if m:
        return float(m[1])
    if re.search(r"Slot\s+current", saida, re.I):
        t = re.search(r"^\s*\d+\s+(-?\d+(?:\.\d+)?)\s*$", saida, re.M)
        if t:
            return float(t[1])
    return None


def versao(saida: str) -> dict:
    checar_erro(saida)
    kv = chave_valor(saida)
    return {
        "hardware": _texto(kv.get("Hardware version")),
        "firmware": _texto(kv.get("Firmware version")),
        "web": _texto(kv.get("Web version")),
    }


# V1: "System up time : 43 day 1 hour 1 minute 43 second"
# V3: "System running time : 15 weeks, 6 day 19 hour 38 minute 58 second."
_UPTIME = re.compile(
    r"System (?:up|running) time\s*:\s*(?:(\d+)\s*weeks?,?)?\s*(?:(\d+)\s*days?,?)?\s*(?:(\d+)\s*hours?)?"
    r"\s*(?:(\d+)\s*minutes?)?\s*(?:(\d+)\s*seconds?)?",
    re.I,
)


def uptime(saida: str) -> dict:
    """→ {"uptime_s", "boot_local"} — boot sem fuso (o fuso vem do `show time`)."""
    checar_erro(saida)
    m = _UPTIME.search(saida)
    seg = None
    if m and any(m.groups()):
        w, d, h, mi, s = (int(x or 0) for x in m.groups())
        seg = (((w * 7 + d) * 24 + h) * 60 + mi) * 60 + s
    boot = None
    # V1: "System boot time"; V3: "System uptime time" (é a hora em que ligou).
    b = re.search(r"System (?:boot|uptime) time\s*:\s*(.+?)\s*$", saida, re.M)
    if b:
        try:
            boot = datetime.strptime(b[1].strip(), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            boot = None
    return {"uptime_s": seg, "boot_local": boot}


def relogio(saida: str) -> datetime | None:
    """`show time` → datetime com fuso (`2026-10-02 13:59:11 -0300 GMT`)."""
    checar_erro(saida)
    m = re.search(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+([+-]\d{4})", saida)
    if not m:
        return None
    return datetime.strptime(f"{m[1]} {m[2]}", "%Y-%m-%d %H:%M:%S %z")
