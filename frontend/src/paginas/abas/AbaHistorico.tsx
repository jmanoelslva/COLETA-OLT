import { useState } from 'react'
import { api, type DetalheOlt } from '../../api'
import { Estado, Sev, useDados } from '../../componentes/comum'
import { DataAlarme, Local } from './AbaAlarmes'

const PERIODOS = [
  { h: 1, nome: '1 h' }, { h: 6, nome: '6 h' }, { h: 24, nome: '24 h' },
  { h: 24 * 7, nome: '7 dias' }, { h: 24 * 30, nome: '30 dias' }, { h: 24 * 90, nome: '90 dias' },
]

const TIPOS = [
  { id: '', nome: 'Todos os tipos' },
  { id: 'queda', nome: 'Queda de ONU' },
  { id: 'los_pon', nome: 'PON sem sinal' },
  { id: 'tx_onu', nome: 'TX da ONU' },
  { id: 'rx_onu', nome: 'RX da ONU' },
  { id: 'uni_link', nome: 'Porta LAN' },
  { id: 'sfp_incompativel', nome: 'SFP' },
]

export function AbaHistorico({ olt, porta, onuId }: { olt: DetalheOlt | { id: string; portas_pon: number[] }; porta?: number; onuId?: number }) {
  const [horas, setHoras] = useState(24)
  const [fPorta, setFPorta] = useState<number | ''>(porta ?? '')
  const [codigo, setCodigo] = useState('')
  const fixo = onuId != null
  const { dados, erro, carregando, recarregar } = useDados(
    () => api.alarmesHistorico(olt.id, {
      horas, porta: fPorta === '' ? undefined : fPorta, onu_id: onuId, codigo: codigo || undefined,
    }),
    [olt.id, horas, fPorta, codigo, onuId], 60_000,
  )

  return (
    <>
      <div className="filtros">
        <div role="group" aria-label="Período" className="segmentado">
          {PERIODOS.map(p => (
            <button key={p.h} className="chip" aria-pressed={horas === p.h} onClick={() => setHoras(p.h)}>{p.nome}</button>
          ))}
        </div>
        {!fixo && (
          <select aria-label="Porta PON" value={fPorta} onChange={e => setFPorta(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">Todas as PONs</option>
            {olt.portas_pon.map(p => <option key={p} value={p}>PON {p}</option>)}
          </select>
        )}
        <select aria-label="Tipo de alarme" value={codigo} onChange={e => setCodigo(e.target.value)}>
          {TIPOS.map(t => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
      </div>
      <Estado erro={erro} carregando={carregando} vazio={!dados} tentar={recarregar}>
        {dados?.eventos.length === 0 && <p className="vazio">Nenhum evento nesse período.</p>}
        <ol className="linha-tempo">
          {dados?.eventos.map(e => (
            <li key={e.id} className={e.acao === 'normalizou' ? 'normalizou' : ''}>
              <span className="lt-quando"><DataAlarme a={e} /></span>
              <span className="lt-o-que">
                {e.acao === 'normalizou' ? <span className="sev sev-ok">Normalizou</span> : <Sev s={e.severidade} />}
                {e.rotulo}
              </span>
              {!fixo && <span className="lt-onde"><Local a={e} oltId={olt.id} />{e.descricao && <span className="cliente">{e.descricao}</span>}</span>}
            </li>
          ))}
        </ol>
        {dados?.limite_atingido && (
          <p className="sutil">Mostrando os eventos mais recentes. Diminua o período ou filtre para ver os anteriores.</p>
        )}
      </Estado>
    </>
  )
}
