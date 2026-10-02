"""Parsers da CLI da C-DATA FD16xx (testados contra saídas reais em tests/fixtures).

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


_LINHA_ONT = re.compile(
    r"^\s*(\d+)/(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$"
)
_TOTAL_ONT = re.compile(r"Total:\s*(\d+),\s*online:\s*(\d+),\s*deactive:\s*(\d+),\s*failed:\s*(\d+)", re.I)


def ont_info_todas(saida: str) -> tuple[list[dict], dict | None]:
    """`show ont info <porta> all` → (onus, totais)."""
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
        })
    t = _TOTAL_ONT.search(saida)
    totais = None
    if t:
        totais = {"total": int(t[1]), "online": int(t[2]), "deactive": int(t[3]), "failed": int(t[4])}
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
    return {
        "porta": _int(kv.get("Port")),
        "onu_id": _int(kv.get("ONT-ID")),
        "sn": _texto(kv.get("SN")),
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
        "online_seg": duracao_online(kv.get("On line time")),
        "line_profile": _texto(kv.get("Line Profile-name")),
        "service_profile": _texto(kv.get("Service Profile-name")),
    }


_LINHA_OPT = re.compile(
    r"^\s*\d+/\d+\s+(\d+)\s+(\d+)(?:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+))?\s*$"
)


def optical_todas(saida: str) -> list[dict]:
    """`show ont optical-info <porta> all`. ONU offline vem só com o ID."""
    checar_erro(saida)
    out = []
    for linha in saida.splitlines():
        m = _LINHA_OPT.match(linha)
        if not m:
            continue
        out.append({
            "porta": int(m[1]),
            "onu_id": int(m[2]),
            "tensao": _num(m[3]),
            "tx": _num(m[4]),
            "rx": _num(m[5]),
            "bias": _num(m[6]),
            "temp": _num(m[7]),
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
    }


_LINHA_RX_OLT = re.compile(r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?|--)\s*$")


def ddm_porta(saida: str) -> dict:
    """`show port ddm-info <porta> [with-onu-optical]` → SFP da PON + RX na OLT por ONU."""
    checar_erro(saida)
    kv = chave_valor(saida)
    sfp = {
        "temp": _num(kv.get("Temperature(C)")),
        "tensao": _num(kv.get("Supply Voltage(V)")),
        "bias": _num(kv.get("TX Bias current(mA)")),
        "tx": _num(kv.get("TX power(dBm)")),
        "rx": _num(kv.get("RX power(dBm)")),
        "vendor": _texto(kv.get("Vendor")),
        "produto": _texto(kv.get("Product name")),
        "serial": _texto(kv.get("Serial number")),
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


_LINHA_ALARME = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+PON\s+(\d+)/(\d+)/(\d+)"
    r"(?:\s+ONU\s+(\d+))?(?:\s+UNI\s+(\d+/\d+))?\s+(.+?)\s*$"
)
_LINHA_ALARME_GENERICA = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(.+?)\s*$")


def alarmes(saida: str) -> list[dict]:
    """`show alarm active all` / `show alarm history all`."""
    checar_erro(saida)
    out = []
    for linha in saida.splitlines():
        linha = linha.strip()
        m = _LINHA_ALARME.match(linha)
        if m:
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
    checar_erro(saida)
    kv = chave_valor(saida)
    return {
        "uso": _num((kv.get("Utilization") or "").rstrip("%")),
        "load1": _num(kv.get("Load Average(1min)")),
        "load5": _num(kv.get("Load Average(5min)")),
        "load15": _num(kv.get("Load Average(15min)")),
    }


def ventoinhas(saida: str) -> list[dict]:
    checar_erro(saida)
    out = []
    for m in re.finditer(r"FAN\[(\d+)\]\s*status:\s*(\S+)(?:\s*\((\d+)\s*RPM\))?", saida, re.I):
        out.append({"id": int(m[1]), "status": m[2], "rpm": int(m[3]) if m[3] else None})
    return out


def fontes(saida: str) -> list[dict]:
    checar_erro(saida)
    out = []
    for m in re.finditer(r"^\s*(\d+)\s+(working|notworking|\S+)\s*$", saida, re.M | re.I):
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
    checar_erro(saida)
    m = re.search(r"temperature of the board:\s*(-?\d+(?:\.\d+)?)", saida, re.I)
    return float(m[1]) if m else None


def versao(saida: str) -> dict:
    checar_erro(saida)
    kv = chave_valor(saida)
    return {
        "hardware": _texto(kv.get("Hardware version")),
        "firmware": _texto(kv.get("Firmware version")),
        "web": _texto(kv.get("Web version")),
    }


_UPTIME = re.compile(
    r"System up time\s*:\s*(?:(\d+)\s*days?)?\s*(?:(\d+)\s*hours?)?\s*(?:(\d+)\s*minutes?)?\s*(?:(\d+)\s*seconds?)?",
    re.I,
)


def uptime(saida: str) -> dict:
    """→ {"uptime_s", "boot_local"} — boot sem fuso (o fuso vem do `show time`)."""
    checar_erro(saida)
    m = _UPTIME.search(saida)
    seg = None
    if m and any(m.groups()):
        d, h, mi, s = (int(x or 0) for x in m.groups())
        seg = ((d * 24 + h) * 60 + mi) * 60 + s
    boot = None
    b = re.search(r"System boot time\s*:\s*(.+?)\s*$", saida, re.M)
    if b:
        try:
            boot = datetime.strptime(b[1], "%a %b %d %H:%M:%S %Y")
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
