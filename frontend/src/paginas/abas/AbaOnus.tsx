import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type DetalheOlt, type Onu } from '../../api'
import { Estado, useDados } from '../../componentes/comum'
import { Regua } from '../../componentes/Regua'
import { ROTULO_CLASSE, ROTULO_MOTIVO, dbm, motivoOffline, type MotivoOffline } from '../../formatos'
import { useParametros } from '../../parametros'

type Filtro = 'todas' | 'problemas' | 'offline'

export function AbaOnus({ olt }: { olt: DetalheOlt }) {
  const [busca, setBusca] = useSearchParams()
  // Porta é o filtro principal: abre na primeira PON. "todas" = OLT inteira.
  const portaParam = busca.get('porta')
  const porta = portaParam === 'todas' ? undefined : Number(portaParam) || olt.portas_pon[0]
  const filtro = (busca.get('mostrar') as Filtro | null) ?? 'todas'
  // Vindo da tela inicial ("Offline por motivo"): só as offline daquele motivo.
  const motivo = filtro === 'offline' ? (busca.get('motivo') as MotivoOffline | null) : null
  const [texto, setTexto] = useState('')
  // Buscando cliente/serial: procura na OLT inteira, não só na porta aberta.
  const buscandoTudo = texto.trim().length >= 2
  const { limites } = useParametros()
  const alvo = buscandoTudo ? undefined : porta
  const { dados, erro, carregando, recarregar } = useDados(() => api.onus(olt.id, alvo), [olt.id, alvo], 60_000)

  const mudar = (chave: string, valor: string | null) => {
    const n = new URLSearchParams(busca)
    if (valor === null) n.delete(chave); else n.set(chave, valor)
    setBusca(n, { replace: true })
  }

  const temProblema = (o: Onu) => o.gravidade >= 2 || (!o.online && /^losi?$/i.test(o.last_down_cause ?? ''))
  const passa = (o: Onu, f: Filtro) => f === 'todas' || (f === 'offline' ? !o.online : temProblema(o))

  const lista = useMemo(() => {
    const t = texto.trim().toLowerCase()
    return (dados ?? [])
      .filter(o => !buscandoTudo || (o.sn ?? '').toLowerCase().includes(t) || (o.descricao ?? '').toLowerCase().includes(t)
        || `${o.porta}/${o.onu_id}` === t)
      .filter(o => passa(o, filtro))
      .filter(o => !motivo || motivoOffline(o.last_down_cause) === motivo)
      .sort((a, b) => filtro === 'problemas'
        ? b.gravidade - a.gravidade || (a.rx ?? 0) - (b.rx ?? 0)
        : a.porta - b.porta || a.onu_id - b.onu_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dados, texto, filtro, buscandoTudo, motivo])

  const contar = (f: Filtro) => (dados ?? []).filter(o => passa(o, f)).length

  return (
    <>
      <div className="filtros">
        <div className="segmentado" role="group" aria-label="Porta PON">
          {olt.portas.map(p => (
            <button key={p.porta} className="chip" aria-pressed={!buscandoTudo && porta === p.porta}
              onClick={() => mudar('porta', String(p.porta))}>
              PON {p.porta} <small>{p.onus_online}/{p.onus_total}</small>
            </button>
          ))}
          <button className="chip" aria-pressed={!buscandoTudo && porta === undefined} onClick={() => mudar('porta', 'todas')}>
            Todas as PONs
          </button>
        </div>
      </div>
      <div className="filtros">
        <input type="search" placeholder="Buscar cliente ou serial na OLT inteira" value={texto}
          onChange={e => setTexto(e.target.value)} aria-label="Buscar ONU" />
        <div className="segmentado" role="group" aria-label="Mostrar">
          {(['todas', 'problemas', 'offline'] as Filtro[]).map(f => (
            <button key={f} className="chip" aria-pressed={filtro === f} onClick={() => { const n = new URLSearchParams(busca); if (f === 'todas') n.delete('mostrar'); else n.set('mostrar', f); n.delete('motivo'); setBusca(n, { replace: true }) }}>
              {f === 'problemas' ? 'Com problema' : f === 'offline' ? 'Offline' : 'Todas'} {dados && contar(f)}
            </button>
          ))}
        </div>
      </div>
      {motivo && (
        <p className="filtro-motivo">
          <span>Só as offline com motivo <strong>{ROTULO_MOTIVO[motivo] ?? motivo}</strong> ({lista.length})</span>
          <button className="chip" onClick={() => mudar('motivo', null)}>Ver todas as offline</button>
        </p>
      )}
      <p className="legenda-regua sutil">
        {buscandoTudo && <span>Resultado da busca em todas as PONs.</span>}
        <span className="marca-desc">▼</span> RX ONU, sinal que chega na ONU
        <span className="marca-sub">▲</span> RX OLT, sinal da ONU que chega na OLT
      </p>
      <Estado erro={erro} carregando={carregando} vazio={!dados} tentar={recarregar}>
        {lista.length === 0 && (
          <p className="vazio">
            {buscandoTudo ? 'Nenhuma ONU com esse cliente ou serial.'
              : filtro === 'problemas' ? 'Nenhuma ONU com problema nesta porta.'
              : filtro === 'offline' ? 'Nenhuma ONU offline nesta porta.' : 'Nenhuma ONU nesta porta.'}
          </p>
        )}
        <ul className="lista-onus">
          {lista.map(o => <LinhaOnu key={`${o.porta}/${o.onu_id}`} o={o} oltId={olt.id} limites={limites} />)}
        </ul>
      </Estado>
    </>
  )
}
function LinhaOnu({ o, oltId, limites }: { o: Onu; oltId: string; limites: ReturnType<typeof useParametros>['limites'] }) {
  return (
    <li>
      <Link to={`/olt/${oltId}/onu/${o.porta}/${o.onu_id}`} className={`onu-linha grav-${o.gravidade}`}>
        <span className="onu-id">{o.porta}/{o.onu_id}</span>
        <span className="onu-quem">
          <strong>{o.descricao ?? o.sn ?? 'Sem descrição'}</strong>
          <span className="sutil">{o.descricao ? o.sn : ''}</span>
        </span>
        {o.online ? (
          <span className="onu-sinal">
            <Regua rx={o.rx} rxOlt={o.rx_olt} limites={limites} />
            <span className="onu-valores">
              <span className={`v-${o.classe_rx}`} title={ROTULO_CLASSE[o.classe_rx]}>▼ {dbm(o.rx)}</span>
              <span className={`v-${o.classe_rx_olt}`} title={ROTULO_CLASSE[o.classe_rx_olt]}>▲ {dbm(o.rx_olt)}</span>
            </span>
          </span>
        ) : (
          <span className="onu-off">Offline{o.last_down_cause ? `: ${o.last_down_cause}` : ''}</span>
        )}
        {o.alertas.length > 0 && <span className="onu-alerta">{o.alertas[0]}{o.alertas.length > 1 ? ` (+${o.alertas.length - 1})` : ''}</span>}
      </Link>
    </li>
  )
}
