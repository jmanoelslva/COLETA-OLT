import type { ClasseRx, Severidade } from './api'

export const ROTULO_SEV: Record<Severidade, string> = {
  critico: 'Crítico', maior: 'Alto', menor: 'Baixo', info: 'Info',
}

export const ROTULO_CLASSE: Record<ClasseRx, string> = {
  bom: 'Bom', atencao: 'Atenção', critico: 'Crítico', saturado: 'Forte demais', sem_leitura: 'Sem leitura',
}

const dataHora = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
})
const hora = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' })

export function quando(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const hoje = new Date()
  return d.toDateString() === hoje.toDateString() ? `hoje ${hora.format(d)}` : dataHora.format(d)
}

export function ha(iso: string | null | undefined): string {
  if (!iso) return 'nunca'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'agora'
  if (s < 3600) return `há ${Math.round(s / 60)} min`
  if (s < 86400) return `há ${Math.round(s / 3600)} h`
  return `há ${Math.round(s / 86400)} d`
}

export function duracao(seg: number | null | undefined): string {
  if (seg == null) return '—'
  const d = Math.floor(seg / 86400)
  const h = Math.floor((seg % 86400) / 3600)
  const m = Math.floor((seg % 3600) / 60)
  if (d) return `${d} d ${h} h`
  if (h) return `${h} h ${m} min`
  return `${m} min`
}

export function dbm(v: number | null | undefined): string {
  return v == null ? '—' : `${v.toFixed(2)}`
}

export function num(v: number | null | undefined, casas = 0, sufixo = ''): string {
  return v == null ? '—' : `${v.toFixed(casas)}${sufixo}`
}

export type MotivoOffline = 'sinal' | 'energia' | 'ranging' | 'gerencia' | 'outro' | 'sem_registro'

export const ROTULO_MOTIVO: Record<MotivoOffline, string> = {
  sinal: 'sem sinal (LOS)',
  ranging: 'falha de ranging',
  energia: 'sem energia',
  gerencia: 'falha de gerência',
  outro: 'outro motivo',
  sem_registro: 'não subiram desde que a OLT ligou',
}

/** Mesma regra de coletor/analise.py::motivo_offline. */
export function motivoOffline(causa: string | null | undefined): MotivoOffline {
  const c = (causa ?? '').trim().toLowerCase().replace(/ /g, '-')
  if (c === 'dying-gasp') return 'energia'
  if (c === 'los' || c === 'losi') return 'sinal'
  if (c.startsWith('omcc')) return 'gerencia'
  if (c.startsWith('ranging')) return 'ranging'
  if (c === '' || c === '--' || c === 'n/a') return 'sem_registro'
  return 'outro'
}
