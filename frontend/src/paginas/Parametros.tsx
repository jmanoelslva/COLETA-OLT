import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Parametros as P } from '../api'
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
    setForm(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(emMin(k) ? x / 60 : x)])))
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

  const iguaisAoPadrao = !!(valores && padrao && Object.keys(padrao).every(k => valores[k] === padrao[k]))

  const restaurar = async () => {
    if (!padrao) return
    setSalvando(true)
    setMsg(null)
    try {
      const r = await api.salvarParametros(padrao)
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
                  {padrao && (
                    <small id={`${c.chave}-pad`} className="sutil">
                      padrão {emMin(c.chave) ? padrao[c.chave] / 60 : padrao[c.chave]}
                    </small>
                  )}
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
                <span>Voltar todos os valores para o padrão? O que não foi salvo também será descartado.</span>
                <button type="button" className="botao perigo" onClick={restaurar} disabled={salvando}>Restaurar padrões</button>
                <button type="button" className="botao-sec" onClick={() => setConfirmarPadrao(false)}>Cancelar</button>
              </span>
            )}
            {msg && <span className={msg.ok ? 'ok' : 'aviso-erro'} role="status">{msg.texto}</span>}
          </div>
        </form>
      )}
      {!valores && msg && <p className="aviso-erro">{msg.texto}</p>}
    </main>
  )
}
