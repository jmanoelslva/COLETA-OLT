"""API HTTP do coletor (consumida pelo frontend próprio e, depois, pelo backend do app técnico)."""

from __future__ import annotations

import json
import logging
import secrets
import time
from concurrent.futures import TimeoutError as FuturoTimeout
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import alarmes as cat
from . import __version__, acl, admin, analise, integracao, inventario, sessao_tecnico
from .agendador import TIPOS, Agendador
from .cdata.parsers import ErroCli
from .cdata.sessao import ErroSessao
from .cofre import Cofre
from .config import RAIZ, OltConfig, carregar_olts, carregar_settings
from .db import PARAMETROS_PADRAO, Banco, agora_utc, de_iso, iso

log = logging.getLogger(__name__)

settings = carregar_settings()
banco = Banco(settings.banco)
cofre = Cofre(settings.dados)
agendador: Agendador | None = None

# Nunca saem pela API.
_SENSIVEIS = ("senha_cifrada", "senha_enable_cifrada", "usuario")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    global agendador
    importadas = inventario.importar(banco, cofre, carregar_olts(settings.arquivo_olts))
    if importadas:
        log.info("OLTs importadas de %s: %s", settings.arquivo_olts, importadas)
    agendador = Agendador(inventario.listar(banco, cofre), banco, settings)
    agendador.iniciar()
    yield
    agendador.parar()


app = FastAPI(title="Coletor de OLTs", version=__version__, lifespan=ciclo_de_vida)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origens), allow_methods=["*"],
                   allow_headers=["*"])

_acl_cache: tuple[float, list[str]] = (0.0, [])


@app.middleware("http")
async def filtrar_por_ip(request: Request, call_next):
    """ACL de IPs editável em Configurações (ver coletor/acl.py)."""
    global _acl_cache
    if request.url.path.startswith("/api/"):
        agora = time.monotonic()
        if agora - _acl_cache[0] > 5:
            _acl_cache = (agora, banco.parametros().get("acl_ips") or [])
        ip = acl.ip_do_pedido(request)
        if not acl.permitido(ip, _acl_cache[1]):
            return JSONResponse(status_code=403, content={
                "detail": f"O IP {ip} não está liberado no coletor. Peça para incluí-lo em Configurações, "
                          "na lista de IPs liberados."})
        # Login pelo PWA técnico. /api/saude fica aberto (só diz que o coletor
        # existe — o app técnico usa para mostrar o menu) e chamada local no
        # servidor (ip None, ex.: integração do backend do técnico) não precisa.
        # /api/integracao/* é do backend do técnico, autenticado pelo token de serviço.
        if (settings.auth_modo == "tecnico" and ip is not None and request.url.path != "/api/saude"
                and not request.url.path.startswith("/api/integracao/")):
            cookie = request.cookies.get(settings.tecnico_cookie)
            try:
                tecnico = await run_in_threadpool(
                    sessao_tecnico.validar, cookie, settings.tecnico_url, settings.tecnico_cookie)
            except sessao_tecnico.TecnicoIndisponivel as e:
                log.warning("backend do técnico não respondeu ao validar sessão: %s", e)
                return JSONResponse(status_code=503, content={
                    "detail": "O app técnico não respondeu para confirmar o seu login. Tente de novo em instantes."})
            if tecnico is None:
                return JSONResponse(status_code=401, content={
                    "detail": "Entre no app técnico para usar o coletor.", "login": "/login"})
            request.state.tecnico = tecnico
    return await call_next(request)


def autenticar(request: Request) -> None:
    if not settings.api_token:
        return
    token = request.headers.get("x-api-token") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not secrets.compare_digest(token, settings.api_token):
        raise HTTPException(401, "token inválido")


def _olt_ou_404(olt_id: str) -> dict:
    with banco.conexao() as c:
        r = c.execute("SELECT * FROM olts WHERE id = ?", (olt_id,)).fetchone()
    if not r:
        raise HTTPException(404, "OLT não encontrada")
    return _publico(r)


def _publico(r) -> dict:
    o = {k: v for k, v in dict(r).items() if k not in _SENSIVEIS}
    o["portas_pon"] = json.loads(o["portas_pon"])
    fab = inventario.FABRICANTES.get(o.get("fabricante", ""), {})
    o["fabricante_nome"] = fab.get("nome", o.get("fabricante"))
    o["coleta_suportada"] = bool(fab.get("coleta"))
    return o


def _status_mais_recente(c, olt_id: str) -> dict | None:
    r = c.execute("SELECT * FROM olt_status WHERE olt_id = ? ORDER BY coletado_em DESC LIMIT 1", (olt_id,)).fetchone()
    if not r:
        return None
    s = dict(r)
    for k in ("ventoinhas", "fontes", "firmware", "versao"):
        s[k] = json.loads(s[k]) if s[k] else None
    return s


