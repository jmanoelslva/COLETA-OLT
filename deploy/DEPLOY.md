# Deploy do Coletor de OLTs

Pensado para o **mesmo servidor do PWA HOTNET Técnico** (e do portal do
cliente), sem mexer nos arquivos deles: outro diretório, outro serviço
systemd e outra porta local. Mesmo modelo do `deploy/install.sh` do app
técnico.

## Duas formas de publicar

| | 1. Dentro do app técnico (recomendado) | 2. Domínio próprio |
|---|---|---|
| Endereço | `https://tecnico.hotnet.net.br/olt/` | `https://olt.hotnet.net.br` (ou outro) |
| Login | **o do app técnico** — quem está logado no PWA entra direto | usuário e senha do servidor web (HTTP Basic) |
| No PWA técnico | aparece o menu **OLTs** no painel | nada muda |
| DNS / certificado | usa os do técnico | precisa de DNS e certificado novos |
| Requisito | PWA técnico **1.6.0+** instalado no servidor | domínio só do coletor |

No modo 1, o coletor não cria vhost: grava um trecho em
`/etc/coletor-olt/web/`, que o vhost do técnico (1.6.0+) inclui **se
existir**. Sem o coletor, o técnico funciona igual e o menu OLTs não aparece.
O coletor valida a sessão do técnico (cookie `TECSESSION`) no `/auth/me` do
backend dele, na mesma máquina — sem sessão, a tela manda para o login do
técnico e volta para o coletor depois de entrar.

| | |
|---|---|
| Código | `/opt/coletor-olt` (clone do repositório) |
| Dados | `/var/lib/coletor-olt` — banco SQLite, `chave.key`, `known_hosts` das OLTs |
| Configuração | `/etc/coletor-olt/coletor.env`, `install.conf`, `web/` (modo 1), `htpasswd` (modo 2) |
| Serviço | `coletor-olt` (systemd), ouvindo só em `127.0.0.1:8090` |
| Arquivos web | `/var/www/coletor-olt/dist` (nome próprio, não colide com o técnico) |

## Antes de instalar

1. **Modo 1**: atualize o PWA técnico para a **1.6.0 ou mais nova** e rode
   o instalador dele (`sudo bash /opt/hotnet-tecnico/deploy/install.sh`,
   Enter nas perguntas) — é isso que coloca a linha de include no vhost.
   **Modo 2**: crie o DNS de um domínio **só do coletor**; o instalador
   recusa domínio que já pertence a outro site.
2. **Acesso às OLTs**: o servidor precisa entrar por SSH nas OLTs. Libere o
   **IP de saída do servidor** na ACL/firewall de gerência de cada OLT (o
   instalador mostra esse IP no final). Sem isso, "Testar acesso" falha com
   "Unable to connect".
3. **Sistema**: Debian 12+ ou Ubuntu 22.04+ (Python 3.11+). O servidor do
   app técnico já atende.
4. **Porta local**: o backend do técnico usa a 8000; o coletor usa a 8090.

## Instalar

```bash
git clone https://github.com/jmanoelslva/COLETA-OLT.git /tmp/coleta-olt
sudo bash /tmp/coleta-olt/deploy/install.sh
```

O script pergunta:

- **Onde publicar**: 1 = dentro do app técnico (padrão quando ele está
  instalado), 2 = domínio próprio;
- **Domínio** (só no modo 2);
- **Porta local** (Enter = 8090);
- **IPs liberados** (opcional, IPv4/IPv6): vazio = qualquer IP, sempre com
  login. Dá para ajustar depois em Configurações;
- No modo 2: **e-mail** do Let's Encrypt e **usuário e senha** do primeiro
  acesso.

Depois: abra o coletor (modo 1: pelo menu **OLTs** do PWA técnico ou em
`https://tecnico.hotnet.net.br/olt/`) e cadastre as OLTs em **Cadastrar
OLT**, usando **Testar acesso** antes de salvar.

Se o vhost do técnico ainda não tiver a linha de include, o instalador do
coletor avisa e termina mesmo assim (o serviço já fica rodando); `/olt/`
passa a funcionar quando o técnico for atualizado.

## Atualizar

```bash
sudo bash /opt/coletor-olt/deploy/install.sh
```

Vindo da 1.2.0 ou anterior, atualize o repositório antes, para já rodar o
instalador novo:

```bash
sudo git -c safe.directory=/opt/coletor-olt -C /opt/coletor-olt pull --ff-only
```

Faz `git pull`, reinstala dependências, gera o build, reinicia o serviço e
republica. Não apaga dados, a chave, os acessos nem reemite certificado. Dá
para trocar de modo rodando de novo e escolhendo a outra opção: o instalador
desativa o que era do modo anterior (só arquivos do coletor).

## Segurança

- **Modo 1**: só entra quem tem sessão válida no app técnico (o mesmo login
  do Controllr). Saiu do técnico, perde o acesso ao coletor em até 1 min.
- **Modo 2**: o site inteiro, inclusive `/api`, fica atrás de usuário/senha
  do servidor web:

  ```bash
  sudo htpasswd -B /etc/coletor-olt/htpasswd nome     # incluir/trocar
  sudo htpasswd -D /etc/coletor-olt/htpasswd nome     # remover
  ```
- **IPs liberados**: há duas listas, e as duas valem juntas:
  - a do **servidor web**, definida no `install.sh` (muda rodando o
    instalador de novo);
  - a de **Configurações → IPs liberados**, no próprio coletor, que vale na
    hora e aceita IPv4 e IPv6. Ela mostra o seu IP e não deixa salvar uma
    lista que te tranque fora. Se o domínio tiver registro AAAA, o
    navegador costuma usar IPv6 — inclua a rede IPv6 também.
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
curl -s 127.0.0.1:8090/api/saude          # {"app": "coletor-olt", ...}
```

Checklist — modo 1 (dentro do app técnico):

- [ ] `https://tecnico.hotnet.net.br/` continua abrindo o PWA técnico normal.
- [ ] Logado no PWA, aparece o menu **OLTs** e ele abre o coletor sem pedir
      senha.
- [ ] Numa aba anônima, `https://tecnico.hotnet.net.br/olt/` leva ao login
      do técnico e, depois de entrar, volta para o coletor.
- [ ] Recarregar uma tela interna do coletor (ex.: uma ONU) abre a mesma
      tela, não o app técnico.
- [ ] "Cadastrar OLT" → "Testar acesso" conecta em cada OLT.

Checklist — modo 2 (domínio próprio):

- [ ] `https://<domínio>` pede usuário e senha; sem senha dá 401.
- [ ] De um IP fora da lista (se configurada) dá 403.
- [ ] "Cadastrar OLT" → "Testar acesso" conecta em cada OLT.

Nos dois: depois de ~1 min a OLT aparece na tela inicial com ONUs e alarmes,
e `journalctl -u coletor-olt` fica sem "FALHOU" repetido.

## Desfazer o modo 1

`sudo rm /etc/coletor-olt/web/*.conf` e recarregar o servidor web
(`systemctl reload nginx` ou `apache2`): `/olt/` some e o menu OLTs deixa de
aparecer no técnico, que segue funcionando.
