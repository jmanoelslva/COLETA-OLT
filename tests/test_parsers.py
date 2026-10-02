from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from coletor import alarmes as cat
from coletor import analise
from coletor.cdata import parsers as p

FIX = Path(__file__).parent / "fixtures"


def ler(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8")


def test_ont_info_todas():
    onus, totais = p.ont_info_todas(ler("ont_info_todas.txt"))
    assert totais == {"total": 59, "online": 57, "deactive": 0, "failed": 0}
    assert len(onus) == 59
    ids = [o["onu_id"] for o in onus]
    assert 23 not in ids and 65 in ids  # IDs pulam números
    o4 = next(o for o in onus if o["onu_id"] == 4)
    assert o4["run_state"] == "offline" and o4["last_down_cause"] == "LOS"
    o60 = next(o for o in onus if o["onu_id"] == 60)
    assert o60["last_down_cause"] is None  # "--"


def test_ont_info_uma():
    d = p.ont_info_uma(ler("ont_info_online.txt"))
    assert d["porta"] == 1 and d["onu_id"] == 1
    assert d["descricao"].startswith("CLIENTE-")
    assert d["distancia_m"] == 298
    assert d["online_seg"] == ((12 * 24 + 17) * 60 + 26) * 60 + 41
    assert d["last_up"] == "2026-09-19 19:53:53"
    off = p.ont_info_uma(ler("ont_info_offline.txt"))
    assert off["run_state"] == "offline" and off["distancia_m"] is None and off["online_seg"] is None


def test_optical_todas_offline_sem_valores():
    sinais = {s["onu_id"]: s for s in p.optical_todas(ler("optical_todas.txt"))}
    assert len(sinais) == 59
    assert sinais[4]["rx"] is None and sinais[4]["temp"] is None
    assert sinais[63]["rx"] == -26.77
    assert sinais[1] == {"porta": 1, "onu_id": 1, "tensao": 3.22, "tx": 2.20, "rx": -18.23, "bias": 19.80,
                         "temp": 62.49}


def test_optical_uma_e_offline():
    assert p.optical_uma(ler("optical_uma.txt"))["rx"] == -18.23
    with pytest.raises(p.ErroCli):
        p.optical_uma(ler("optical_offline.txt"))


def test_ddm_com_onus():
    r = p.ddm_porta(ler("ddm_com_onus.txt"))
    assert r["sfp"]["tx"] == 5.67 and r["sfp"]["vendor"] == "ANSAOEN"
    assert r["rx_olt"][2] == -28.23 and r["rx_olt"][63] == -30.45
    assert 4 not in r["rx_olt"] and len(r["rx_olt"]) == 57


def test_ddm_porta_sem_onus():
    r = p.ddm_porta(ler("ddm_porta.txt"))
    assert r["sfp"]["temp"] == 66.5 and r["rx_olt"] == {}


def test_alarmes():
    ativos = p.alarmes(ler("alarmes_ativos.txt"))
    assert len(ativos) == 157
    pon = [a for a in ativos if a["onu_id"] is None]
    assert pon[0]["mensagem"] == "Do not support this tranceiver" and pon[0]["porta"] == 8
    uni = next(a for a in ativos if a["uni"])
    assert uni["uni"] == "0/1" and "link status is down" in uni["mensagem"]
    hist = p.alarmes(ler("alarmes_historico.txt"))
    assert len(hist) == 2000


@pytest.mark.parametrize("msg,codigo,acao", [
    ("Dying gasp(DGi)", "dgi", "alarme"),
    ("Dying gasp(DGi) clear", "dgi", "normalizou"),
    ("Loss of signal for ONU(LOSi) clear", "losi", "normalizou"),
    ("Loss of signal(LOS)", "los_pon", "alarme"),
    ("The ONT Tx power exceeds the high alarm threshold", "tx_onu", "alarme"),
    ("The ONT Tx power becomes normal", "tx_onu", "normalizou"),
    ("UNI 0/1 The Ethernet port link status is up", "uni_link", "normalizou"),
    ("The Ethernet port link status is down", "uni_link", "alarme"),
    ("Do not support this tranceiver", "sfp_incompativel", "alarme"),
    ("ONU does not react correctly after deactive or disable(DFi)", "dfi", "alarme"),
    ("Mensagem nova qualquer", "outro", "alarme"),
])
def test_classificar(msg, codigo, acao):
    c = cat.classificar(msg)
    assert (c.codigo, c.acao) == (codigo, acao)


def test_todos_alarmes_reais_tem_classificacao():
    for nome in ("alarmes_ativos.txt", "alarmes_historico.txt"):
        for a in p.alarmes(ler(nome)):
            assert cat.classificar(a["mensagem"]).codigo != "outro", a["mensagem"]


def test_data_estimada_sem_relogio():
    fuso = timezone(timedelta(hours=-3))
    boot = datetime(2026, 8, 20, 12, 57, 27, tzinfo=fuso).astimezone(timezone.utc)
    agora = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)
    real, est = cat.converter_data("2000-02-11 21:21:15", fuso, boot, agora)
    assert est
    assert real.astimezone(fuso).strftime("%Y-%m-%d %H:%M") == "2026-10-01 13:18"
    ok, est2 = cat.converter_data("2026-10-02 13:27:53", fuso, boot, agora)
    assert not est2 and ok == datetime(2026, 10, 2, 16, 27, 53, tzinfo=timezone.utc)
    assert cat.converter_data("2000-02-11 21:21:15", fuso, None, agora) == (None, False)