def _ultimas_coletas(c, olt_id: str) -> dict:
    out = {}
    for t in TIPOS:
        r = c.execute(
            "SELECT inicio, fim, ok, erro FROM coletas WHERE olt_id = ? AND tipo = ? ORDER BY inicio DESC LIMIT 1",
            (olt_id, t),
        ).fetchone()
        ok = c.execute(
            "SELECT MAX(fim) AS f FROM coletas WHERE olt_id = ? AND tipo = ? AND ok = 1", (olt_id, t)
        ).fetchone()
        out[t] = {**(dict(r) if r else {}), "ultimo_ok": ok["f"] if ok else None}
    return out


rotas = Depends(autenticar)


def autenticar_servico(request: Request) -> None:
    """Token de serviço do backend do app técnico (COLETOR_SERVICO_TOKEN)."""
    if not settings.servico_token:
        raise HTTPException(503, "integração desligada: defina COLETOR_SERVICO_TOKEN no coletor")
    token = request.headers.get("x-servico-token", "")
    if not secrets.compare_digest(token.encode(), settings.servico_token.encode()):
        raise HTTPException(401, "token de serviço inválido")


servico = Depends(autenticar_servico)

# ------------------------------------------------------------------ admin

COOKIE_ADMIN = "coletor_admin"
sessoes_admin = admin.Sessoes()


def _usuario_admin(request: Request) -> str | None:
    return sessoes_admin.validar(request.cookies.get(COOKIE_ADMIN), admin.marca(banco))


def exigir_admin(request: Request) -> None:
    """Cadastro de OLTs e Configurações: só com o login de admin do coletor."""
    if _usuario_admin(request) is None:
        # 403 (e não 401): 401 faz a interface mandar para o login do app técnico.
        raise HTTPException(403, "Só o admin do coletor pode fazer isso. Entre em Admin, no alto da tela.")


so_admin = Depends(exigir_admin)


@app.get("/api/admin", dependencies=[rotas])
def estado_admin(request: Request) -> dict:
    usuario = _usuario_admin(request)
    return {"configurado": admin.configurado(banco), "logado": usuario is not None, "usuario": usuario}


@app.post("/api/admin/entrar", dependencies=[rotas])
def entrar_admin(corpo: dict[str, Any], request: Request, response: Response) -> dict:
    chave = acl.ip_do_pedido(request) or "local"
    if sessoes_admin.bloqueado(chave):
        raise HTTPException(429, "Muitas tentativas erradas. Espere 15 minutos e tente de novo.")
    if not admin.configurado(banco):
        raise HTTPException(409, "Admin ainda não definido. No servidor: sudo bash /opt/coletor-olt/deploy/install.sh")
    usuario, senha = str(corpo.get("usuario") or ""), str(corpo.get("senha") or "")
    if not admin.conferir(banco, usuario, senha):
        sessoes_admin.falhou(chave)
        log.warning("login de admin recusado (IP %s, usuário %r)", chave, usuario[:64])
        raise HTTPException(401, "Usuário ou senha de admin incorretos.")
    sessoes_admin.acertou(chave)
    token = sessoes_admin.criar(usuario.strip(), admin.marca(banco) or "")
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE_ADMIN, token, max_age=admin.SESSAO_S, httponly=True, secure=https,
                        samesite="strict", path="/")
    log.info("admin %s entrou (IP %s)", usuario.strip(), chave)
    return {"configurado": True, "logado": True, "usuario": usuario.strip()}


@app.post("/api/admin/sair", dependencies=[rotas])
def sair_admin(request: Request, response: Response) -> dict:
    sessoes_admin.encerrar(request.cookies.get(COOKIE_ADMIN))
    response.delete_cookie(COOKIE_ADMIN, path="/")
    return {"configurado": admin.configurado(banco), "logado": False, "usuario": None}


@app.put("/api/admin/senha", dependencies=[rotas, so_admin])
def trocar_senha_admin(corpo: dict[str, Any], request: Request, response: Response) -> dict:
    """Troca usuário/senha do admin (pede a senha atual). Encerra as outras sessões."""
    atual = admin.usuario_atual(banco) or ""
    if not admin.conferir(banco, atual, str(corpo.get("senha_atual") or "")):
        raise HTTPException(422, {"senha_atual": "senha atual incorreta"})
    novo_usuario = str(corpo.get("usuario") or atual).strip()
    nova = str(corpo.get("nova_senha") or "")
    erros = admin.validar_credenciais(novo_usuario, nova)
    if erros:
        raise HTTPException(422, {"nova_senha" if k == "senha" else k: v for k, v in erros.items()})
    admin.definir(banco, novo_usuario, nova)
    sessoes_admin.encerrar_todas()
    log.info("usuário/senha do admin trocados")
    return entrar_admin({"usuario": novo_usuario, "senha": nova}, request, response)


