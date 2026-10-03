"""Acesso de administrador do coletor.

Ver o coletor é para qualquer técnico; cadastrar, editar e excluir OLTs, ver
credenciais, testar acesso e mudar as Configurações é só para o admin — um
usuário e senha próprios do coletor, separados do login do app técnico.

A senha fica só como hash scrypt (biblioteca padrão) na tabela `admin`. As
sessões ficam em memória: reiniciar o serviço pede login de novo.

Definir/trocar pelo servidor:  python -m coletor.admin
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from .db import Banco, agora_utc, iso

SESSAO_S = 8 * 3600
TENTATIVAS_MAX = 5
TENTATIVAS_JANELA_S = 15 * 60
SENHA_MINIMA = 8

_N, _R, _P = 2**14, 8, 1


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${h.hex()}"


def conferir_hash(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p),
                              dklen=len(h) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), h)


# Hash de uma senha qualquer: compara contra ele quando o usuário não existe,
# para a resposta levar o mesmo tempo (não revela se o usuário está certo).
_HASH_FALSO = gerar_hash(secrets.token_hex(8))


def validar_credenciais(usuario: str, senha: str) -> dict[str, str]:
    erros = {}
    if not usuario.strip() or len(usuario.strip()) > 64 or any(c.isspace() for c in usuario.strip()):
        erros["usuario"] = "use de 1 a 64 caracteres, sem espaços"
    if len(senha) < SENHA_MINIMA:
        erros["senha"] = f"a senha precisa de pelo menos {SENHA_MINIMA} caracteres"
    return erros


def configurado(banco: Banco) -> bool:
    with banco.conexao() as c:
        return c.execute("SELECT 1 FROM admin WHERE id = 1").fetchone() is not None


def usuario_atual(banco: Banco) -> str | None:
    with banco.conexao() as c:
        r = c.execute("SELECT usuario FROM admin WHERE id = 1").fetchone()
    return r["usuario"] if r else None


def marca(banco: Banco) -> str | None:
    """Muda a cada troca de usuário/senha (inclusive pela linha de comando, em
    outro processo): sessão aberta antes da troca deixa de valer."""
    with banco.conexao() as c:
        r = c.execute("SELECT usuario, atualizado_em, senha_hash FROM admin WHERE id = 1").fetchone()
    return hashlib.sha256(f"{r['usuario']}|{r['atualizado_em']}|{r['senha_hash']}".encode()).hexdigest() if r else None


def definir(banco: Banco, usuario: str, senha: str) -> None:
    erros = validar_credenciais(usuario, senha)
    if erros:
        raise ValueError("; ".join(erros.values()))
    with banco.conexao() as c:
        c.execute(
            "INSERT INTO admin (id, usuario, senha_hash, atualizado_em) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET usuario = excluded.usuario, senha_hash = excluded.senha_hash, "
            "atualizado_em = excluded.atualizado_em",
            (usuario.strip(), gerar_hash(senha), iso(agora_utc())),
        )


def conferir(banco: Banco, usuario: str, senha: str) -> bool:
    with banco.conexao() as c:
        r = c.execute("SELECT usuario, senha_hash FROM admin WHERE id = 1").fetchone()
    if not r:
        conferir_hash(senha, _HASH_FALSO)
        return False
    ok_usuario = hmac.compare_digest(usuario.strip().encode(), r["usuario"].encode())
    ok_senha = conferir_hash(senha, r["senha_hash"])
    return ok_usuario and ok_senha


# ------------------------------------------------------------------ sessões


@dataclass
class _Sessao:
    usuario: str
    marca: str
    expira: float


class Sessoes:
    def __init__(self, validade_s: float = SESSAO_S):
        self.validade_s = validade_s
        self._sessoes: dict[str, _Sessao] = {}
        self._falhas: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def criar(self, usuario: str, marca: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            agora = time.monotonic()
            self._sessoes = {t: s for t, s in self._sessoes.items() if s.expira > agora}
            self._sessoes[token] = _Sessao(usuario, marca, agora + self.validade_s)
        return token

    def validar(self, token: str | None, marca_atual: str | None) -> str | None:
        """Usuário da sessão, ou None (sem sessão, expirada ou admin trocado depois dela)."""
        if not token:
            return None
        with self._lock:
            s = self._sessoes.get(token)
            if not s or s.expira <= time.monotonic() or s.marca != marca_atual:
                self._sessoes.pop(token, None)
                return None
            return s.usuario

    def encerrar(self, token: str | None) -> None:
        with self._lock:
            self._sessoes.pop(token or "", None)

    def encerrar_todas(self) -> None:
        with self._lock:
            self._sessoes.clear()

    # Limite de tentativas erradas por IP (força bruta).
    def bloqueado(self, chave: str) -> bool:
        with self._lock:
            agora = time.monotonic()
            falhas = [t for t in self._falhas.get(chave, []) if agora - t < TENTATIVAS_JANELA_S]
            self._falhas[chave] = falhas
            return len(falhas) >= TENTATIVAS_MAX

    def falhou(self, chave: str) -> None:
        with self._lock:
            self._falhas.setdefault(chave, []).append(time.monotonic())

    def acertou(self, chave: str) -> None:
        with self._lock:
            self._falhas.pop(chave, None)


# ------------------------------------------------------------------ linha de comando


def main(argv: list[str] | None = None) -> int:
    """Define (ou troca) o usuário e a senha do admin direto no servidor."""
    import argparse
    import getpass
    import sys

    from .config import carregar_settings

    ap = argparse.ArgumentParser(prog="python -m coletor.admin", description=main.__doc__)
    ap.add_argument("--se-vazio", action="store_true", help="só pergunta se ainda não houver admin (instalador)")
    args = ap.parse_args(argv)

    banco = Banco(carregar_settings().banco)
    atual = usuario_atual(banco)
    if atual and args.se_vazio:
        print(f"Admin do coletor já definido (usuário: {atual}).")
        return 0
    if not sys.stdin.isatty():
        print("Sem terminal para digitar a senha: rode  python -m coletor.admin  no servidor.", file=sys.stderr)
        return 1
    try:
        return _perguntar(banco, atual)
    except (EOFError, KeyboardInterrupt):
        print("\nAdmin não alterado.", file=sys.stderr)
        return 1


def _perguntar(banco: Banco, atual: str | None) -> int:
    import getpass
    import sys

    print("Admin do coletor: só ele cadastra/edita/exclui OLTs e muda as Configurações.")
    usuario = input(f"Usuário admin [{atual or 'admin'}]: ").strip() or atual or "admin"
    for _ in range(3):
        senha = getpass.getpass(f"Senha (mín. {SENHA_MINIMA} caracteres): ")
        if getpass.getpass("Repita a senha: ") != senha:
            print("As senhas não conferem.")
            continue
        erros = validar_credenciais(usuario, senha)
        if erros:
            print("; ".join(erros.values()))
            continue
        definir(banco, usuario, senha)
        print(f"Admin definido (usuário: {usuario}). Quem estava logado como admin precisa entrar de novo.")
        return 0
    print("Admin não alterado.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
