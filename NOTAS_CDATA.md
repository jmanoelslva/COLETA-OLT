# C-DATA FD1616GS — notas da CLI

Levantado na OLT de testes (`OLT-IGC-NRO`, 8 portas PON em uso). Saídas
reais em `tools/capturas/` (fora do Git — têm serial e nome de cliente).

## Acesso

- SSH só oferece host key `ssh-rsa`/`ssh-dss` → paramiko `<4`.
- Depois do SSH a OLT pede usuário/senha de novo dentro do shell.
- Navegação: `enable` → `config` → `interface gpon 0/0`
  (prompt `OLT-IGC-NRO(config-interface-gpon-0/0)#`).
- CLI já sem paginação.
- Aceita várias sessões simultâneas. A sessão Telnet `admin` que aparece
  no banner é do Controllr — não derrubar.

## Comandos (dentro de `interface gpon 0/0`)

| Comando | O que traz | Tempo |
|---|---|---|
| `show ont info <porta> all` | Tabela: ONT-ID, SN, control/run/config/match state, last down cause; rodapé com totais | rápido |
| `show ont info <porta> <id>` | Bloco `chave : valor`: SN, Description (nome do cliente), distância, last up/down/dying-gasp, online time, perfis | rápido |
| `show ont optical-info <porta> all` | Tabela por ONU: tensão, TX, **RX na ONU**, bias, temperatura. ONU offline = linha só com o ID | rápido |
| `show ont optical-info <porta> <id>` | Mesmo + thresholds (todos `[-,-]` nessa OLT). ONU offline → `Error:Get onu optical info fail!` | rápido |
| `show port ddm-info <porta> with-onu-optical` | DDM do SFP da PON (temp, tensão, bias, TX, RX, vendor/modelo/serial) + **RX na OLT** por ONU | **lento: ~55 s, pode passar de 1 min** |

### Alarmes (view `config`, fora do `interface gpon`)

| Comando | O que traz | Tempo |
|---|---|---|
| `show alarm active all` | Alarmes ativos, 1 por linha, mais recente primeiro; rodapé `total number : N` | rápido |
| `show alarm history all` | Eventos (levanta **e** limpa), 1 por linha; **buffer circular de 2000 linhas** | ~1 s |

Formato da linha: `AAAA-MM-DD HH:MM:SS PON F/S/P [ONU id] [UNI x/y] <mensagem>`.
Sem `ONU` = alarme da porta PON inteira (ex.: `Loss of signal(LOS)`,
`Do not support this tranceiver`).

Pares levanta → limpa vistos:

| Levanta | Limpa |
|---|---|
| `Dying gasp(DGi)` | `Dying gasp(DGi) clear` |
| `Loss of signal for ONU(LOSi)` | `... clear` |
| `Loss of frame for ONU(LOFi)` | `... clear` |
| `Loss of signal(LOS)` (PON) | `Loss of signal(LOS) clear` |
| `The ONT Tx power exceeds the high/low alarm threshold` | `The ONT Tx power becomes normal` |
| `UNI x/y The Ethernet port link status is down` | `... is up` |
| `The ONT Rx power exceeds the high alarm threshold` | (não visto ainda) |
| `ONU does not react correctly after deactive or disable(DFi)` | (não visto ainda) |

Observações:

- **O histórico da OLT cobre só ~1 h** nessa OLT: ONUs com TX oscilando
  (ex.: 0/0/8 ONU 7, 0/0/6 ONU 10) geram evento a cada minuto e enchem o
  buffer. O coletor precisa ler o histórico a cada ≤5 min e deduplicar
  por (data, PON, ONU, UNI, mensagem) — o histórico de verdade fica no SQLite.
- Ordem não é estritamente decrescente (diferença de 1 s entre linhas).
- Alarmes com data em 1999/2000 = OLT subiu sem relógio: ela conta a
  partir de `2000-01-01 00:00 UTC` (= `1999-12-31 21:00 -0300`) desde o
  boot. Na OLT de testes o relógio ficou assim por ~42 dias e foi acertado
  em ~2026-10-01. Dá para **estimar a data real**:
  `real = boot_time + (data_falsa - 1999-12-31 21:00:00)`, com `boot_time`
  do `show uptime`. Gravar a data original e marcar como "estimada".
  Conferido: último evento falso `2000-02-11 21:21` → ~`2026-10-01 13:18`,
  antes do primeiro evento com data real (`2026-10-01 17:10`).
- Antes de cada ciclo, comparar `show time` com o relógio do servidor; se
  divergir mais que alguns minutos, marcar as datas do ciclo como suspeitas.
- Uma DGi/LOSi/LOFi sempre vem em trio no mesmo segundo → agrupar como
  um evento só ("ONU caiu: falta de energia" vs "ONU caiu: LOS").

### Dados da OLT

View `config`, todos rápidos (~1 s):

| Comando | O que traz |
|---|---|
| `show firmware info` | 2 bancos de firmware (status, versão, data, tamanho) + `boot selection` |
| `show cpu` | Utilização % e load average 1/5/15 min |
| `show fan` | `FAN[n] status: <Normal/...> (<rpm>RPM)` |
| `show power state` | Tabela Slot-ID × WorkStatus (`working`/`notworking`) |
| `show temperature` | Uma linha: `The temperature of the board: 58.0(C)` |
| `show version` | Versão de hardware, firmware (com data de build) e web. **Não traz modelo nem uptime** |
| `show uptime` | `System up time : 43 day 1 hour 1 minute 43 second` + `System boot time : Thu Aug 20 12:57:27 2026` |
| `show time` | `2026-10-02 13:59:11 -0300 GMT` — relógio atual com fuso |
| `show memory` | Total/livre (MB) e utilização %. Só existe em `config` — dentro de `interface gpon` dá `Unknown command: (vtysh)...` |

Em `interface gpon 0/0`:

| Comando | O que traz |
|---|---|
| `show port ddm-info <porta>` | DDM do SFP da PON (temp, tensão, bias, TX, RX, vendor/modelo/serial) + thresholds (`[-,-]` = não configurado). **Rápido** (~2 s) — só o `with-onu-optical` é lento |

Observações:

- Na OLT de testes a fonte do slot 2 está `notworking` — pode ser fonte
  redundante não instalada ou fonte com defeito; confirmar antes de
  tratar como alarme.
- Load average ~8 com CPU em 10% — normal para essa plataforma? Coletar
  e acompanhar antes de definir limite.

## Detalhes de parsing

- ONT-IDs não são contíguos — sempre ler o ID da linha.
- Valores ausentes: `--` ou linha vazia → `NULL`, nunca 0.
- `On line time` vem como `12days 17h:26m:41s`.
- Erros começam com `Error:`.

## Decisões de coleta

- `ddm-info` roda numa **sessão SSH dedicada**, porta por porta, para não
  atrasar alarmes/consultas rápidas. Um ciclo novo não começa enquanto o
  anterior não terminar (8 portas ≈ 8–12 min).
- Timeout por comando: 300 s.