# ------------------------------------------------------------------ OLTs


@app.get("/api/olts", dependencies=[rotas])
def listar_olts() -> list[dict]:
    with banco.conexao() as c:
        olts = [_publico(r) for r in c.execute("SELECT * FROM olts ORDER BY nome")]
        for o in olts:
            o["status"] = _status_mais_recente(c, o["id"])
            sev = c.execute(
                "SELECT severidade, COUNT(*) n FROM alarmes_ativos WHERE olt_id = ? GROUP BY severidade",
                (o["id"],),
            ).fetchall()
            o["alarmes_ativos"] = {r["severidade"]: r["n"] for r in sev}
            onus = c.execute(
                "SELECT COUNT(*) total, SUM(run_state = 'online') online FROM onus WHERE olt_id = ?", (o["id"],)
            ).fetchone()
            o["onus"] = {"total": onus["total"], "online": onus["online"] or 0}
            motivos: dict[str, int] = {}
            for r in c.execute(
                "SELECT last_down_cause, COUNT(*) n FROM onus WHERE olt_id = ? AND run_state != 'online' "
                "GROUP BY last_down_cause", (o["id"],)
            ):
                m = analise.motivo_offline(r["last_down_cause"])
                motivos[m] = motivos.get(m, 0) + r["n"]
            o["offline_por_motivo"] = motivos
            # Resumo por porta para a fileira de PONs da tela inicial.
            links = {r["porta"]: r["link"] for r in c.execute(
                "SELECT p.porta, p.link FROM pon_sfp p JOIN (SELECT porta, MAX(coletado_em) m FROM pon_sfp "
                "WHERE olt_id = ? GROUP BY porta) u ON u.porta = p.porta AND u.m = p.coletado_em WHERE p.olt_id = ?",
                (o["id"], o["id"]))}
            por_porta = {r["porta"]: dict(r) for r in c.execute(
                "SELECT porta, COUNT(*) total, SUM(run_state = 'online') online, "
                "SUM(run_state != 'online' AND lower(last_down_cause) IN ('los', 'losi')) los "
                "FROM onus WHERE olt_id = ? GROUP BY porta", (o["id"],))}
            o["portas"] = [{"porta": p, "total": por_porta.get(p, {}).get("total", 0),
                            "online": por_porta.get(p, {}).get("online") or 0,
                            "los": por_porta.get(p, {}).get("los") or 0, "link": links.get(p)}
                           for p in o["portas_pon"]]
            o["coletas"] = _ultimas_coletas(c, o["id"])
    return olts


@app.get("/api/olts/{olt_id}", dependencies=[rotas])
def detalhe_olt(olt_id: str) -> dict:
    o = _olt_ou_404(olt_id)
    with banco.conexao() as c:
        o["status"] = _status_mais_recente(c, olt_id)
        o["coletas"] = _ultimas_coletas(c, olt_id)
        portas = []
        for porta in o["portas_pon"]:
            sfp = c.execute(
                "SELECT * FROM pon_sfp WHERE olt_id = ? AND porta = ? ORDER BY coletado_em DESC LIMIT 1",
                (olt_id, porta),
            ).fetchone()
            res = c.execute(
                "SELECT COUNT(*) total, SUM(run_state = 'online') online FROM onus WHERE olt_id = ? AND porta = ?",
                (olt_id, porta),
            ).fetchone()
            portas.append({"porta": porta, "sfp": dict(sfp) if sfp else None,
                           "onus_total": res["total"], "onus_online": res["online"] or 0})
        o["portas"] = portas
    o["faixas"] = agendador.status(olt_id) if agendador else []
    return o


