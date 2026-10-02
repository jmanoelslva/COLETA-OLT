"""SQLite do coletor. Datas sempre em UTC ISO-8601 (`2026-10-02T16:59:11Z`)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS olts (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    modelo TEXT,
    host TEXT,
    hostname TEXT,
    portas_pon TEXT NOT NULL,          -- JSON
    ativa INTEGER NOT NULL DEFAULT 1
);
-- Demais colunas de olts (fabricante, credenciais...) vêm de MIGRACOES_OLTS.

CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL                -- JSON
);

-- Cadastro/estado atual de cada ONU (sobrescrito a cada coleta).
CREATE TABLE IF NOT EXISTS onus (
    olt_id TEXT NOT NULL,
    porta INTEGER NOT NULL,
    onu_id INTEGER NOT NULL,
    sn TEXT,
    descricao TEXT,
    control_flag TEXT,
    run_state TEXT,
    config_state TEXT,
    match_state TEXT,
    last_down_cause TEXT,
    distancia_m INTEGER,
    last_up TEXT,
    last_down TEXT,
    last_dying_gasp TEXT,
    online_seg INTEGER,
    line_profile TEXT,
    service_profile TEXT,
    detalhe_em TEXT,                   -- última vez que o detalhe foi lido
    primeiro_visto TEXT NOT NULL,
    visto_em TEXT NOT NULL,
    PRIMARY KEY (olt_id, porta, onu_id)
);
CREATE INDEX IF NOT EXISTS ix_onus_sn ON onus (sn);
CREATE INDEX IF NOT EXISTS ix_onus_desc ON onus (descricao);

-- Série histórica: sinal medido na ONU (descida).
CREATE TABLE IF NOT EXISTS sinais_onu (
    olt_id TEXT NOT NULL,
    porta INTEGER NOT NULL,
    onu_id INTEGER NOT NULL,
    coletado_em TEXT NOT NULL,
    rx REAL, tx REAL, tensao REAL, bias REAL, temp REAL
);
CREATE INDEX IF NOT EXISTS ix_sinais_onu ON sinais_onu (olt_id, porta, onu_id, coletado_em);
CREATE INDEX IF NOT EXISTS ix_sinais_onu_tempo ON sinais_onu (coletado_em);

-- Série histórica: sinal da ONU recebido na OLT (subida).
CREATE TABLE IF NOT EXISTS sinais_olt (
    olt_id TEXT NOT NULL,
    porta INTEGER NOT NULL,
    onu_id INTEGER NOT NULL,
    coletado_em TEXT NOT NULL,
    rx_olt REAL
);
CREATE INDEX IF NOT EXISTS ix_sinais_olt ON sinais_olt (olt_id, porta, onu_id, coletado_em);
CREATE INDEX IF NOT EXISTS ix_sinais_olt_tempo ON sinais_olt (coletado_em);

-- DDM do SFP de cada porta PON.
CREATE TABLE IF NOT EXISTS pon_sfp (
    olt_id TEXT NOT NULL,
    porta INTEGER NOT NULL,
    coletado_em TEXT NOT NULL,
    temp REAL, tensao REAL, bias REAL, tx REAL, rx REAL,
    vendor TEXT, produto TEXT, serial TEXT
);
CREATE INDEX IF NOT EXISTS ix_pon_sfp ON pon_sfp (olt_id, porta, coletado_em);

-- Totais por porta (rodapé do "show ont info <porta> all").
CREATE TABLE IF NOT EXISTS pon_resumo (
    olt_id TEXT NOT NULL,
    porta INTEGER NOT NULL,
    coletado_em TEXT NOT NULL,
    total INTEGER, online INTEGER
);
CREATE INDEX IF NOT EXISTS ix_pon_resumo ON pon_resumo (olt_id, porta, coletado_em);

-- Saúde da OLT.
CREATE TABLE IF NOT EXISTS olt_status (
    olt_id TEXT NOT NULL,
    coletado_em TEXT NOT NULL,
    cpu REAL, load1 REAL, load5 REAL, load15 REAL,
    mem_total_mb REAL, mem_livre_mb REAL, mem_uso REAL,
    temp_placa REAL,
    uptime_s INTEGER,
    boot_em TEXT,
    relogio_olt TEXT,
    desvio_relogio_s REAL,
    ventoinhas TEXT, fontes TEXT, firmware TEXT, versao TEXT   -- JSON
);
CREATE INDEX IF NOT EXISTS ix_olt_status ON olt_status (olt_id, coletado_em);

-- Todo evento já visto no "show alarm history" (o buffer da OLT só guarda ~2000).
CREATE TABLE IF NOT EXISTS alarmes_eventos (
    id INTEGER PRIMARY KEY,
    olt_id TEXT NOT NULL,
    chave TEXT NOT NULL,               -- data_olt|porta|onu|uni|mensagem
    data_olt TEXT NOT NULL,            -- como a OLT mostrou (hora local dela)
    data_utc TEXT,                     -- convertida; NULL se não deu para estimar
    data_estimada INTEGER NOT NULL DEFAULT 0,
    porta INTEGER, onu_id INTEGER, uni TEXT,
    mensagem TEXT NOT NULL,
    codigo TEXT NOT NULL,
    acao TEXT NOT NULL,                -- 'alarme' | 'normalizou'
    severidade TEXT NOT NULL,
    visto_em TEXT NOT NULL,
    UNIQUE (olt_id, chave)
);
CREATE INDEX IF NOT EXISTS ix_eventos_tempo ON alarmes_eventos (olt_id, data_utc);
CREATE INDEX IF NOT EXISTS ix_eventos_onu ON alarmes_eventos (olt_id, porta, onu_id, data_utc);
CREATE INDEX IF NOT EXISTS ix_eventos_visto ON alarmes_eventos (visto_em);

-- Fotografia do "show alarm active" mais recente.
CREATE TABLE IF NOT EXISTS alarmes_ativos (
    olt_id TEXT NOT NULL,
    chave TEXT NOT NULL,
    data_olt TEXT NOT NULL,
    data_utc TEXT,
    data_estimada INTEGER NOT NULL DEFAULT 0,
    porta INTEGER, onu_id INTEGER, uni TEXT,
    mensagem TEXT NOT NULL,
    codigo TEXT NOT NULL,
    severidade TEXT NOT NULL,
    primeiro_visto TEXT NOT NULL,
    ultimo_visto TEXT NOT NULL,
    PRIMARY KEY (olt_id, chave)
);

-- Log de cada execução de coleta.
CREATE TABLE IF NOT EXISTS coletas (
    id INTEGER PRIMARY KEY,
    olt_id TEXT NOT NULL,
    tipo TEXT NOT NULL,
    origem TEXT NOT NULL,              -- 'agendada' | 'manual'
    inicio TEXT NOT NULL,
    fim TEXT,
    ok INTEGER,
    erro TEXT,
    detalhe TEXT
);
CREATE INDEX IF NOT EXISTS ix_coletas ON coletas (olt_id, tipo, inicio);
"""

