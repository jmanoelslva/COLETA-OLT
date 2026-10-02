# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

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

[Não lançado]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanoelslva/COLETA-OLT/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jmanoelslva/COLETA-OLT/releases/tag/v1.0.0
