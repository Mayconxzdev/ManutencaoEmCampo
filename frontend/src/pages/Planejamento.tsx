/**
 * Planejamento — Substitui Prog. MAQ e Prog. EQUIP.
 * Planejamento de manutenção.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Calendar as CalendarIcon, List, Table as TableIcon, Filter, CheckCircle, AlertTriangle, Play, HelpCircle } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

const MONTHS_SHORT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

export default function Planejamento() {
  const [viewMode, setViewMode] = useState<'matrix' | 'list'>('matrix');
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [assetType, setAssetType] = useState<string>('');
  const [planningData, setPlanningData] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const fetchPlanning = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/planning`, {
        params: {
          year,
          type: assetType || undefined
        }
      });
      setPlanningData(res.data);
    } catch (err) {
      console.error("Erro ao carregar planejamento:", err);
    } finally {
      setLoading(false);
    }
  }, [assetType, year]);

  useEffect(() => {
    fetchPlanning();
  }, [fetchPlanning]);

  const handleGenerateOrders = async () => {
    if (!window.confirm('O sistema vai atualizar as programações futuras dos ativos operacionais. Nenhuma manutenção concluída será alterada. Deseja continuar?')) {
      return;
    }
    try {
      setMessage("Atualizando as programações futuras...");
      const res = await axios.post(`${API_URL}/planning/generate-orders`, null, {
        params: { horizon_months: 12 }
      });
      setMessage(res.data.message);
      fetchPlanning();
    } catch (err: any) {
      console.error("Erro ao rodar planejamento automático:", err);
      setMessage(err.response?.data?.detail || "Erro ao processar");
    }
  };

  const getCellContent = (cell: any) => {
    if (!cell) return <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>—</span>;

    // Se for histórico legado
    if (cell.source_value && !cell.friendly_number) {
      return (
        <div style={{
          backgroundColor: '#EDF2F7',
          color: '#4A5568',
          fontSize: '11px',
          padding: '4px 6px',
          borderRadius: '4px',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          fontWeight: 'bold',
          cursor: 'help'
        }} title={`Histórico legado: ${cell.source_value} (${cell.interpretation || 'Não interpretado'})`}>
          <HelpCircle size={10} />
          <span>{cell.source_value}</span>
        </div>
      );
    }

    // Se for ordem real
    let bg = '#EDF2F7';
    let color = '#4A5568';
    let icon = null;

    if (cell.needs_review) {
      bg = '#FEFCBF';
      color = '#744210';
      icon = <HelpCircle size={11} />;
    } else if (cell.execution_status === 'completed') {
      bg = '#C6F6D5';
      color = '#22543D';
      icon = <CheckCircle size={11} />;
    } else if (cell.status === 'overdue') {
      bg = '#FED7D7';
      color = '#742A2A';
      icon = <AlertTriangle size={11} />;
    } else if (cell.execution_status === 'in_progress') {
      bg = '#BEE3F8';
      color = '#2A4365';
      icon = <Play size={11} />;
    } else {
      bg = '#E2E8F0';
      color = '#2D3748';
      icon = <CalendarIcon size={11} />;
    }

    return (
      <div
        style={{
          backgroundColor: bg,
          color: color,
          fontSize: '11px',
          padding: '4px 6px',
          borderRadius: '4px',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          fontWeight: 'bold',
          cursor: 'pointer'
        }}
        onClick={() => {
          if (cell.id) {
            localStorage.setItem('mec_auto_open_order', cell.id);
            window.location.reload();
          }
        }}
      >
        {icon}
        <span>#{cell.friendly_number}</span>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Planejamento</h1>
          <p className="page-subtitle">Veja o planejamento dos equipamentos operacionais e organize as próximas rotinas.</p>
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            className="btn btn-secondary"
            onClick={handleGenerateOrders}
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <span>Atualizar programação futura</span>
          </button>
        </div>
      </div>

      {message && (
        <div style={{
          backgroundColor: 'var(--primary-light)',
          color: 'var(--primary)',
          padding: '12px 16px',
          borderRadius: '10px',
          fontWeight: '600',
          fontSize: '14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{message}</span>
          <button onClick={() => setMessage('')} className="btn-close-clean" style={{ background: 'none', border: 'none', color: 'var(--primary)', fontWeight: 'bold', cursor: 'pointer' }}>X</button>
        </div>
      )}

      {/* Barra de Filtros */}
      <div className="card" style={{ display: 'flex', gap: '16px', alignItems: 'center', padding: '16px 20px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontWeight: '600' }}>
          <Filter size={18} />
          <span>Filtros:</span>
        </div>

        <div style={{ width: '120px' }}>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="form-control" style={{ backgroundColor: 'white' }}>
            <option value={2026}>2026</option>
            <option value={2025}>2025</option>
            <option value={2024}>2024</option>
            <option value={2023}>2023</option>
          </select>
        </div>

        <div style={{ width: '160px' }}>
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="form-control" style={{ backgroundColor: 'white' }}>
            <option value="">Máquinas e equipamentos operacionais</option>
            <option value="machine">Máquinas</option>
            <option value="equipment">Equipamentos</option>
          </select>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: '4px', border: '1px solid var(--border)', borderRadius: '8px', padding: '4px' }}>
          <button
            onClick={() => setViewMode('matrix')}
            style={{
              border: 'none',
              padding: '6px 12px',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: viewMode === 'matrix' ? 'var(--primary)' : 'transparent',
              color: viewMode === 'matrix' ? 'white' : 'var(--text-main)',
              fontWeight: '600',
              fontSize: '13px'
            }}
          >
            <TableIcon size={16} />
            Matriz Anual
          </button>
          <button
            onClick={() => setViewMode('list')}
            style={{
              border: 'none',
              padding: '6px 12px',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: viewMode === 'list' ? 'var(--primary)' : 'transparent',
              color: viewMode === 'list' ? 'white' : 'var(--text-main)',
              fontWeight: '600',
              fontSize: '13px'
            }}
          >
            <List size={16} />
            Lista Ordenada
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontWeight: '600' }}>Carregando dados de planejamento...</div>
      ) : viewMode === 'matrix' ? (
        <div className="card" style={{ padding: '0px', overflowX: 'auto' }}>
          <table className="table" style={{ margin: '0px', width: '100%', minWidth: '900px' }}>
            <thead>
              <tr style={{ backgroundColor: 'var(--primary-light)', color: 'var(--primary)' }}>
                <th style={{ width: '110px' }}>Patrimônio</th>
                <th style={{ minWidth: '220px' }}>Descrição</th>
                {MONTHS_SHORT.map((m, idx) => (
                  <th key={idx} style={{ textAlign: 'center', width: '70px', fontSize: '12px' }}>{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {planningData.length === 0 ? (
                <tr>
                  <td colSpan={14} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>Nenhum ativo planejado encontrado para este ano.</td>
                </tr>
              ) : (
                planningData.map((row) => (
                  <tr key={row.asset_id}>
                    <td style={{ fontWeight: 'bold', fontSize: '13px', color: 'var(--primary)' }}>{row.patrimonio}</td>
                    <td style={{ fontSize: '13px' }}>
                      <div style={{ fontWeight: '600' }}>{row.description}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{row.type === 'machine' ? 'Máquina' : 'Equipamento'}</div>
                    </td>
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                      <td key={m} style={{ textAlign: 'center', padding: '8px 4px' }}>
                        {getCellContent(row.months[m])}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* Legenda Clara */}
          <div style={{
            borderTop: '1px solid var(--border)',
            padding: '16px 20px',
            display: 'flex',
            gap: '20px',
            flexWrap: 'wrap',
            fontSize: '12px',
            color: 'var(--text-muted)',
            fontWeight: '600',
            backgroundColor: '#F7FAFC'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '3px', backgroundColor: '#C6F6D5' }}></div>
              <span>Concluída (no prazo)</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '3px', backgroundColor: '#FED7D7' }}></div>
              <span>Atrasada confirmada</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '3px', backgroundColor: '#FEFCBF' }}></div>
              <span>Programação importada / a conferir</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '3px', backgroundColor: '#BEE3F8' }}></div>
              <span>Em Andamento</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '3px', backgroundColor: '#E2E8F0' }}></div>
              <span>Programada (Futura)</span>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {planningData.flatMap(row =>
            Object.entries(row.months)
              .filter(([_, cell]) => cell !== null)
              .map(([m, cell]: any) => ({
                patrimonio: row.patrimonio,
                description: row.description,
                asset_id: row.asset_id,
                month: Number(m),
                ...cell
              }))
          )
          .sort((a, b) => b.month - a.month)
          .map((item, idx) => (
            <div key={idx} className="card" style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontWeight: 'bold', color: 'var(--primary)' }}>{item.patrimonio}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>•</span>
                  <span style={{ fontWeight: '600' }}>{item.description}</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Competência: <b>{MONTHS_SHORT[item.month - 1]} / {year}</b> {item.friendly_number ? `(OM #${item.friendly_number})` : '(Histórico Legado)'}
                </div>
              </div>
              <div>
                {getCellContent(item)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
