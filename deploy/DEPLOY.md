# Deploy do Coletor de OLTs

Pensado para o **mesmo servidor do PWA HOTNET Técnico** (e do portal do
cliente), sem mexer em nada deles: outro diretório, outro domínio, outro
serviço systemd e outra porta local. Mesmo modelo do `deploy/install.sh` do
app técnico.

| | |
|---|---|
| Código | `/opt/coletor-olt` (clone do repositório) |
| Dados | `/var/lib/coletor-olt` — banco SQLite, `chave.key`, `known_hosts` das OLTs |
| Configuração | `/etc/coletor-olt/coletor.env`, `/etc/coletor-olt/htpasswd`, `/etc/coletor-olt/install.conf` |
| Serviço | `coletor-olt` (systemd), ouvindo só em `127.0.0.1:8090` |
| Site | `https://<domínio>` servido pelo Apache/Nginx já em uso, com senha |

## Antes de instalar

1. **DNS**: crie o registro do domínio do coletor (sugestão:
   `olt.hotnet.net.br`) apontando para o servidor.
2. **Acesso às OLTs**: o servidor precisa entrar por SSH nas OLTs. Libere o
   **IP de saída do servidor** na ACL/firewall de gerência de cada OLT (o
   instalador mostra esse IP no final). Sem isso, "Testar acesso" falha com
   "Unable to connect".
3. **Sistema**: Debian 12+ ou Ubuntu 22.04+ (o coletor precisa de Python
   3.11+). O servidor do app técnico já atende.
4. **Porta local**: o backend do app técnico usa a 8000; o coletor usa a
   8090 por padrão. Qualquer porta livre serve.

## Instalar

```bash
git clone https://github.com/jmanoelslva/COLETA-OLT.git /tmp/coleta-olt
sudo bash /tmp/coleta-olt/deploy/install.sh
```

O script pergunta:

- **Domínio** do coletor;
- **Porta local** (Enter = 8090);
- **IPs liberados** (opcional): redes que podem abrir o site, separadas por
  espaço — ex.: a rede do escritório/NOC. Vazio = qualquer IP, sempre com
  senha;
- **E-mail** do Let's Encrypt (opcional);
- **Usuário e senha** do primeiro acesso ao site (só na primeira vez).

Depois: abra `https://<domínio>`, entre com o usuário criado e cadastre as
OLTs em **Cadastrar OLT**, usando **Testar acesso** antes de salvar.

## Atualizar

Rode o mesmo comando de novo (com o repositório já em `/opt/coletor-olt`):

```bash
sudo bash /opt/coletor-olt/deploy/install.sh
```

Ele faz `git pull`, reinstala dependências, gera o build, reinicia o serviço
e republica o site. Não apaga dados, a chave, os acessos nem reemite o
certificado. As respostas da primeira vez aparecem como padrão (Enter).

## Segurança

- A interface **não tem login próprio**. O site inteiro, inclusive `/api`,
  fica atrás de usuário/senha do servidor web (HTTP Basic) e, se
  configurado, de lista de IPs. Incluir pessoa ou trocar senha:

  ```bash
  sudo htpasswd -B /etc/coletor-olt/htpasswd nome
  ```

  Remover: `sudo htpasswd -D /etc/coletor-olt/htpasswd nome`.
- O serviço roda com usuário próprio (`coletor-olt`, sem shell), só escreve
  em `/var/lib/coletor-olt` e só ouve em `127.0.0.1`.
- As senhas das OLTs ficam cifradas no banco com `chave.key`. **Faça backup
  do banco e da chave juntos** — sem a chave, as senhas cadastradas não
  servem e as OLTs precisam ser recadastradas.
- Use nas OLTs um usuário **só de leitura** para o coletor, separado do
  usuário do Controllr.

## Levar o que já foi coletado na máquina de testes (opcional)

O normal é começar do zero no servidor e cadastrar as OLTs pela tela. Para
levar o histórico já coletado, copie **juntos** `dados/coletor.sqlite3` e
`dados/chave.key` para `/var/lib/coletor-olt/` com o serviço parado:

```bash
sudo systemctl stop coletor-olt
sudo cp coletor.sqlite3 chave.key /var/lib/coletor-olt/
sudo chown coletor-olt:coletor-olt /var/lib/coletor-olt/*
sudo chmod 600 /var/lib/coletor-olt/chave.key
sudo systemctl start coletor-olt
```

## Verificar

```bash
systemctl status coletor-olt              # serviço de pé
journalctl -u coletor-olt -f              # coletas: "alarmes ok em 4s", etc.
curl -s 127.0.0.1:8090/api/olts | head    # API local (sem senha, só no servidor)
```

Checklist depois de instalar:

- [ ] `https://<domínio>` pede usuário e senha; sem senha dá 401.
- [ ] De um IP fora da lista (se configurada) dá 403.
- [ ] "Cadastrar OLT" → "Testar acesso" conecta em cada OLT.
- [ ] Depois de ~1 min, a OLT aparece na tela inicial com ONUs e alarmes.
- [ ] `journalctl -u coletor-olt` sem "FALHOU" repetido.

## Integração com o app técnico (futuro)

O backend do app técnico, no mesmo servidor, pode consultar a API direto em
`http://127.0.0.1:8090/api/...` sem passar pelo site. Para isso, defina
`COLETOR_API_TOKEN` em `/etc/coletor-olt/coletor.env` e envie o mesmo valor
no header `X-Api-Token`. Atenção: com o token definido, a interface web
também passa a precisar dele — isso será ajustado na integração.
