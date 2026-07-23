/**
 * ConferirProgramacoes — Tela de Conferência das Programações.
 * Conferência de programações de manutenção.
 * Permite auditar e resolver as ordens antigas classificadas como "a conferir".
 */
import { useState, useEffect } from 'react';
import axios from 'axios';
import { HelpCircle, Check, X, AlertCircle } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

export default function ConferirProgramacoes() {
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const fetchOrders = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/quality/review`);
      setOrders(res.data);
    } catch (err) {
      console.error("Erro ao carregar ordens para revisão:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders();
  }, []);

  const handleResolve = async (orderId: string, decision: string) => {
    try {
      await axios.post(`${API_URL}/quality/review/${orderId}`, null, {
        params: {
          decision,
          notes: "Resolvido via auditoria em lote",
          operator_name: sessionStorage.getItem('mec_operator_name') || "Auditor"
        }
      });
      setMessage("Decisão salva com sucesso.");
      // Atualizar lista local
      setOrders(prev => prev.filter(o => o.id !== orderId));
    } catch (err) {
      console.error("Erro ao salvar decisão de revisão:", err);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h1 className="page-title">Histórico Legado — Situações a Conferir</h1>
        <p className="page-subtitle">Auditoria técnica e regularização das programações antigas sem evidência de execução (seção 11 e 12)</p>
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
          <button onClick={() => setMessage('')} style={{ background: 'none', border: 'none', color: 'var(--primary)', fontWeight: 'bold', cursor: 'pointer' }}>X</button>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>Carregando programações para conferência...</div>
      ) : orders.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          <Check size={48} style={{ color: '#48BB78', marginBottom: '16px' }} />
          <h3 style={{ fontSize: '16px', fontWeight: 'bold', margin: '0px' }}>Tudo em ordem!</h3>
          <p style={{ margin: '8px 0px 0px 0px', fontSize: '13px' }}>Nenhuma programação antiga necessita de conferência ou regularização pendente no momento.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="card" style={{
            backgroundColor: '#FFFAF0',
            borderColor: '#FEEBC8',
            color: '#7B341E',
            padding: '16px 20px',
            fontSize: '13px',
            fontWeight: '600',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            <AlertCircle size={20} />
            <span>Existem {orders.length} programações que necessitam de sua validação. Elas não afetarão as metas ou os contadores atuais enquanto não forem conferidas.</span>
          </div>

          {orders.map(order => (
            <div key={order.id} className="card" style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontWeight: 'bold', color: 'var(--primary)', fontSize: '15px' }}>{order.asset.patrimonio}</span>
                  <span style={{ color: 'var(--text-muted)' }}>•</span>
                  <span style={{ fontWeight: '700' }}>{order.asset.description}</span>
                  <span style={{
                    backgroundColor: '#EDF2F7',
                    color: '#4A5568',
                    fontSize: '11px',
                    fontWeight: 'bold',
                    padding: '2px 6px',
                    borderRadius: '4px'
                  }}>{order.asset.sector.name}</span>
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '6px' }}>
                  Competência Planejada: <b>{order.planned_month}/{order.planned_year}</b> • Código original: <b>#{order.friendly_number}</b>
                </div>
              </div>

              {/* Botões de Ação */}
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => handleResolve(order.id, 'completed_on_time')}
                  className="btn"
                  style={{
                    backgroundColor: '#C6F6D5',
                    color: '#22543D',
                    border: 'none',
                    padding: '8px 12px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    borderRadius: '6px'
                  }}
                >
                  <Check size={14} />
                  Concluída no Prazo
                </button>

                <button
                  onClick={() => handleResolve(order.id, 'not_applicable')}
                  className="btn"
                  style={{
                    backgroundColor: '#E2E8F0',
                    color: '#2D3748',
                    border: 'none',
                    padding: '8px 12px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    borderRadius: '6px'
                  }}
                >
                  <X size={14} />
                  Não Aplicada
                </button>

                <button
                  onClick={() => handleResolve(order.id, 'completed_with_delay')}
                  className="btn"
                  style={{
                    backgroundColor: '#FEEBC8',
                    color: '#744210',
                    border: 'none',
                    padding: '8px 12px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    borderRadius: '6px'
                  }}
                >
                  <HelpCircle size={14} />
                  Pendente / Atraso Real
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
