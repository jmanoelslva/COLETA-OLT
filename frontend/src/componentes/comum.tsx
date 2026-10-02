import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Severidade } from '../api'
import { ROTULO_SEV } from '../formatos'

/** Carrega dados e recarrega sozinho a cada `intervaloMs` (se dado). */
export function useDados<T>(carregar: () => Promise<T>, deps: unknown[], intervaloMs?: number) {
  const [dados, setDados] = useState<T | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)
  const ref = useRef(carregar)
  ref.current = carregar

  const recarregar = useCallback(async () => {
    setCarregando(true)
    try {
      setDados(await ref.current())
      setErro(null)
    } catch (e) {
      setErro(e instanceof Error ? e.message : String(e))
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => {
    setDados(null)
    recarregar()
    if (!intervaloMs) return
    const id = setInterval(() => document.visibilityState === 'visible' && recarregar(), intervaloMs)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { dados, erro, carregando, recarregar, setDados }
}

export function Estado({ erro, carregando, vazio, children, tentar }: {
  erro: string | null; carregando: boolean; vazio?: boolean; children: ReactNode; tentar?: () => void
}) {
  if (erro) {
    return (
      <div className="aviso aviso-erro" role="alert">
        <p>{erro}</p>
        {tentar && <button className="botao-sec" onClick={tentar}>Tentar de novo</button>}
      </div>
    )
  }
  if (carregando && vazio) return <p className="carregando" aria-busy="true">Carregando…</p>
  return <>{children}</>
}

export function Sev({ s }: { s: Severidade }) {
  return <span className={`sev sev-${s}`}>{ROTULO_SEV[s]}</span>
}

export function Pilula({ classe, children }: { classe: string; children: ReactNode }) {
  return <span className={`pilula ${classe}`}>{children}</span>
}
