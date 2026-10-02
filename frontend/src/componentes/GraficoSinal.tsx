import { useMemo, useState } from 'react'

export interface Serie {
  nome: string
  classe: string // cor via CSS
  pontos: { t: number; v: number | null }[]
}

interface Props {
  series: Serie[]
  faixas?: { de: number; ate: number; classe: string }[]
  unidade: string
  min?: number
  max?: number
}

const L = 640
const A = 220
const M = { e: 38, d: 10, c: 10, b: 24 }

/** Linhas no tempo com faixas de fundo. Buraco (sem leitura) quebra a linha. */
export function GraficoSinal({ series, faixas = [], unidade, min, max }: Props) {
  const [foco, setFoco] = useState<number | null>(null)

  const { t0, t1, v0, v1 } = useMemo(() => {
    const ts = series.flatMap(s => s.pontos.map(p => p.t))
    const vs = series.flatMap(s => s.pontos.flatMap(p => (p.v == null ? [] : [p.v])))
    const vmin = min ?? Math.floor(Math.min(...vs, -28) - 1)
    const vmax = max ?? Math.ceil(Math.max(...vs, -14) + 1)
    return { t0: Math.min(...ts), t1: Math.max(...ts), v0: vmin, v1: vmax }
  }, [series, min, max])

  if (!series.some(s => s.pontos.some(p => p.v != null))) {
    return <p className="vazio">Ainda não há leituras neste período.</p>
  }

  const px = (t: number) => M.e + ((t - t0) / Math.max(t1 - t0, 1)) * (L - M.e - M.d)
  const py = (v: number) => M.c + (1 - (v - v0) / (v1 - v0)) * (A - M.c - M.b)
  const passo = (v1 - v0) > 16 ? 5 : 2
  const grade: number[] = []
  for (let v = Math.ceil(v0 / passo) * passo; v <= v1; v += passo) grade.push(v)

  const caminho = (pts: Serie['pontos']) => {
    let d = ''
    let caneta = false
    for (const p of pts) {
      if (p.v == null) { caneta = false; continue }
      d += `${caneta ? 'L' : 'M'}${px(p.t).toFixed(1)},${py(p.v).toFixed(1)}`
      caneta = true
    }
    return d
  }

  const dias = t1 - t0 > 6 * 86400e3
  const varios = t1 - t0 > 36 * 3600e3
  const fmt = new Intl.DateTimeFormat('pt-BR', dias ? { day: '2-digit', month: '2-digit' } : varios ? { day: '2-digit', month: '2-digit', hour: '2-digit' } : { hour: '2-digit', minute: '2-digit' })
  const tiques = Array.from({ length: 5 }, (_, i) => t0 + ((t1 - t0) * i) / 4)

  const pertoDe = (t: number) =>
    series.map(s => {
      let melhor = s.pontos[0]
      for (const p of s.pontos) if (Math.abs(p.t - t) < Math.abs(melhor.t - t)) melhor = p
      return { s, p: melhor }
    })

  const mover = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const xr = ((e.clientX - r.left) / r.width) * L
    setFoco(t0 + ((xr - M.e) / (L - M.e - M.d)) * (t1 - t0))
  }

  const lidos = foco != null ? pertoDe(foco) : null

  return (
    <figure className="grafico">
      <svg viewBox={`0 0 ${L} ${A}`} onPointerMove={mover} onPointerLeave={() => setFoco(null)} role="img"
        aria-label={`Gráfico de ${series.map(s => s.nome).join(' e ')} em ${unidade}`}>
        {faixas.map((f, i) => {
          const a = py(Math.min(f.ate, v1)); const b = py(Math.max(f.de, v0))
          return b > a ? <rect key={i} x={M.e} y={a} width={L - M.e - M.d} height={b - a} className={f.classe} /> : null
        })}
        {grade.map(v => (
          <g key={v}>
            <line x1={M.e} x2={L - M.d} y1={py(v)} y2={py(v)} className="g-grade" />
            <text x={M.e - 6} y={py(v) + 4} textAnchor="end" className="g-eixo">{v}</text>
          </g>
        ))}
        {tiques.map((t, i) => (
          <text key={t} x={px(t)} y={A - 6} textAnchor={i === 0 ? 'start' : i === tiques.length - 1 ? 'end' : 'middle'} className="g-eixo">{fmt.format(new Date(t))}</text>
        ))}
        {series.map(s => <path key={s.nome} d={caminho(s.pontos)} className={`g-linha ${s.classe}`} />)}
        {lidos && (
          <g>
            <line x1={px(lidos[0].p.t)} x2={px(lidos[0].p.t)} y1={M.c} y2={A - M.b} className="g-foco" />
            {lidos.map(({ s, p }) => p.v != null && (
              <circle key={s.nome} cx={px(p.t)} cy={py(p.v)} r="4" className={`g-ponto ${s.classe}`} />
            ))}
          </g>
        )}
      </svg>
      <figcaption className="g-legenda">
        {series.map(s => {
          const p = lidos?.find(l => l.s === s)?.p ?? [...s.pontos].reverse().find(q => q.v != null)
          return (
            <span key={s.nome} className="g-item">
              <i className={`g-cor ${s.classe}`} />{s.nome}
              <b>{p?.v != null ? `${p.v.toFixed(2)} ${unidade}` : '—'}</b>
            </span>
          )
        })}
        {lidos && <span className="g-quando">{new Date(lidos[0].p.t).toLocaleString('pt-BR')}</span>}
      </figcaption>
    </figure>
  )
}
