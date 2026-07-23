/** Indicadores da qualidade com drill-down auditável por OM. */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Award, AlertTriangle, ShieldCheck, ListChecks } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

const MONTHS_FULL = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

const METRIC_LABELS: Record<string, string> = {
  planejado: 'Base planejada',
  realizado_no_prazo: 'No prazo',
  realizado_com_atraso: 'Concluídas com atraso',
  atrasado_atual_confirmado: 'Atrasadas confirmadas',
  a_conferir: 'A conferir',
  abertas: 'Abertas',
  em_execucao: 'Em execução',
  concluidas: 'Concluídas',
};

export default function Indicadores() {
  const navigate = useNavigate();
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [assetType, setAssetType] = useState<string>('');
  const [indicators, setIndicators] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [drilldown, setDrilldown] = useState<any>(null);
  const [drillLoading, setDrillLoading] = useState(false);

  const fetchIndicators = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/quality/indicators`, {
        params: { year, type: assetType || undefined },
      });
      setIndicators(res.data);
      setDrilldown(null);
    } catch (err) {
      console.error('Erro ao carregar indicadores:', err);
    } finally {
      setLoading(false);
    }
  }, [assetType, year]);

  useEffect(() => { fetchIndicators(); }, [fetchIndicators]);

  const openMetric = async (metric: string) => {
    setDrillLoading(true);
    try {
      const res = await axios.get(`${API_URL}/quality/indicators/drilldown`, {
        params: { year, type: assetType || undefined, metric },
      });
      setDrilldown(res.data);
    } finally {
      setDrillLoading(false);
    }
  };

  if (loading || !indicators) {
    return <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontWeight: '600' }}>Carregando indicadores da qualidade...</div>;
  }

  const cumprimento = indicators.cumprimento_anual.toFixed(1);
  const metaAtingida = indicators.cumprimento_anual >= indicators.meta;

  const metricCard = (metric: string, value: any) => (
    <button
      key={metric}
      type="button"
      onClick={() => openMetric(metric)}
      style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, backgroundColor: 'white', textAlign: 'left', cursor: 'pointer' }}
    >
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{METRIC_LABELS[metric] || metric}</div>
      <strong style={{ fontSize: 20 }}>{value ?? 0}</strong>
      <div style={{ fontSize: 11, color: 'var(--primary)', marginTop: 4 }}>Ver OMs usadas</div>
    </button>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title">Indicadores da Qualidade</h1>
          <p className="page-subtitle">Acompanhamento auditável de metas de manutenção preventiva.</p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="form-control" style={{ width: 110, backgroundColor: 'white' }}>
            <option value={2026}>2026</option>
            <option value={2025}>2025</option>
            <option value={2024}>2024</option>
          </select>
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="form-control" style={{ width: 180, backgroundColor: 'white' }}>
            <option value="">Todos os Ativos</option>
            <option value="machine">Apenas Máquinas</option>
            <option value="equipment">Apenas Equipamentos</option>
          </select>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 20 }}>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 24, textAlign: 'center', borderColor: metaAtingida ? '#C6F6D5' : '#FEEBC8', backgroundColor: metaAtingida ? '#F0FFF4' : '#FFFAF0' }}>
          <div style={{ width: 56, height: 56, borderRadius: '50%', backgroundColor: metaAtingida ? '#C6F6D5' : '#FEEBC8', color: metaAtingida ? '#22543D' : '#7B341E', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}><Award size={28} /></div>
          <span style={{ fontSize: 13, fontWeight: 'bold', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Cumprimento Anual</span>
          <span style={{ fontSize: 38, fontWeight: 800, color: metaAtingida ? '#22543D' : '#7B341E', margin: '8px 0px' }}>{cumprimento}%</span>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>Meta: <b>{indicators.meta}%</b> • {metaAtingida ? <span style={{ color: '#2F855A' }}>Atingida</span> : <span style={{ color: '#C05621' }}>Abaixo da meta</span>}</div>
        </div>
        {metricCard('atrasado_atual_confirmado', indicators.atrasado_atual_confirmado)}
        {metricCard('a_conferir', indicators.a_conferir)}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', padding: 20, justifyContent: 'space-between' }}>
          <span style={{ fontSize: 12, fontWeight: 'bold', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Máquinas Paradas</span>
          <div style={{ fontSize: 32, fontWeight: 800, color: indicators.maquinas_paradas > 0 ? '#C53030' : 'var(--text-main)', marginTop: 8 }}>{indicators.maquinas_paradas}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 12 }}>Ativos em estado crítico de parada no momento</div>
        </div>
      </div>

      <div className="card" style={{ padding: '18px 20px' }}>
        <h3 style={{ margin: '0 0 14px 0', fontSize: 15, color: 'var(--primary)' }}>Painel operacional</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
          {[
            ['Total de OMs', indicators.total_ordens], ['Abertas', indicators.abertas], ['Em execução', indicators.em_execucao], ['Concluídas', indicators.concluidas],
            ['Materiais pendentes', indicators.pendencias_material], ['Corretivas abertas', indicators.corretivas_abertas], ['Paradas abertas', indicators.paradas_abertas],
            ['Itens respondidos', `${indicators.itens_respondidos}/${indicators.itens_total}`], ['Preenchimento', `${(indicators.preenchimento_pct || 0).toFixed(1)}%`],
          ].map(([label, value]) => <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, backgroundColor: 'white' }}><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div><strong style={{ fontSize: 20 }}>{value}</strong></div>)}
        </div>
      </div>

      {indicators.composition && (
        <div className="card" style={{ padding: '18px 20px' }}>
          <h3 style={{ margin: '0 0 10px 0', fontSize: 15, color: 'var(--primary)', display: 'flex', alignItems: 'center', gap: 8 }}><ListChecks size={18} /> Composição auditável</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
            {['planejado', 'realizado_no_prazo', 'realizado_com_atraso', 'a_conferir', 'abertas', 'em_execucao', 'concluidas'].map((metric) => metricCard(metric, indicators.composition.metrics?.[metric]?.count))}
          </div>
          <p style={{ margin: '10px 0 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Clique em qualquer indicador para ver exatamente quais OMs formaram o número.</p>
        </div>
      )}

      {drilldown && (
        <div className="card" style={{ padding: '18px 20px' }}>
          <h3 style={{ margin: '0 0 10px 0', fontSize: 15, color: 'var(--primary)' }}>Drill-down: {METRIC_LABELS[drilldown.metric] || drilldown.metric} ({drilldown.total})</h3>
          {drillLoading ? <p>Carregando OMs...</p> : drilldown.items.length === 0 ? <p className="subtitle">Nenhuma OM nesta composição.</p> : (
            <div style={{ overflowX: 'auto' }}>
              <table className="table-modern" style={{ width: '100%' }}>
                <thead><tr><th>OM</th><th>Ativo</th><th>Competência</th><th>Status</th><th>Execução</th><th>Concluída</th></tr></thead>
                <tbody>
                  {drilldown.items.map((o: any) => (
                    <tr key={o.id}>
                      <td><button type="button" className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => navigate(`/ordens/${o.id}/executar`)}>OM {o.friendly_number || o.id.slice(0, 8)}</button></td>
                      <td>{o.asset_patrimonio} · {o.asset_description}</td>
                      <td>{o.planned_month || '-'} / {o.planned_year || '-'}</td>
                      <td>{o.status}</td><td>{o.execution_status}</td><td>{o.completed_at ? new Date(o.completed_at).toLocaleString('pt-BR') : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ padding: '24px 28px' }}>
        <h3 style={{ margin: '0 0 20px 0', fontSize: 16, fontWeight: 'bold', color: 'var(--primary)' }}>Cumprimento Mensal (%)</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {MONTHS_FULL.map((m, idx) => {
            const data = indicators.cumprimento_mensal[idx + 1] || { planejado: 0, realizado: 0, pct: 100 };
            const pct = data.pct.toFixed(0);
            return (
              <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <span style={{ width: 90, fontSize: 13, fontWeight: 600 }}>{m}</span>
                <div style={{ flex: 1, height: 20, backgroundColor: '#EDF2F7', borderRadius: 10, overflow: 'hidden', display: 'flex', alignItems: 'center' }}><div style={{ width: data.planejado > 0 ? `${pct}%` : '100%', height: '100%', backgroundColor: data.planejado > 0 && data.pct >= indicators.meta ? '#48BB78' : '#ECC94B' }} /></div>
                <span style={{ width: 80, fontSize: 13, fontWeight: 'bold', textAlign: 'right' }}>{data.planejado > 0 ? `${pct}%` : 'N/A'}</span>
                <button type="button" className="btn btn-secondary" style={{ width: 92, fontSize: 11, padding: '4px 8px' }} onClick={() => setDrilldown({ metric: `mensal_${idx + 1}`, total: data.order_ids?.length || 0, items: [], rules: indicators.composition?.rules || {} })}>{data.planejado > 0 ? `${data.realizado}/${data.planejado}` : '—'}</button>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 20 }}>
        <div className="card" style={{ padding: '20px 24px' }}>
          <h3 style={{ fontSize: 15, fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 8, color: '#744210', margin: '0 0 16px 0' }}><AlertTriangle size={18} /> <span>Pendências de Configuração</span></h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span>Ativos sem planejamento configurado:</span><b style={{ color: indicators.ativos_sem_plano > 0 ? '#C53030' : 'inherit' }}>{indicators.ativos_sem_plano}</b></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, borderTop: '1px solid var(--border)', paddingTop: 10 }}><span>Registros legados aguardando revisão em lote:</span><b>{indicators.a_conferir}</b></div>
          </div>
        </div>
        <div className="card" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}><ShieldCheck size={40} style={{ color: 'var(--primary)' }} /><div><h4 style={{ margin: 0, fontSize: 14, fontWeight: 'bold' }}>Rastreabilidade</h4><p style={{ margin: '4px 0 0 0', fontSize: 12, color: 'var(--text-muted)' }}>A API devolve regras, filtros e IDs das OMs usadas em cada métrica.</p></div></div>
        </div>
      </div>
    </div>
  );
}
