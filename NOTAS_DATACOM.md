# Datacom DM4610 (DmOS 12.6) — notas da CLI

Levantado na `OLT-ARC-VSJ` (DM4610 HW2, placa 8GPON+8GX+4GT+2XS, DmOS
12.6.0). Saídas reais em `tools/capturas/` (fora do Git).

## Acesso

- SSH direto no prompt `OLT-ARC-VSJ#`, sem login duplo nem `enable`/`config`.
- `paginate false` desliga a paginação (vale só para a sessão).
- Datas já vêm com fuso: `2026-10-02 14:51:17 UTC-3`.

## Comandos (todos rápidos, 1–4 s)

| Comando | O que traz |
|---|---|
| `show onu-global-count` | Totais da OLT: total, não provisionadas, up, down |
| `show interface gpon 1/1/<porta> onu` | **Tabela por ONU**: ID, serial, oper state, last down reason, RX/TX na ONU, nome (cliente). ~4 s para ~95 ONUs. ONU down = `N/A` |
| `show interface gpon 1/1/<porta> onu <id>` | Detalhe `chave : valor`: serial, equipment ID (modelo), nome, uptime, last down reason/time, distância (km), line profile, versão/firmware, RX/TX |
| `show platform` | Slots: modelo, papel, status, firmware (placa, FAN, PSU) |
| `show environment` | Sensores de temperatura (com faixa de alarme e status), ventoinhas (RPM/status), fontes |
| `show interface transceivers` | SFP de cada PON: temperatura, tensão, corrente, TX, RX (RX = N/A nas GPON) |
| `show firmware` | Bancos de firmware e qual está ativo |
| `show system uptime` | Linha estilo `uptime` do Linux (dias, load average) |
| `show inventory` | Chassi, placa, serial, MACs, presença de transceiver por porta |
| `show interface gpon 1/1/<porta> onu <id> rssi` | **RX OLT** de uma ONU: `RSSI [dBm]: -22.29`. **~2 s por ONU e não existe versão por porta** (`onu rssi`, `onu all rssi`, `onu 0-5 rssi` não funcionam) |
| `show alarm` | Alarmes **ativos**: data com fuso, severidade da própria OLT (`CRITICAL`...), origem `gpon-1/1/<porta>/<onu>`, nome (`GPON_DGi`, `GPON_LOSi`...), descrição |
| `show system cpu` | Carga ativa/ociosa (5 s, 1 min, 5 min) geral e por núcleo; `cpuSysUptime` em segundos |
| `show system memory` | Total/usada/disponível (5 s, 1 min, 5 min, 30 min) em MiB |

## Diferenças para a C-DATA

- Uma chamada por porta já traz status **e** sinal na ONU **e** nome do
  cliente — não precisa do detalhe por ONU para ter a descrição.
- IDs de ONU começam em 0.
- Motivos de queda vistos: `Dying gasp`, `LOS`, `OMCC problem`, `N/A`.
- Distância em km (`1 [km]`) no detalhe.
- O detalhe tem um campo `Password` (senha da ONU) — **não guardar**.

- RSSI (RX na OLT) é por ONU: 643 ONUs × 2 s ≈ 21 min por volta completa.

## Histórico de alarmes

Não existe `show alarm history` no DmOS. O `show log` completo é lento e
pesa na OLT; `show log tail 100` funciona (3 s), mas decidimos não usar.
O histórico vem de:

- **Quedas de ONU**: `Last down reason` + `Last down time` do detalhe da
  ONU (hora exata). A volta é calculada pelo `Uptime` (precisão de minutos,
  marcada como estimada). Se a ONU cair duas vezes entre duas visitas, só a
  última fica registrada.
- **Demais alarmes**: diferença entre leituras de `show alarm` (5 min). O
  que aparece vira "alarme" com a hora da OLT; o que some vira "normalizou"
  com a hora da leitura. Alarmes que nascem e somem entre leituras se perdem.

## Como o coletor usa (coletor/datacom/)

| Coleta | Comandos | Frequência |
|---|---|---|
| Alarmes ativos | `show alarm` | 5 min |
| Equipamento | `show system cpu/memory/uptime`, `show environment`, `show platform`, `show interface transceivers`, `show firmware` | 5 min |
| ONUs | `show interface gpon 1/1/<p> onu` (8 portas ≈ 19 s) | 15 min |
| Rodízio | `... onu <id>` + `... onu <id> rssi` (~3 s por ONU) | contínuo |

Ordem do rodízio: ONUs que mudaram de estado na última lista (urgentes) →
sem detalhe ainda → sinal fora da faixa boa → o resto, do detalhe mais
antigo para o mais novo. 643 ONUs ≈ 30 min por volta.
