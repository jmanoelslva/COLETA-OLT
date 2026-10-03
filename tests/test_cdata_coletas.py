"""Coleta de ONUs da C-DATA contra uma OLT falsa: porta sem ONU não derruba o ciclo."""

from pathlib import Path

import pytest

from coletor import coletas, db
from coletor.cdata import parsers as p
from coletor.config import OltConfig

FIX = Path(__file__).parent / "fixtures"
SEM_ONT = "show ont info 2 all\nError: There is no ONT avaliable.\nOLT-TESTE(config-interface-gpon-0/0)# "


class OltFalsa:
    def __init__(self):
        self.comandos = []

    def executar(self, comando, view=None, timeout=60):
        self.comandos.append(comando)
        if comando == "show ont info 1 all":
            return (FIX / "v3_ont_info_todas.txt").read_text(encoding="utf-8")
        if comando == "show ont optical-info 1 all":
            return (FIX / "v3_optical_todas.txt").read_text(encoding="utf-8")
        if comando.startswith("show ont info 1 "):
            return (FIX / "v3_ont_info_online.txt").read_text(encoding="utf-8")
        p.checar_erro(SEM_ONT)  # porta 2 vazia: a OLT responde erro


@pytest.fixture
def ambiente(tmp_path):
    banco = db.Banco(tmp_path / "t.sqlite3")
    olt = OltConfig(id="cd", nome="CD", host="x", usuario="u", senha="s", portas_pon=(1, 2))
    with banco.conexao() as c:
        c.execute("INSERT INTO olts (id, nome, portas_pon) VALUES ('cd', 'CD', '[1, 2]')")
    return banco, olt, coletas.EstadoOlt()


def test_porta_sem_ont(ambiente):
    banco, olt, estado = ambiente
    s = OltFalsa()
    assert coletas.coletar_onus(s, olt, banco, estado) == {"onus": 34}
    assert "show ont optical-info 2 all" not in s.comandos
    with banco.conexao() as c:
        r = c.execute("SELECT total, online FROM pon_resumo WHERE olt_id = 'cd' AND porta = 2").fetchone()
    assert (r["total"], r["online"]) == (0, 0)


def test_rx_olt_desligado_na_cdata(tmp_path):
    from coletor import agendador as ag
    from coletor.config import Settings
    from coletor.drivers import DRIVERS

    assert not DRIVERS["cdata"].coleta_rx_olt and DRIVERS["datacom"].coleta_rx_olt
    b = db.Banco(tmp_path / "t.sqlite3")
    olt = OltConfig(id="cd", nome="CD", host="x", usuario="u", senha="s", portas_pon=(1,))
    s = Settings(dados=tmp_path, arquivo_olts=tmp_path / "x.toml", api_token="", cors_origens=())
    c = ag.ColetorOlt(olt, b, s, coletas.EstadoOlt())
    assert "rx_olt" not in c._vencimentos()
    a = ag.Agendador([], b, s)
    a.coletores["cd"] = c
    with pytest.raises(ValueError):
        a.forcar("cd", "rx_olt")
