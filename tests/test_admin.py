"""Acesso de admin: só ele cadastra/edita/exclui OLTs e muda as Configurações."""

import dataclasses
import importlib
import os

import pytest

from coletor import admin, db


def test_hash_e_conferencia(tmp_path):
    h = admin.gerar_hash("senha-boa-123")
    assert h.startswith("scrypt$") and "senha-boa-123" not in h
    assert admin.conferir_hash("senha-boa-123", h) and not admin.conferir_hash("outra", h)
    b = db.Banco(tmp_path / "t.sqlite3")
    assert not admin.configurado(b) and not admin.conferir(b, "admin", "x")
    with pytest.raises(ValueError):
        admin.definir(b, "admin", "curta")
    admin.definir(b, "admin", "senha-boa-123")
    assert admin.conferir(b, "admin", "senha-boa-123")
    assert not admin.conferir(b, "outro", "senha-boa-123")


def test_sessao_cai_quando_admin_muda(tmp_path):
    b = db.Banco(tmp_path / "t.sqlite3")
    admin.definir(b, "admin", "senha-boa-123")
    s = admin.Sessoes()
    tok = s.criar("admin", admin.marca(b))
    assert s.validar(tok, admin.marca(b)) == "admin"
    admin.definir(b, "admin", "senha-nova-456")  # ex.: trocada pela linha de comando
    assert s.validar(tok, admin.marca(b)) is None


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setitem(os.environ, "COLETOR_DADOS", str(tmp_path / "api"))
    m = importlib.import_module("coletor.api")
    b = db.Banco(tmp_path / "t.sqlite3")
    monkeypatch.setattr(m, "banco", b)
    monkeypatch.setattr(m, "sessoes_admin", admin.Sessoes())
    monkeypatch.setattr(m, "settings", dataclasses.replace(m.settings, auth_modo="", api_token=""))
    return m, b


def test_rotas_de_admin_bloqueadas_sem_login(api):
    from fastapi.testclient import TestClient

    m, b = api
    c = TestClient(m.app)
    assert c.get("/api/admin").json() == {"configurado": False, "logado": False, "usuario": None}
    for metodo, rota in [("post", "/api/olts"), ("put", "/api/olts/x"), ("delete", "/api/olts/x"),
                         ("post", "/api/olts/testar"), ("get", "/api/olts/x/cadastro"), ("put", "/api/parametros")]:
        r = getattr(c, metodo)(rota, **({"json": {}} if metodo in ("post", "put") else {}))
        assert r.status_code == 403, rota
    # leitura continua liberada
    assert c.get("/api/olts").status_code == 200 and c.get("/api/parametros").status_code == 200
    assert c.post("/api/admin/entrar", json={"usuario": "admin", "senha": "x"}).status_code == 409


def test_login_troca_de_senha_e_bloqueio(api):
    from fastapi.testclient import TestClient

    m, b = api
    admin.definir(b, "admin", "senha-boa-123")
    c = TestClient(m.app)
    assert c.post("/api/admin/entrar", json={"usuario": "admin", "senha": "errada"}).status_code == 401
    r = c.post("/api/admin/entrar", json={"usuario": "admin", "senha": "senha-boa-123"})
    assert r.status_code == 200 and r.json()["logado"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert c.get("/api/admin").json()["logado"]
    assert c.put("/api/parametros", json={"retencao_dias": 30}).status_code == 200
    assert c.get("/api/olts/nao-existe/cadastro").status_code == 404

    r = c.put("/api/admin/senha", json={"senha_atual": "errada", "nova_senha": "nova-senha-789"})
    assert r.status_code == 422
    r = c.put("/api/admin/senha", json={"senha_atual": "senha-boa-123", "nova_senha": "nova-senha-789"})
    assert r.status_code == 200 and c.get("/api/admin").json()["logado"]
    assert admin.conferir(b, "admin", "nova-senha-789")

    c.post("/api/admin/sair")
    assert not c.get("/api/admin").json()["logado"]
    assert c.put("/api/parametros", json={"retencao_dias": 30}).status_code == 403

    for _ in range(admin.TENTATIVAS_MAX):
        c.post("/api/admin/entrar", json={"usuario": "admin", "senha": "chute"})
    r = c.post("/api/admin/entrar", json={"usuario": "admin", "senha": "nova-senha-789"})
    assert r.status_code == 429
