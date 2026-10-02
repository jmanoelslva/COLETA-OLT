import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ErroApi, type CadastroOlt, type Fabricante, type ResultadoTeste } from '../api'

const VAZIO: CadastroOlt = {
  id: '', nome: '', fabricante: 'cdata', modelo: '', host: '', porta_ssh: 22, usuario: '',
  frame_slot: '0/0', portas_pon: [1, 2, 3, 4, 5, 6, 7, 8], ativa: true, senha: '', senha_enable: '',
}

/** "1-8" ou "1,2,5-7" → [1,2,5,6,7] */
function lerPortas(t: string): number[] | null {
  const out = new Set<number>()
  for (const parte of t.split(/[,\s]+/).filter(Boolean)) {
    const m = parte.match(/^(\d+)(?:-(\d+))?$/)
    if (!m) return null
    const a = Number(m[1]); const b = Number(m[2] ?? m[1])
    if (b < a || b - a > 64) return null
    for (let i = a; i <= b; i++) out.add(i)
  }
  return out.size ? [...out].sort((x, y) => x - y) : null
}

function escreverPortas(p: number[]): string {
  const faixas: string[] = []
  let i = 0
  while (i < p.length) {
    let j = i
    while (j + 1 < p.length && p[j + 1] === p[j] + 1) j++
    faixas.push(i === j ? `${p[i]}` : `${p[i]}-${p[j]}`)
    i = j + 1
  }
  return faixas.join(', ')
}

const paraId = (nome: string) =>
  nome.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40)

