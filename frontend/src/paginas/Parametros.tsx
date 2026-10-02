import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ErroApi, type Parametros as P } from '../api'
import { useParametros } from '../parametros'

interface Campo { chave: string; nome: string; unidade: string; passo?: number; ajuda?: string }

const GRUPOS: { titulo: string; texto: string; campos: Campo[] }[] = [
  {
    titulo: 'Frequência de coleta',
    texto: 'Vale na hora, sem reiniciar. Se uma coleta demorar mais que o intervalo, a próxima espera ela terminar.',
    campos: [
      { chave: 'intervalo_alarmes_s', nome: 'Alarmes', unidade: 'min' },
      { chave: 'intervalo_sistema_s', nome: 'Equipamento (CPU, temperatura, SFP)', unidade: 'min' },
      { chave: 'intervalo_onus_s', nome: 'ONUs e RX ONU', unidade: 'min' },
      { chave: 'intervalo_rx_olt_s', nome: 'RX OLT', unidade: 'min', ajuda: 'Leva cerca de 1 min por porta PON.' },
    ],
  },
  {
    titulo: 'Faixas do RX ONU',
    texto: 'Abaixo de "atenção" fica amarelo, abaixo de "crítico" fica vermelho, acima de "forte demais" pede atenuador.',
    campos: [
      { chave: 'rx_onu_atencao', nome: 'Atenção abaixo de', unidade: 'dBm', passo: 0.5 },
      { chave: 'rx_onu_critico', nome: 'Crítico abaixo de', unidade: 'dBm', passo: 0.5 },
      { chave: 'rx_onu_saturado', nome: 'Forte demais acima de', unidade: 'dBm', passo: 0.5 },
    ],
  },
  {
    titulo: 'Faixas do RX OLT',
    texto: 'A OLT costuma aceitar sinal mais fraco que a ONU.',
    campos: [
      { chave: 'rx_olt_atencao', nome: 'Atenção abaixo de', unidade: 'dBm', passo: 0.5 },
      { chave: 'rx_olt_critico', nome: 'Crítico abaixo de', unidade: 'dBm', passo: 0.5 },
      { chave: 'rx_olt_saturado', nome: 'Forte demais acima de', unidade: 'dBm', passo: 0.5 },
    ],
  },
  {
    titulo: 'Alertas e histórico',
    texto: '',
    campos: [
      { chave: 'degradacao_db', nome: 'Queda que conta como degradação', unidade: 'dB', passo: 0.5, ajuda: 'Comparado com a média dos últimos 7 dias.' },
      { chave: 'oscilacao_eventos_1h', nome: 'Alarmes por hora para marcar "oscilando"', unidade: 'alarmes' },
      { chave: 'temp_onu_atencao', nome: 'ONU quente acima de', unidade: '°C' },
      { chave: 'retencao_dias', nome: 'Guardar histórico por', unidade: 'dias', ajuda: 'O que for mais antigo é apagado automaticamente.' },
    ],
  },
]

const emMin = (k: string) => k.startsWith('intervalo_')

// acl_ips é lista; o resto dos parâmetros é número.
const numericos = (v: P): P => Object.fromEntries(Object.entries(v).filter(([, x]) => typeof x === 'number'))
const aclDe = (v: P | null): string[] => ((v as Record<string, unknown> | null)?.acl_ips as string[] | undefined) ?? []

