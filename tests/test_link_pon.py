"""Link da PON inferido na C-DATA (RX do SFP sem luz ou nenhuma ONU online)."""

import pytest

from coletor import analise, db
from coletor.coletas import inferir_link


@pytest.fixture
def banco(tmp_path):
    b = db.Banco(tmp_path / "t.sqlite3")
    with b.conexao() as c:
        linhas = [(1, 1, "online"), (1, 2, "offline"),   # porta 1: uma online
                  (2, 1, "offline"), (2, 2, "offline")]  # porta 2: todas offline
        for porta, onu, est in linhas:
            c.execute("INSERT INTO onus (olt_id, porta, onu_id, run_state, primeiro_visto, visto_em) "
                      "VALUES ('o', ?, ?, ?, 'x', 'x')", (porta, onu, est))
    return b


@pytest.mark.parametrize("porta,rx,esperado", [
    (1, -22.75, "up"),
    (1, -40.0, "down"),   # SFP sem luz, mesmo com ONU marcada online (lista ainda não atualizou)
    (2, -22.75, "down"),  # nenhuma ONU online
    (3, -40.0, None),     # porta sem ONUs cadastradas: não acusa
    (1, None, "up"),
])
def test_inferir_link(banco, porta, rx, esperado):
    with banco.conexao() as c:
        assert inferir_link(c, "o", porta, {"rx": rx}) == esperado


PAR = {"degradacao_db": 3.0}


def test_diagnostico_sem_link_e_sem_duplicar_los():
    portas = [{"porta": 2, "admin": None, "link": "down"}, {"porta": 3, "admin": "disabled", "link": "down"}]
    inc = analise.diagnosticar_olt([], [], [], None, PAR, portas)
    assert [i["categoria"] for i in inc] == ["pon_sem_link"] and inc[0]["porta"] == 2
    # Com LOS da PON ativo, fica só o incidente do alarme.
    ativos = [{"codigo": "los_pon", "porta": 2}]
    inc = analise.diagnosticar_olt([], ativos, [], None, PAR, portas)
    assert [i["categoria"] for i in inc] == ["pon_sem_sinal"]


@pytest.mark.parametrize("causa,motivo", [
    ("dying-gasp", "energia"), ("Dying gasp", "energia"), ("LOS", "sinal"),
    ("LOSi", "sinal"), ("OMCC problem", "gerencia"), (None, "sem_registro"), ("N/A", "sem_registro"), ("--", "sem_registro"),
    ("Ranging failed", "ranging"), ("Deactivated", "outro"),
])
def test_motivo_offline(causa, motivo):
    assert analise.motivo_offline(causa) == motivo
