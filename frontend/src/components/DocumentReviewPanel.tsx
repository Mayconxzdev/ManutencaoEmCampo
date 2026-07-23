import { CheckCircle, FileSearch, RefreshCcw, AlertTriangle, Eye } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type ReviewItem = {
  id: string;
  file_name: string;
  source_path: string;
  status: string;
  reason_code?: string;
  reason_message?: string;
  suggested_asset_id?: string | null;
  selected_asset_id?: string | null;
  file_hash?: string | null;
};

type AssetOption = { id: string; patrimonio: string; description: string };

export default function DocumentReviewPanel() {
  const [summary, setSummary] = useState<any>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [assets, setAssets] = useState<AssetOption[]>([]);
  const [status, setStatus] = useState('pending');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [assetByItem, setAssetByItem] = useState<Record<string, string>>({});
  const [ocrJobs, setOcrJobs] = useState<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [summaryRes, itemsRes, assetsRes, ocrRes] = await Promise.all([
        axios.get(`${API_URL}/v2/document-review/summary`),
        axios.get(`${API_URL}/v2/document-review/items`, { params: { status, limit: 80 } }),
        axios.get(`${API_URL}/v2/assets`, { params: { page_size: 500 } }),
        axios.get(`${API_URL}/v2/document-review/ocr/jobs`, { params: { limit: 20 } }),
      ]);
      setSummary(summaryRes.data);
      setItems(itemsRes.data.items || []);
      setAssets(assetsRes.data.items || []);
      setOcrJobs(ocrRes.data.items || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao carregar revisão documental.');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const decide = async (item: ReviewItem, action: string) => {
    setMessage('');
    setError('');
    try {
      await axios.post(`${API_URL}/v2/document-review/items/${item.id}/decision`, {
        action,
        selected_asset_id: assetByItem[item.id] || item.suggested_asset_id,
        operator_name: sessionStorage.getItem('mec_operator_name') || undefined,
        selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined,
      });
      setMessage('Decisão registrada.');
      await load();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao registrar decisão.');
    }
  };

  const createOcrJob = async (item: ReviewItem) => {
    setMessage('');
    setError('');
    try {
      await axios.post(`${API_URL}/v2/document-review/ocr/jobs`, {
        source_kind: 'file_review_item',
        source_id: item.id,
        run_now: false,
        operator_name: sessionStorage.getItem('mec_operator_name') || undefined,
        selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined,
      });
      setMessage('OCR/extração textual enfileirado.');
      await load();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao executar OCR.');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}><FileSearch size={20} /> Revisão documental e OCR</h3>
          <p className="subtitle">Fila humana para arquivos ambíguos, duplicados, sem ativo claro ou que precisam OCR.</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={load} disabled={loading}><RefreshCcw size={16} /> Atualizar</button>
      </div>
      {message && <div className="card" style={{ color: 'var(--success)', display: 'flex', gap: 8 }}><CheckCircle size={18} /> {message}</div>}
      {error && <div className="card" style={{ color: 'var(--danger)', display: 'flex', gap: 8 }}><AlertTriangle size={18} /> {error}</div>}
      <div className="card" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <select className="form-control" value={status} onChange={(e) => setStatus(e.target.value)} style={{ maxWidth: 220 }}>
          <option value="pending">Pendentes</option>
          <option value="duplicate">Duplicados</option>
          <option value="conflict">Conflitos</option>
          <option value="ignored">Ignorados</option>
          <option value="resolved">Resolvidos</option>
          <option value="all">Todos</option>
        </select>
        {(summary?.file_review || []).map((row: any) => <span key={row.status} className="status-pill">{row.status}: {row.total}</span>)}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {items.length === 0 ? <div className="card subtitle">Nenhum item nesta fila.</div> : items.map((item) => (
          <div key={item.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <strong>{item.file_name}</strong>
                <div className="subtitle" style={{ fontSize: 12 }}>{item.source_path}</div>
                {item.reason_message && <div style={{ fontSize: 12, color: 'var(--warning)' }}>{item.reason_code}: {item.reason_message}</div>}
              </div>
              <span className="status-pill">{item.status}</span>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <select className="form-control" value={assetByItem[item.id] || item.suggested_asset_id || ''} onChange={(e) => setAssetByItem((cur) => ({ ...cur, [item.id]: e.target.value }))} style={{ minWidth: 260, maxWidth: 420 }}>
                <option value="">Selecione o ativo...</option>
                {assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.patrimonio} · {asset.description}</option>)}
              </select>
              <button className="btn btn-primary" type="button" onClick={() => decide(item, 'approve')}><CheckCircle size={15} /> Aprovar/vincular</button>
              <button className="btn btn-secondary" type="button" onClick={() => decide(item, 'duplicate')}>Duplicado</button>
              <button className="btn btn-secondary" type="button" onClick={() => decide(item, 'ignore')}>Ignorar</button>
              <button className="btn btn-secondary" type="button" onClick={() => createOcrJob(item)}><Eye size={15} /> OCR</button>
            </div>
          </div>
        ))}
      </div>
      <div className="card">
        <h4 style={{ marginTop: 0 }}>Últimos OCRs</h4>
        {ocrJobs.length === 0 ? <p className="subtitle">Nenhum job OCR registrado.</p> : ocrJobs.map((job) => (
          <div key={job.id} style={{ borderTop: '1px solid var(--border)', padding: '8px 0', fontSize: 12 }}>
            <strong>{job.status}</strong> · {job.method || 'sem método'} · {job.file_path}
            {job.text_preview && <div className="subtitle">{job.text_preview}</div>}
            {job.error_message && <div style={{ color: 'var(--warning)' }}>{job.error_message}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
