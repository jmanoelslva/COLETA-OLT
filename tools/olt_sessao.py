"""Sessão SSH interativa e persistente com a OLT, controlada por HTTP local.

Uso só de desenvolvimento: mantém um shell aberto na OLT de testes e expõe
POST http://127.0.0.1:8765/cmd (corpo = comando) para rodar comandos sob
demanda. Cada saída é gravada em tools/capturas/ para escrever os parsers.

Credenciais: `--olt <id>` usa o cadastro do coletor (recomendado); sem isso,
tools/olt_teste.env (fora do Git) — ver olt_teste.env.example.

Por segurança só deixa passar navegação (enable/config/interface/exit) e
comandos de leitura (show/display). Qualquer outro exige ?force=1.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import paramiko

AQUI = Path(__file__).resolve().parent
ENV = AQUI / "olt_teste.env"
CAPTURAS = AQUI / "capturas"
PORTA_HTTP = 8765
OCIOSO_KEEPALIVE_S = 120

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\r")
PROMPT = re.compile(r"(?m)^\S*[>#]\s*$")
PERMITIDOS = re.compile(
    r"^\s*(enable|config(ure)?( terminal)?|interface\s+gpon\s+\d+/\d+|exit|end|"
    r"show\b.*|display\b.*|paginate\s+false|terminal\s+length\s+0|)\s*$",
    re.IGNORECASE,
)


def ler_cadastro(olt_id: str) -> dict[str, str]:
    """Credenciais do cadastro (banco do coletor, senha decifrada só em memória)."""
    sys.path.insert(0, str(AQUI.parent))
    from coletor import inventario
    from coletor.cofre import Cofre
    from coletor.config import carregar_settings
    from coletor.db import Banco

    st = carregar_settings()
    olt = inventario.obter(Banco(st.banco), Cofre(st.dados), olt_id)
    if not olt:
        sys.exit(f"OLT '{olt_id}' não está cadastrada.")
    return {"OLT_HOST": olt.host, "OLT_PORT": str(olt.porta_ssh), "OLT_USER": olt.usuario,
            "OLT_PASSWORD": olt.senha, "OLT_ENABLE_PASSWORD": olt.senha_enable}


def ler_env() -> dict[str, str]:
    if len(sys.argv) > 2 and sys.argv[1] == "--olt":
        return ler_cadastro(sys.argv[2])
    if not ENV.exists():
        sys.exit(f"Falta {ENV} — copie olt_teste.env.example e preencha.")
    cfg = {}
    for linha in ENV.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


class Sessao:
    def __init__(self, cfg: dict[str, str]):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.ultimo_uso = time.monotonic()
        self.cliente: paramiko.SSHClient | None = None
        self.canal: paramiko.Channel | None = None

    def conectar(self) -> str:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(
            self.cfg["OLT_HOST"],
            port=int(self.cfg.get("OLT_PORT", "22")),
            username=self.cfg["OLT_USER"],
            password=self.cfg["OLT_PASSWORD"],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
        )
        c.get_transport().set_keepalive(30)
        self.cliente = c
        self.canal = c.invoke_shell(width=512, height=1000)
        saida = self._ler_ate_prompt(timeout=20)
        # Algumas C-DATA pedem login de novo dentro do shell.
        if re.search(r"(user ?name|login)\s*:\s*$", saida, re.I):
            saida += self._enviar(self.cfg["OLT_USER"])
            if re.search(r"password\s*:\s*$", saida, re.I):
                saida += self._enviar(self.cfg["OLT_PASSWORD"], eco=False)
        return saida

    def _ler_ate_prompt(self, timeout: float = 60) -> str:
        assert self.canal
        buf = ""
        fim = time.monotonic() + timeout
        quieto_desde = time.monotonic()
        while time.monotonic() < fim:
            if self.canal.recv_ready():
                pedaco = self.canal.recv(65535).decode("utf-8", "replace")
                buf += pedaco
                quieto_desde = time.monotonic()
                if re.search(r"--\s*more\s*--", pedaco, re.I):
                    self.canal.send(" ")
                continue
            limpo = ANSI.sub("", buf)
            parado = time.monotonic() - quieto_desde
            if parado > 0.6 and (
                PROMPT.search(limpo.splitlines()[-1] if limpo.splitlines() else "")
                or re.search(r"(password|user ?name|login)\s*:\s*$", limpo, re.I)
            ):
                break
            if self.canal.closed:
                break
            time.sleep(0.05)
        return ANSI.sub("", buf)

    def _enviar(self, texto: str, eco: bool = True, timeout: float = 60) -> str:
        assert self.canal
        self.canal.send(texto + "\n")
        saida = self._ler_ate_prompt(timeout)
        return saida if eco else saida.replace(texto, "***")

    # "show port ddm-info ... with-onu-optical" passa de 1 min em porta cheia.
    def rodar(self, comando: str, timeout: float = 300) -> str:
        with self.lock:
            if not self.canal or self.canal.closed:
                raise RuntimeError("sessão SSH caiu — reinicie o script")
            saida = self._enviar(comando, timeout=timeout)
            if comando.strip().lower() == "enable" and re.search(r"password\s*:\s*$", saida, re.I):
                senha = self.cfg.get("OLT_ENABLE_PASSWORD") or self.cfg["OLT_PASSWORD"]
                saida += self._enviar(senha, eco=False)
            self.ultimo_uso = time.monotonic()
            return saida

    def manter_viva(self) -> None:
        while True:
            time.sleep(15)
            if self.canal is None or self.canal.closed:
                print("[!] sessão SSH encerrada pela OLT", flush=True)
                return
            if time.monotonic() - self.ultimo_uso > OCIOSO_KEEPALIVE_S:
                try:
                    self.rodar("")
                except Exception as e:  # noqa: BLE001
                    print(f"[!] keepalive falhou: {e}", flush=True)


def salvar(comando: str, saida: str) -> Path:
    CAPTURAS.mkdir(exist_ok=True)
    nome = re.sub(r"[^A-Za-z0-9]+", "_", comando).strip("_")[:60] or "enter"
    arq = CAPTURAS / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nome}.txt"
    arq.write_text(f"# {comando}\n{saida}", encoding="utf-8")
    return arq


def main() -> None:
    sessao = Sessao(ler_env())
    print(sessao.conectar(), flush=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != "/cmd":
                self.send_error(404)
                return
            comando = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode().strip()
            forcar = parse_qs(url.query).get("force") == ["1"]
            if not forcar and not PERMITIDOS.match(comando):
                self._responder(403, f"Bloqueado (não é leitura/navegação): {comando!r}\n")
                return
            try:
                saida = sessao.rodar(comando)
            except Exception as e:  # noqa: BLE001
                self._responder(500, f"Erro: {e}\n")
                return
            arq = salvar(comando, saida)
            self._responder(200, f"{saida}\n# salvo em {arq.name}\n")

        def _responder(self, status: int, corpo: str):
            dados = corpo.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def log_message(self, *_):
            pass

    threading.Thread(target=sessao.manter_viva, daemon=True).start()
    print(f"[ok] sessão aberta; aguardando comandos em http://127.0.0.1:{PORTA_HTTP}/cmd", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORTA_HTTP), Handler).serve_forever()


if __name__ == "__main__":
    main()
