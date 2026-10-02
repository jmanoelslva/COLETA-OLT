"""Sessão SSH interativa com a C-DATA FD16xx.

A CLI tem "views" (`>`, `#`, `(config)#`, `(config-interface-gpon-F/S)#`) e
cada comando só existe em uma delas — `executar()` navega até a view certa
antes de mandar o comando.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

import paramiko

from ..config import OltConfig
from .parsers import checar_erro

log = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\r")
_PROMPT = re.compile(r"^\S+?(?:\([^)]*\))?[>#]\s*$")
_PEDE_LOGIN = re.compile(r"(user ?name|login)\s*:\s*$", re.I)
_PEDE_SENHA = re.compile(r"password\s*:\s*$", re.I)

VIEW_CONFIG = "config"
VIEW_GPON = "gpon"


class ErroSessao(Exception):
    """Falha de conexão/login/timeout — a sessão deve ser descartada."""


class SessaoCData:
    def __init__(self, olt: OltConfig, known_hosts: Path):
        self.olt = olt
        self.known_hosts = known_hosts
        self._cliente: paramiko.SSHClient | None = None
        self._canal: paramiko.Channel | None = None
        self._view = ""
        self.hostname: str | None = None
        self.ultimo_uso = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ conexão

    @property
    def conectada(self) -> bool:
        return self._canal is not None and not self._canal.closed

    def conectar(self) -> None:
        self.fechar()
        c = paramiko.SSHClient()
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        self.known_hosts.touch(exist_ok=True)
        c.load_host_keys(str(self.known_hosts))
        # Primeira conexão grava a chave; nas seguintes, chave diferente = recusa.
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(
                self.olt.host,
                port=self.olt.porta_ssh,
                username=self.olt.usuario,
                password=self.olt.senha,
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
            )
        except (paramiko.SSHException, OSError) as e:
            raise ErroSessao(f"SSH {self.olt.host}:{self.olt.porta_ssh}: {e}") from e
        c.save_host_keys(str(self.known_hosts))
        c.get_transport().set_keepalive(30)
        self._cliente = c
        self._canal = c.invoke_shell(width=512, height=2000)

        saida = self._ler_ate_prompt(20)
        # A C-DATA pede usuário/senha de novo dentro do shell.
        if _PEDE_LOGIN.search(saida):
            saida = self._enviar(self.olt.usuario, 20)
        if _PEDE_SENHA.search(saida):
            saida = self._enviar(self.olt.senha, 20)
        if not self._view_do_prompt(saida):
            self.fechar()
            raise ErroSessao("login na CLI falhou (prompt não apareceu)")
        self.ultimo_uso = time.monotonic()
        log.info("[%s] sessão SSH aberta (%s)", self.olt.id, self.hostname)

    def fechar(self) -> None:
        if self._cliente:
            try:
                self._cliente.close()
            except Exception:  # noqa: BLE001
                pass
        self._cliente = None
        self._canal = None
        self._view = ""

    # ------------------------------------------------------------ I/O

    def _ler_ate_prompt(self, timeout: float) -> str:
        assert self._canal
        buf = ""
        fim = time.monotonic() + timeout
        ultimo_dado = time.monotonic()
        while time.monotonic() < fim:
            if self._canal.recv_ready():
                pedaco = self._canal.recv(65535).decode("utf-8", "replace")
                buf += pedaco
                ultimo_dado = time.monotonic()
                if re.search(r"--\s*more\s*--", pedaco, re.I):
                    self._canal.send(" ")
                continue
            if self._canal.closed:
                raise ErroSessao("OLT encerrou a sessão")
            if time.monotonic() - ultimo_dado > 0.5:
                limpo = _ANSI.sub("", buf).rstrip(" ")
                ultima = limpo.splitlines()[-1] if limpo.splitlines() else ""
                if _PROMPT.match(ultima) or _PEDE_LOGIN.search(ultima) or _PEDE_SENHA.search(ultima):
                    return _ANSI.sub("", buf)
            time.sleep(0.05)
        raise ErroSessao(f"timeout de {timeout:.0f}s esperando o prompt")

    def _enviar(self, texto: str, timeout: float) -> str:
        assert self._canal
        self._canal.send(texto + "\n")
        saida = self._ler_ate_prompt(timeout)
        self._view_do_prompt(saida)
        return saida

    def _view_do_prompt(self, saida: str) -> str:
        linhas = [l for l in saida.splitlines() if l.strip()]
        if not linhas:
            return ""
        p = linhas[-1].strip()
        m = re.match(r"^(\S+?)(?:\(([^)]*)\))?([>#])$", p)
        if not m:
            return ""
        self.hostname = m[1]
        modo = m[2] or ""
        if modo.startswith("config-interface-gpon"):
            self._view = VIEW_GPON
        elif modo == "config":
            self._view = VIEW_CONFIG
        elif m[3] == "#":
            self._view = "enable"
        else:
            self._view = "user"
        return self._view

    def _ir_para(self, view: str) -> None:
        for _ in range(6):
            if self._view == view:
                return
            if self._view == "user":
                saida = self._enviar("enable", 120)
                if _PEDE_SENHA.search(saida.rstrip()):
                    self._enviar(self.olt.senha_enable or self.olt.senha, 120)
            elif self._view == "enable":
                self._enviar("config", 120)
            elif self._view == VIEW_CONFIG and view == VIEW_GPON:
                self._enviar(f"interface gpon {self.olt.frame_slot}", 120)
            elif self._view == VIEW_GPON and view == VIEW_CONFIG:
                self._enviar("exit", 120)
            else:
                self._enviar("", 120)
        if self._view != view:
            raise ErroSessao(f"não consegui chegar na view {view} (estou em {self._view!r})")

    # A CLI atende um comando por vez (inclusive os do Controllr): até um comando
    # rápido pode esperar na fila, por isso o prazo folgado.
    def executar(self, comando: str, view: str, timeout: float = 180) -> str:
        """Roda `comando` na view pedida. Levanta ErroCli se a OLT responder erro."""
        with self._lock:
            if not self.conectada:
                self.conectar()
            self._ir_para(view)
            saida = self._enviar(comando, timeout)
            self.ultimo_uso = time.monotonic()
        checar_erro(saida)
        return saida

    def manter_viva(self) -> None:
        with self._lock:
            if self.conectada:
                self._enviar("", 120)
                self.ultimo_uso = time.monotonic()
