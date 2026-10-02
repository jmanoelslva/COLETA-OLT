"""Gera olts.toml a partir de tools/olt_teste.env (credenciais temporárias de teste).
Não imprime usuário nem senha."""

import json
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

env = {}
for linha in (RAIZ / "tools" / "olt_teste.env").read_text(encoding="utf-8").splitlines():
    linha = linha.strip()
    if linha and not linha.startswith("#") and "=" in linha:
        k, v = linha.split("=", 1)
        env[k.strip()] = v.strip()

texto = (RAIZ / "olts.example.toml").read_text(encoding="utf-8")
texto = texto.replace('host = "192.0.2.10"', f"host = {json.dumps(env['OLT_HOST'])}", 1)
texto = texto.replace("porta_ssh = 22", f"porta_ssh = {int(env.get('OLT_PORT', '22'))}", 1)
texto = texto.replace('usuario = ""', f"usuario = {json.dumps(env['OLT_USER'])}", 1)
texto = texto.replace('senha = ""', f"senha = {json.dumps(env['OLT_PASSWORD'])}", 1)
if env.get("OLT_ENABLE_PASSWORD"):
    texto = texto.replace('# senha_enable = ""', f"senha_enable = {json.dumps(env['OLT_ENABLE_PASSWORD'])}", 1)

destino = RAIZ / "olts.toml"
destino.write_text(texto, encoding="utf-8")
olt = tomllib.loads(texto)["olt"][0]
print("ok:", olt["id"], f"{olt['host']}:{olt['porta_ssh']}",
      "usuario preenchido" if olt["usuario"] else "USUARIO VAZIO",
      "senha preenchida" if olt["senha"] else "SENHA VAZIA", olt["portas_pon"])
