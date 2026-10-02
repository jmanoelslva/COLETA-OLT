import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Incidente, type ResumoOlt } from '../api'
import { Estado, Sev, useDados } from '../componentes/comum'
import { duracao, ha, num } from '../formatos'

type Saude = 'ok' | 'atencao' | 'critico' | 'sem_dados' | 'pausada'

const ROTULO_SAUDE: Record<Saude, string> = {
  ok: 'Operando normal',
  atencao: 'Requer atenção',
  critico: 'Problema crítico',
  sem_dados: 'Sem coleta recente',
  pausada: 'Coleta pausada',
}

function saudeDa(o: ResumoOlt, inc: Incidente[] | undefined): Saude {
  if (!o.coleta_suportada || !o.ativa) return 'pausada'
  const falhou = Object.values(o.coletas).some(c => c.ok === 0)
  const nunca = !Object.values(o.coletas).some(c => c.ultimo_ok)
  if (nunca || (falhou && !o.status)) return 'sem_dados'
  const portas = o.portas ?? []
  if (portas.some(p => p.link === 'down') || inc?.some(i => i.severidade === 'critico')) return 'critico'
  if (portas.some(p => p.los > 0) || falhou || inc?.some(i => i.severidade === 'maior')) return 'atencao'
  return 'ok'
}

export function Olts() {
  const { dados, erro, carregando, recarregar } = useDados(api.olts, [], 30_000)
  const incidentes = useIncidentes(dados)

  return (
    <main className="pagina inicio">
      <header className="topo topo-acoes">
        <h1>Rede</h1>
        <Link to="/olts/nova" className="botao-sec">Cadastrar OLT</Link>
      </header>
      <Estado erro={erro} carregando={carregando} vazio={!dados} tentar={recarregar}>
        {dados?.length === 0 && (
          <p className="vazio">Nenhuma OLT cadastrada ainda. Use Cadastrar OLT para incluir a primeira.</p>
        )}
        {dados && dados.length > 0 && (
          <>
            <ResumoRede olts={dados} />
            <Atencao olts={dados} incidentes={incidentes} />
            <h2 className="titulo-olts">OLTs</h2>
            <ul className="cartoes-olt">
              {dados.map(o => <CartaoOlt key={o.id} o={o} saude={saudeDa(o, incidentes[o.id])} />)}
            </ul>
          </>
        )}
      </Estado>
    </main>
  )
}