export function Parametros() {
  const { recarregar } = useParametros()
  const [valores, setValores] = useState<P | null>(null)
  const [padrao, setPadrao] = useState<P | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [confirmarPadrao, setConfirmarPadrao] = useState(false)

  const aplicar = (v: P) => {
    setValores(v)
    setForm(Object.fromEntries(Object.entries(numericos(v)).map(([k, x]) => [k, String(emMin(k) ? x / 60 : x)])))
  }

  useEffect(() => {
    api.parametros().then(r => { aplicar(r.valores); setPadrao(r.padrao) })
      .catch(e => setMsg({ ok: false, texto: e.message }))
  }, [])

  const salvar = async (e: React.FormEvent) => {
    e.preventDefault()
    setSalvando(true)
    setMsg(null)
    try {
      const novos: P = {}
      for (const [k, v] of Object.entries(form)) {
        const n = Number(v.replace(',', '.'))
        if (Number.isNaN(n)) throw new Error(`Valor inválido em ${k}`)
        const final = emMin(k) ? Math.round(n * 60) : n
        if (valores && final !== valores[k]) novos[k] = final
      }
      if (Object.keys(novos).length === 0) {
        setMsg({ ok: true, texto: 'Nada mudou.' })
        return
      }
      const r = await api.salvarParametros(novos)
      aplicar(r.valores)
      recarregar()
      setMsg({ ok: true, texto: 'Configurações salvas.' })
    } catch (err) {
      setMsg({ ok: false, texto: err instanceof Error ? err.message : String(err) })
    } finally {
      setSalvando(false)
    }
  }

  // A lista de IPs liberados não entra no "Restaurar padrões".
  const iguaisAoPadrao = !!(valores && padrao &&
    Object.keys(numericos(padrao)).every(k => valores[k] === padrao[k]))

  const restaurar = async () => {
    if (!padrao) return
    setSalvando(true)
    setMsg(null)
    try {
      const r = await api.salvarParametros(numericos(padrao))
      aplicar(r.valores)
      recarregar()
      setMsg({ ok: true, texto: 'Valores padrão restaurados.' })
    } catch (err) {
      setMsg({ ok: false, texto: err instanceof Error ? err.message : String(err) })
    } finally {
      setSalvando(false)
      setConfirmarPadrao(false)
    }
  }

  return (
    <main className="pagina">
      <header className="topo">
        <Link to="/" className="voltar">OLTs</Link>
        <h1>Configurações</h1>
        <p className="sutil">Coletor de OLTs, versão {__VERSAO__}</p>
      </header>
      {!valores && !msg && <p className="carregando">Carregando…</p>}
      {valores && (
        <form onSubmit={salvar} className="form-parametros">
          {GRUPOS.map(g => (
            <fieldset key={g.titulo}>
              <legend>{g.titulo}</legend>
              {g.texto && <p className="sutil">{g.texto}</p>}
              {g.campos.map(c => (
                <label key={c.chave} className="campo-linha">
                  <span>
                    {c.nome}
                    {c.ajuda && <small>{c.ajuda}</small>}
                  </span>
                  <span className="entrada">
                    <input
                      inputMode="decimal"
                      value={form[c.chave] ?? ''}
                      onChange={e => setForm(f => ({ ...f, [c.chave]: e.target.value }))}
                      aria-describedby={`${c.chave}-pad`}
                    />
                    <span>{c.unidade}</span>
                  </span>
                  {padrao && (() => {
                    const pad = emMin(c.chave) ? padrao[c.chave] / 60 : padrao[c.chave]
                    const alterado = Number((form[c.chave] ?? '').replace(',', '.')) !== pad
                    return (
                      <small id={`${c.chave}-pad`} className={`padrao${alterado ? ' padrao-alterado' : ''}`}
                        title={alterado ? 'Valor diferente do padrão' : undefined}>
                        padrão {pad} {c.unidade}
                      </small>
                    )
                  })()}
                </label>
              ))}
            </fieldset>
          ))}
          <div className="acoes">
            <button className="botao" disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar configurações'}</button>
            {!confirmarPadrao ? (
              <button type="button" className="botao-sec" disabled={salvando || iguaisAoPadrao}
                title={iguaisAoPadrao ? 'Já está tudo no padrão' : undefined} onClick={() => setConfirmarPadrao(true)}>
                Restaurar padrões
              </button>
            ) : (
              <span className="confirmar-padrao" role="alertdialog" aria-label="Confirmar restauração">
                <span>Voltar coleta, faixas e alertas para o padrão? A lista de IPs liberados não muda.</span>
                <button type="button" className="botao perigo" onClick={restaurar} disabled={salvando}>Restaurar padrões</button>
                <button type="button" className="botao-sec" onClick={() => setConfirmarPadrao(false)}>Cancelar</button>
              </span>
            )}
            {msg && <span className={msg.ok ? 'ok' : 'aviso-erro'} role="status">{msg.texto}</span>}
          </div>
        </form>
      )}
      {valores && <AclIps atual={aclDe(valores)} aoSalvar={v => { aplicar(v) }} />}
      {!valores && msg && <p className="aviso-erro">{msg.texto}</p>}
    </main>
  )
}

