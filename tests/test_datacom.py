from datetime import timedelta, timezone
from pathlib import Path

import pytest

from coletor.cdata.parsers import ErroCli
from coletor.datacom import parsers as d

FIX = Path(__file__).parent / "fixtures"


def ler(nome: str) -> str:
    return (FIX / nome).read_text(encoding="utf-8")


def test_onus_porta():
    onus = d.onus_porta(ler("datacom_onus_porta.txt"))
    assert len(onus) > 80
    o0 = onus[0]
    assert o0["porta"] == 1 and o0["onu_id"] == 0 and o0["run_state"] == "online"
    assert o0["last_down_cause"] == "Dying gasp" and o0["rx"] == -21.25 and o0["tx"] == 1.52
    assert o0["descricao"].startswith("CLIENTE-")
    assert {o["last_down_cause"] for o in onus} >= {"Dying gasp", "LOS", "OMCC problem"}
    off = next(o for o in onus if o["onu_id"] == 91)
    assert off["run_state"] == "offline" and off["rx"] is None and off["last_down_cause"] is None
    sem_nome = next(o for o in onus if o["onu_id"] == 14)
    assert sem_nome["descricao"] is None


def test_onu_detalhe():
    o = d.onu_detalhe(ler("datacom_onu_online.txt"))
    assert o["onu_id"] == 2 and o["run_state"] == "online" and o["distancia_m"] == 1000
    assert o["online_seg"] == (3 * 60 + 35) * 60
    assert o["last_down_cause"] == "Dying gasp"
    assert o["last_down_dt"].utcoffset() == timedelta(hours=-3)
    assert o["last_down_dt"].astimezone(timezone.utc).strftime("%H:%M:%S") == "14:16:41"
    assert o["modelo_onu"] == "FD511G-X-F670" and o["rx"] == -20.81
    assert "senha" not in o and "password" not in o
    off = d.onu_detalhe(ler("datacom_onu_offline.txt"))
    assert off["run_state"] == "offline" and off["last_down_dt"] is None and off["distancia_m"] is None


@pytest.mark.parametrize("texto,seg", [("03:35", 12900), ("1d 03:35", 99300), ("2 days, 01:00:05", 176405), ("N/A", None)])
def test_uptime_onu(texto, seg):
    assert d.duracao_uptime(texto) == seg


def test_rssi():
    assert d.rssi(ler("datacom_rssi.txt")) == -22.29
    assert d.rssi(ler("datacom_rssi_offline.txt")) is None


def test_erro_sintaxe():
    with pytest.raises(ErroCli):
        d.rssi(ler("datacom_erro_sintaxe.txt"))


def test_alarmes():
    al = d.alarmes(ler("datacom_alarmes.txt"))
    assert len(al) == 11
    a = al[0]
    assert a["porta"] == 1 and a["onu_id"] == 38 and a["nome"] == "GPON_DGi" and a["severidade_olt"] == "CRITICAL"
    assert a["data"].utcoffset() == timedelta(hours=-3)


def test_equipamento():
    c = d.cpu(ler("datacom_cpu.txt"))
    assert (c["uso_5s"], c["uso"], c["uso_5min"]) == (26.0, 32.0, 36.0) and c["uptime_s"] == 3501612
    m = d.memoria(ler("datacom_memoria.txt"))
    assert m["total_mb"] == 985.0 and m["livre_mb"] == 266.3 and m["uso"] == pytest.approx(73.0, abs=0.1)
    amb = d.ambiente(ler("datacom_ambiente.txt"))
    assert len(amb["sensores"]) == 6 and amb["sensores"][0]["nome"] == "Card" and amb["sensores"][0]["temp"] == 29.8
    assert amb["sensores"][0]["max"] == 55.0 and amb["sensores"][0]["status"] == "NORMAL"
    assert [v["rpm"] for v in amb["ventoinhas"]] == [6000, 6000, 6120]
    assert amb["fontes"] == [{"slot": "1/PSU1", "status": "OK"}]
    t = d.transceivers(ler("datacom_transceivers.txt"))
    assert sorted(t) == list(range(1, 9)) and t[1]["tx"] == 5.76 and t[1]["rx"] is None
    fw = d.firmware(ler("datacom_firmware.txt"))
    assert fw["boot"].startswith("12.6.0") and len(fw["bancos"]) == 2
    pl = d.plataforma(ler("datacom_plataforma.txt"))
    assert pl[0]["modelo"] == "DM4610 HW2" and pl[1]["status"] == "Ready"
    up = d.uptime(ler("datacom_uptime.txt"))
    assert up["uptime_s"] == ((40 * 24 + 12) * 60 + 31) * 60 and up["load1"] == 0.95
    assert d.contagem_global(ler("datacom_contagem.txt")) == {"total": 643, "nao_provisionadas": 0, "up": 615, "down": 28}
