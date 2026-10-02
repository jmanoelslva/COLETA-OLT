"""Firmware C-DATA V3.x (V3.3.76): mesmos parsers da V1, formatos novos."""

from pathlib import Path

from coletor import alarmes as cat
from coletor.cdata import parsers as p

FIX = Path(__file__).parent / "fixtures"


def ler(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8")


def test_ont_info_todas_com_descricao():
    onus, totais = p.ont_info_todas(ler("v3_ont_info_todas.txt"))
    assert totais == {"total": 34, "online": 33, "deactive": 0, "failed": 0, "success": 33}
    assert len(onus) == 34
    o1 = onus[0]
    assert o1["porta"] == 1 and o1["onu_id"] == 1 and o1["sn"].startswith("TEST")
    assert o1["run_state"] == "online" and o1["last_down_cause"] == "dying-gasp"
    assert o1["descricao"].startswith("CLIENTE-")


def test_ont_info_uma():
    d = p.ont_info_uma(ler("v3_ont_info_online.txt"))
    assert d["onu_id"] == 1 and d["porta"] == 1
    assert d["sn"] == "TEST000000EC"  # sem o "(XXXX-XXXXXXXX)"
    assert d["descricao"].startswith("CLIENTE-")
    assert d["online_seg"] == 12 * 86400 + 2 * 60 + 25
    assert d["line_profile"] == "LINE-PPPOE" and d["service_profile"] == "SRV-PPPOE"


def test_optical_todas_traz_rx_olt():
    sinais = p.optical_todas(ler("v3_optical_todas.txt"), porta=1)
    assert len(sinais) == 33
    s1 = sinais[0]
    assert s1["porta"] == 1 and s1["onu_id"] == 1
    # ordem das colunas V3: RX, TX, RX na OLT, temperatura, tensão, corrente
    assert s1["rx"] < -10 and 0 < s1["tx"] < 5 and s1["rx_olt"] < -20
    assert 20 < s1["temp"] < 60 and 3 < s1["tensao"] < 3.6 and 5 < s1["bias"] < 30


def test_optical_uma():
    s = p.optical_uma(ler("v3_optical_uma.txt"))
    assert s["onu_id"] == 1 and s["rx"] is not None and s["rx_olt"] is not None


def test_ddm_porta():
    sfp = p.ddm_porta(ler("v3_ddm_porta.txt"))["sfp"]
    assert sfp["temp"] is not None and sfp["tx"] > 0 and sfp["rx"] < 0
    assert sfp["tensao"] and sfp["bias"] and sfp["vendor"] == "OEM" and sfp["serial"]


def test_alarmes_ativos():
    al = p.alarmes(ler("v3_alarmes_ativos.txt"))
    assert al[0] == {"data_olt": "2026-10-02 19:21:04", "porta": 2, "onu_id": 18, "uni": None,
                     "mensagem": "Loss of signal for ONU(LOSi)"}
    uni = next(a for a in al if a["uni"])
    assert uni["uni"] == "0/1" and uni["mensagem"] == "The Ethernet port link status is down"
    assert all(a["porta"] for a in al if "tranceiver" not in a["mensagem"])
    for a in al:
        assert cat.classificar(a["mensagem"]).codigo != "outro", a["mensagem"]


def test_alarmes_historico_clear():
    al = p.alarmes(ler("v3_alarmes_historico.txt"))
    assert al[0]["mensagem"] == "Dying gasp(DGi)" and al[0]["onu_id"] == 8
    clear = al[1]
    assert clear["mensagem"] == "Dying gasp(DGi) clear" and clear["onu_id"] == 8
    assert clear["data_olt"] == "2026-10-02 19:50:55"
    assert cat.classificar(clear["mensagem"]).acao == "normalizou"
    assert not any("(clear)" in a["mensagem"] for a in al)


def test_sistema():
    assert p.cpu(ler("v3_cpu.txt"))["uso"] is not None
    assert p.temperatura(ler("v3_temperatura.txt")) is not None
    assert p.fontes(ler("v3_power.txt")) == [{"slot": 1, "status": "working"}, {"slot": 2, "status": "ausente"}]
    u = p.uptime(ler("v3_uptime.txt"))
    assert u["uptime_s"] > 15 * 7 * 86400 and u["boot_local"] is not None


def test_catalogo_v3():
    for msg, codigo in [
        ("The ONT temperature exceeds the alarm threshold", "temp_onu"),
        ("The ONT voltage exceeds the alarm threshold", "tensao_onu"),
        ("The ONT bias current exceeds the alarm threshold", "bias_onu"),
        ("This tranceiver is not adapted,The default type will be used", "sfp_incompativel"),
        ("The TX output power of the optical port is higher than the warning upper threshold", "tx_pon"),
    ]:
        assert cat.classificar(msg).codigo == codigo
