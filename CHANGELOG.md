# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [1.5.1] - 2026-10-02

### Corrigido

- Instalador: na atualização, baixa a versão nova antes das perguntas e, se o
  próprio instalador mudou, continua pela versão nova. Antes, novidades do
  instalador (como gerar o token de integração) só valiam rodando duas vezes.

## [1.5.0] - 2026-10-02

### Adicionado

- **Integração com o app técnico** (`/api/integracao/onu`): pelo serial da
  ONU — igual no Controllr e na OLT — devolve o que o Controllr não guarda:
  histórico de RX/TX da ONU e RX na OLT, quedas com motivo, hora, volta e
  duração, alarmes ativos e a situação da PON (quantas caíram juntas nos
  últimos 15 minutos). Também aceita OLT + porta + posição e tem
  `POST /api/integracao/onu/atualizar` para ler a ONU na hora.
- Token de serviço `COLETOR_SERVICO_TOKEN` (cabeçalho `X-Servico-Token`) só
  para essas rotas; o instalador gera um no modo técnico, se ainda não houver.
- O coletor registra quando o serial atual apareceu em cada posição
  (`sn_desde`): após troca de ONU, o histórico entregue começa na troca.

## [1.4.1] - 2026-10-02

### Corrigido

- Coleta de ONUs da C-DATA falhava inteira quando uma porta PON não tinha
  ONU cadastrada: a OLT responde `Error: There is no ONT avaliable` em vez de
  uma tabela vazia. A porta agora é registrada com 0 ONUs e o ciclo segue
  para as demais.

## [1.4.0] - 2026-10-02

### Adicionado

- **Suporte ao firmware C-DATA V3.x** (testado na V3.3.76), mantendo a V1.x.
  A sessão reconhece o prompt `(config-gpon-F/S)#` e o paginador
  `--More ( Press 'Q' to quit )--`, e os parsers leem os formatos novos de
  alarmes (AlarmId/Level, `ONU: n`, `ONU-SN(...)` e o `(clear)` na linha de
  baixo, que vira evento de normalização), lista de ONUs, detalhe da ONU, SFP
  da PON, CPU, temperatura, fontes e uptime.
- Na V3 a descrição (nome do cliente) já vem na lista de ONUs e o RX na OLT
  vem no `show ont optical-info <porta> all`: os dois são gravados a cada
  ciclo de ONUs, e o ciclo lento de RX na OLT passa a ler só o SFP da PON
  (sem o demorado `with-onu-optical`).
- Novos alarmes no catálogo: temperatura, tensão e corrente do laser da ONU,
  TX do SFP da PON fora do limite e SFP não reconhecido.
- `tools/diagnostico_cdata.py`: roda todos os comandos de leitura numa OLT
  cadastrada e confere cada parser, sem gravar no banco.

### Corrigido

- A sessão manda `terminal length 0` ao entrar no modo privilegiado. Algumas
  OLTs não guardam essa opção na configuração, e a paginação ficava ativa em
  toda sessão nova. A quebra pelo `--More--` continua como reserva.
- Fontes: slot sem fonte aparece como "slot vazio", e não mais como alerta.

## [1.3.1] - 2026-10-02

### Corrigido

- Cadastro de OLT (C-DATA): o campo Frame/slot esticava para acompanhar a
  altura de "Portas PON em uso" e ficava desalinhado. Os campos agora ocupam
  só a altura do próprio conteúdo, e o Frame/slot ganhou uma dica curta.

## [1.3.0] - 2026-10-02

### Adicionado

- **Publicação dentro do app técnico**, em `https://<domínio do técnico>/olt/`,
  sem domínio nem certificado novos. O instalador pergunta o modo (dentro do
  técnico ou domínio próprio) e, no primeiro, só grava um trecho em
  `/etc/coletor-olt/web/` que o vhost do técnico (PWA técnico 1.6.0+) inclui
  se existir — o técnico continua funcionando igual sem o coletor.
- **Login pelo app técnico** (`COLETOR_AUTH=tecnico`): o coletor aceita a
  sessão do PWA técnico (cookie `TECSESSION`), validada no `/auth/me` do
  backend dele e guardada por 1 minuto. Sem sessão, a interface manda para o
  login do técnico e volta para o coletor depois de entrar.
- `GET /api/saude` aberto, usado pelo PWA técnico para mostrar o menu
  **OLTs** só quando o coletor está instalado.
- Interface funciona com caminho base configurável no build
  (`COLETOR_BASE=/olt/`); na barra de cima aparecem o técnico logado e o
  link "‹ App técnico".

### Alterado

- `deploy/DEPLOY.md` reescrito com os dois modos e um checklist para cada.

## [1.2.2] - 2026-10-02

### Corrigido

- Configurações: o valor padrão de cada campo ("padrão 5 min") ficava solto
  numa linha abaixo do campo, sem unidade e desalinhado. Agora fica na mesma
  linha, em coluna própria, com a unidade, e muda de cor quando o valor
  digitado é diferente do padrão. A barra fixa de "Salvar configurações"
  ganhou uma borda para não se confundir com o conteúdo.

## [1.2.1] - 2026-10-02

### Corrigido

