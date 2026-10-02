"""ACL de IPs da API, editável em Configurações (parâmetro `acl_ips`).

Fica além da lista de IPs do servidor web (install.sh): esta vale na hora,
sem reinstalar. O IP real vem do header X-Real-IP, que o Apache/Nginx
sempre sobrescreve — por isso só é aceito quando a conexão chega do próprio
servidor (o coletor só ouve em 127.0.0.1). Chamada local sem esse header
(backend do app técnico, curl no servidor) não passa pela ACL.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable

from fastapi import Request

_LOCAIS = {"127.0.0.1", "::1", "localhost", "testclient"}

Rede = ipaddress.IPv4Network | ipaddress.IPv6Network


def ip_do_pedido(request: Request) -> str | None:
    """IP de quem está usando o site; None = chamada local direta (liberada)."""
    origem = request.client.host if request.client else None
    if origem in _LOCAIS:
        real = (request.headers.get("x-real-ip") or "").strip()
        return real or None
    return origem


def normalizar(itens: Iterable[str]) -> list[str]:
    """Valida e padroniza ("10.0.0.5" → "10.0.0.5/32", "10.1.2.3/24" → "10.1.2.0/24").
    Linhas vazias e comentários (# ...) são ignorados. ValueError aponta o item ruim."""
    out: list[str] = []
    for bruto in itens:
        item = str(bruto).split("#", 1)[0].strip()
        if not item:
            continue
        try:
            rede = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise ValueError(item) from None
        if str(rede) not in out:
            out.append(str(rede))
    return out


def permitido(ip: str | None, redes: list[str]) -> bool:
    if ip is None or not redes:
        return True
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if endereco.version == 6 and endereco.ipv4_mapped:  # ::ffff:1.2.3.4
        endereco = endereco.ipv4_mapped
    return any(endereco in ipaddress.ip_network(r) for r in redes)
