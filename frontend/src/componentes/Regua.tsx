import type { Limites } from '../api'

// Escala comum para descida (ONU) e subida (OLT): mais forte à direita.
export const ESCALA_MIN = -32
export const ESCALA_MAX = -5

const x = (v: number) => ((Math.min(Math.max(v, ESCALA_MIN), ESCALA_MAX) - ESCALA_MIN) / (ESCALA_MAX - ESCALA_MIN)) * 100

function Trilha({ y, h, critico, atencao, saturado }: { y: number; h: number; critico: number; atencao: number; saturado: number }) {
  return (
    <g>
      <rect x="0" y={y} width={`${x(critico)}%`} height={h} className="z-critico" />
      <rect x={`${x(critico)}%`} y={y} width={`${x(atencao) - x(critico)}%`} height={h} className="z-atencao" />
      <rect x={`${x(atencao)}%`} y={y} width={`${x(saturado) - x(atencao)}%`} height={h} className="z-bom" />
      <rect x={`${x(saturado)}%`} y={y} width={`${100 - x(saturado)}%`} height={h} className="z-saturado" />
    </g>
  )
}

interface Props {
  rx: number | null
  rxOlt: number | null
  limites: Limites
  grande?: boolean
}

/** Régua de sinal: trilha de cima = descida (RX na ONU, ▼), de baixo = subida (RX na OLT, ▲). */
export function Regua({ rx, rxOlt, limites, grande }: Props) {
  const h = grande ? 12 : 7
  const alto = grande ? 70 : 32
  const yOnu = grande ? 16 : 8
  const yOlt = yOnu + h + (grande ? 6 : 3)
  const marcas = [-30, -25, -20, -15, -10]
  const titulo =
    `RX ONU: ${rx == null ? 'sem leitura' : `${rx.toFixed(2)} dBm`}. ` +
    `RX OLT: ${rxOlt == null ? 'sem leitura' : `${rxOlt.toFixed(2)} dBm`}.`
  return (
    <svg className={`regua${grande ? ' regua-grande' : ''}`} width="100%" height={alto} role="img" aria-label={titulo}>
      <title>{titulo}</title>
      <Trilha y={yOnu} h={h} critico={limites.rx_onu_critico} atencao={limites.rx_onu_atencao} saturado={limites.rx_onu_saturado} />
      <Trilha y={yOlt} h={h} critico={limites.rx_olt_critico} atencao={limites.rx_olt_atencao} saturado={limites.rx_olt_saturado} />
      {grande && marcas.map(m => (
        <g key={m}>
          <line x1={`${x(m)}%`} x2={`${x(m)}%`} y1={yOlt + h} y2={yOlt + h + 4} className="regua-tique" />
          <text x={`${x(m)}%`} y={alto - 2} textAnchor="middle" className="regua-num">{m}</text>
        </g>
      ))}
      {rx != null && <Marcador xp={x(rx)} y={yOnu - 1} baixo={false} grande={grande} />}
      {rxOlt != null && <Marcador xp={x(rxOlt)} y={yOlt + h + 1} baixo grande={grande} />}
    </svg>
  )
}

function Marcador({ xp, y, baixo, grande }: { xp: number; y: number; baixo: boolean; grande?: boolean }) {
  const s = grande ? 8 : 6
  // Triângulo apontando para a trilha: ▼ em cima (descida), ▲ embaixo (subida).
  return (
    <svg x={`${xp}%`} y={baixo ? y : y - s} overflow="visible">
      <polygon
        className="marcador"
        points={baixo ? `0,0 ${-s},${s} ${s},${s}` : `0,${s} ${-s},0 ${s},0`}
      />
    </svg>
  )
}
