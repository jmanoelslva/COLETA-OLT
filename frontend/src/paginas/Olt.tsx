import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useAdmin } from '../admin'
import { api, type DetalheOlt } from '../api'
import { Estado, useDados } from '../componentes/comum'
import { duracao, ha, quando } from '../formatos'
import { AbaAlarmes } from './abas/AbaAlarmes'
import { AbaDiagnostico } from './abas/AbaDiagnostico'
import { AbaEquipamento } from './abas/AbaEquipamento'
import { AbaHistorico } from './abas/AbaHistorico'
import { AbaOnus } from './abas/AbaOnus'
import { Voltar } from '../componentes/Voltar'

const ABAS = [
  { id: 'diagnostico', nome: 'Diagnóstico' },
  { id: 'alarmes', nome: 'Alarmes ativos' },
  { id: 'historico', nome: 'Histórico' },
  { id: 'onus', nome: 'ONUs' },
  { id: 'equipamento', nome: 'Equipamento' },
] as const

export function Olt() {
  const { id = '' } = useParams()
  const [busca, setBusca] = useSearchParams()
  const aba = busca.get('aba') ?? 'diagnostico'
  const { dados: olt, erro, carregando, recarregar } = useDados(() => api.olt(id), [id], 20_000)
  const { admin } = useAdmin()

  const trocar = (a: string) => {
    const n = new URLSearchParams(busca)
    n.set('aba', a)
    setBusca(n, { replace: true })
  }

  return (
    <main className="pagina">
      <header className="topo">
        <Voltar para="/" rotulo="OLTs" />
        <div className="topo-acoes">
          <h1>{olt?.nome ?? id}</h1>
          {admin && <Link to={`/olt/${id}/editar`} className="botao-sec">Editar cadastro</Link>}
        </div>
        {olt && <Resumo olt={olt} />}
      </header>
      <Estado erro={erro} carregando={carregando} vazio={!olt} tentar={recarregar}>
        {olt && !olt.coleta_suportada && (
          <p className="vazio">A coleta de {olt.fabricante_nome} ainda não está disponível. O cadastro está salvo e o acesso pode ser testado em Editar cadastro.</p>
        )}
        {olt && olt.coleta_suportada && (
          <>
            <ColetarAgora olt={olt} aoTerminar={recarregar} />
            <nav className="abas" role="tablist" aria-label="Seções da OLT">
              {ABAS.map(a => (
                <button key={a.id} role="tab" aria-selected={aba === a.id} className="aba" onClick={() => trocar(a.id)}>
                  {a.nome}
                </button>
              ))}
            </nav>
            <section role="tabpanel" className="painel">
              {aba === 'diagnostico' && <AbaDiagnostico olt={olt} />}
              {aba === 'alarmes' && <AbaAlarmes olt={olt} />}
              {aba === 'historico' && <AbaHistorico olt={olt} />}
              {aba === 'onus' && <AbaOnus olt={olt} />}
              {aba === 'equipamento' && <AbaEquipamento olt={olt} />}
            </section>
          </>
        )}
      </Estado>
    </main>
  )
}

function Resumo({ olt }: { olt: DetalheOlt }) {
  const s = olt.status
  const ok = olt.coletas.alarmes?.ultimo_ok
  return (
    <p className="sutil">
      {olt.hostname ?? olt.host}
      {s && <>, ligada há {duracao(s.uptime_s)}</>}
      {s?.temp_placa != null && <>, {s.temp_placa.toFixed(0)} °C</>}
      <br />
      Alarmes lidos {ha(ok)}
    </p>
  )
}

const TIPOS = [
  { id: 'alarmes', nome: 'Alarmes', dica: 'alguns segundos' },
  { id: 'onus', nome: 'ONUs e RX ONU', dica: '~1 min' },
  { id: 'rx_olt', nome: 'RX OLT', dica: 'entra na fila aos poucos' },
  { id: 'sistema', nome: 'Equipamento', dica: 'alguns segundos' },
]

function ColetarAgora({ olt, aoTerminar }: { olt: DetalheOlt; aoTerminar: () => void }) {
  const [aberto, setAberto] = useState(false)
  const [tipo, setTipo] = useState('alarmes')
  const [porta, setPorta] = useState<number | ''>('')
  const [rodando, setRodando] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)

  const emExecucao = olt.faixas.map(f => f.em_execucao).filter(Boolean)

  const coletar = async () => {
    setRodando(true)
    setMsg(null)
    try {
      const r = await api.coletar(olt.id, tipo, porta === '' ? undefined : porta)
      setMsg({ ok: true, texto: typeof r.aviso === 'string' ? r.aviso : 'Coleta concluída.' })
      aoTerminar()
    } catch (e) {
      setMsg({ ok: false, texto: e instanceof Error ? e.message : String(e) })
    } finally {
      setRodando(false)
    }
  }

  return (
    <div className="coletar">
      <button className="botao-sec" aria-expanded={aberto} onClick={() => setAberto(a => !a)}>
        Coletar agora
      </button>
      {emExecucao.length > 0 && (
        <span className="sutil coletando">
          Coletando {emExecucao.map(e => e!.tipo).join(' e ')} desde {quando(emExecucao[0]!.inicio)}
        </span>
      )}
      {aberto && (
        <div className="coletar-form">
          <fieldset>
            <legend>O que coletar</legend>
            {TIPOS.filter(t => t.id !== 'rx_olt' || olt.coleta_rx_olt).map(t => (
              <label key={t.id} className="opcao">
                <input type="radio" name="tipo" value={t.id} checked={tipo === t.id} onChange={() => setTipo(t.id)} />
                {t.nome} <span className="sutil">{t.dica}</span>
              </label>
            ))}
          </fieldset>
          {(tipo === 'onus' || tipo === 'rx_olt') && (
            <label className="campo">
              Porta PON
              <select value={porta} onChange={e => setPorta(e.target.value === '' ? '' : Number(e.target.value))}>
                <option value="">Todas</option>
                {olt.portas_pon.map(p => <option key={p} value={p}>PON {p}</option>)}
              </select>
            </label>
          )}
          <button className="botao" onClick={coletar} disabled={rodando}>
            {rodando ? 'Coletando…' : 'Coletar'}
          </button>
          {msg && <p className={msg.ok ? 'ok' : 'aviso-erro'} role="status">{msg.texto}</p>}
        </div>
      )}
    </div>
  )
}
