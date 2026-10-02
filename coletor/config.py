"""Configuração do serviço: variáveis de ambiente + inventário de OLTs (olts.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class OltConfig:
    id: str
    nome: str
    host: str
    usuario: str
    senha: str = field(repr=False)
    porta_ssh: int = 22
    senha_enable: str = field(default="", repr=False)
    modelo: str = "C-DATA FD1616GS"
    fabricante: str = "cdata"
    frame_slot: str = "0/0"
    portas_pon: tuple[int, ...] = tuple(range(1, 9))
    ativa: bool = True


@dataclass(frozen=True)
class Settings:
    dados: Path
    arquivo_olts: Path
    api_token: str
    cors_origens: tuple[str, ...]
    # "tecnico" = só entra quem está logado no PWA técnico (cookie TECSESSION,
    # validado no backend dele). Vazio = sem login no coletor (ex.: domínio
    # próprio, protegido por usuário/senha do servidor web).
    auth_modo: str = ""
    tecnico_url: str = "http://127.0.0.1:8000"
    tecnico_cookie: str = "TECSESSION"
    # Token do backend do app técnico para /api/integracao/* (vazio = integração desligada).
    servico_token: str = ""

    @property
    def banco(self) -> Path:
        return self.dados / "coletor.sqlite3"

    @property
    def known_hosts(self) -> Path:
        return self.dados / "known_hosts"


def carregar_settings() -> Settings:
    dados = Path(os.environ.get("COLETOR_DADOS", RAIZ / "dados"))
    return Settings(
        dados=dados,
        arquivo_olts=Path(os.environ.get("COLETOR_OLTS", RAIZ / "olts.toml")),
        # Vazio = sem autenticação (só para rodar local). Em produção é obrigatório.
        api_token=os.environ.get("COLETOR_API_TOKEN", ""),
        cors_origens=tuple(
            o.strip() for o in os.environ.get("COLETOR_CORS", "http://localhost:5174").split(",") if o.strip()
        ),
        auth_modo=os.environ.get("COLETOR_AUTH", "").strip().lower(),
        tecnico_url=os.environ.get("COLETOR_TECNICO_URL", "http://127.0.0.1:8000").rstrip("/"),
        tecnico_cookie=os.environ.get("COLETOR_TECNICO_COOKIE", "TECSESSION"),
        servico_token=os.environ.get("COLETOR_SERVICO_TOKEN", "").strip(),
    )


def carregar_olts(arquivo: Path) -> list[OltConfig]:
    """Lê o olts.toml (opcional). Usado só para importar OLTs no banco na subida."""
    if not arquivo.exists():
        return []
    with arquivo.open("rb") as f:
        bruto = tomllib.load(f)
    olts = []
    ids = set()
    for item in bruto.get("olt", []):
        olt = OltConfig(
            id=item["id"],
            nome=item.get("nome", item["id"]),
            host=item["host"],
            porta_ssh=int(item.get("porta_ssh", 22)),
            usuario=item["usuario"],
            senha=item["senha"],
            senha_enable=item.get("senha_enable", ""),
            modelo=item.get("modelo", "C-DATA FD1616GS"),
            fabricante=item.get("fabricante", "cdata"),
            frame_slot=item.get("frame_slot", "0/0"),
            portas_pon=tuple(int(p) for p in item.get("portas_pon", range(1, 9))),
            ativa=bool(item.get("ativa", True)),
        )
        if olt.id in ids:
            raise SystemExit(f"id de OLT repetido em {arquivo}: {olt.id}")
        ids.add(olt.id)
        olts.append(olt)
    return olts
