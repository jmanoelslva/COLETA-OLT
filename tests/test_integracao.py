"""Consulta da ONU pelo serial para o app técnico (/api/integracao/onu)."""

import dataclasses
import importlib
import os

import pytest

from coletor import coletas, db, integracao
from coletor.config import OltConfig
from tests.test_cdata_coletas import OltFalsa

SN = "TEST000000EC"


def _evento(c, i, quando, codigo, acao, msg, onu_id=1, porta=1):
    c.execute(
        "INSERT INTO alarmes_eventos (olt_id, chave, data_olt, data_utc, porta, onu_id, mensagem, codigo, acao, "
        "severidade, visto_em) VALUES ('cd', ?, ?, ?, ?, ?, ?, ?, ?, 'maior', ?)",
        (f"k{i}", quando, quando, porta, onu_id, msg, codigo, acao, quando))


@pytest.fixture
def banco(tmp_path):
    b = db.Banco(tmp_path / "t.sqlite3")
    olt = OltConfig(id="cd", nome="OLT-CD", host="x", usuario="u", senha="s", portas_pon=(1,))
    with b.conexao() as c:
        c.execute("INSERT INTO olts (id, nome, portas_pon) VALUES ('cd', 'OLT-CD', '[1]')")
    coletas.coletar_onus(OltFalsa(), olt, b, coletas.EstadoOlt())
    return b


def test_localizar(banco):
    with banco.conexao() as c:
        o = integracao.localizar(c, sn=" test000000ec ")
        assert (o["olt_id"], o["porta"], o["onu_id"], o["olt_nome"]) == ("cd", 1, 1, "OLT-CD")
        assert integracao.localizar(c, olt="olt-cd", porta=1, onu_id=1)["sn"] == SN
        with pytest.raises(integracao.NaoEncontrada):
            integracao.localizar(c, sn="XXXX00000000")
        with pytest.raises(ValueError):
            integracao.localizar(c, olt="cd")


def test_quedas_com_volta_e_duracao(banco):
    with banco.conexao() as c:
        # queda por energia (trio no mesmo segundo) e volta 10 min depois; depois uma LOS sem volta
        _evento(c, 1, "2026-10-01T10:00:00Z", "dgi", "alarme", "Dying gasp(DGi)")
        _evento(c, 2, "2026-10-01T10:00:00Z", "losi", "alarme", "Loss of signal for ONU(LOSi)")
        _evento(c, 3, "2026-10-01T10:10:00Z", "dgi", "normalizou", "Dying gasp(DGi) clear")
        _evento(c, 4, "2026-10-01T12:00:00Z", "losi", "alarme", "Loss of signal for ONU(LOSi)")
        _evento(c, 5, "2026-10-01T12:00:00Z", "losi", "alarme", "Loss of signal for ONU(LOSi)", onu_id=2)
        q = integracao.quedas(integracao.eventos_da_onu(c, "cd", 1, 1, "2026-01-01T00:00:00Z"))
    assert len(q) == 2
    assert q[0]["caiu_em"] == "2026-10-01T12:00:00Z" and q[0]["voltou_em"] is None
    assert q[1]["motivo"] == "ONU caiu: falta de energia (dying gasp)"
    assert q[1]["voltou_em"] == "2026-10-01T10:10:00Z" and q[1]["duracao_s"] == 600


def test_troca_de_onu_reinicia_historico(banco):
    olt = OltConfig(id="cd", nome="OLT-CD", host="x", usuario="u", senha="s", portas_pon=(1,))
    with banco.conexao() as c:
        antes = c.execute("SELECT sn_desde FROM onus WHERE porta = 1 AND onu_id = 1").fetchone()[0]
        c.execute("UPDATE onus SET sn = 'OUTRA0000000', sn_desde = '2026-01-01T00:00:00Z' WHERE onu_id = 1")
    coletas.coletar_onus(OltFalsa(), olt, banco, coletas.EstadoOlt())  # volta a ONU da fixture
    with banco.conexao() as c:
        depois = c.execute("SELECT sn_desde FROM onus WHERE porta = 1 AND onu_id = 1").fetchone()[0]
        mesma = c.execute("SELECT sn_desde FROM onus WHERE porta = 1 AND onu_id = 2").fetchone()[0]
    assert antes and depois >= antes
    assert mesma == antes  # serial igual: mantém


@pytest.fixture
def cliente(tmp_path, monkeypatch, banco):
    from fastapi.testclient import TestClient

    monkeypatch.setitem(os.environ, "COLETOR_DADOS", str(tmp_path / "api"))
    api = importlib.import_module("coletor.api")
    monkeypatch.setattr(api, "banco", banco)
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, servico_token="segredo",
                                                             auth_modo="tecnico", api_token=""))
    return TestClient(api.app)  # sem "with": não sobe o agendador


def test_api_exige_token(cliente):
    assert cliente.get("/api/integracao/onu", params={"sn": SN}).status_code == 401
    assert cliente.get("/api/integracao/onu", params={"sn": SN},
                       headers={"X-Servico-Token": "errado"}).status_code == 401


def test_api_historico(cliente):
    h = {"X-Servico-Token": "segredo"}
    r = cliente.get("/api/integracao/onu", params={"sn": SN.lower()}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["olt"] == {"id": "cd", "nome": "OLT-CD", "fabricante": "cdata"}
    assert d["onu"]["sn"] == SN and d["onu"]["descricao"].startswith("CLIENTE-")
    assert d["sinais"]["onu"] and d["sinais"]["olt"] and d["pon"]["total"] == 34
    assert set(d) >= {"quedas", "eventos", "alarmes_ativos", "limites", "atualizado_em", "historico_desde"}
    assert cliente.get("/api/integracao/onu", params={"sn": "XXXX00000000"}, headers=h).status_code == 404
    assert cliente.get("/api/integracao/onu", params={"olt": "OLT-CD", "porta": 1, "onu_id": 1},
                       headers=h).json()["onu"]["sn"] == SN
