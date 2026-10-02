"""Coletas da Datacom de ponta a ponta contra uma OLT falsa (fixtures) e um SQLite temporário."""

import re
from pathlib import Path

import pytest

from coletor import analise, db
from coletor.coletas import EstadoOlt
from coletor.config import OltConfig
from coletor.datacom import coletas as dc

FIX = Path(__file__).parent / "fixtures"

RESPOSTAS = [
    (r"show alarm", "datacom_alarmes.txt"),
    (r"show system cpu", "datacom_cpu.txt"),
    (r"show system memory", "datacom_memoria.txt"),
    (r"show environment", "datacom_ambiente.txt"),
    (r"show platform", "datacom_plataforma.txt"),
    (r"show interface transceivers", "datacom_transceivers.txt"),
    (r"show interface gpon", "datacom_portas_gpon.txt"),
    (r"show firmware", "datacom_firmware.txt"),
    (r"show system uptime", "datacom_uptime.txt"),
    (r"show interface gpon 1/1/1 onu", "datacom_onus_porta.txt"),
    (r"show interface gpon 1/1/1 onu 91", "datacom_onu_offline.txt"),
    (r"show interface gpon 1/1/1 onu \d+", "datacom_onu_online.txt"),
    (r"show interface gpon 1/1/1 onu \d+ rssi", "datacom_rssi.txt"),
]


class OltFalsa:
    hostname = "OLT-TESTE"

    def __init__(self):
        self.comandos = []

    def executar(self, comando, view=None, timeout=60):
        self.comandos.append(comando)
        for padrao, arq in RESPOSTAS:
            if re.fullmatch(padrao, comando):
                return (FIX / arq).read_text(encoding="utf-8")
        raise AssertionError(f"sem fixture: {comando}")


@pytest.fixture
def ambiente(tmp_path):
    banco = db.Banco(tmp_path / "t.sqlite3")
    olt = OltConfig(id="dc", nome="DC", host="x", usuario="u", senha="s", fabricante="datacom", portas_pon=(1,))
    with banco.conexao() as c:
        c.execute("INSERT INTO olts (id, nome, portas_pon, fabricante) VALUES ('dc', 'DC', '[1]', 'datacom')")
    return banco, olt, EstadoOlt()


def test_ciclo_completo(ambiente):
    banco, olt, estado = ambiente
    s = OltFalsa()
    r = dc.coletar_alarmes(s, olt, banco, estado)
    assert r["ativos"] == 11
    dc.coletar_sistema(s, olt, banco, estado)
    dc.coletar_onus(s, olt, banco, estado)
    with banco.conexao() as c:
        st = c.execute("SELECT * FROM olt_status").fetchone()
        assert st["temp_placa"] == 29.8 and st["cpu"] == 32.0 and st["uptime_s"] > 0
        sfp = c.execute("SELECT * FROM pon_sfp").fetchall()
        assert len(sfp) == 1  # só a porta cadastrada
        assert (sfp[0]["admin"], sfp[0]["link"], sfp[0]["produto"]) == ("enabled", "up", "opway-OP46C1-datacom-custom")
        assert c.execute("SELECT COUNT(*) FROM onus").fetchone()[0] > 80
        # quedas de ONU (DGi/LOSi) não viram evento pelo diff de alarmes
        assert c.execute("SELECT COUNT(*) FROM alarmes_eventos WHERE codigo IN ('dgi','losi')").fetchone()[0] == 0

    # rodízio: ONU 2 tem queda registrada e está de volta
    out = dc.coletar_onu(s, olt, banco, estado, porta=1, onu_id=2)
    assert out["rx_olt"] == -22.29 and out["eventos_novos"] == 2
    with banco.conexao() as c:
        ev = [dict(r) for r in c.execute("SELECT * FROM alarmes_eventos WHERE onu_id = 2 ORDER BY data_utc")]
        assert [e["acao"] for e in ev] == ["alarme", "normalizou"]
        assert ev[0]["codigo"] == "dgi" and ev[0]["data_utc"] == "2026-10-02T14:16:41Z"
        onu = c.execute("SELECT * FROM onus WHERE porta = 1 AND onu_id = 2").fetchone()
        assert onu["distancia_m"] == 1000 and onu["modelo_onu"] == "FD511G-X-F670"
        assert c.execute("SELECT rx_olt FROM sinais_olt").fetchone()[0] == -22.29
    # segunda visita não duplica
    assert dc.coletar_onu(s, olt, banco, estado, porta=1, onu_id=2)["eventos_novos"] == 0

    # ONU offline: sem RSSI (nem pede), sem evento
    out = dc.coletar_onu(s, olt, banco, estado, porta=1, onu_id=91)
    assert out["rx_olt"] is None and "show interface gpon 1/1/1 onu 91 rssi" not in s.comandos


def test_alarme_que_some_vira_normalizou(ambiente):
    banco, olt, estado = ambiente
    s = OltFalsa()
    dc.coletar_alarmes(s, olt, banco, estado)
    with banco.conexao() as c:  # finge um alarme não-queda ativo na leitura anterior
        c.execute("""INSERT INTO alarmes_ativos (olt_id, chave, data_olt, data_utc, porta, onu_id, mensagem, codigo,
                     severidade, primeiro_visto, ultimo_visto)
                     VALUES ('dc', 'k1', '2026-10-02 10:00:00 UTC-3', '2026-10-02T13:00:00Z', 1, 5,
                             'GPON_LOAMi ONU loss of OAM', 'loami', 'menor', 'x', 'x')""")
    r = dc.coletar_alarmes(s, olt, banco, estado)
    assert r["normalizados"] == 1


def test_rodizio_prioriza_sem_detalhe(ambiente):
    banco, olt, estado = ambiente
    s = OltFalsa()
    dc.coletar_onus(s, olt, banco, estado)
    dc.coletar_onu(s, olt, banco, estado, porta=1, onu_id=2)
    itens = dc.itens_rodizio(olt, banco, estado)
    assert itens[-1] == {"porta": 1, "onu_id": 2}  # a que acabou de ser lida vai para o fim


def test_mudanca_de_estado_vira_urgente(ambiente):
    banco, olt, estado = ambiente
    s = OltFalsa()
    dc.coletar_onus(s, olt, banco, estado)
    with banco.conexao() as c:
        c.execute("UPDATE onus SET run_state = 'offline' WHERE porta = 1 AND onu_id = 0")
    r = dc.coletar_onus(s, olt, banco, estado)
    assert r["mudaram_de_estado"] == 1 and estado.extras["urgentes"] == [{"porta": 1, "onu_id": 0}]


def test_avaliar_causa_omcc():
    par = {"rx_onu_saturado": -8.0, "rx_onu_atencao": -21.0, "rx_onu_critico": -25.0, "rx_olt_saturado": -8.0,
           "rx_olt_atencao": -25.0, "rx_olt_critico": -28.0, "degradacao_db": 3.0, "temp_onu_atencao": 70.0,
           "oscilacao_eventos_1h": 6}
    r = analise.avaliar_onu({"run_state": "offline", "last_down_cause": "OMCC problem"}, par)
    assert "OMCC" in r["alertas"][0]
    r = analise.avaliar_onu({"run_state": "offline", "last_down_cause": "Dying gasp"}, par)
    assert "energia" in r["alertas"][0]
