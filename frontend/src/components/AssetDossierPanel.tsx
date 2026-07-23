import { useEffect, useState } from 'react';
import axios from 'axios';
import { AlertTriangle, CheckCircle2, FileArchive, FolderSync, Image, RefreshCw, ShieldCheck, UserRound } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type Traceability = {
  asset: { patrimonio: string; description: string };
  history: Array<{
    order_id: string;
    friendly_number?: number | null;
    competence?: string | null;
    completed_at?: string | null;
    status: string;
    final_condition?: string | null;
    checked_by_name?: string | null;
    performed_by_name?: string | null;
    final_pdf_path?: string | null;
    final_pdf_sha256?: string | null;
    final_revision?: number | null;
    events: Array<{ type: string; at?: string | null; operator_name?: string | null }>;
    evidences: Array<{ id: string; type: string; uploaded_at?: string | null; uploader_name?: string | null; dossier_status?: string | null; dossier_path?: string | null }>;
  }>;
  dossier_jobs: Array<{ id: string; status: string; target_path?: string | null; completed_at?: string | null; last_error?: string | null }>;
  nonconformities: Array<{ id: string; code: string; title: string; status: string; severity: string; due_date?: string | null }>;
};

function formatDate(value?: string | null) {
  if (!value) return 'Não informado';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('pt-BR');
}

function conditionLabel(value?: string | null) {
  if (value === 'stopped') return 'Parada';
  if (value === 'released_with_attention') return 'Apta com atenção';
  if (value === 'released') return 'Apta';
  return 'Em registro';
}

/** Prontuário legível do ativo: histórico, evidências, NAS e qualidade. */
export default function AssetDossierPanel({ assetId }: { assetId: string }) {
  const [data, setData] = useState<Traceability | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const response = await axios.get<Traceability>(`${API_URL}/v2/assets/${assetId}/traceability`);
      setData(response.data);
      setError('');
    } catch {
      setError('Não foi possível carregar o prontuário deste equipamento agora. Os registros anteriores não foram apagados.');
    } finally {
      setLoading(false);
    }
  };

  // `load` é propositalmente recriada para atualizar estado local; a troca de
  // ativo é a dependência funcional desta consulta.
  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [assetId]);

  const sync = async () => {
    setSyncing(true);
    try {
      await axios.post(`${API_URL}/v2/assets/${assetId}/dossier/sync`);
      await load();
    } catch {
      setError('A cópia para o NAS não pôde ser atualizada agora. O sistema mantém o original local e tentará novamente.');
    } finally {
      setSyncing(false);
    }
  };

  if (loading) return <p>Carregando prontuário do equipamento...</p>;
  if (error) return <div className="card" style={{ color: 'var(--danger)', padding: 16 }}>{error}</div>;
  if (!data) return null;

  const latestJob = data.dossier_jobs[0];
  const synced = latestJob?.status === 'synced' || latestJob?.status === 'completed';

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <section className="card" style={{ padding: 16, background: 'var(--bg-app)' }}>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, display: 'flex', gap: 8, alignItems: 'center' }}><FileArchive size={19} /> Prontuário completo</h3>
            <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
              Aqui ficam as manutenções, responsáveis, checklists, fotos, documentos e apontamentos deste equipamento.
            </p>
          </div>
          <button className="btn btn-secondary" type="button" onClick={sync} disabled={syncing}>
            <FolderSync size={16} /> {syncing ? 'Atualizando cópia...' : 'Atualizar cópia no NAS'}
          </button>
        </div>
        <div style={{ marginTop: 12, fontSize: 13, display: 'flex', gap: 8, alignItems: 'center', color: synced ? 'var(--success)' : 'var(--warning)' }}>
          {synced ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {synced ? 'Cópia do dossiê conferida no NAS.' : 'Cópia no NAS aguardando nova tentativa; o registro local está preservado.'}
        </div>
        {latestJob?.target_path && <code style={{ display: 'block', marginTop: 8, fontSize: 11, overflowWrap: 'anywhere', color: 'var(--text-muted)' }}>{latestJob.target_path}</code>}
      </section>

      <section className="card" style={{ padding: 16 }}>
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Manutenções deste equipamento ({data.history.length})</h3>
        {data.history.length === 0 ? <p style={{ color: 'var(--text-muted)' }}>Ainda não há manutenção concluída ou registrada neste equipamento.</p> : (
          <div style={{ display: 'grid', gap: 12 }}>
            {data.history.map((order) => {
              return (
                <article key={order.order_id} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <strong>Manutenção {order.friendly_number ? `OM nº ${order.friendly_number}` : ''} {order.competence ? `· ${order.competence}` : ''}</strong>
                    <span className="asset-badge">{conditionLabel(order.final_condition)}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 8, color: 'var(--text-muted)', fontSize: 13 }}>
                    <span><UserRound size={14} style={{ verticalAlign: 'text-bottom' }} /> Executada por: {order.performed_by_name || 'Não informado'}</span>
                    <span><UserRound size={14} style={{ verticalAlign: 'text-bottom' }} /> Conferida por: {order.checked_by_name || 'Não informado'}</span>
                    <span>Concluída: {formatDate(order.completed_at)}</span>
                    <span><Image size={14} style={{ verticalAlign: 'text-bottom' }} /> Evidências: {order.evidences.length}</span>
                  </div>
                  {order.evidences.length > 0 && (
                    <p style={{ margin: '9px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
                      {order.evidences.map((evidence) => `${evidence.type}${evidence.uploader_name ? ` (${evidence.uploader_name})` : ''}`).join(' · ')}
                    </p>
                  )}
                  {order.final_pdf_path && (
                    <a
                      href={`${API_URL}/v2/orders/${order.order_id}/final-pdf?revision=${order.final_revision || 1}&sha=${encodeURIComponent(order.final_pdf_sha256 || '')}`}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-secondary btn-sm"
                      style={{ marginTop: 10, display: 'inline-block' }}
                    >
                      Abrir PDF final arquivado
                    </a>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="card" style={{ padding: 16 }}>
        <h3 style={{ marginTop: 0, display: 'flex', gap: 8, alignItems: 'center', fontSize: 16 }}><ShieldCheck size={18} /> Problemas e ações a acompanhar</h3>
        {data.nonconformities.length === 0 ? <p style={{ color: 'var(--text-muted)' }}>Nenhuma não conformidade formal aberta para este equipamento.</p> : (
          <div style={{ display: 'grid', gap: 8 }}>
            {data.nonconformities.map((item) => <div key={item.id} style={{ borderLeft: '4px solid var(--warning)', paddingLeft: 10 }}><strong>{item.code} — {item.title}</strong><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Situação: {item.status} · Prazo: {item.due_date || 'não definido'}</div></div>)}
          </div>
        )}
      </section>

      <button className="btn btn-secondary" type="button" onClick={load}><RefreshCw size={16} /> Atualizar informações</button>
    </div>
  );
}
