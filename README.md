# Coletor de OLTs

Serviço que entra nas OLTs por SSH, coleta alarmes, sinais das ONUs e
saúde do equipamento, guarda o histórico em SQLite e mostra tudo numa
interface web pensada para o técnico em campo. Depois será integrado ao
app do técnico (`PROJETO_PWA_TÉCNICO_HOTNET`) pela API.

Fabricantes suportados: **C-DATA FD16xx** (testado na FD1616GS) e **Datacom
DmOS** (testado no DM4610, DmOS 12.6). Comandos e particularidades de cada
CLI em [NOTAS_CDATA.md](NOTAS_CDATA.md) e [NOTAS_DATACOM.md](NOTAS_DATACOM.md).

As OLTs são cadastradas pela interface (**Cadastrar OLT**), com teste de
acesso antes de salvar. A senha fica criptografada no banco
(dados/chave.key — guarde no backup). O olts.toml é opcional: na subida,
as OLTs que estiverem nele e ainda não no banco são importadas.

## O que coleta (C-DATA)

| Coleta | Comandos | Intervalo padrão |
|---|---|---|
| Alarmes | `show alarm active all`, `show alarm history all`, `show time`, `show uptime` | 5 min |
| Equipamento | `show cpu/memory/temperature/fan/power state/firmware info/version`, `show port ddm-info <porta>` | 5 min |
| ONUs e RX ONU | `show ont info <porta> all`, `show ont optical-info <porta> all` (+ detalhe de até 40 ONUs por ciclo) | 15 min |
| RX OLT (sinal da ONU na OLT) | `show port ddm-info <porta> with-onu-optical` (~1 min por porta) | 15 min |

Intervalos, faixas de sinal e retenção (90 dias) mudam pela tela
**Configurações** ou `PUT /api/parametros`, valendo na hora. Também dá
para forçar qualquer coleta, de uma porta ou da OLT inteira, pelo botão
**Coletar agora**, e ler uma ONU na hora pela tela dela.

A CLI das OLTs atende **um comando por vez**, mesmo com várias sessões. Por
isso cada OLT tem uma sessão SSH e uma fila com prioridade (manual →
alarmes → equipamento → ONUs → sinal na OLT). O sinal na OLT roda em
pedaços (C-DATA: uma porta; Datacom: uma ONU), e entre um pedaço e outro o
que for mais prioritário passa na frente. Uma coleta nunca é empilhada
sobre outra.

## Estrutura

- `coletor/` — backend Python (FastAPI + paramiko + SQLite)
  - `cdata/parsers.py` — leitura das saídas da CLI (testada com saídas reais anonimizadas em `tests/fixtures/`)
  - `cdata/sessao.py` — sessão SSH, navegação entre views (`config`, `interface gpon`)
  - `coletas.py` — o que cada coleta roda e grava
  - `agendador.py` — faixas rápida/lenta por OLT, coleta forçada, limpeza
  - `alarmes.py` — catálogo de alarmes e correção das datas da OLT sem relógio
  - `analise.py` — faixas de sinal, degradação, diagnóstico por ONU e por PON
  - `api.py` — API HTTP (e serve o frontend buildado)
- `frontend/` — interface (Vite + React + TypeScript)
- `tools/` — sessão SSH interativa de desenvolvimento, gerador de fixtures, simulador
- `deploy/` — exemplo de serviço systemd

## Rodando local

```bash
python -m venv .venv
.venv/Scripts/activate                 # Windows
pip install -r requirements-dev.txt
cp olts.example.toml olts.toml         # preencha usuário/senha
python -m coletor                      # API + agendador em http://127.0.0.1:8090
```

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5174 (proxy /api → 8090)
```

Sem OLT por perto: `python tools/simular.py` cria um banco com 3 dias de
histórico a partir das fixtures, e `python tools/dev.py` sobe a API com
ele (OLT "simulada", coleta pausada).

Testes: `python -m pytest`.

## Variáveis de ambiente

| Variável | Padrão | |
|---|---|---|
| `COLETOR_OLTS` | `./olts.toml` | inventário de OLTs (tem senha: `chmod 600`) |
| `COLETOR_DADOS` | `./dados` | SQLite e `known_hosts` das OLTs |
| `COLETOR_API_TOKEN` | vazio | se definido, a API exige `X-Api-Token` (obrigatório em produção) |
| `COLETOR_HOST` / `COLETOR_PORTA` | `127.0.0.1` / `8090` | onde a API escuta |
| `COLETOR_CORS` | `http://localhost:5174` | origens permitidas, separadas por vírgula |

## Segurança

- Só comandos de leitura (`show ...`) e navegação entre views são enviados.
- A primeira conexão grava a chave SSH da OLT em `dados/known_hosts`; se
  ela mudar depois, a conexão é recusada.
- Credenciais ficam só em `olts.toml`, fora do Git.

## API (resumo)

| Método | Caminho | |
|---|---|---|
| GET | `/api/olts` | lista com resumo (ONUs online, alarmes por gravidade, última coleta) |
| GET | `/api/olts/{id}` | detalhe: status do equipamento, portas PON/SFP, faixas de coleta |
| GET | `/api/olts/{id}/diagnostico` | incidentes priorizados |
| GET | `/api/olts/{id}/alarmes/ativos` | alarmes ativos (queda DGi/LOSi/LOFi agrupada) |
| GET | `/api/olts/{id}/alarmes/historico?horas=&porta=&onu_id=&codigo=` | eventos guardados |
| GET | `/api/olts/{id}/onus?porta=&busca=` | ONUs com sinal, classes e alertas |
| GET | `/api/olts/{id}/onus/{porta}/{onu}` | uma ONU |
| POST | `/api/olts/{id}/onus/{porta}/{onu}/atualizar` | lê a ONU na OLT agora |
| GET | `/api/olts/{id}/onus/{porta}/{onu}/sinais?horas=` | série histórica |
| POST | `/api/olts/{id}/coletar/{alarmes\|sistema\|onus\|rx_olt}?porta=` | força uma coleta |
| GET/PUT | `/api/parametros` | intervalos, faixas, retenção |
