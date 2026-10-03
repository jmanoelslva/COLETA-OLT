import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api, type EstadoAdmin } from './api'

/**
 * Acesso de admin do coletor: só ele cadastra/edita/exclui OLTs e muda as
 * Configurações. É um login à parte (usuário e senha do admin), além do login
 * do app técnico; o servidor confere em toda ação (aqui só esconde botões).
 */

type CtxAdmin = {
  estado: EstadoAdmin | null
  admin: boolean
  aplicar: (e: EstadoAdmin) => void
  sair: () => Promise<void>
  abrirLogin: () => void
}

const Ctx = createContext<CtxAdmin>({
  estado: null, admin: false, aplicar: () => {}, sair: async () => {}, abrirLogin: () => {},
})

export const useAdmin = () => useContext(Ctx)

export function ProvedorAdmin({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<EstadoAdmin | null>(null)
  const [login, setLogin] = useState(false)

  useEffect(() => { api.admin().then(setEstado).catch(() => {}) }, [])

  const sair = useCallback(async () => {
    setEstado(await api.sairAdmin())
  }, [])

  return (
    <Ctx.Provider value={{ estado, admin: !!estado?.logado, aplicar: setEstado, sair, abrirLogin: () => setLogin(true) }}>
      {children}
      {login && <JanelaLogin configurado={estado?.configurado ?? true} aoFechar={() => setLogin(false)} aoEntrar={e => { setEstado(e); setLogin(false) }} />}
    </Ctx.Provider>
  )
}

/** Botão da barra: "Admin" para entrar; logado, mostra o usuário e "Sair". */
export function BotaoAdmin() {
  const { estado, admin, sair, abrirLogin } = useAdmin()
  if (!estado) return null
  if (admin) {
    return (
      <span className="barra-admin">
        <span className="barra-admin-selo" title="Logado como admin do coletor">Admin: {estado.usuario}</span>
        <button type="button" className="barra-link barra-botao" onClick={() => sair()}>Sair</button>
      </span>
    )
  }
  return <button type="button" className="barra-link barra-botao" onClick={abrirLogin}>Admin</button>
}

/** Envolve as páginas de admin: sem login, explica e oferece entrar. */
export function SoAdmin({ children }: { children: ReactNode }) {
  const { estado, admin, abrirLogin } = useAdmin()
  if (!estado) return <main className="pagina"><p className="carregando">Carregando…</p></main>
  if (admin) return <>{children}</>
  return (
    <main className="pagina">
      <div className="aviso">
        <p>Cadastro de OLTs e Configurações são só para o admin do coletor.</p>
        <button type="button" className="botao" onClick={abrirLogin}>Entrar como admin</button>
      </div>
    </main>
  )
}

function JanelaLogin({ configurado, aoFechar, aoEntrar }: {
  configurado: boolean; aoFechar: () => void; aoEntrar: (e: EstadoAdmin) => void
}) {
  const [usuario, setUsuario] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [entrando, setEntrando] = useState(false)
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal()
  }, [])

  const entrar = async (ev: FormEvent) => {
    ev.preventDefault()
    setEntrando(true)
    setErro(null)
    try {
      aoEntrar(await api.entrarAdmin(usuario, senha))
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e))
      setSenha('')
    } finally {
      setEntrando(false)
    }
  }

  return (
    <dialog ref={ref} className="janela" onClose={aoFechar} aria-labelledby="titulo-admin">
      <form onSubmit={entrar} className="janela-form">
        <h2 id="titulo-admin">Entrar como admin</h2>
        {!configurado ? (
          <p className="sutil">
            O admin ainda não foi definido. No servidor, rode o instalador de novo
            (<code>sudo bash /opt/coletor-olt/deploy/install.sh</code>) ou <code>python -m coletor.admin</code>.
          </p>
        ) : (
          <>
            <label>Usuário
              <input autoFocus autoComplete="username" value={usuario} onChange={e => setUsuario(e.target.value)} required />
            </label>
            <label>Senha
              <input type="password" autoComplete="current-password" value={senha} onChange={e => setSenha(e.target.value)} required />
            </label>
          </>
        )}
        {erro && <p className="aviso-erro" role="alert">{erro}</p>}
        <div className="janela-acoes">
          <button type="button" className="botao-sec" onClick={() => ref.current?.close()}>Cancelar</button>
          {configurado && <button className="botao" disabled={entrando}>{entrando ? 'Entrando…' : 'Entrar'}</button>}
        </div>
      </form>
    </dialog>
  )
}

/** Troca do usuário/senha do admin (em Configurações). */
export function TrocarSenhaAdmin() {
  const { estado, aplicar } = useAdmin()
  const [usuario, setUsuario] = useState(estado?.usuario ?? '')
  const [atual, setAtual] = useState('')
  const [nova, setNova] = useState('')
  const [repetir, setRepetir] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)

  const salvar = async (ev: FormEvent) => {
    ev.preventDefault()
    if (nova !== repetir) {
      setMsg({ ok: false, texto: 'A nova senha e a repetição não conferem.' })
      return
    }
    setSalvando(true)
    setMsg(null)
    try {
      aplicar(await api.trocarSenhaAdmin({ usuario, senha_atual: atual, nova_senha: nova }))
      setAtual(''); setNova(''); setRepetir('')
      setMsg({ ok: true, texto: 'Usuário e senha do admin salvos. Outras sessões de admin foram encerradas.' })
    } catch (e) {
      const campos = (e as { campos?: Record<string, string> }).campos
      setMsg({ ok: false, texto: campos ? Object.values(campos).join('; ') : e instanceof Error ? e.message : String(e) })
    } finally {
      setSalvando(false)
    }
  }

  return (
    <section className="form-parametros">
      <form onSubmit={salvar}>
        <fieldset>
          <legend>Acesso de admin</legend>
          <p className="sutil">Usuário e senha que liberam o cadastro de OLTs e estas Configurações. Mínimo de 8 caracteres.</p>
          <div className="campos-admin">
            <label>Usuário
              <input autoComplete="username" value={usuario} onChange={e => setUsuario(e.target.value)} required />
            </label>
            <label>Senha atual
              <input type="password" autoComplete="current-password" value={atual} onChange={e => setAtual(e.target.value)} required />
            </label>
            <label>Nova senha
              <input type="password" autoComplete="new-password" minLength={8} value={nova} onChange={e => setNova(e.target.value)} required />
            </label>
            <label>Repita a nova senha
              <input type="password" autoComplete="new-password" minLength={8} value={repetir} onChange={e => setRepetir(e.target.value)} required />
            </label>
          </div>
          <div className="acoes-acl">
            <button className="botao" disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar acesso de admin'}</button>
            {msg && <span className={msg.ok ? 'ok' : 'aviso-erro'} role="status">{msg.texto}</span>}
          </div>
        </fieldset>
      </form>
    </section>
  )
}