/** Diagnóstico de cada OLT (atualiza junto com a lista). */
function useIncidentes(olts: ResumoOlt[] | null) {
  const [porOlt, setPorOlt] = useState<Record<string, Incidente[]>>({})
  const chave = olts?.map(o => `${o.id}:${Object.values(o.coletas).map(c => c.ultimo_ok).join()}`).join('|')
  useEffect(() => {
    if (!olts) return
    let vivo = true
    Promise.all(olts.filter(o => o.coleta_suportada).map(o =>
      api.diagnostico(o.id).then(d => [o.id, d] as const).catch(() => [o.id, [] as Incidente[]] as const),
    )).then(res => vivo && setPorOlt(Object.fromEntries(res)))
    return () => { vivo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave])
  return porOlt
}

function ResumoRede({ olts }: { olts: ResumoOlt[] }) {
  const total = olts.reduce((s, o) => s + o.onus.total, 0)
  const online = olts.reduce((s, o) => s + o.onus.online, 0)
  const los = olts.reduce((s, o) => s + (o.offline_por_motivo?.sinal ?? 0), 0)
  const criticos = olts.reduce((s, o) => s + (o.alarmes_ativos.critico ?? 0), 0)
  const pct = total ? (online / total) * 100 : 0
  return (
    <section className="resumo-rede" aria-label="Resumo da rede">
      <div className="rr-principal">
        <span className="rr-rotulo">ONUs online</span>
        <span className="rr-valor">{online}<small>/{total}</small></span>
        <span className="rr-barra" aria-hidden="true"><i style={{ width: `${pct}%` }} /></span>
        <span className="rr-nota">{pct.toFixed(1)}% da base em {olts.length} {olts.length === 1 ? 'OLT' : 'OLTs'}</span>
      </div>
      <dl className="rr-numeros">
        <div className={total - online ? 'atento' : ''}><dt>Offline</dt><dd>{total - online}</dd></div>
        <div className={los ? 'ruim' : ''}><dt>Sem sinal (LOS)</dt><dd>{los}</dd></div>
        <div className={criticos ? 'ruim' : ''}><dt>Alarmes críticos</dt><dd>{criticos}</dd></div>
      </dl>
    </section>
  )
}

// Problemas de uma ONU só ficam fora da lista da tela inicial (viram um resumo por OLT).
const POR_ONU = new Set(['onu_critica', 'onu_oscilando', 'sn_duplicado'])

function Atencao({ olts, incidentes }: { olts: ResumoOlt[]; incidentes: Record<string, Incidente[]> }) {
  if (!Object.keys(incidentes).length) return null
  const nome = Object.fromEntries(olts.map(o => [o.id, o.nome]))
  const peso = (s: string) => (s === 'critico' ? 0 : 1)
  const infra = Object.entries(incidentes)
    .flatMap(([id, lista]) => lista
      .filter(i => (i.severidade === 'critico' || i.severidade === 'maior') && !POR_ONU.has(i.categoria))
      .map(i => ({ id, i })))
    .sort((a, b) => peso(a.i.severidade) - peso(b.i.severidade))
  const porOnu = Object.entries(incidentes)
    .map(([id, lista]) => ({
      id,
      criticas: lista.filter(i => i.categoria === 'onu_critica').length,
      oscilando: lista.filter(i => i.categoria === 'onu_oscilando').length,
    }))
    .filter(x => x.criticas || x.oscilando)

  return (
    <section className="atencao" aria-labelledby="titulo-atencao">
      <h2 id="titulo-atencao">Precisa de atenção agora</h2>
      {infra.length === 0 ? (
        <p className="atencao-vazia">Nenhum problema de porta PON ou de OLT agora.</p>
      ) : (
        <ul>
          {infra.slice(0, 6).map(({ id, i }, n) => (
            <li key={n}>
              <Link to={destino(id, i)} className={`atencao-item borda-${i.severidade}`}>
                <Sev s={i.severidade} />
                <span className="atencao-texto">
                  <strong>{i.titulo}</strong>
                  <span className="sutil">{nome[id]}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {infra.length > 6 && <p className="sutil atencao-mais">E mais {infra.length - 6}, no diagnóstico de cada OLT.</p>}
      {porOnu.length > 0 && (
        <p className="atencao-onus">
          <span className="sutil">ONUs individuais:</span>
          {porOnu.map(x => (
            <Link key={x.id} to={`/olt/${x.id}?aba=onus&porta=todas&mostrar=problemas`}>
              {nome[x.id]}: {[x.criticas && `${x.criticas} com sinal crítico`, x.oscilando && `${x.oscilando} oscilando`]
                .filter(Boolean).join(', ')}
            </Link>
          ))}
        </p>
      )}
    </section>
  )
}
function destino(oltId: string, i: Incidente): string {
  if (i.onus?.length === 1 && i.porta != null) return `/olt/${oltId}/onu/${i.porta}/${i.onus[0]}`
  if (i.porta != null) return `/olt/${oltId}?aba=onus&porta=${i.porta}`
  return `/olt/${oltId}`
}

const MOTIVOS: { chave: 'sinal' | 'energia' | 'ranging' | 'gerencia' | 'outro' | 'sem_registro'; nome: string; classe: string }[] = [
  { chave: 'sinal', nome: 'sem sinal (LOS)', classe: 'ruim' },
  { chave: 'ranging', nome: 'falha de ranging', classe: 'atento' },
  { chave: 'energia', nome: 'sem energia', classe: '' },
  { chave: 'gerencia', nome: 'falha de gerência', classe: 'atento' },
  { chave: 'outro', nome: 'outro motivo', classe: '' },
  { chave: 'sem_registro', nome: 'não subiram desde que a OLT ligou', classe: 'sutil' },
]

const NOME_COLETA: Record<string, string> = { alarmes: 'alarmes', sistema: 'equipamento', onus: 'ONUs', rx_olt: 'sinal na OLT' }

function CartaoOlt({ o, saude }: { o: ResumoOlt; saude: Saude }) {
  const offline = o.onus.total - o.onus.online
  const crit = o.alarmes_ativos.critico ?? 0
  const alto = o.alarmes_ativos.maior ?? 0
  const falhas = Object.entries(o.coletas).filter(([, c]) => c.ok === 0)
  const ultima = Object.values(o.coletas).map(c => c.ultimo_ok).filter(Boolean).sort().pop()
  const m = o.offline_por_motivo ?? {}
  const motivos = MOTIVOS.filter(x => (m[x.chave] ?? 0) > 0)

  return (
    <li className={`cartao-olt saude-${saude}`}>
      <div className="co-cabeca">
        <Link to={`/olt/${o.id}`} className="co-nome">
          <strong>{o.nome}</strong>
          <span className="sutil">
            {o.modelo || o.fabricante_nome}
            {o.status?.uptime_s != null && <>, ligada há {duracao(o.status.uptime_s)}</>}
          </span>
        </Link>
        <span className={`co-saude saude-${saude}`}>{ROTULO_SAUDE[saude]}</span>
      </div>

      {saude === 'pausada' ? (
        <p className="sutil co-pausada">
          {!o.coleta_suportada ? `Coleta de ${o.fabricante_nome} ainda não disponível.` : 'Coleta desativada no cadastro.'}
        </p>
      ) : (
        <>
          <dl className="co-numeros">
            <div><dt>Online</dt><dd>{o.onus.online}<small>/{o.onus.total}</small></dd></div>
            <div className={offline ? 'atento' : ''}><dt>Offline</dt><dd>{offline}</dd></div>
            <div className={crit ? 'ruim' : alto ? 'atento' : ''}>
              <dt>Alarmes</dt><dd>{crit}<small> críticos{alto ? `, ${alto} altos` : ''}</small></dd>
            </div>
            <div><dt>Temperatura</dt><dd>{num(o.status?.temp_placa, 0, ' °C')}</dd></div>
            <div><dt>CPU</dt><dd>{num(o.status?.cpu, 0, '%')}</dd></div>
          </dl>

          {o.portas && o.portas.length > 0 && <FileiraPons o={o} />}

          {offline > 0 && motivos.length > 0 && (
            <div className="olt-motivos">
              <span className="motivos-rotulo">Offline por motivo</span>
              <ul>
                {motivos.map(x => (
                  <li key={x.chave}>
                    <Link to={`/olt/${o.id}?aba=onus&porta=todas&mostrar=offline&motivo=${x.chave}`}
                      className={`motivo motivo-${x.chave}`}>
                      <b>{m[x.chave]}</b>{x.nome}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="co-rodape">
        <span className={falhas.length ? 'ruim' : 'sutil'}>
          {falhas.length
            ? `Falha na última coleta de ${falhas.map(([t]) => NOME_COLETA[t] ?? t).join(', ')}`
            : `Atualizada ${ha(ultima)}`}
        </span>
        <span className="co-links">
          <Link to={`/olt/${o.id}?aba=alarmes`} className="atalho atalho-alarmes">Alarmes</Link>
          <Link to={`/olt/${o.id}?aba=onus`} className="atalho atalho-onus">ONUs</Link>
          <Link to={`/olt/${o.id}?aba=equipamento`} className="atalho atalho-equip">Equipamento</Link>
        </span>
      </div>
    </li>
  )
}

/** As portas PON como no painel da OLT: cor = estado, número = online/total. */
function FileiraPons({ o }: { o: ResumoOlt }) {
  return (
    <ol className="fileira-pons" aria-label="Portas PON">
      {o.portas!.map(p => {
        const estado = p.total === 0 ? 'vazia' : p.link === 'down' ? 'sem-link' : p.los > 0 ? 'com-los' : 'ok'
        const dica = p.total === 0 ? 'sem ONUs cadastradas'
          : p.link === 'down' ? 'sem link'
          : `${p.online} de ${p.total} online${p.los ? `, ${p.los} em LOS` : ''}`
        return (
          <li key={p.porta}>
            <Link to={`/olt/${o.id}?aba=onus&porta=${p.porta}`} className={`pon pon-${estado}`}
              title={`PON ${p.porta}: ${dica}`} aria-label={`PON ${p.porta}: ${dica}`}>
              <span className="pon-num">PON {p.porta}</span>
              <span className="pon-qtd">{p.total ? `${p.online}/${p.total}` : '—'}</span>
              {p.link === 'down'
                ? <span className="pon-los">sem link</span>
                : p.los > 0 && <span className="pon-los">{p.los} LOS</span>}
            </Link>
          </li>
        )
      })}
    </ol>
  )
}
