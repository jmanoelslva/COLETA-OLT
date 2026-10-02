import { api, type DetalheOlt } from '../../api'
import { GraficoSinal } from '../../componentes/GraficoSinal'
import { useDados } from '../../componentes/comum'
import { dbm, duracao, ha, num, quando } from '../../formatos'

export function AbaEquipamento({ olt }: { olt: DetalheOlt }) {
  const s = olt.status
  const hist = useDados(() => api.statusHistorico(olt.id, 24), [olt.id], 300_000)
  if (!s) return <p className="vazio">A primeira leitura do equipamento ainda não terminou.</p>

  // DmOS não informa fabricante/modelo do SFP: a coluna só aparece se alguma porta tiver.
  const temModulo = olt.portas.some(p => p.sfp?.vendor || p.sfp?.produto)
  const temLink = olt.portas.some(p => p.sfp?.link)
  const relogioOk = s.desvio_relogio_s == null || Math.abs(s.desvio_relogio_s) < 300
  return (
    <div className="equipamento">
      <dl className="medidas">
        <div><dt>CPU</dt><dd>{num(s.cpu, 0, '%')}<small> carga {num(s.load1, 1)}</small></dd></div>
        <div><dt>Memória</dt><dd>{num(s.mem_uso, 0, '%')}<small> livre {num(s.mem_livre_mb, 0)} de {num(s.mem_total_mb, 0)} MB</small></dd></div>
        <div><dt>Temperatura da placa</dt><dd>{num(s.temp_placa, 1, ' °C')}</dd></div>
        <div><dt>Ligada há</dt><dd>{duracao(s.uptime_s)}<small> desde {quando(s.boot_em)}</small></dd></div>
        <div className={relogioOk ? '' : 'ruim'}>
          <dt>Relógio da OLT</dt>
          <dd>{relogioOk ? 'Certo' : `${Math.round((s.desvio_relogio_s ?? 0) / 60)} min de diferença`}</dd>
        </div>
        <div><dt>Lido</dt><dd>{ha(s.coletado_em)}</dd></div>
      </dl>

      <h3>Ventoinhas e fontes</h3>
      <ul className="itens">
        {s.ventoinhas?.map(f => (
          <li key={`f${f.id}`} className={f.status.toLowerCase() === 'normal' ? '' : 'ruim'}>
            Ventoinha {f.id}: {f.status === 'Normal' ? 'normal' : f.status}{f.rpm ? `, ${f.rpm} RPM` : ''}
          </li>
        ))}
        {s.fontes?.map(f => (
          <li key={`p${f.slot}`} className={f.status === 'working' ? '' : 'atento'}>
            Fonte {f.slot}: {f.status === 'working' ? 'funcionando' : 'sem funcionar (ou slot vazio)'}
          </li>
        ))}
      </ul>

      <h3>Portas PON</h3>
      <table className="tabela tabela-rotulada">
        <thead>
          <tr>
            <th>PON</th>
            {temLink && <th>Estado</th>}
            <th className="num">ONUs online</th>
            <th className="num">TX do SFP</th>
            <th className="num">Temperatura</th>
            <th className="num">Tensão</th>
            <th className="num">Corrente</th>
            {temModulo && <th>Módulo</th>}
          </tr>
        </thead>
        <tbody>
          {olt.portas.map(p => (
            <tr key={p.porta}>
              <td data-rotulo="PON">{p.porta}</td>
              {temLink && (
                <td data-rotulo="Estado" className={p.sfp?.admin === 'disabled' ? 'sutil' : p.sfp?.link === 'up' ? 'ok' : 'ruim'}>
                  {p.sfp?.admin === 'disabled' ? 'Desabilitada' : p.sfp?.link === 'up' ? 'Link ativo' : p.sfp?.link === 'down' ? 'Sem link' : p.onus_total === 0 ? 'Sem ONUs' : '—'}
                </td>
              )}
              <td data-rotulo="ONUs online" className="num">{p.onus_online}/{p.onus_total}</td>
              <td data-rotulo="TX do SFP" className="num">{p.sfp?.tx != null ? `${dbm(p.sfp.tx)} dBm` : '—'}</td>
              <td data-rotulo="Temperatura" className="num">{num(p.sfp?.temp, 1, ' °C')}</td>
              <td data-rotulo="Tensão" className="num">{num(p.sfp?.tensao, 2, ' V')}</td>
              <td data-rotulo="Corrente" className="num">{num(p.sfp?.bias, 1, ' mA')}</td>
              {temModulo && (
                <td data-rotulo="Módulo" className="sutil">
                  {[p.sfp?.vendor, p.sfp?.produto].filter(Boolean).join(' ') || '—'}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Últimas 24 h</h3>
      {hist.dados && (
        <GraficoSinal
          unidade=""
          min={0}
          max={100}
          series={[
            { nome: 'CPU %', classe: 's-cpu', pontos: hist.dados.map(h => ({ t: Date.parse(h.coletado_em), v: h.cpu })) },
            { nome: 'Memória %', classe: 's-mem', pontos: hist.dados.map(h => ({ t: Date.parse(h.coletado_em), v: h.mem_uso })) },
            { nome: 'Temperatura °C', classe: 's-temp', pontos: hist.dados.map(h => ({ t: Date.parse(h.coletado_em), v: h.temp_placa })) },
          ]}
        />
      )}

      <h3>Firmware</h3>
      <p>
        {s.versao?.firmware ?? '—'}<br />
        <span className="sutil">
          Hardware {s.versao?.hardware ?? '—'}, web {s.versao?.web ?? '—'}, iniciando por {s.firmware?.boot ?? '—'}
        </span>
      </p>
    </div>
  )
}
