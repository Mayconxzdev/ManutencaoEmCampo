import { RefreshCcw, WifiOff, CheckCircle, AlertTriangle } from 'lucide-react';
import { useEffect, useState } from 'react';
import axios from 'axios';
import { getQueuedOperations, syncQueuedOperations } from '../db';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type LocalOp = {
  id: string;
  type: string;
  order_id: string;
  created_at: string;
  attempts: number;
  last_error?: string;
};

export default function OfflineSyncPanel() {
  const [localOps, setLocalOps] = useState<LocalOp[]>([]);
  const [serverStatus, setServerStatus] = useState<any>(null);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    const queued = await getQueuedOperations();
    setLocalOps(queued as any);
    try {
      const response = await axios.get(`${API_URL}/v2/offline/status`);
      setServerStatus(response.data);
    } catch {
      setServerStatus(null);
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 10000);
    return () => window.clearInterval(timer);
  }, []);

  const syncNow = async () => {
    setSyncing(true);
    setMessage('');
    setError('');
    try {
      const result = await syncQueuedOperations();
      setMessage(`Sincronização concluída: ${result.synced} aplicada(s), ${result.failed} com falha.`);
      await load();
    } catch (err: any) {
      setError(err?.message || 'Erro ao sincronizar fila offline.');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}><WifiOff size={20} /> Fila offline e sincronização</h3>
          <p className="subtitle">Operações salvas no navegador quando a rede falhar. A API 1.9.2 aplica com idempotência.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={syncNow} disabled={syncing || localOps.length === 0}>
          <RefreshCcw size={16} /> {syncing ? 'Sincronizando...' : `Sincronizar agora (${localOps.length})`}
        </button>
      </div>
      {message && <div className="card" style={{ color: 'var(--success)', display: 'flex', gap: 8 }}><CheckCircle size={18} /> {message}</div>}
      {error && <div className="card" style={{ color: 'var(--danger)', display: 'flex', gap: 8 }}><AlertTriangle size={18} /> {error}</div>}
      <div className="card">
        <h4 style={{ marginTop: 0 }}>Pendentes neste dispositivo</h4>
        {localOps.length === 0 ? <p className="subtitle">Nenhuma operação offline pendente.</p> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {localOps.map((op) => (
              <div key={op.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
                <strong>{op.type}</strong> · OM {op.order_id?.slice(0, 8)} · {new Date(op.created_at).toLocaleString('pt-BR')}
                {op.last_error && <div style={{ color: 'var(--danger)', fontSize: 12 }}>{op.last_error}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card">
        <h4 style={{ marginTop: 0 }}>Histórico recebido pelo servidor</h4>
        {!serverStatus?.available ? <p className="subtitle">Tabela de sync ainda não disponível ou servidor offline.</p> : (
          <>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              {(serverStatus.counts || []).map((row: any) => <span key={row.status} className="status-pill">{row.status}: {row.total}</span>)}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(serverStatus.recent || []).map((row: any) => (
                <div key={row.client_op_id} style={{ fontSize: 12, borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                  <strong>{row.operation_type}</strong> · {row.status} · tentativas {row.attempts} {row.last_error ? `· ${row.last_error}` : ''}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
