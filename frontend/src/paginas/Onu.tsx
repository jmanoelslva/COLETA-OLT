import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { GraficoSinal } from '../componentes/GraficoSinal'
import { Estado, useDados } from '../componentes/comum'
import { ROTULO_CLASSE, dbm, duracao, ha, num } from '../formatos'
import { useParametros } from '../parametros'
import { AbaHistorico } from './abas/AbaHistorico'

const PERIODOS = [{ h: 24, nome: '24 h' }, { h: 72, nome: '3 dias' }, { h: 24 * 7, nome: '7 dias' }, { h: 24 * 30, nome: '30 dias' }, { h: 24 * 90, nome: '90 dias' }]

export function Onu() {
  const { id = '', porta: p = '', onu: n = '' } = useParams()
  const porta = Number(p)
  const onuId = Number(n)
  const { limites } = useParametros()
  const [horas, setHoras] = useState(72)
  const [atualizando, setAtualizando] = useState(false)
  const [erroAtualizar, setErroAtualizar] = useState<string | null>(null)
  const { dados: onu, erro, carregando, recarregar, setDados } = useDados(() => api.onu(id, porta, onuId), [id, porta, onuId])
  const sinais = useDados(() => api.sinais(id, porta, onuId, horas), [id, porta, onuId, horas])

  const atualizar = async () => {
    setAtualizando(true)
    setErroAtualizar(null)
    try {
      setDados(await api.atualizarOnu(id, porta, onuId))
      sinais.recarregar()
    } catch (e) {
      setErroAtualizar(e instanceof Error ? e.message : String(e))
    } finally {
      setAtualizando(false)
    }
  }

  return (
    <main className="pagina">
      <header className="topo">
        <Link to={`/olt/${id}?aba=onus&porta=${porta}`} className="voltar">PON {porta}</Link>
        <h1>{onu?.descricao ?? `ONU ${porta}/${onuId}`}</h1>
        {onu && (
          <p className="sutil">
            ONU {porta}/{onuId}, serial {onu.sn ?? '—'}
            {onu.distancia_m != null && <>, {(onu.distancia_m / 1000).toFixed(2)} km da OLT</>}
          </p>
        )}
      </header>
      <Estado erro={erro} carregando={carregando} vazio={!onu} tentar={recarregar}>
        {onu && (
          <>
            <section className={`estado-onu grav-${onu.gravidade}`}>
              <div className="estado-linha">
                <strong className={onu.online ? 'online' : 'offline'}>{onu.online ? 'Online' : 'Offline'}</strong>
                <span className="sutil">
                  {onu.online ? `há ${duracao(onu.online_seg)}` : onu.last_down ? `desde ${onu.last_down}` : ''}
                </span>
                <button className="botao-sec" onClick={atualizar} disabled={atualizando}>
                  {atualizando ? 'Lendo na OLT…' : 'Ler agora na OLT'}
                </button>
              </div>
              {erroAtualizar && <p className="aviso-erro" role="alert">{erroAtualizar}</p>}

              {onu.online && (
                <>
                  <dl className="leituras">
                    <div className={`v-${onu.classe_rx}`}>
                      <dt>▼ RX ONU</dt><dd>{dbm(onu.rx)}<small> dBm</small></dd>
                      <span>{ROTULO_CLASSE[onu.classe_rx]}</span>
                    </div>
                    <div className={`v-${onu.classe_rx_olt}`}>
                      <dt>▲ RX OLT</dt><dd>{dbm(onu.rx_olt)}<small> dBm</small></dd>
                      <span>{ROTULO_CLASSE[onu.classe_rx_olt]}</span>
                    </div>
                    <div>
                      <dt>Média 7 dias</dt><dd>{dbm(onu.rx_media_7d)}<small> dBm</small></dd>
                      <span>{onu.delta_7d != null ? `${onu.delta_7d > 0 ? '+' : ''}${onu.delta_7d.toFixed(1)} dB agora` : ''}</span>
                    </div>
                    <div>
                      <dt>Atenuação total</dt><dd>{num(onu.atenuacao_db, 1)}<small> dB</small></dd>
                      <span>TX do SFP − RX ONU</span>
                    </div>
                  </dl>
                  <p className="sutil">
                    Sinal na ONU lido {ha(onu.sinal_em)}, na OLT {ha(onu.rx_olt_em)}.
                    {' '}{[
                      onu.tx != null && `TX da ONU ${dbm(onu.tx)} dBm`,
                      onu.temp != null && num(onu.temp, 0, ' °C'),
                      onu.tensao != null && num(onu.tensao, 2, ' V'),
                    ].filter(Boolean).join(', ')}.
                  </p>
                </>
              )}

              {onu.alertas.length > 0 && (
                <ul className="alertas">{onu.alertas.map(a => <li key={a}>{a}</li>)}</ul>
              )}
            </section>

            <section>
              <div className="titulo-secao">
                <h2>Sinal no tempo</h2>
                <div className="segmentado" role="group" aria-label="Período">
                  {PERIODOS.map(x => (
                    <button key={x.h} className="chip" aria-pressed={horas === x.h} onClick={() => setHoras(x.h)}>{x.nome}</button>
                  ))}
                </div>
              </div>
              <Estado erro={sinais.erro} carregando={sinais.carregando} vazio={!sinais.dados}>
                {sinais.dados && (
                  <GraficoSinal
                    unidade="dBm"
                    faixas={[
                      { de: -99, ate: limites.rx_onu_critico, classe: 'f-critico' },
                      { de: limites.rx_onu_critico, ate: limites.rx_onu_atencao, classe: 'f-atencao' },
                      { de: limites.rx_onu_saturado, ate: 99, classe: 'f-saturado' },
                    ]}
                    series={[
                      { nome: 'RX ONU', classe: 's-desc', pontos: sinais.dados.onu.map(s => ({ t: Date.parse(s.coletado_em), v: s.rx })) },
                      { nome: 'RX OLT', classe: 's-sub', pontos: sinais.dados.olt.map(s => ({ t: Date.parse(s.coletado_em), v: s.rx_olt })) },
                    ]}
                  />
                )}
              </Estado>
              <p className="sutil">O fundo mostra as faixas de crítico e atenção do RX ONU.</p>
            </section>

            <section>
              <h2>Cadastro</h2>
              <dl className="cadastro">
                {onu.modelo_onu && <div><dt>Modelo da ONU</dt><dd>{onu.modelo_onu}{onu.versao_onu ? `, ${onu.versao_onu}` : ''}</dd></div>}
                <div><dt>Perfil de linha</dt><dd>{onu.line_profile ?? '—'}</dd></div>
                <div><dt>Perfil de serviço</dt><dd>{onu.service_profile ?? '—'}</dd></div>
                <div><dt>Última queda</dt><dd>{onu.last_down ?? '—'}{onu.last_down_cause ? ` (${onu.last_down_cause})` : ''}</dd></div>
                <div><dt>Último dying gasp</dt><dd>{onu.last_dying_gasp ?? '—'}</dd></div>
                <div><dt>Subiu em</dt><dd>{onu.last_up ?? '—'}</dd></div>
                <div><dt>Estado na OLT</dt><dd>{[onu.control_flag, onu.config_state, onu.match_state].filter(Boolean).join(', ')}</dd></div>
              </dl>
            </section>

            <section>
              <h2>Eventos desta ONU</h2>
              <AbaHistorico olt={{ id, portas_pon: [porta] }} porta={porta} onuId={onuId} />
            </section>
          </>
        )}
      </Estado>
    </main>
  )
}
