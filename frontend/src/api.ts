export type Severidade = 'critico' | 'maior' | 'menor' | 'info'
export type ClasseRx = 'bom' | 'atencao' | 'critico' | 'saturado' | 'sem_leitura'

export interface Coleta { inicio?: string; fim?: string; ok?: number; erro?: string | null; ultimo_ok: string | null }

export interface StatusOlt {
  coletado_em: string
  cpu: number | null; load1: number | null; load5: number | null; load15: number | null
  mem_total_mb: number | null; mem_livre_mb: number | null; mem_uso: number | null
  temp_placa: number | null; uptime_s: number | null; boot_em: string | null
  relogio_olt: string | null; desvio_relogio_s: number | null
  ventoinhas: { id: number; status: string; rpm: number | null }[] | null
  fontes: { slot: number; status: string }[] | null
  firmware: { bancos: Record<string, Record<string, string>>; boot: string | null } | null
  versao: { hardware: string | null; firmware: string | null; web: string | null } | null
}

export interface ResumoOlt {
  id: string; nome: string; modelo: string; host: string; hostname: string | null
  portas_pon: number[]; ativa: number
  fabricante: string; fabricante_nome: string; coleta_suportada: boolean
  status: StatusOlt | null
  alarmes_ativos: Partial<Record<Severidade, number>>
  onus: { total: number; online: number }
  offline_por_motivo?: Partial<Record<'energia' | 'sinal' | 'ranging' | 'gerencia' | 'sem_registro' | 'outro', number>>
  portas?: { porta: number; total: number; online: number; los: number; link: string | null }[]
  coletas: Record<string, Coleta>
}

export interface Sfp {
  coletado_em: string; temp: number | null; tensao: number | null; bias: number | null
  tx: number | null; rx: number | null; vendor: string | null; produto: string | null; serial: string | null
  admin?: string | null; link?: string | null
}

export interface Faixa {
  faixa: 'rapida' | 'lenta'; conectada: boolean
  em_execucao: { tipo: string; inicio: string; origem: string } | null
  proxima_em_s: Record<string, number>; fila: number
}

export interface DetalheOlt extends Omit<ResumoOlt, 'alarmes_ativos' | 'onus' | 'portas' | 'offline_por_motivo'> {
  portas: { porta: number; sfp: Sfp | null; onus_total: number; onus_online: number }[]
  faixas: Faixa[]
}

export interface Alarme {
  chave?: string; id?: number
  data_olt: string; data_utc: string | null; data_estimada: number
  porta: number | null; onu_id: number | null; uni: string | null
  mensagem: string; codigo: string; severidade: Severidade; rotulo: string
  acao?: 'alarme' | 'normalizou'
  descricao?: string | null; sn?: string | null
  primeiro_visto?: string
  codigos?: string[]; agrupado?: boolean
}

export interface Onu {
  olt_id: string; porta: number; onu_id: number; sn: string | null; descricao: string | null
  control_flag: string | null; run_state: string | null; config_state: string | null; match_state: string | null
  last_down_cause: string | null; distancia_m: number | null
  last_up: string | null; last_down: string | null; last_dying_gasp: string | null; online_seg: number | null
  line_profile: string | null; service_profile: string | null; detalhe_em: string | null; visto_em: string
  modelo_onu?: string | null; versao_onu?: string | null
  rx: number | null; tx: number | null; temp: number | null; tensao: number | null; bias: number | null
  sinal_em: string | null; rx_olt: number | null; rx_olt_em: string | null
  rx_media_7d: number | null; eventos_1h: number; sfp_tx: number | null
  online: boolean; classe_rx: ClasseRx; classe_rx_olt: ClasseRx
  delta_7d: number | null; degradada: boolean; oscilando: boolean; atenuacao_db: number | null
  alertas: string[]; gravidade: number
}

export interface Incidente {
  severidade: Severidade; categoria: string; titulo: string; texto: string
  porta?: number; onus?: number[]; descricao?: string | null
}

export type Parametros = Record<string, number>

export interface Limites {
  rx_onu_saturado: number; rx_onu_atencao: number; rx_onu_critico: number
  rx_olt_saturado: number; rx_olt_atencao: number; rx_olt_critico: number
}

export interface CadastroOlt {
  id: string; nome: string; fabricante: string; modelo: string; host: string; porta_ssh: number
  usuario: string; frame_slot: string; portas_pon: number[]; ativa: number | boolean
  tem_senha?: boolean; tem_senha_enable?: boolean
  senha?: string; senha_enable?: string
}

export interface Fabricante { nome: string; coleta: boolean; modelo_padrao: string }

export interface ResultadoTeste {
  ok: boolean; erro?: string; hostname?: string | null; firmware?: string | null
  relogio_olt?: string | null; tempo_ms?: number; aviso?: string
}

export class ErroApi extends Error {
  constructor(public status: number, mensagem: string, public campos?: Record<string, string>) {
    super(mensagem)
  }
}

