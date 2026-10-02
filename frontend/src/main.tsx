import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { FormOlt } from './paginas/FormOlt'
import { Olt } from './paginas/Olt'
import { Olts } from './paginas/Olts'
import { Onu } from './paginas/Onu'
import { Parametros } from './paginas/Parametros'
import { api, DENTRO_DO_TECNICO } from './api'
import { ProvedorParametros } from './parametros'
import './estilo.css'

/** Quem está logado no app técnico (modo /olt/). */
function UsuarioTecnico() {
  const [usuario, setUsuario] = useState<string | null>(null)
  useEffect(() => { api.acesso().then(a => setUsuario(a.usuario)).catch(() => {}) }, [])
  return usuario ? <span className="barra-usuario">{usuario}</span> : null
}

function App() {
  return (
    <ProvedorParametros>
      <div className="barra">
        <Link to="/" className="marca" aria-label="Início">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M3 22c6 0 8-12 14-12h12" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            <circle cx="27" cy="10" r="3.2" className="marca-ponto" />
          </svg>
          OLTs HOTNET
        </Link>
        <span className="barra-direita">
          {DENTRO_DO_TECNICO && <UsuarioTecnico />}
          {DENTRO_DO_TECNICO && <a href="/" className="barra-link">‹ App técnico</a>}
          <NavLink to="/configuracoes" className="barra-link">Configurações</NavLink>
        </span>
      </div>
      <Routes>
        <Route path="/" element={<Olts />} />
        <Route path="/olts/nova" element={<FormOlt />} />
        <Route path="/olt/:id/editar" element={<FormOlt />} />
        <Route path="/olt/:id" element={<Olt />} />
        <Route path="/olt/:id/onu/:porta/:onu" element={<Onu />} />
        <Route path="/configuracoes" element={<Parametros />} />
        <Route path="*" element={<main className="pagina"><p className="vazio">Página não encontrada. <Link to="/">Voltar às OLTs</Link></p></main>} />
      </Routes>
    </ProvedorParametros>
  )
}

createRoot(document.getElementById('raiz')!).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