def test_sistema():
    assert p.cpu(ler("cpu.txt")) == {"uso": 10.0, "load1": 7.76, "load5": 8.34, "load15": 8.66}
    assert p.memoria(ler("memoria.txt")) == {"total_mb": 1011.0, "livre_mb": 556.0, "uso": 46.0}
    assert p.temperatura(ler("temperatura.txt")) == 58.0
    assert [f["rpm"] for f in p.ventoinhas(ler("fan.txt"))] == [7200, 7440, 7080]
    assert p.fontes(ler("power.txt")) == [{"slot": 1, "status": "working"}, {"slot": 2, "status": "notworking"}]
    fw = p.firmware(ler("firmware.txt"))
    assert fw["boot"] == "firmware2" and fw["bancos"]["firmware1"]["version"] == "1.1.0"
    assert p.versao(ler("versao.txt"))["hardware"] == "V1.0"
    up = p.uptime(ler("uptime.txt"))
    assert up["uptime_s"] == ((43 * 24 + 1) * 60 + 1) * 60 + 43
    assert up["boot_local"] == datetime(2026, 8, 20, 12, 57, 27)
    rel = p.relogio(ler("time.txt"))
    assert rel.utcoffset() == timedelta(hours=-3)


def test_unknown_command_vira_erro():
    with pytest.raises(p.ErroCli):
        p.memoria("show memory\nUnknown command: (vtysh)show memory\n\nOLT(config-interface-gpon-0/0)# ")


PAR = {
    "rx_onu_saturado": -8.0, "rx_onu_atencao": -21.0, "rx_onu_critico": -25.0,
    "rx_olt_saturado": -8.0, "rx_olt_atencao": -25.0, "rx_olt_critico": -28.0,
    "degradacao_db": 3.0, "temp_onu_atencao": 70.0, "oscilacao_eventos_1h": 6,
}


def test_avaliar_onu_so_rx_olt_ruim():
    # ONT 2 da captura: RX ONU bom, RX OLT péssimo.
    r = analise.avaliar_onu({"run_state": "online", "rx": -19.79, "rx_olt": -28.23}, PAR)
    assert r["classe_rx"] == "bom" and r["classe_rx_olt"] == "critico"
    assert any("RX OLT" in a for a in r["alertas"])


def test_avaliar_onu_perda_por_sentido():
    # ONT 2 real (C-DATA): SFP +5.67, ONU TX 1.55 → RX OLT perde 4.3 dB a mais.
    r = analise.avaliar_onu({"run_state": "online", "rx": -19.79, "rx_olt": -28.23, "tx": 1.55, "sfp_tx": 5.67}, PAR)
    assert "RX OLT perde 4.3 dB" in r["alertas"][0]
    # Datacom 1/0 real: perdas parecidas (27.0 × 26.1) → sem alerta de lado.
    r = analise.avaliar_onu({"run_state": "online", "rx": -21.25, "rx_olt": -24.56, "tx": 1.52, "sfp_tx": 5.76}, PAR)
    assert not any("curvatura" in a or "laser" in a for a in r["alertas"])


def test_avaliar_onu_offline_por_energia():
    r = analise.avaliar_onu({"run_state": "offline", "last_down_cause": "dying-gasp"}, PAR)
    assert r["gravidade"] == 0 and "energia" in r["alertas"][0]


def test_avaliar_onu_degradada_e_atenuacao():
    r = analise.avaliar_onu({"run_state": "online", "rx": -22.0, "rx_media_7d": -18.0, "sfp_tx": 5.67}, PAR)
    assert r["degradada"] and r["delta_7d"] == -4.0 and r["atenuacao_db"] == 27.67


def test_agrupar_trio_de_queda():
    base = {"porta": 8, "onu_id": 66, "acao": "alarme", "data_olt": "2026-10-02 13:09:21",
            "data_utc": "2026-10-02T16:09:21Z", "severidade": "maior"}
    evs = [{**base, "id": i, "codigo": c} for i, c in enumerate(("lofi", "losi", "dgi"))]
    g = analise.agrupar_eventos(evs)
    assert len(g) == 1 and "energia" in g[0]["rotulo"] and len(g[0]["ids"]) == 3


def test_diagnostico_queda_em_massa_por_energia():
    onus = [{"porta": 3, "onu_id": i, "sn": f"S{i}", "online": False, "classe_rx": "sem_leitura",
             "classe_rx_olt": "sem_leitura", "degradada": False, "oscilando": False, "alertas": []}
            for i in range(1, 6)]
    quedas = [{"porta": 3, "onu_id": i, "codigo": "dgi"} for i in range(1, 5)]
    inc = analise.diagnosticar_olt(onus, [], quedas, None, PAR)
    assert inc[0]["categoria"] == "queda_energia"
