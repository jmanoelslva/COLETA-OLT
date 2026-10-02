"""Validação da sessão do PWA técnico contra um /auth/me falso."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from coletor import sessao_tecnico as st

CHAMADAS = []


class TecnicoFalso(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        CHAMADAS.append(self.headers.get("Cookie"))
        if self.path != "/auth/me":
            self.send_response(404); self.end_headers(); return
        if self.headers.get("Cookie") == "TECSESSION=valida":
            corpo = json.dumps({"username": "joao.campo", "user_pk": 7}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(corpo)
        elif self.headers.get("Cookie") == "TECSESSION=quebra":
            self.send_response(500); self.end_headers()
        else:
            self.send_response(401); self.end_headers()

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def url():
    srv = HTTPServer(("127.0.0.1", 0), TecnicoFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def limpa():
    st._cache.clear()
    CHAMADAS.clear()


def test_sessao_valida_e_cache(url):
    assert st.validar("valida", url, "TECSESSION") == st.Tecnico("joao.campo")
    assert st.validar("valida", url, "TECSESSION") == st.Tecnico("joao.campo")
    assert len(CHAMADAS) == 1  # a segunda veio do cache


def test_sessao_invalida_ou_ausente(url):
    assert st.validar("vencida", url, "TECSESSION") is None
    assert st.validar(None, url, "TECSESSION") is None
    assert st.validar("", url, "TECSESSION") is None


def test_backend_fora_do_ar_nao_e_sessao_invalida(url):
    with pytest.raises(st.TecnicoIndisponivel):
        st.validar("quebra", url, "TECSESSION")
    with pytest.raises(st.TecnicoIndisponivel):
        st.validar("valida", "http://127.0.0.1:9", "TECSESSION")  # porta fechada
