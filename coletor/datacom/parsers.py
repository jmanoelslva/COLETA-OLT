"""Parsers da CLI DmOS (Datacom DM4610, DmOS 12.6) — testados com saídas reais
anonimizadas em tests/fixtures/datacom_*.txt.

Tabelas do DmOS são alinhadas pela linha de traços (`----  ----`): as colunas
são recortadas pelas posições dos traços, o que aguenta valores com espaço
("Dying gasp", "OMCC problem", "DM4610 HW2").
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..cdata.parsers import ErroCli, chave_valor


_ERRO = re.compile(r"^\s*(syntax error.*|Error\s*:.*|% ?(Invalid|Unknown|Incomplete).*|Aborted:.*)$", re.I | re.M)


def checar_erro(saida: str) -> None:
    m = _ERRO.search(saida)
    if m:
        raise ErroCli(m.group(1).strip())


def _na(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v in ("", "N/A", "-", "--") else v


def _num(v: str | None) -> float | None:
    v = _na(v)
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", v)
    return float(m.group(0)) if m else None


def data_dmos(v: str | None) -> datetime | None:
    """`2026-10-02 11:16:41 UTC-3` → datetime com fuso."""
    v = _na(v)
    if not v:
        return None
    m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.\d+)?\s*UTC([+-]\d{1,2})(?::?(\d\d))?", v)
    if not m:
        return None
    h = int(m[2])
    off = timedelta(hours=h, minutes=(int(m[3] or 0) * (1 if h >= 0 else -1)))
    return datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(off))


def colunas(saida: str) -> list[dict[str, str]]:
    """Tabela alinhada por traços → lista de dicts (cabeçalho = linha acima dos traços)."""
    linhas = saida.splitlines()
    for i, l in enumerate(linhas):
        if i and re.fullmatch(r"\s*-{2,}(\s+-{2,})+\s*", l):
            spans = [(m.start(), m.end()) for m in re.finditer(r"-+", l)]
            inicios = [s for s, _ in spans] + [None]
            cab = linhas[i - 1]

            def fatiar(texto: str) -> list[str]:
                return [texto[inicios[k]:inicios[k + 1]].strip() if inicios[k] < len(texto) else ""
                        for k in range(len(spans))]

            nomes = fatiar(cab.ljust(len(l)))
            out = []
            for d in linhas[i + 1:]:
                if not d.strip() or re.fullmatch(r"\s*-+.*", d) or d.rstrip().endswith("#"):
                    break
                out.append(dict(zip(nomes, fatiar(d))))
            return out
    return []


# ---------------------------------------------------------------- ONUs


def onus_porta(saida: str) -> list[dict]:
    """`show interface gpon 1/1/<p> onu` → status + sinal na ONU + nome, por ONU."""
    checar_erro(saida)
    out = []
    for r in colunas(saida):
        itf = r.get("Itf", "")
        m = re.match(r"\d+/\d+/(\d+)$", itf)
        if not m or not r.get("ONU ID", "").isdigit():
            continue
        estado = (r.get("Oper State") or "").lower()
        out.append({
            "porta": int(m[1]),
            "onu_id": int(r["ONU ID"]),
            "sn": _na(r.get("Serial Number")),
            "run_state": "online" if estado == "up" else "offline" if estado == "down" else estado or None,
            "last_down_cause": _na(r.get("Last Down Reason")),
            "rx": _num(r.get("Rx Power [dBm]")),
            "tx": _num(r.get("Tx Power [dBm]")),
            "descricao": _na(r.get("Name")),
        })
    return out


def duracao_uptime(v: str | None) -> int | None:
    """Uptime da ONU: `03:35` (h:min), `1d 03:35`, `2 days, 03:35:10`."""
    v = _na(v)
    if not v:
        return None
    dias = 0
    d = re.search(r"(\d+)\s*d(?:ays?)?", v)
    if d:
        dias = int(d[1])
    hm = re.search(r"(\d+):(\d\d)(?::(\d\d))?", v)
    if not hm and not d:
        return None
    h, mi, s = (int(hm[1]), int(hm[2]), int(hm[3] or 0)) if hm else (0, 0, 0)
    return ((dias * 24 + h) * 60 + mi) * 60 + s


def onu_detalhe(saida: str) -> dict:
    """`show interface gpon 1/1/<p> onu <id>`. O campo Password é ignorado de propósito."""
    checar_erro(saida)
    kv = chave_valor(saida)
    dist_km = _num(kv.get("Distance"))
    estado = (kv.get("Operational state") or "").strip().lower()
    return {
        "onu_id": int(kv["ID"]) if (kv.get("ID") or "").strip().isdigit() else None,
        "sn": _na(kv.get("Serial Number")),
        "descricao": _na(kv.get("Name")),
        "modelo_onu": _na(kv.get("Equipment ID")),
        "run_state": "online" if estado == "up" else "offline" if estado == "down" else estado or None,
        "control_flag": (_na(kv.get("Primary status")) or "").lower() or None,
        "last_down_cause": _na(kv.get("Last down reason")),
        "last_down_dt": data_dmos(kv.get("Last down time")),
        "online_seg": duracao_uptime(kv.get("Uptime")),
        "distancia_m": int(round(dist_km * 1000)) if dist_km is not None else None,
        "line_profile": _na(kv.get("Line Profile")),
        "service_profile": _na(kv.get("Service Profile")),
        "versao_onu": _na(kv.get("Version")),
        "rx": _num(kv.get("Rx Optical Power [dBm]")),
        "tx": _num(kv.get("Tx Optical Power [dBm]")),
    }


def rssi(saida: str) -> float | None:
    """RX na OLT de uma ONU. ONU fora do ar → None."""
    checar_erro(saida)
    m = re.search(r"RSSI \[dBm\]\s*:\s*(-?\d+(?:\.\d+)?)", saida)
    return float(m[1]) if m else None


def contagem_global(saida: str) -> dict | None:
    checar_erro(saida)
    m = re.search(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", saida, re.M)
    if not m:
        return None
    return {"total": int(m[1]), "nao_provisionadas": int(m[2]), "up": int(m[3]), "down": int(m[4])}


# ---------------------------------------------------------------- alarmes

_LINHA_ALARME = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC[+-]\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*?)\s*$"
)


def alarmes(saida: str) -> list[dict]:
    """`show alarm` (só ativos)."""
    checar_erro(saida)
    out = []
    for linha in saida.splitlines():
        m = _LINHA_ALARME.match(linha.strip())
        if not m:
            continue
        origem = m[3]
        porta = onu = None
        g = re.match(r"gpon-\d+/\d+/(\d+)(?:/(\d+))?$", origem)
        if g:
            porta = int(g[1])
            onu = int(g[2]) if g[2] else None
        out.append({
            "data_olt": m[1],
            "data": data_dmos(m[1]),
            "severidade_olt": m[2].upper(),
            "origem": origem,
            "porta": porta,
            "onu_id": onu,
            "status": m[4],
            "nome": m[5],
            "descricao": m[6],
        })
    return out


# ---------------------------------------------------------------- equipamento


def cpu(saida: str) -> dict:
    checar_erro(saida)
    m = re.search(r"^\s*active\s+(\d+)%\s+(\d+)%\s+(\d+)%", saida, re.M)
    up = re.search(r"cpuSysUptime\s+(\d+)", saida)
    return {
        "uso_5s": float(m[1]) if m else None,
        "uso": float(m[2]) if m else None,  # média de 1 min
        "uso_5min": float(m[3]) if m else None,
        "uptime_s": int(up[1]) if up else None,
    }


def _mib(v: str) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*(MiB|KiB|GiB|bytes)", v)
    if not m:
        return None
    n = float(m[1])
    return {"GiB": n * 1024, "MiB": n, "KiB": n / 1024, "bytes": n / 1048576}[m[2]]


def memoria(saida: str) -> dict:
    checar_erro(saida)
    out = {"total_mb": None, "livre_mb": None, "uso": None}
    t = re.search(r"^\s*total\s+(\S+ \S+)", saida, re.M)
    u = re.search(r"^\s*used\s+(\S+ \S+)", saida, re.M)
    a = re.search(r"^\s*available\s+(\S+ \S+)", saida, re.M)
    total = _mib(t[1]) if t else None
    usado = _mib(u[1]) if u else None
    disp = _mib(a[1]) if a else None
    out["total_mb"] = round(total, 1) if total else None
    out["livre_mb"] = round(disp, 1) if disp is not None else None
    if total and usado is not None:
        out["uso"] = round(usado / total * 100, 1)
    return out


def _tabela_barras(bloco: str) -> list[list[str]]:
    linhas = []
    for l in bloco.splitlines():
        if "|" in l and not re.match(r"^\s*-+", l):
            cels = [c.strip() for c in l.split("|")]
            if cels and re.match(r"^\d+/", cels[0]):
                linhas.append(cels)
    return linhas


def ambiente(saida: str) -> dict:
    """`show environment` → sensores, ventoinhas, fontes."""
    checar_erro(saida)
    partes = re.split(r"(?m)^\s*(Temperature Sensors|Fan Information|Power Information):", saida)
    blocos = dict(zip(partes[1::2], partes[2::2]))
    sensores = []
    for c in _tabela_barras(blocos.get("Temperature Sensors", "")):
        lim = re.findall(r"-?\d+(?:\.\d+)?", c[3]) if len(c) > 3 else []
        sensores.append({"id": c[0], "nome": c[1], "temp": _num(c[2]),
                         "min": float(lim[0]) if lim else None, "max": float(lim[1]) if len(lim) > 1 else None,
                         "status": c[5] if len(c) > 5 else None})
    vent = [{"id": c[0], "rpm": int(_num(c[1]) or 0) or None, "status": c[2] if len(c) > 2 else None}
            for c in _tabela_barras(blocos.get("Fan Information", ""))]
    fontes = [{"slot": c[0], "status": c[1]} for c in _tabela_barras(blocos.get("Power Information", ""))]
    return {"sensores": sensores, "ventoinhas": vent, "fontes": fontes}


def transceivers(saida: str) -> dict[int, dict]:
    """`show interface transceivers` → SFP de cada porta GPON."""
    checar_erro(saida)
    out = {}
    for l in saida.splitlines():
        cels = [c.strip() for c in l.split("|")]
        m = re.match(r"gpon \d+/\d+/(\d+)$", cels[0]) if cels else None
        if m and len(cels) >= 6:
            out[int(m[1])] = {"temp": _num(cels[1]), "tensao": _num(cels[2]), "bias": _num(cels[3]),
                              "tx": _num(cels[4]), "rx": _num(cels[5]),
                              "vendor": None, "produto": None, "serial": None}
    return out


def portas_gpon(saida: str) -> dict[int, dict]:
    """`show interface gpon` → estado de cada porta PON e modelo do SFP."""
    checar_erro(saida)
    out: dict[int, dict] = {}
    blocos = re.split(r"(?m)^(?=Physical interface\s*:)", saida)
    for b in blocos:
        m = re.match(r"Physical interface\s*:\s*gpon \d+/\d+/(\d+),\s*(\w+),\s*Physical link is (\w+)", b)
        if not m:
            continue
        t = re.search(r"Transceiver type\s*:\s*(.+?)\s*$", b, re.M)
        n = re.search(r"\((\d+) ONUs\)", b)
        out[int(m[1])] = {
            "admin": m[2].lower(),           # enabled / disabled
            "link": m[3].lower(),            # up / down
            "transceiver": _na(t[1]) if t else None,
            "onus": int(n[1]) if n else None,
        }
    return out


def firmware(saida: str) -> dict:
    checar_erro(saida)
    bancos = {}
    ativo = None
    for i, m in enumerate(re.finditer(r"^(\d+\.\d+\.\S+)\s+(Active|Inactive)\s*$", saida, re.M)):
        bancos[f"banco{i + 1}"] = {"version": m[1], "status": m[2]}
        if m[2] == "Active":
            ativo = m[1]
    return {"bancos": bancos, "boot": ativo}

def plataforma(saida: str) -> list[dict]:
    checar_erro(saida)
    return [{"slot": r.get("Chassis/Slot"), "modelo": r.get("Product model"), "papel": r.get("Role"),
             "status": r.get("Status"), "firmware": _na(r.get("Firmware version"))} for r in colunas(saida)]


def uptime(saida: str) -> dict:
    """`show system uptime` (formato do `uptime` do Linux)."""
    checar_erro(saida)
    seg = None
    m = re.search(r"up\s+(?:(\d+)\s+days?,\s*)?(?:(\d+):(\d+)|(\d+)\s+min)", saida)
    if m:
        d = int(m[1] or 0)
        h, mi = (int(m[2]), int(m[3])) if m[2] else (0, int(m[4] or 0))
        seg = ((d * 24 + h) * 60 + mi) * 60
    la = re.search(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", saida)
    return {"uptime_s": seg, "load1": float(la[1]) if la else None, "load5": float(la[2]) if la else None,
            "load15": float(la[3]) if la else None}
