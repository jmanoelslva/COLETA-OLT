import { createContext, useContext, type ReactNode } from 'react'
import { api, type Limites, type Parametros } from './api'
import { useDados } from './componentes/comum'

const PADRAO: Limites = {
  rx_onu_saturado: -8, rx_onu_atencao: -21, rx_onu_critico: -25,
  rx_olt_saturado: -8, rx_olt_atencao: -25, rx_olt_critico: -28,
}

const Ctx = createContext<{ limites: Limites; valores: Parametros | null; recarregar: () => void }>({
  limites: PADRAO, valores: null, recarregar: () => {},
})

export function ProvedorParametros({ children }: { children: ReactNode }) {
  const { dados, recarregar } = useDados(api.parametros, [])
  const v = dados?.valores
  const limites = v ? (Object.fromEntries(Object.keys(PADRAO).map(k => [k, v[k]])) as unknown as Limites) : PADRAO
  return <Ctx.Provider value={{ limites, valores: v ?? null, recarregar }}>{children}</Ctx.Provider>
}

export const useParametros = () => useContext(Ctx)