MIGRACOES_OLTS = [
    ("fabricante", "TEXT NOT NULL DEFAULT 'cdata'"),
    ("porta_ssh", "INTEGER NOT NULL DEFAULT 22"),
    ("usuario", "TEXT NOT NULL DEFAULT ''"),
    ("senha_cifrada", "TEXT NOT NULL DEFAULT ''"),       # Fernet (coletor/cofre.py)
    ("senha_enable_cifrada", "TEXT NOT NULL DEFAULT ''"),
    ("frame_slot", "TEXT NOT NULL DEFAULT '0/0'"),
    ("criado_em", "TEXT"),
    ("atualizado_em", "TEXT"),
]

MIGRACOES = {
    "olts": MIGRACOES_OLTS,
    "olt_status": [("sensores", "TEXT"), ("plataforma", "TEXT")],  # JSON (Datacom)
    # sn_desde: quando o serial atual apareceu nesta posição (troca de ONU zera o histórico dela).
    "onus": [("modelo_onu", "TEXT"), ("versao_onu", "TEXT"), ("sn_desde", "TEXT")],
    "pon_sfp": [("admin", "TEXT"), ("link", "TEXT")],  # estado da porta PON (Datacom)
}

# Tudo aqui é editável em tempo real pela API (PUT /api/parametros).
PARAMETROS_PADRAO: dict[str, Any] = {
    "intervalo_alarmes_s": 300,
    "intervalo_sistema_s": 300,
    "intervalo_onus_s": 900,
    "intervalo_rx_olt_s": 900,
    "retencao_dias": 90,
    # Faixas de sinal (dBm). Acima de "saturado" = forte demais.
    "rx_onu_saturado": -8.0,
    "rx_onu_atencao": -21.0,
    "rx_onu_critico": -25.0,
    "rx_olt_saturado": -8.0,
    "rx_olt_atencao": -25.0,
    "rx_olt_critico": -28.0,
    # Queda de sinal em relação à média dos últimos 7 dias que conta como degradação.
    "degradacao_db": 3.0,
    "temp_onu_atencao": 70.0,
    # ONU com N+ alarmes na última hora é marcada como "oscilando".
    "oscilacao_eventos_1h": 6,
    # IPs/redes que podem usar o coletor (vazio = todos). Ver coletor/acl.py.
    "acl_ips": [],
}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def de_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Banco:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.conexao() as c:
            c.executescript(SCHEMA)
            for tabela, colunas in MIGRACOES.items():
                existentes = {r["name"] for r in c.execute(f"PRAGMA table_info({tabela})")}
                for coluna, tipo in colunas:
                    if coluna not in existentes:
                        c.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            for k, v in PARAMETROS_PADRAO.items():
                c.execute("INSERT OR IGNORE INTO parametros (chave, valor) VALUES (?, ?)", (k, json.dumps(v)))

    @contextmanager
    def conexao(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.caminho, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # ------------------------------------------------------------ parâmetros

    def parametros(self) -> dict[str, Any]:
        with self.conexao() as c:
            rows = c.execute("SELECT chave, valor FROM parametros").fetchall()
        out = dict(PARAMETROS_PADRAO)
        out.update({r["chave"]: json.loads(r["valor"]) for r in rows})
        return out

    def salvar_parametros(self, novos: dict[str, Any]) -> dict[str, Any]:
        with self.conexao() as c:
            for k, v in novos.items():
                if k not in PARAMETROS_PADRAO:
                    raise KeyError(k)
                c.execute(
                    "INSERT INTO parametros (chave, valor) VALUES (?, ?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (k, json.dumps(v)),
                )
        return self.parametros()

    # ------------------------------------------------------------ limpeza

    def limpar_antigos(self, dias: int) -> dict[str, int]:
        limite = iso(agora_utc() - timedelta(days=dias))
        apagados = {}
        with self.conexao() as c:
            for tabela, coluna in (
                ("sinais_onu", "coletado_em"),
                ("sinais_olt", "coletado_em"),
                ("pon_sfp", "coletado_em"),
                ("pon_resumo", "coletado_em"),
                ("olt_status", "coletado_em"),
                ("alarmes_eventos", "visto_em"),
                ("coletas", "inicio"),
            ):
                cur = c.execute(f"DELETE FROM {tabela} WHERE {coluna} < ?", (limite,))
                apagados[tabela] = cur.rowcount
            # ONU que sumiu da OLT há mais tempo que a retenção.
            cur = c.execute("DELETE FROM onus WHERE visto_em < ?", (limite,))
            apagados["onus"] = cur.rowcount
        return apagados
