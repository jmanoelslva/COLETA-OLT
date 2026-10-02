import pytest
from starlette.requests import Request

from coletor import acl


def pedido(host: str, real: str | None = None) -> Request:
    headers = [(b"x-real-ip", real.encode())] if real else []
    return Request({"type": "http", "client": (host, 50000), "headers": headers, "path": "/api/x"})


def test_ip_do_pedido():
    assert acl.ip_do_pedido(pedido("127.0.0.1", "177.85.130.17")) == "177.85.130.17"  # via Apache/Nginx
    assert acl.ip_do_pedido(pedido("127.0.0.1")) is None  # chamada local direta
    # Conexão que não vem do proxy local: header ignorado (não dá para forjar o IP).
    assert acl.ip_do_pedido(pedido("200.1.1.1", "10.0.0.1")) == "200.1.1.1"


def test_normalizar_ipv6():
    assert acl.normalizar(["2804:ABC::1", "2804:abc:1::/48", "::1"]) == ["2804:abc::1/128", "2804:abc:1::/48", "::1/128"]
    with pytest.raises(ValueError):
        acl.normalizar(["2804:abc::zz"])


def test_normalizar():
    assert acl.normalizar(["10.0.0.5", " 177.85.130.17/24 ", "", "# só comentário", "10.0.0.5",
                           "2804:abc::/32  # escritório"]) == \
        ["10.0.0.5/32", "177.85.130.0/24", "2804:abc::/32"]
    with pytest.raises(ValueError, match="300.1.1.1"):
        acl.normalizar(["300.1.1.1"])


@pytest.mark.parametrize("ip,redes,esperado", [
    ("177.85.130.17", [], True),                       # lista vazia = todos
    (None, ["10.0.0.0/8"], True),                       # local sempre passa
    ("177.85.130.17", ["177.85.130.0/24"], True),
    ("177.85.131.1", ["177.85.130.0/24"], False),
    ("::ffff:177.85.130.17", ["177.85.130.0/24"], True),
    ("lixo", ["10.0.0.0/8"], False),
    # IPv6
    ("2804:abc:1:2::10", ["2804:abc::/32"], True),
    ("2804:abd::1", ["2804:abc::/32"], False),
    ("2804:abc::1", ["2804:abc::1/128"], True),
    ("2804:abc::1", ["177.85.130.0/24"], False),        # cliente IPv6, lista só IPv4
    ("177.85.130.17", ["2804:abc::/32"], False),        # cliente IPv4, lista só IPv6
    ("2804:abc::1", ["177.85.130.0/24", "2804:abc::/48"], True),
])
def test_permitido(ip, redes, esperado):
    assert acl.permitido(ip, redes) is esperado
