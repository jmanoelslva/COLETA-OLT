"""Login pelo PWA técnico (modo COLETOR_AUTH=tecnico).

Com o coletor publicado em tecnico.hotnet.net.br/olt/, o navegador manda o
cookie de sessão do técnico (TECSESSION, path=/) também para /olt/api/*. O
coletor pergunta ao backend do técnico, na mesma máquina, se a sessão é
válida (GET /auth/me — que já confere a sessão com o Controllr) e guarda a
resposta por um minuto, para não chamar o backend a cada clique.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

VALIDADE_S = 60
_cache: dict[str, tuple[float, "Tecnico | None"]] = {}


@dataclass(frozen=True)
class Tecnico:
    usuario: str


class TecnicoIndisponivel(Exception):
    """Backend do técnico não respondeu (não é sessão inválida)."""


def _chave(cookie: str) -> str:
    # Não guarda o valor do cookie em memória, só um hash dele.
    return hashlib.sha256(cookie.encode()).hexdigest()


def validar(cookie: str | None, url_tecnico: str, nome_cookie: str) -> Tecnico | None:
    """Técnico logado, ou None se não há sessão válida."""
    if not cookie:
        return None
    chave = _chave(cookie)
    agora = time.monotonic()
    em_cache = _cache.get(chave)
    if em_cache and agora - em_cache[0] < VALIDADE_S:
        return em_cache[1]

    req = urllib.request.Request(f"{url_tecnico}/auth/me", headers={"Cookie": f"{nome_cookie}={cookie}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            corpo = json.loads(r.read().decode("utf-8") or "{}")
        tecnico: Tecnico | None = Tecnico(usuario=str(corpo.get("username") or "técnico"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            tecnico = None
        else:
            raise TecnicoIndisponivel(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TecnicoIndisponivel(str(e)) from e

    if len(_cache) > 2000:  # sessões antigas não ficam para sempre
        _cache.clear()
    _cache[chave] = (agora, tecnico)
    return tecnico
