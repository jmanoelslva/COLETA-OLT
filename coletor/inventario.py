"""Cadastro de OLTs (no SQLite, senha criptografada)."""

from __future__ import annotations

import json
import re
from typing import Any

from .cofre import Cofre
from .config import OltConfig
from .db import Banco, agora_utc, iso

# Fabricantes conhecidos. `coleta=False`: dá para cadastrar e testar o acesso,
# mas os comandos/parsers ainda não foram levantados.
FABRICANTES: dict[str, dict[str, Any]] = {
    "cdata": {"nome": "C-DATA", "coleta": True, "modelo_padrao": "C-DATA FD1616GS"},
    "datacom": {"nome": "Datacom (DmOS)", "coleta": True, "modelo_padrao": "Datacom DM4610"},
}

ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")

# Tabelas com dados de coleta, apagadas junto quando a OLT é excluída com histórico.
TABELAS_HISTORICO = ("onus", "sinais_onu", "sinais_olt", "pon_sfp", "pon_resumo", "olt_status",
                     "alarmes_eventos", "alarmes_ativos", "coletas")


def _para_config(r, cofre: Cofre) -> OltConfig:
    return OltConfig(
        id=r["id"], nome=r["nome"], host=r["host"] or "", usuario=r["usuario"],
        senha=cofre.decifrar(r["senha_cifrada"]), porta_ssh=int(r["porta_ssh"]),
        senha_enable=cofre.decifrar(r["senha_enable_cifrada"]), modelo=r["modelo"] or "",
        fabricante=r["fabricante"], frame_slot=r["frame_slot"],
        portas_pon=tuple(json.loads(r["portas_pon"])), ativa=bool(r["ativa"]),
    )


def listar(banco: Banco, cofre: Cofre) -> list[OltConfig]:
    with banco.conexao() as c:
        return [_para_config(r, cofre) for r in c.execute("SELECT * FROM olts ORDER BY nome")]


def obter(banco: Banco, cofre: Cofre, olt_id: str) -> OltConfig | None:
    with banco.conexao() as c:
        r = c.execute("SELECT * FROM olts WHERE id = ?", (olt_id,)).fetchone()
    return _para_config(r, cofre) if r else None


def cadastro_publico(banco: Banco, olt_id: str) -> dict | None:
    """Cadastro para a tela de edição — nunca devolve senha."""
    with banco.conexao() as c:
        r = c.execute("SELECT * FROM olts WHERE id = ?", (olt_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["portas_pon"] = json.loads(d["portas_pon"])
    d["tem_senha"] = bool(d.pop("senha_cifrada"))
    d["tem_senha_enable"] = bool(d.pop("senha_enable_cifrada"))
    return d


def validar(dados: dict, novo: bool) -> dict[str, str]:
    erros = {}
    if novo and not ID_VALIDO.match(dados.get("id", "")):
        erros["id"] = "use letras minúsculas, números e hífen (ex.: cdata-centro)"
    if not str(dados.get("nome", "")).strip():
        erros["nome"] = "obrigatório"
    if dados.get("fabricante") not in FABRICANTES:
        erros["fabricante"] = "fabricante não suportado"
    if not str(dados.get("host", "")).strip():
        erros["host"] = "obrigatório"
    try:
        p = int(dados.get("porta_ssh", 22))
        if not 1 <= p <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        erros["porta_ssh"] = "porta inválida"
    if not str(dados.get("usuario", "")).strip():
        erros["usuario"] = "obrigatório"
    if novo and not dados.get("senha"):
        erros["senha"] = "obrigatória"
    portas = dados.get("portas_pon")
    if not isinstance(portas, list) or not portas or not all(isinstance(x, int) and 1 <= x <= 64 for x in portas):
        erros["portas_pon"] = "informe as portas PON em uso (ex.: 1-8)"
    if not re.match(r"^\d+/\d+$", str(dados.get("frame_slot", "0/0"))):
        erros["frame_slot"] = "formato F/S, ex.: 0/0"
    return erros


def salvar(banco: Banco, cofre: Cofre, dados: dict, novo: bool) -> None:
    agora = iso(agora_utc())
    campos = {
        "nome": dados["nome"].strip(),
        "fabricante": dados["fabricante"],
        "modelo": (dados.get("modelo") or FABRICANTES[dados["fabricante"]]["modelo_padrao"]).strip(),
        "host": dados["host"].strip(),
        "porta_ssh": int(dados.get("porta_ssh", 22)),
        "usuario": dados["usuario"].strip(),
        "frame_slot": dados.get("frame_slot", "0/0"),
        "portas_pon": json.dumps(sorted(set(dados["portas_pon"]))),
        "ativa": int(bool(dados.get("ativa", True))),
        "atualizado_em": agora,
    }
    # Senha em branco na edição = manter a atual.
    if dados.get("senha"):
        campos["senha_cifrada"] = cofre.cifrar(dados["senha"])
    if "senha_enable" in dados and (dados["senha_enable"] or dados.get("limpar_senha_enable")):
        campos["senha_enable_cifrada"] = cofre.cifrar(dados["senha_enable"])
    with banco.conexao() as c:
        if novo:
            campos.update(id=dados["id"], criado_em=agora)
            cols = ", ".join(campos)
            c.execute(f"INSERT INTO olts ({cols}) VALUES ({', '.join('?' * len(campos))})", tuple(campos.values()))
        else:
            sets = ", ".join(f"{k} = ?" for k in campos)
            c.execute(f"UPDATE olts SET {sets} WHERE id = ?", (*campos.values(), dados["id"]))


def excluir(banco: Banco, olt_id: str, apagar_historico: bool) -> None:
    with banco.conexao() as c:
        if apagar_historico:
            for t in TABELAS_HISTORICO:
                c.execute(f"DELETE FROM {t} WHERE olt_id = ?", (olt_id,))
        c.execute("DELETE FROM olts WHERE id = ?", (olt_id,))


def importar(banco: Banco, cofre: Cofre, olts: list[OltConfig]) -> list[str]:
    """Importa do olts.toml as OLTs que ainda não estão no banco (as que já
    estão não são tocadas: o banco é quem manda depois da importação)."""
    novas = []
    with banco.conexao() as c:
        existentes = {r["id"] for r in c.execute("SELECT id FROM olts")}
        sem_cred = {r["id"] for r in c.execute("SELECT id FROM olts WHERE senha_cifrada = ''")}
    for o in olts:
        if o.id in existentes and o.id not in sem_cred:
            continue
        salvar(banco, cofre, {
            "id": o.id, "nome": o.nome, "fabricante": o.fabricante, "modelo": o.modelo, "host": o.host,
            "porta_ssh": o.porta_ssh, "usuario": o.usuario, "senha": o.senha, "senha_enable": o.senha_enable,
            "frame_slot": o.frame_slot, "portas_pon": list(o.portas_pon), "ativa": o.ativa,
        }, novo=o.id not in existentes)
        novas.append(o.id)
    return novas