@app.get("/api/olts/{olt_id}/status/historico", dependencies=[rotas])
def historico_status(olt_id: str, horas: int = Query(24, ge=1, le=24 * 90)) -> list[dict]:
    _olt_ou_404(olt_id)
    desde = iso(agora_utc() - timedelta(hours=horas))
    with banco.conexao() as c:
        rows = c.execute(
            "SELECT coletado_em, cpu, load1, mem_uso, temp_placa FROM olt_status "
            "WHERE olt_id = ? AND coletado_em >= ? ORDER BY coletado_em",
            (olt_id, desde),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ alarmes


def _enriquecer_evento(ev: dict) -> dict:
    c = cat.classificar(ev["mensagem"])
    return {**ev, "rotulo": c.rotulo}


@app.get("/api/olts/{olt_id}/alarmes/ativos", dependencies=[rotas])
def alarmes_ativos(olt_id: str) -> list[dict]:
    _olt_ou_404(olt_id)
    with banco.conexao() as c:
        rows = [_enriquecer_evento(dict(r)) for r in c.execute(
            "SELECT a.*, o.descricao, o.sn FROM alarmes_ativos a "
            "LEFT JOIN onus o ON o.olt_id = a.olt_id AND o.porta = a.porta AND o.onu_id = a.onu_id "
            "WHERE a.olt_id = ? ORDER BY a.data_olt DESC, a.porta, a.onu_id", (olt_id,))]
    # Junta o trio DGi/LOSi/LOFi: queda por energia não pode aparecer como "sem sinal".
    agrupados = analise.agrupar_eventos([{**r, "id": r["chave"], "acao": "alarme"} for r in rows])
    agrupados.sort(key=lambda r: (cat.SEVERIDADE_ORDEM.get(r["severidade"], 9), -(_ts(r["data_utc"]))))
    return agrupados


def _ts(s: str | None) -> float:
    d = de_iso(s)
    return d.timestamp() if d else 0.0


@app.get("/api/olts/{olt_id}/alarmes/historico", dependencies=[rotas])
def alarmes_historico(
    olt_id: str,
    horas: int = Query(24, ge=1, le=24 * 90),
    porta: int | None = None,
    onu_id: int | None = None,
    codigo: str | None = None,
    severidade: str | None = None,
    agrupar: bool = True,
    limite: int = Query(500, ge=1, le=5000),
) -> dict:
    _olt_ou_404(olt_id)
    desde = iso(agora_utc() - timedelta(hours=horas))
    filtros = ["e.olt_id = ?", "(e.data_utc >= ? OR (e.data_utc IS NULL AND e.visto_em >= ?))"]
    args: list[Any] = [olt_id, desde, desde]
    if codigo == "queda":  # o trio DGi/LOSi/LOFi, para o agrupamento dizer a causa certa
        filtros.append("e.codigo IN ('dgi', 'losi', 'lofi')")
        codigo = None
    for campo, valor in (("e.porta", porta), ("e.onu_id", onu_id), ("e.codigo", codigo),
                         ("e.severidade", severidade)):
        if valor is not None:
            filtros.append(f"{campo} = ?")
            args.append(valor)
    with banco.conexao() as c:
        rows = [_enriquecer_evento(dict(r)) for r in c.execute(
            "SELECT e.*, o.descricao FROM alarmes_eventos e "
            "LEFT JOIN onus o ON o.olt_id = e.olt_id AND o.porta = e.porta AND o.onu_id = e.onu_id "
            f"WHERE {' AND '.join(filtros)} "
            "ORDER BY COALESCE(e.data_utc, e.visto_em) DESC, e.id DESC LIMIT ?", (*args, limite))]
        contagem = c.execute(
            "SELECT codigo, acao, COUNT(*) n FROM alarmes_eventos e "
            f"WHERE {' AND '.join(filtros)} GROUP BY codigo, acao", args,
        ).fetchall()
    eventos = analise.agrupar_eventos(rows) if agrupar else rows
    return {"eventos": eventos, "contagem": [dict(r) for r in contagem], "limite_atingido": len(rows) >= limite}


# ------------------------------------------------------------------ ONUs


def _onus_avaliadas(c, olt_id: str, porta: int | None = None) -> list[dict]:
    par = banco.parametros()
    agora = agora_utc()
    d2 = iso(agora - timedelta(days=2))
    d7 = iso(agora - timedelta(days=7))
    h1 = iso(agora - timedelta(hours=1))
    filtro_porta = "AND o.porta = :porta" if porta is not None else ""
    rows = c.execute(
        f"""
        WITH ult_onu AS (
            SELECT porta, onu_id, MAX(coletado_em) m FROM sinais_onu
            WHERE olt_id = :olt AND coletado_em >= :d2 GROUP BY porta, onu_id),
        sin_onu AS (
            SELECT s.porta, s.onu_id, s.rx, s.tx, s.temp, s.tensao, s.bias, s.coletado_em
            FROM sinais_onu s JOIN ult_onu u ON u.porta = s.porta AND u.onu_id = s.onu_id AND u.m = s.coletado_em
            WHERE s.olt_id = :olt),
        ult_olt AS (
            SELECT porta, onu_id, MAX(coletado_em) m FROM sinais_olt
            WHERE olt_id = :olt AND coletado_em >= :d2 GROUP BY porta, onu_id),
        sin_olt AS (
            SELECT s.porta, s.onu_id, s.rx_olt, s.coletado_em
            FROM sinais_olt s JOIN ult_olt u ON u.porta = s.porta AND u.onu_id = s.onu_id AND u.m = s.coletado_em
            WHERE s.olt_id = :olt),
        media AS (
            SELECT porta, onu_id, ROUND(AVG(rx), 2) rx_media_7d FROM sinais_onu
            WHERE olt_id = :olt AND coletado_em >= :d7 AND rx IS NOT NULL GROUP BY porta, onu_id),
        ev AS (
            SELECT porta, onu_id, COUNT(*) eventos_1h FROM alarmes_eventos
            WHERE olt_id = :olt AND acao = 'alarme' AND data_utc >= :h1 AND onu_id IS NOT NULL
            GROUP BY porta, onu_id),
        sfp AS (
            SELECT p.porta, p.tx sfp_tx FROM pon_sfp p
            JOIN (SELECT porta, MAX(coletado_em) m FROM pon_sfp WHERE olt_id = :olt GROUP BY porta) u
              ON u.porta = p.porta AND u.m = p.coletado_em
            WHERE p.olt_id = :olt)
        SELECT o.*, so.rx, so.tx, so.temp, so.tensao, so.bias, so.coletado_em AS sinal_em,
               sl.rx_olt, sl.coletado_em AS rx_olt_em, m.rx_media_7d, COALESCE(ev.eventos_1h, 0) eventos_1h,
               sfp.sfp_tx
        FROM onus o
        LEFT JOIN sin_onu so ON so.porta = o.porta AND so.onu_id = o.onu_id
        LEFT JOIN sin_olt sl ON sl.porta = o.porta AND sl.onu_id = o.onu_id
        LEFT JOIN media m ON m.porta = o.porta AND m.onu_id = o.onu_id
        LEFT JOIN ev ON ev.porta = o.porta AND ev.onu_id = o.onu_id
        LEFT JOIN sfp ON sfp.porta = o.porta
        WHERE o.olt_id = :olt {filtro_porta}
        ORDER BY o.porta, o.onu_id
        """,
        {"olt": olt_id, "d2": d2, "d7": d7, "h1": h1, **({"porta": porta} if porta is not None else {})},
    ).fetchall()
    return [{**dict(r), **analise.avaliar_onu(dict(r), par)} for r in rows]


@app.get("/api/olts/{olt_id}/onus", dependencies=[rotas])
def listar_onus(olt_id: str, porta: int | None = None, busca: str | None = None) -> list[dict]:
    _olt_ou_404(olt_id)
    with banco.conexao() as c:
        onus = _onus_avaliadas(c, olt_id, porta)
    if busca:
        b = busca.strip().lower()
        onus = [o for o in onus if b in (o.get("sn") or "").lower() or b in (o.get("descricao") or "").lower()]
    return onus


@app.get("/api/olts/{olt_id}/diagnostico", dependencies=[rotas])
def diagnostico(olt_id: str) -> list[dict]:
    _olt_ou_404(olt_id)
    m15 = iso(agora_utc() - timedelta(minutes=15))
    with banco.conexao() as c:
        onus = _onus_avaliadas(c, olt_id)
        ativos = [dict(r) for r in c.execute("SELECT * FROM alarmes_ativos WHERE olt_id = ?", (olt_id,))]
        quedas = [dict(r) for r in c.execute(
            "SELECT porta, onu_id, codigo FROM alarmes_eventos WHERE olt_id = ? AND acao = 'alarme' "
            "AND codigo IN ('losi', 'dgi') AND data_utc >= ?", (olt_id, m15))]
        status = _status_mais_recente(c, olt_id)
        portas = [dict(r) for r in c.execute(
            "SELECT p.porta, p.admin, p.link FROM pon_sfp p JOIN (SELECT porta, MAX(coletado_em) m FROM pon_sfp "
            "WHERE olt_id = ? GROUP BY porta) u ON u.porta = p.porta AND u.m = p.coletado_em WHERE p.olt_id = ?",
            (olt_id, olt_id))]
    return analise.diagnosticar_olt(onus, ativos, quedas, status, banco.parametros(), portas)


@app.get("/api/olts/{olt_id}/onus/{porta}/{onu_id}", dependencies=[rotas])
def detalhe_onu(olt_id: str, porta: int, onu_id: int) -> dict:
    _olt_ou_404(olt_id)
    with banco.conexao() as c:
        onus = _onus_avaliadas(c, olt_id, porta)
    onu = next((o for o in onus if o["onu_id"] == onu_id), None)
    if not onu:
        raise HTTPException(404, "ONU não encontrada nesta OLT")
    return onu


@app.post("/api/olts/{olt_id}/onus/{porta}/{onu_id}/atualizar", dependencies=[rotas])
async def atualizar_onu(olt_id: str, porta: int, onu_id: int) -> dict:
    _olt_ou_404(olt_id)
    try:
        futuro = _agendador().consultar_onu(olt_id, porta, onu_id)
    except KeyError:
        raise HTTPException(409, "a coleta desta OLT está pausada ou o fabricante ainda não é suportado")
    await _esperar(futuro, 90)
    return detalhe_onu(olt_id, porta, onu_id)


@app.get("/api/olts/{olt_id}/onus/{porta}/{onu_id}/sinais", dependencies=[rotas])
def sinais_onu(olt_id: str, porta: int, onu_id: int, horas: int = Query(72, ge=1, le=24 * 90)) -> dict:
    _olt_ou_404(olt_id)
    desde = iso(agora_utc() - timedelta(hours=horas))
    with banco.conexao() as c:
        onu = [dict(r) for r in c.execute(
            "SELECT coletado_em, rx, tx, temp, tensao, bias FROM sinais_onu "
            "WHERE olt_id = ? AND porta = ? AND onu_id = ? AND coletado_em >= ? ORDER BY coletado_em",
            (olt_id, porta, onu_id, desde))]
        olt = [dict(r) for r in c.execute(
            "SELECT coletado_em, rx_olt FROM sinais_olt "
            "WHERE olt_id = ? AND porta = ? AND onu_id = ? AND coletado_em >= ? ORDER BY coletado_em",
            (olt_id, porta, onu_id, desde))]
    return {"onu": onu, "olt": olt, "limites": {k: v for k, v in banco.parametros().items() if k.startswith("rx_")}}


# ------------------------------------------------------------------ integração (app técnico)


def _historico_onu(sn: str | None, olt: str | None, porta: int | None, onu_id: int | None, horas: int) -> dict:
    agora = agora_utc()
    with banco.conexao() as c:
        try:
            onu = integracao.localizar(c, sn, olt, porta, onu_id)
        except integracao.NaoEncontrada as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        olt_id, porta, onu_id = onu["olt_id"], onu["porta"], onu["onu_id"]
        # Depois de uma troca de ONU na mesma posição, o que veio antes é de outro aparelho.
        desde = max(iso(agora - timedelta(hours=horas)), onu.get("sn_desde") or "")
        avaliada = next(o for o in _onus_avaliadas(c, olt_id, porta) if o["onu_id"] == onu_id)
        sinais = {
            "onu": [dict(r) for r in c.execute(
                "SELECT coletado_em, rx, tx, temp, tensao, bias FROM sinais_onu "
                "WHERE olt_id = ? AND porta = ? AND onu_id = ? AND coletado_em >= ? ORDER BY coletado_em",
                (olt_id, porta, onu_id, desde))],
            "olt": [dict(r) for r in c.execute(
                "SELECT coletado_em, rx_olt FROM sinais_olt "
                "WHERE olt_id = ? AND porta = ? AND onu_id = ? AND coletado_em >= ? ORDER BY coletado_em",
                (olt_id, porta, onu_id, desde))],
        }
        eventos = integracao.eventos_da_onu(c, olt_id, porta, onu_id, desde)
        ativos = [_enriquecer_evento(dict(r)) for r in c.execute(
            "SELECT * FROM alarmes_ativos WHERE olt_id = ? AND porta = ? AND onu_id = ? ORDER BY data_olt DESC",
            (olt_id, porta, onu_id))]
        pon = integracao.situacao_pon(c, olt_id, porta, iso(agora - timedelta(minutes=15)))
        coletas = _ultimas_coletas(c, olt_id)
    return {
        "olt": {"id": olt_id, "nome": onu["olt_nome"], "fabricante": onu["fabricante"]},
        "onu": avaliada,
        "historico_desde": desde,
        "sinais": sinais,
        "limites": {k: v for k, v in banco.parametros().items() if k.startswith("rx_")},
        "quedas": integracao.quedas(eventos),
        "eventos": eventos,
        "alarmes_ativos": analise.agrupar_eventos([{**r, "id": r["chave"], "acao": "alarme"} for r in ativos]),
        "pon": pon,
        "atualizado_em": {t: coletas[t].get("ultimo_ok") for t in ("onus", "alarmes")},
    }


@app.get("/api/integracao/onu", dependencies=[servico])
def integracao_onu(
    sn: str | None = Query(None, description="Serial da ONU (igual ao do Controllr)"),
    olt: str | None = Query(None, description="Sem serial: id ou nome da OLT (olt_name do Controllr)"),
    porta: int | None = None,
    onu_id: int | None = None,
    horas: int = Query(72, ge=1, le=24 * 90),
) -> dict:
    """Tudo o que o coletor sabe de uma ONU, para a tela do cliente no app técnico."""
    return _historico_onu(sn, olt, porta, onu_id, horas)


@app.post("/api/integracao/onu/atualizar", dependencies=[servico])
async def integracao_onu_atualizar(
    sn: str | None = None, olt: str | None = None, porta: int | None = None, onu_id: int | None = None,
    horas: int = Query(72, ge=1, le=24 * 90),
) -> dict:
    """Lê a ONU na OLT agora (só ela, sem reconectar a OLT) e devolve o histórico atualizado."""
    with banco.conexao() as c:
        try:
            onu = integracao.localizar(c, sn, olt, porta, onu_id)
        except integracao.NaoEncontrada as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
    try:
        futuro = _agendador().consultar_onu(onu["olt_id"], onu["porta"], onu["onu_id"])
    except KeyError:
        raise HTTPException(409, "a coleta desta OLT está pausada ou o fabricante ainda não é suportado")
    await _esperar(futuro, 90)
    return _historico_onu(None, onu["olt_id"], onu["porta"], onu["onu_id"], horas)


# ------------------------------------------------------------------ coleta manual


@app.post("/api/olts/{olt_id}/coletar/{tipo}", dependencies=[rotas])
async def coletar_agora(olt_id: str, tipo: str, porta: int | None = None, esperar: bool = True) -> dict:
    _olt_ou_404(olt_id)
    if tipo not in TIPOS:
        raise HTTPException(400, f"tipo inválido; use um de {list(TIPOS)}")
    kwargs = {"portas": [porta]} if porta is not None and tipo in ("onus", "rx_olt") else {}
    try:
        futuro = _agendador().forcar(olt_id, tipo, **kwargs)
    except KeyError:
        raise HTTPException(409, "a coleta desta OLT está pausada ou o fabricante ainda não é suportado")
    if not esperar:
        return {"enfileirado": True}
    return await _esperar(futuro, 900 if tipo == "rx_olt" else 300)


def _agendador() -> Agendador:
    if agendador is None:
        raise HTTPException(503, "agendador não iniciado")
    return agendador


async def _esperar(futuro, timeout: float) -> dict:
    try:
        return await run_in_threadpool(futuro.result, timeout)
    except FuturoTimeout:
        raise HTTPException(504, "a OLT ainda está respondendo; o resultado vai aparecer na próxima consulta")
    except ErroSessao as e:
        raise HTTPException(502, f"sem conexão com a OLT: {e}")
    except ErroCli as e:
        raise HTTPException(502, f"a OLT respondeu erro: {e}")


@app.get("/api/olts/{olt_id}/coletas", dependencies=[rotas])
def historico_coletas(olt_id: str, limite: int = Query(50, ge=1, le=500)) -> dict:
    _olt_ou_404(olt_id)
    with banco.conexao() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM coletas WHERE olt_id = ? ORDER BY inicio DESC LIMIT ?", (olt_id, limite))]
    return {"faixas": agendador.status(olt_id) if agendador else [], "coletas": rows}


# ------------------------------------------------------------------ cadastro de OLTs


@app.get("/api/fabricantes", dependencies=[rotas])
def fabricantes() -> dict:
    return inventario.FABRICANTES


@app.get("/api/olts/{olt_id}/cadastro", dependencies=[rotas, so_admin])
def ler_cadastro(olt_id: str) -> dict:
    d = inventario.cadastro_publico(banco, olt_id)
    if not d:
        raise HTTPException(404, "OLT não encontrada")
    return d


def _corpo_olt(corpo: dict[str, Any], olt_id: str | None) -> dict:
    dados = dict(corpo)
    if olt_id:
        dados["id"] = olt_id
    dados.setdefault("frame_slot", "0/0")
    return dados


@app.post("/api/olts", dependencies=[rotas, so_admin], status_code=201)
def criar_olt(corpo: dict[str, Any]) -> dict:
    dados = _corpo_olt(corpo, None)
    erros = inventario.validar(dados, novo=True)
    if not erros and inventario.cadastro_publico(banco, dados["id"]):
        erros["id"] = "já existe uma OLT com esse identificador"
    if erros:
        raise HTTPException(422, erros)
    inventario.salvar(banco, cofre, dados, novo=True)
    _agendador().aplicar(dados["id"], inventario.obter(banco, cofre, dados["id"]))
    return inventario.cadastro_publico(banco, dados["id"])


@app.put("/api/olts/{olt_id}", dependencies=[rotas, so_admin])
def editar_olt(olt_id: str, corpo: dict[str, Any]) -> dict:
    if not inventario.cadastro_publico(banco, olt_id):
        raise HTTPException(404, "OLT não encontrada")
    dados = _corpo_olt(corpo, olt_id)
    erros = inventario.validar(dados, novo=False)
    if erros:
        raise HTTPException(422, erros)
    inventario.salvar(banco, cofre, dados, novo=False)
    _agendador().aplicar(olt_id, inventario.obter(banco, cofre, olt_id))
    return inventario.cadastro_publico(banco, olt_id)


@app.delete("/api/olts/{olt_id}", dependencies=[rotas, so_admin])
def excluir_olt(olt_id: str, apagar_historico: bool = False) -> dict:
    if not inventario.cadastro_publico(banco, olt_id):
        raise HTTPException(404, "OLT não encontrada")
    _agendador().aplicar(olt_id, None)
    inventario.excluir(banco, olt_id, apagar_historico)
    return {"excluida": olt_id, "historico_apagado": apagar_historico}


@app.post("/api/olts/testar", dependencies=[rotas, so_admin])
async def testar_conexao(corpo: dict[str, Any]) -> dict:
    """Testa com os dados do formulário. Senha em branco + `id` de OLT existente
    usa a senha guardada."""
    from .teste_conexao import testar

    guardada = inventario.obter(banco, cofre, corpo["id"]) if corpo.get("id") else None
    try:
        olt = OltConfig(
            id=corpo.get("id") or "teste",
            nome=corpo.get("nome") or "teste",
            host=str(corpo["host"]).strip(),
            porta_ssh=int(corpo.get("porta_ssh") or 22),
            usuario=str(corpo["usuario"]).strip(),
            senha=corpo.get("senha") or (guardada.senha if guardada else ""),
            senha_enable=corpo.get("senha_enable") or (guardada.senha_enable if guardada else ""),
            fabricante=corpo.get("fabricante") or "cdata",
            frame_slot=corpo.get("frame_slot") or "0/0",
        )
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "informe host, porta, usuário e senha")
    if not olt.senha:
        raise HTTPException(422, "informe a senha")
    return await run_in_threadpool(testar, olt, settings.known_hosts)


