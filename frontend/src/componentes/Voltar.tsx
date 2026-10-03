import type { MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

/**
 * Botão "voltar" do topo das páginas. Se a página anterior é do próprio
 * coletor, volta no histórico — mantém PON, filtros, busca e rolagem da
 * lista. Aberta por link direto (sem histórico), vai para `para`.
 */
export function Voltar({ para, rotulo }: { para: string; rotulo: string }) {
  const navegar = useNavigate()
  const temAnterior = (window.history.state as { idx?: number } | null)?.idx

  const clicar = (e: MouseEvent<HTMLAnchorElement>) => {
    // Ctrl/Cmd/botão do meio: deixa abrir em outra aba normalmente.
    if (!temAnterior || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navegar(-1)
  }

  return (
    <Link to={para} className="voltar" onClick={clicar} aria-label={`Voltar para ${rotulo}`}>
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>{rotulo}</span>
    </Link>
  )
}
