import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { AlertTriangle, CheckCircle2, ClipboardList, PlayCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../components/toastContext';
import { formatManutencaoEmCampoDateTime } from '../utils/dateTime';

const API_URL = window.location.port === '5173' ? `http://${window.location.hostname}:8000` : window.location.origin;

type Pending = {
  id: string; friendly_number?: number | null; asset_code?: string | null; asset_description?: string | null;
  asset_sector?: string | null; started_at?: string | null; age_days: number; answered_items: number; total_items: number; started_by?: string | null;
};

export default function ManutencoesPendentesRevisar() {
  const navigate = useNavigate();
  const toast = useToast();
  const [items, setItems] = useState<Pending[]>([]);
  const [loading, setLoading] = useState(true);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [working, setWorking] = useState<string | null>(null);
  const selectedUserId = sessionStorage.getItem('mec_operator_id') || '';
  const operatorName = sessionStorage.getItem('mec_operator_name') || '';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_URL}/v2/execution/drafts`, { params: { alert_from_days: 2 } });
      setItems(response.data?.items || []);
    } catch (error: any) {
      toast.error('Não foi possível abrir a fila', error?.response?.data?.detail || 'Tente novamente.');
    } finally { setLoading(false); }
  }, [toast]);
  useEffect(() => { void load(); }, [load]);

  const decide = async (order: Pending, decision: 'continue' | 'test_draft' | 'not_performed') => {
    setWorking(`${order.id}-${decision}`);
    try {
      const response = await axios.post(`${API_URL}/v2/orders/${order.id}/execution-review`, {
        decision, notes: notes[order.id] || '', selected_user_id: selectedUserId, operator_name: operatorName,
      });
      toast.success('Revisão registrada', response.data?.message || 'Registro preservado.');
      if (decision === 'continue') navigate(`/ordens/${order.id}/executar`);
      else setItems(current => current.filter(item => item.id !== order.id));
    } catch (error: any) {
      toast.error('Não foi possível registrar', error?.response?.data?.detail || 'Tente novamente.');
    } finally { setWorking(null); }
  };

  return <main className="page-shell" style={{ maxWidth: 1040 }}>
    <header style={{ display: 'grid', gap: 6, marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><ClipboardList color="var(--primary)" /><h1 style={{ margin: 0 }}>Manutenções pendentes para revisar</h1></div>
      <p style={{ margin: 0, color: 'var(--text-muted)' }}>Aqui ficam todos os checklists iniciados, inclusive os de hoje. Separe a manutenção real de teste ou de uma tentativa que não aconteceu. Nada é apagado.</p>
    </header>
    {loading ? <p>Carregando pendências…</p> : items.length === 0 ? <section className="empty-state"><CheckCircle2 size={38} color="var(--success)" /><h2>Nenhum checklist em andamento</h2><p>O aplicativo está pronto para iniciar a operação real.</p></section> : <section style={{ display: 'grid', gap: 12 }}>
      {items.map(order => <article key={order.id} className="card" style={{ padding: 16, display: 'grid', gap: 10, borderLeft: '4px solid var(--warning)' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'start' }}><AlertTriangle color={order.age_days >= 2 ? 'var(--warning)' : 'var(--primary)'} /><div><strong>{order.asset_description || 'Equipamento sem descrição'}</strong><div style={{ color: 'var(--text-muted)', fontSize: 14 }}>OM {order.friendly_number || '—'} · Código: {order.asset_code || 'não informado'} · {order.asset_sector || 'Setor não informado'}</div><div style={{ color: 'var(--text-muted)', fontSize: 14 }}>Iniciada por {order.started_by || 'não informado'} em {formatManutencaoEmCampoDateTime(order.started_at)} · {order.answered_items}/{order.total_items} itens respondidos</div></div></div>
        <textarea className="form-control" rows={2} value={notes[order.id] || ''} onChange={event => setNotes(current => ({ ...current, [order.id]: event.target.value }))} placeholder="Observação da revisão (opcional)" />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" disabled={!!working} onClick={() => decide(order, 'continue')}><PlayCircle size={16} /> É real: continuar checklist</button>
          <button className="btn btn-secondary" disabled={!!working} onClick={() => decide(order, 'test_draft')}>Foi teste no aplicativo</button>
          <button className="btn btn-secondary" disabled={!!working} onClick={() => decide(order, 'not_performed')}>Não foi realizada</button>
        </div>
      </article>)}
    </section>}
  </main>;
}