// "/" no domínio próprio; "/olt/" quando publicado dentro do app técnico.
export const BASE = import.meta.env.BASE_URL
export const DENTRO_DO_TECNICO = BASE !== '/'

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(`${BASE}api${caminho}`, {
      ...init,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ErroApi(0, 'Sem conexão com o coletor. Confira a rede e tente de novo.')
  }
  if (!r.ok) {
    let msg = `Erro ${r.status}`
    let campos: Record<string, string> | undefined
    try {
      const corpo = await r.json()
      // Sem sessão do app técnico: vai para o login dele e volta para cá depois.
      if (r.status === 401 && typeof corpo.login === 'string') {
        const voltar = window.location.pathname + window.location.search
        window.location.assign(`${corpo.login}?voltar=${encodeURIComponent(voltar)}`)
      }
      if (typeof corpo.detail === 'string') msg = corpo.detail
      else if (corpo.detail && typeof corpo.detail === 'object' && !Array.isArray(corpo.detail)) {
        campos = corpo.detail
        msg = 'Confira os campos destacados.'
      } else msg = JSON.stringify(corpo.detail)
    } catch { /* corpo não é JSON */ }
    throw new ErroApi(r.status, msg, campos)
  }
  return r.json() as Promise<T>
}

export type EstadoAdmin = { configurado: boolean; logado: boolean; usuario: string | null }

export const api = {
  admin: () => pedir<EstadoAdmin>('/admin'),
  entrarAdmin: (usuario: string, senha: string) =>
    pedir<EstadoAdmin>('/admin/entrar', { method: 'POST', body: JSON.stringify({ usuario, senha }) }),
  sairAdmin: () => pedir<EstadoAdmin>('/admin/sair', { method: 'POST' }),
  trocarSenhaAdmin: (d: { usuario: string; senha_atual: string; nova_senha: string }) =>
    pedir<EstadoAdmin>('/admin/senha', { method: 'PUT', body: JSON.stringify(d) }),
  olts: () => pedir<ResumoOlt[]>('/olts'),
  olt: (id: string) => pedir<DetalheOlt>(`/olts/${id}`),
  statusHistorico: (id: string, horas = 24) =>
    pedir<{ coletado_em: string; cpu: number | null; mem_uso: number | null; temp_placa: number | null }[]>(
      `/olts/${id}/status/historico?horas=${horas}`),
  diagnostico: (id: string) => pedir<Incidente[]>(`/olts/${id}/diagnostico`),
  alarmesAtivos: (id: string) => pedir<Alarme[]>(`/olts/${id}/alarmes/ativos`),
  alarmesHistorico: (id: string, q: Record<string, string | number | undefined>) => {
    const p = new URLSearchParams()
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)))
    return pedir<{ eventos: Alarme[]; contagem: { codigo: string; acao: string; n: number }[]; limite_atingido: boolean }>(
      `/olts/${id}/alarmes/historico?${p}`)
  },
  onus: (id: string, porta?: number) => pedir<Onu[]>(`/olts/${id}/onus${porta ? `?porta=${porta}` : ''}`),
  onu: (id: string, porta: number, onu: number) => pedir<Onu>(`/olts/${id}/onus/${porta}/${onu}`),
  atualizarOnu: (id: string, porta: number, onu: number) =>
    pedir<Onu>(`/olts/${id}/onus/${porta}/${onu}/atualizar`, { method: 'POST' }),
  sinais: (id: string, porta: number, onu: number, horas: number) =>
    pedir<{ onu: { coletado_em: string; rx: number | null; tx: number | null; temp: number | null }[];
            olt: { coletado_em: string; rx_olt: number | null }[]; limites: Limites }>(
      `/olts/${id}/onus/${porta}/${onu}/sinais?horas=${horas}`),
  coletar: (id: string, tipo: string, porta?: number) =>
    pedir<Record<string, unknown>>(`/olts/${id}/coletar/${tipo}${porta ? `?porta=${porta}` : ''}`, { method: 'POST' }),
  fabricantes: () => pedir<Record<string, Fabricante>>('/fabricantes'),
  cadastro: (id: string) => pedir<CadastroOlt>(`/olts/${id}/cadastro`),
  criarOlt: (d: CadastroOlt) => pedir<CadastroOlt>('/olts', { method: 'POST', body: JSON.stringify(d) }),
  editarOlt: (d: CadastroOlt) => pedir<CadastroOlt>(`/olts/${d.id}`, { method: 'PUT', body: JSON.stringify(d) }),
  excluirOlt: (id: string, apagarHistorico: boolean) =>
    pedir<unknown>(`/olts/${id}?apagar_historico=${apagarHistorico}`, { method: 'DELETE' }),
  testarOlt: (d: Partial<CadastroOlt>) => pedir<ResultadoTeste>('/olts/testar', { method: 'POST', body: JSON.stringify(d) }),
  parametros: () => pedir<{ valores: Parametros; padrao: Parametros }>('/parametros'),
  acesso: () => pedir<{ ip: string | null; local: boolean; liberado: boolean; usuario: string | null }>('/acesso'),
  salvarAcl: (ips: string[]) =>
    pedir<{ valores: Parametros; padrao: Parametros }>('/parametros', { method: 'PUT', body: JSON.stringify({ acl_ips: ips }) }),
  salvarParametros: (v: Parametros) =>
    pedir<{ valores: Parametros; padrao: Parametros }>('/parametros', { method: 'PUT', body: JSON.stringify(v) }),
}