/** Lista de IPs/redes que podem usar o coletor (vale na hora, sem reinstalar). */
function AclIps({ atual, aoSalvar }: { atual: string[]; aoSalvar: (v: P) => void }) {
  const [texto, setTexto] = useState(atual.join('\n'))
  const [acesso, setAcesso] = useState<{ ip: string | null; local: boolean; liberado: boolean } | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => { api.acesso().then(setAcesso).catch(() => {}) }, [])
  useEffect(() => { setTexto(atual.join('\n')) }, [atual.join('|')])  // eslint-disable-line react-hooks/exhaustive-deps

  const linhas = texto.split('\n').map(l => l.trim()).filter(Boolean)
  const mudou = linhas.join('|') !== atual.join('|')

  const salvar = async () => {
    setSalvando(true)
    setMsg(null)
    try {
      const r = await api.salvarAcl(linhas)
      aoSalvar(r.valores)
      setMsg({ ok: true, texto: linhas.length ? 'Lista de IPs salva. Vale a partir de agora.' : 'Lista vazia: qualquer IP pode usar o coletor.' })
    } catch (err) {
      const campo = err instanceof ErroApi ? err.campos?.acl_ips : undefined
      setMsg({ ok: false, texto: campo ?? (err instanceof Error ? err.message : String(err)) })
    } finally {
      setSalvando(false)
    }
  }

  const incluirMeuIp = () => {
    if (acesso?.ip && !linhas.includes(acesso.ip)) setTexto(t => (t.trim() ? `${t.trim()}\n` : '') + acesso.ip)
  }

  return (
    <section className="form-parametros acl">
      <fieldset>
        <legend>IPs liberados</legend>
        <p className="sutil">
          Quem pode abrir o coletor, além da senha do site. Um IP ou rede por linha, IPv4 ou IPv6 (ex.: 177.85.130.0/24 ou 2804:abc::/32),
          com comentário opcional depois de #. Lista vazia libera qualquer IP. Vale na hora, sem reinstalar.
        </p>
        <p className="acl-meu-ip">
          {acesso == null ? 'Verificando o seu IP…'
            : acesso.local ? 'Você está acessando de dentro do servidor (sempre liberado).'
            : <>Seu IP agora: <strong>{acesso.ip}</strong>
                {!linhas.length || acesso.liberado ? '' : ' (fora da lista atual)'}
                {acesso.ip && !linhas.includes(acesso.ip) && (
                  <button type="button" className="chip" onClick={incluirMeuIp}>Incluir meu IP</button>
                )}
              </>}
        </p>
        <textarea rows={Math.max(4, linhas.length + 1)} value={texto} onChange={e => setTexto(e.target.value)}
          spellCheck={false} aria-label="IPs ou redes liberados, um por linha"
          placeholder={'177.85.130.0/24   # escritório (IPv4)\n2804:abc::/32     # escritório (IPv6)\n10.0.0.0/8        # VPN'} />
        <div className="acoes-acl">
          <button type="button" className="botao" onClick={salvar} disabled={salvando || !mudou}>
            {salvando ? 'Salvando…' : 'Salvar lista de IPs'}
          </button>
          {msg && <span className={msg.ok ? 'ok' : 'aviso-erro'} role="status">{msg.texto}</span>}
        </div>
        <p className="sutil">
          Para não se trancar fora, o coletor não salva uma lista que deixe o seu IP de fora. A lista de IPs
          definida na instalação (no servidor web) continua valendo junto com esta.
        </p>
      </fieldset>
    </section>
  )
}