# ------------------------------------------------------------------ parâmetros


@app.get("/api/parametros", dependencies=[rotas])
def ler_parametros() -> dict:
    return {"valores": banco.parametros(), "padrao": PARAMETROS_PADRAO}


@app.get("/api/saude")
def saude() -> dict:
    """Aberto (sem login): o app técnico usa para saber se mostra o menu OLTs."""
    return {"app": "coletor-olt", "versao": __version__, "login": settings.auth_modo or "servidor-web"}


@app.get("/api/acesso", dependencies=[rotas])
def meu_acesso(request: Request) -> dict:
    """IP visto pelo coletor, se está na ACL e quem está logado (para a interface)."""
    ip = acl.ip_do_pedido(request)
    tecnico = getattr(request.state, "tecnico", None)
    return {"ip": ip, "local": ip is None, "liberado": acl.permitido(ip, banco.parametros()["acl_ips"]),
            "usuario": tecnico.usuario if tecnico else None}


@app.put("/api/parametros", dependencies=[rotas, so_admin])
def salvar_parametros(novos: dict[str, Any], request: Request) -> dict:
    erros = {}
    limpos = {}
    for k, v in novos.items():
        if k not in PARAMETROS_PADRAO:
            erros[k] = "parâmetro desconhecido"
            continue
        if k == "acl_ips":
            if not isinstance(v, list):
                erros[k] = "envie uma lista de IPs ou redes"
                continue
            try:
                limpos[k] = acl.normalizar(v)
            except ValueError as e:
                erros[k] = f"IP ou rede inválido: {e}"
                continue
            ip = acl.ip_do_pedido(request)
            if not acl.permitido(ip, limpos[k]):
                erros[k] = (f"a lista não inclui o seu IP atual ({ip}); salvar assim bloquearia o seu "
                            "próprio acesso. Inclua-o ou deixe a lista vazia.")
            continue
        try:
            limpos[k] = type(PARAMETROS_PADRAO[k])(v)
        except (TypeError, ValueError):
            erros[k] = "valor inválido"
            continue
        if k.startswith("intervalo_") and limpos[k] < 60:
            erros[k] = "mínimo de 60 s"
        if k == "retencao_dias" and not 1 <= limpos[k] <= 3650:
            erros[k] = "entre 1 e 3650 dias"
    if erros:
        raise HTTPException(422, erros)
    valores = banco.salvar_parametros(limpos)
    if "acl_ips" in limpos:
        global _acl_cache
        _acl_cache = (0.0, [])  # ACL nova vale na próxima chamada
    if agendador:
        agendador.acordar_todas()
    return {"valores": valores, "padrao": PARAMETROS_PADRAO}


# ------------------------------------------------------------------ frontend


_DIST = RAIZ / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str):
        alvo = (_DIST / caminho).resolve()
        if caminho and alvo.is_file() and _DIST in alvo.parents:
            return FileResponse(alvo)
        return FileResponse(_DIST / "index.html")
