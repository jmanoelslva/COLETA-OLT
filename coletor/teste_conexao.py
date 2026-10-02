"""Teste de acesso a uma OLT antes de salvar o cadastro."""

from __future__ import annotations

import time
from pathlib import Path

import paramiko

from .cdata import parsers as p
from .cdata.sessao import VIEW_CONFIG, ErroSessao, SessaoCData
from .config import OltConfig


def testar(olt: OltConfig, known_hosts: Path) -> dict:
    inicio = time.monotonic()
    if olt.fabricante == "cdata":
        s = SessaoCData(olt, known_hosts)
        try:
            s.conectar()
            versao = p.versao(s.executar("show version", VIEW_CONFIG, timeout=120))
            relogio = p.relogio(s.executar("show time", VIEW_CONFIG, timeout=120))
        except (ErroSessao, p.ErroCli) as e:
            return {"ok": False, "erro": str(e)}
        finally:
            s.fechar()
        return {
            "ok": True,
            "hostname": s.hostname,
            "firmware": versao.get("firmware"),
            "relogio_olt": relogio.isoformat() if relogio else None,
            "tempo_ms": int((time.monotonic() - inicio) * 1000),
        }

    # Fabricante sem driver ainda: só confirma que SSH + login funcionam.
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(olt.host, port=olt.porta_ssh, username=olt.usuario, password=olt.senha,
                  look_for_keys=False, allow_agent=False, timeout=15, banner_timeout=15, auth_timeout=15)
        banner = c.get_transport().remote_version if c.get_transport() else None
    except (paramiko.SSHException, OSError) as e:
        return {"ok": False, "erro": f"SSH {olt.host}:{olt.porta_ssh}: {e}"}
    finally:
        c.close()
    return {"ok": True, "hostname": None, "firmware": banner, "relogio_olt": None,
            "tempo_ms": int((time.monotonic() - inicio) * 1000),
            "aviso": "Login SSH funcionou. A coleta deste fabricante ainda não está disponível."}