export function FormOlt() {
  const { id } = useParams()
  const novo = !id
  const navegar = useNavigate()
  const [f, setF] = useState<CadastroOlt>(VAZIO)
  const [portasTexto, setPortasTexto] = useState('1-8')
  const [idTocado, setIdTocado] = useState(false)
  const [fabs, setFabs] = useState<Record<string, Fabricante>>({})
  const [erros, setErros] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [teste, setTeste] = useState<ResultadoTeste | null>(null)
  const [testando, setTestando] = useState(false)
  const [excluir, setExcluir] = useState(false)
  const [apagarHist, setApagarHist] = useState(false)

  useEffect(() => {
    api.fabricantes().then(setFabs).catch(() => {})
    if (id) {
      api.cadastro(id).then(c => {
        setF({ ...c, senha: '', senha_enable: '' })
        setPortasTexto(escreverPortas(c.portas_pon))
      }).catch(e => setMsg(e.message))
    }
  }, [id])

  const campo = <K extends keyof CadastroOlt>(k: K, v: CadastroOlt[K]) => setF(x => ({ ...x, [k]: v }))
  const fab = fabs[f.fabricante]

  const montar = (): CadastroOlt | null => {
    const portas = lerPortas(portasTexto)
    if (!portas) {
      setErros(e => ({ ...e, portas_pon: 'Use números e faixas, ex.: 1-8 ou 1, 2, 5-7' }))
      return null
    }
    return { ...f, portas_pon: portas, porta_ssh: Number(f.porta_ssh) }
  }

  const salvar = async (e: React.FormEvent) => {
    e.preventDefault()
    setErros({}); setMsg(null)
    const dados = montar()
    if (!dados) return
    setSalvando(true)
    try {
      const r = novo ? await api.criarOlt(dados) : await api.editarOlt(dados)
      navegar(`/olt/${r.id}`)
    } catch (err) {
      if (err instanceof ErroApi && err.campos) setErros(err.campos)
      setMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setSalvando(false)
    }
  }

  const testar = async () => {
    setTeste(null)
    const dados = montar()
    if (!dados) return
    setTestando(true)
    try {
      setTeste(await api.testarOlt({ ...dados, id: novo ? undefined : f.id }))
    } catch (err) {
      setTeste({ ok: false, erro: err instanceof Error ? err.message : String(err) })
    } finally {
      setTestando(false)
    }
  }

  const confirmarExclusao = async () => {
    try {
      await api.excluirOlt(f.id, apagarHist)
      navegar('/')
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err))
    }
  }

  const Erro = ({ k }: { k: string }) => (erros[k] ? <small className="erro-campo" id={`e-${k}`}>{erros[k]}</small> : null)

  return (
    <main className="pagina">
      <header className="topo">
        <Link to={novo ? '/' : `/olt/${id}`} className="voltar">{novo ? 'OLTs' : f.nome || id}</Link>
        <h1>{novo ? 'Cadastrar OLT' : 'Editar OLT'}</h1>
      </header>

      <form className="form-olt" onSubmit={salvar} noValidate>
        <fieldset>
          <legend>Identificação</legend>
          <label className="campo">
            Nome
            <input value={f.nome} required onChange={e => {
              campo('nome', e.target.value)
              if (novo && !idTocado) campo('id', paraId(e.target.value))
            }} aria-invalid={!!erros.nome} />
            <Erro k="nome" />
          </label>
          <label className="campo">
            Identificador
            <input value={f.id} disabled={!novo} onChange={e => { setIdTocado(true); campo('id', e.target.value) }}
              aria-invalid={!!erros.id} />
            <small className="sutil">Usado no endereço da página. Não muda depois.</small>
            <Erro k="id" />
          </label>
          <div className="linha-campos">
            <label className="campo">
              Fabricante
              <select value={f.fabricante} onChange={e => campo('fabricante', e.target.value)}>
                {Object.entries(fabs).map(([k, v]) => <option key={k} value={k}>{v.nome}</option>)}
              </select>
            </label>
            <label className="campo">
              Modelo
              <input value={f.modelo} placeholder={fab?.modelo_padrao} onChange={e => campo('modelo', e.target.value)} />
            </label>
          </div>
          {fab && !fab.coleta && (
            <p className="aviso-campo">
              A coleta de {fab.nome} ainda não está disponível. Dá para cadastrar e testar o acesso agora;
              a coleta liga quando os comandos dela forem levantados.
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend>Acesso SSH</legend>
          <div className="linha-campos">
            <label className="campo cresce">
              Endereço (IP ou nome)
              <input value={f.host} onChange={e => campo('host', e.target.value)} aria-invalid={!!erros.host} autoComplete="off" />
              <Erro k="host" />
            </label>
            <label className="campo curto">
              Porta
              <input inputMode="numeric" value={f.porta_ssh} onChange={e => campo('porta_ssh', Number(e.target.value.replace(/\D/g, '')))}
                aria-invalid={!!erros.porta_ssh} />
              <Erro k="porta_ssh" />
            </label>
          </div>
          <div className="linha-campos">
            <label className="campo">
              Usuário
              <input value={f.usuario} onChange={e => campo('usuario', e.target.value)} aria-invalid={!!erros.usuario} autoComplete="off" />
              <Erro k="usuario" />
            </label>
            <label className="campo">
              Senha
              <input type="password" value={f.senha ?? ''} onChange={e => campo('senha', e.target.value)}
                placeholder={!novo && f.tem_senha ? 'Deixe em branco para manter' : ''} aria-invalid={!!erros.senha}
                autoComplete="new-password" />
              <Erro k="senha" />
            </label>
          </div>
          <label className="campo">
            Senha do enable <span className="sutil">(só se for diferente da senha de login)</span>
            <input type="password" value={f.senha_enable ?? ''} onChange={e => campo('senha_enable', e.target.value)}
              placeholder={!novo && f.tem_senha_enable ? 'Deixe em branco para manter' : ''} autoComplete="new-password" />
          </label>
          <div className="teste">
            <button type="button" className="botao-sec" onClick={testar} disabled={testando}>
              {testando ? 'Testando acesso…' : 'Testar acesso'}
            </button>
            {teste && (
              <p className={teste.ok ? 'ok' : 'aviso-erro'} role="status">
                {teste.ok
                  ? <>Acesso OK{teste.hostname ? `: ${teste.hostname}` : ''}{teste.firmware ? `, ${teste.firmware}` : ''} ({teste.tempo_ms} ms). {teste.aviso}</>
                  : <>Não conectou: {teste.erro}</>}
              </p>
            )}
          </div>
        </fieldset>

        <fieldset>
          <legend>Portas e coleta</legend>
          <div className="linha-campos">
            <label className="campo cresce">
              Portas PON em uso
              <input value={portasTexto} onChange={e => setPortasTexto(e.target.value)} aria-invalid={!!erros.portas_pon} />
              <small className="sutil">Ex.: 1-8, ou 1, 2, 5-7. Porta vazia só gasta tempo de coleta.</small>
              <Erro k="portas_pon" />
            </label>
            {f.fabricante === 'cdata' && (
              <label className="campo curto">
                Frame/slot
                <input value={f.frame_slot} onChange={e => campo('frame_slot', e.target.value)} aria-invalid={!!erros.frame_slot} />
                <small className="sutil">Da "interface gpon", ex.: 0/0</small>
                <Erro k="frame_slot" />
              </label>
            )}
          </div>
          <label className="opcao">
            <input type="checkbox" checked={!!f.ativa} onChange={e => campo('ativa', e.target.checked)} />
            Coletar desta OLT
          </label>
        </fieldset>

        <div className="acoes">
          <button className="botao" disabled={salvando}>{salvando ? 'Salvando…' : novo ? 'Cadastrar OLT' : 'Salvar alterações'}</button>
          {msg && <span className="aviso-erro" role="alert">{msg}</span>}
        </div>
      </form>

      {!novo && (
        <section className="zona-exclusao">
          <h2>Excluir OLT</h2>
          {!excluir ? (
            <button className="botao-sec perigo" onClick={() => setExcluir(true)}>Excluir esta OLT…</button>
          ) : (
            <div className="confirmar">
              <p>A coleta para na hora e a OLT some da lista.</p>
              <label className="opcao">
                <input type="checkbox" checked={apagarHist} onChange={e => setApagarHist(e.target.checked)} />
                Apagar também todo o histórico de sinais e alarmes
              </label>
              <div className="linha-botoes">
                <button className="botao perigo" onClick={confirmarExclusao}>Excluir {f.nome}</button>
                <button className="botao-sec" onClick={() => setExcluir(false)}>Cancelar</button>
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  )
}
