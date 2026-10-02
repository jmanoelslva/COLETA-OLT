import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Alarme, type DetalheOlt, type Severidade } from '../../api'
import { Estado, Sev, useDados } from '../../componentes/comum'
import { ROTULO_SEV, quando } from '../../formatos'

export function Local({ a, oltId }: { a: Alarme; oltId: string }) {
  if (a.porta == null) return <span>OLT</span>
  if (a.onu_id == null) return <span>PON {a.porta}</span>
  return (
    <Link to={`/olt/${oltId}/onu/${a.porta}/${a.onu_id}`}>
      ONU {a.porta}/{a.onu_id}{a.uni ? `, LAN ${a.uni.split('/')[1]}` : ''}
    </Link>
  )
}

export function DataAlarme({ a }: { a: Alarme }) {
  if (!a.data_utc) {
    return <span className="sutil" title={`A OLT registrou ${a.data_olt}, mas estava sem relógio`}>data desconhecida</span>
  }
  return (
    <time dateTime={a.data_utc} title={a.data_estimada ? `A OLT registrou ${a.data_olt} (estava sem relógio)` : undefined}>
      {quando(a.data_utc)}{a.data_estimada ? <span className="sutil"> estimada</span> : null}
    </time>
  )
}

export function AbaAlarmes({ olt }: { olt: DetalheOlt }) {
  const { dados, erro, carregando, recarregar } = useDados(() => api.alarmesAtivos(olt.id), [olt.id], 30_000)
  const [sev, setSev] = useState<Severidade | ''>('')
  const contagem = (s: Severidade) => dados?.filter(a => a.severidade === s).length ?? 0
  const lista = dados?.filter(a => !sev || a.severidade === sev) ?? []

  return (
    <Estado erro={erro} carregando={carregando} vazio={!dados} tentar={recarregar}>
      <div className="filtros" role="group" aria-label="Filtrar por gravidade">
        <button className="chip" aria-pressed={sev === ''} onClick={() => setSev('')}>Todos {dados?.length}</button>
        {(['critico', 'maior', 'menor', 'info'] as Severidade[]).map(s => contagem(s) > 0 && (
          <button key={s} className={`chip chip-${s}`} aria-pressed={sev === s} onClick={() => setSev(s)}>
            {ROTULO_SEV[s]} {contagem(s)}
          </button>
        ))}
      </div>
      {lista.length === 0 && <p className="vazio">Nenhum alarme ativo{sev ? ' com essa gravidade' : ''}.</p>}
      <table className="tabela">
        <thead>
          <tr><th>Gravidade</th><th>Alarme</th><th>Onde</th><th>Desde</th></tr>
        </thead>
        <tbody>
          {lista.map(a => (
            <tr key={String(a.id ?? a.chave)}>
              <td><Sev s={a.severidade} /></td>
              <td>
                {a.rotulo}
                {a.descricao && <span className="cliente">{a.descricao}</span>}
              </td>
              <td><Local a={a} oltId={olt.id} /></td>
              <td><DataAlarme a={a} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Estado>
  )
}