- O instalador atualiza o próprio arquivo com `git pull` durante a execução;
  como o bash lê o script aos poucos, a versão nova podia ser executada pela
  metade. Agora o script inteiro é lido antes de começar.

## [1.2.0] - 2026-10-02

### Adicionado

- **IPs liberados em Configurações**: ACL de IPv4/IPv6 (IP ou rede, com
  comentário opcional) aplicada pelo coletor em toda a `/api`, valendo na
  hora, sem reinstalar. Mostra o IP de quem está acessando, tem botão para
  incluí-lo e recusa salvar uma lista que trancaria o próprio usuário.
  Chamadas locais no servidor (integração com o app técnico) não passam pela
  ACL. "Restaurar padrões" não mexe nessa lista.

### Corrigido

- O instalador sobrescrevia o PWA técnico quando recebia o mesmo domínio
  dele (vhost `sites-available/<domínio>.conf` e build em
  `/var/www/<domínio>`, os mesmos caminhos do app técnico). Agora o coletor
  usa pasta e vhost com nome próprio (`/var/www/coletor-olt`,
  `coletor-olt-<domínio>.conf`, com a marca `@coletor-olt@`) e o instalador
  **recusa, antes de alterar qualquer coisa**, um domínio que já pertence a
  outro site do servidor. Ao trocar de domínio, só desativa vhosts antigos
  do próprio coletor.
- `COLETOR_CORS` no `.env` acompanha o domínio quando ele muda.

## [1.1.0] - 2026-10-02

### Adicionado

- Instalador para o servidor (`deploy/install.sh`), no mesmo modelo do PWA
  técnico e em paralelo com ele: usuário de sistema e serviço systemd
  próprios ouvindo só em `127.0.0.1`, mesmo Apache/Nginx já em uso (só
  adiciona o vhost), certificado Let's Encrypt com renovação automática,
  configuração em `/etc/coletor-olt` e dados em `/var/lib/coletor-olt`.
  Rodar de novo atualiza sem perder dados.
- Site protegido por usuário/senha do servidor web (HTTP Basic), inclusive
  `/api`, com lista opcional de IPs liberados — a interface não tem login
  próprio.
- Vhosts de exemplo para Nginx e Apache e guia de deploy
  (`deploy/DEPLOY.md`) com checklist.

### Removido

- `deploy/coletor-olt.service` (o instalador gera o serviço).

## [1.0.0] - 2026-10-02

Primeira versão: coleta por SSH de OLTs C-DATA e Datacom, histórico em
SQLite e interface web para o técnico.

### Adicionado

- Coleta por SSH da **C-DATA FD16xx** (FD1616GS/FD1608SN): alarmes ativos e
  histórico, equipamento (CPU, memória, temperatura, ventoinhas, fontes,
  firmware, SFP das PONs), ONUs por porta com RX/TX na ONU e RX na OLT
  (`ddm-info ... with-onu-optical`).
- Coleta por SSH da **Datacom DmOS** (DM4610, DmOS 12.6): ONUs por porta,
  detalhe e RSSI por ONU em rodízio, alarmes ativos, equipamento (CPU,
  memória, sensores, ventoinhas, fonte, SFP e estado das portas PON).
- Histórico de quedas da Datacom a partir do `Last down reason/time` das ONUs
  (o DmOS não tem histórico de alarmes); demais alarmes pela diferença entre
  leituras de `show alarm`.
- Uma sessão SSH e uma fila com prioridade por OLT (a CLI atende um comando
  por vez): manual → alarmes → equipamento → ONUs → RX OLT em pedaços.
- Coleta manual ("Coletar agora") por tipo e por porta, e leitura de uma ONU
  na hora.
- Intervalos de coleta, faixas de sinal e retenção (90 dias) configuráveis
  pela tela, valendo sem reiniciar; botão **Restaurar padrões**.
- Cadastro de OLTs pela interface, com teste de acesso antes de salvar e
  senha criptografada no banco (`dados/chave.key`); importação opcional de
  `olts.toml`.
- Diagnóstico por ONU e por porta PON: faixas de RX ONU/RX OLT, perda em cada
  sentido (aponta laser da ONU ou curvatura), degradação contra a média de 7
  dias, ONU oscilando, queda em massa (energia × LOS), sinal ruim
  generalizado na PON, PON sem link, SFP não suportado, serial duplicado,
  relógio da OLT errado.
- Estado da porta PON na C-DATA inferido por RX do SFP sem luz ou nenhuma
  ONU online.
- Correção das datas de alarmes da C-DATA registrados com a OLT sem relógio
  (ano 2000), estimadas a partir do boot.
- Tela inicial com resumo da rede, "Precisa de atenção agora", cartão por OLT
  com saúde, fileira de PONs e ONUs offline por motivo (com link para a lista
  filtrada).
- Telas da OLT (diagnóstico, alarmes ativos, histórico, ONUs, equipamento) e
  da ONU (régua RX ONU/RX OLT, gráfico de sinal, cadastro, eventos).
- Tema claro e escuro; layout para celular.
- Testes dos parsers e das coletas contra saídas reais anonimizadas
  (`tests/fixtures`), simulador e OLT de desenvolvimento (`tools/`).

[Não lançado]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.5.1...HEAD
[1.5.1]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/COLETA-OLT/releases/tag/v1.0.0
