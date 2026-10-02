"""Sessão SSH com o DmOS: sem login duplo nem views — só desliga a paginação."""

from __future__ import annotations

import time

from ..cdata.sessao import ErroSessao, SessaoCData
from . import parsers as p


class SessaoDatacom(SessaoCData):
    def conectar(self) -> None:
        super().conectar()
        self._enviar("paginate false", 60)

    def executar(self, comando: str, view: str | None = None, timeout: float = 180) -> str:
        with self._lock:
            if not self.conectada:
                self.conectar()
            saida = self._enviar(comando, timeout)
            self.ultimo_uso = time.monotonic()
        p.checar_erro(saida)
        return saida


__all__ = ["SessaoDatacom", "ErroSessao"]
