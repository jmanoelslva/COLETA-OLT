import { Link } from 'react-router-dom'
import { api, type DetalheOlt } from '../../api'
import { Estado, Sev, useDados } from '../../componentes/comum'

export function AbaDiagnostico({ olt }: { olt: DetalheOlt }) {
  const { dados, erro, carregando, recarregar } = useDados(() => api.diagnostico(olt.id), [olt.id], 60_000)
  return (
    <Estado erro={erro} carregando={carregando} vazio={!dados} tentar={recarregar}>
      {dados?.length === 0 && <p className="vazio">Nada fora do normal na última coleta.</p>}
      <ol className="incidentes">
        {dados?.map((i, n) => (
          <li key={n} className={`incidente borda-${i.severidade}`}>
            <div className="incidente-topo">
              <Sev s={i.severidade} />
              <h3>{i.titulo}</h3>
            </div>
            {i.descricao && <p className="cliente">{i.descricao}</p>}
            <p>{i.texto}</p>
            {i.onus && i.onus.length > 0 && i.porta != null && (
              <p className="links-onus">
                {i.onus.slice(0, 12).map(o => (
                  <Link key={o} to={`/olt/${olt.id}/onu/${i.porta}/${o}`}>{i.porta}/{o}</Link>
                ))}
                {i.onus.length > 12 && <span className="sutil">e mais {i.onus.length - 12}</span>}
              </p>
            )}
          </li>
        ))}
      </ol>
    </Estado>
  )
}
