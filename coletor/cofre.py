"""Criptografia das senhas das OLTs guardadas no SQLite (Fernet/AES).

A chave vem de COLETOR_CHAVE ou, se não houver, de `<dados>/chave.key`,
criada na primeira execução. Sem a chave o banco não serve para nada —
faça backup dela junto (mas separado) do banco.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class Cofre:
    def __init__(self, pasta_dados: Path):
        chave = os.environ.get("COLETOR_CHAVE", "").strip()
        if not chave:
            arq = pasta_dados / "chave.key"
            if not arq.exists():
                pasta_dados.mkdir(parents=True, exist_ok=True)
                arq.write_bytes(Fernet.generate_key())
                try:
                    os.chmod(arq, 0o600)
                except OSError:
                    pass
            chave = arq.read_text().strip()
        self._f = Fernet(chave.encode())

    def cifrar(self, texto: str) -> str:
        return self._f.encrypt(texto.encode()).decode() if texto else ""

    def decifrar(self, cifrado: str | None) -> str:
        if not cifrado:
            return ""
        try:
            return self._f.decrypt(cifrado.encode()).decode()
        except InvalidToken as e:
            raise RuntimeError("senha da OLT não pôde ser lida: a chave (chave.key/COLETOR_CHAVE) mudou") from e
