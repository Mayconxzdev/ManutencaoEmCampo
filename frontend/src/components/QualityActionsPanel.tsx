import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import axios from 'axios';
import { AlertTriangle, CheckCircle2, ClipboardCheck, PlusCircle } from 'lucide-react';
import { useToast } from './toastContext';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type Asset = { id: string; patrimonio: string; controlled_code?: string | null; description: string; show_in_daily_list?: boolean; sector?: { name: string } | null };
type NC = { id: string; code: string; title: string; description: string; severity: string; status: string; asset_id?: string | null; detected_at?: string | null; due_date?: string | null; action_owner_name?: string | null };

const severityLabel: Record<string, string> = { low: 'Baixa', medium: 'Média', high: 'Alta', critical: 'Crítica' };
const statusLabel: Record<string, string> = { open: 'Aberta', contained: 'Contida', action_in_progress: 'Em correção', effectiveness_pending: 'Aguardando verificação', closed: 'Encerrada', reopened: 'Reaberta' };

/** Fluxo simples da Qualidade: problema, responsável, prazo, ação e histórico. */
export default function QualityActionsPanel() {
  const toast = useToast();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [items, setItems] = useState<NC[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ asset_id: '', title: '', description: '', severity: 'medium', action_owner_name: '', due_date: '' });

  const load = async () => {
    setLoading(true);
    try {
      const [nc, assetResult] = await Promise.all([
        axios.get<NC[]>(`${API_URL}/v2/quality/nonconformities`),
        axios.get<Asset[]>(`${API_URL}/assets`),
      ]);
      setItems(nc.data);
      setAssets((assetResult.data || []).filter((asset) => asset.show_in_daily_list !== false));
    } catch {
      toast.error('Erro', 'Não foi possível carregar os apontamentos da Qualidade.');
    } finally { setLoading(false); }
  };

  // oxlint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.asset_id || !form.title.trim() || !form.description.trim()) return;
    setSaving(true);
    try {
      await axios.post(`${API_URL}/v2/quality/nonconformities`, {
        ...form,
        title: form.title.trim(),
        description: form.description.trim(),
        detected_by_name: sessionStorage.getItem('mec_operator_name') || 'Pessoa não informada',
        detected_by_operator_id: sessionStorage.getItem('mec_operator_id') || undefined,
        device_id: navigator.userAgent.slice(0, 100),
        due_date: form.due_date || undefined,
      });
      setForm({ asset_id: '', title: '', description: '', severity: 'medium', action_owner_name: '', due_date: '' });
      toast.success('Registrado', 'Problema registrado para acompanhamento da Qualidade.');
      await load();
    } catch (error: any) {
      toast.error('Erro', error?.response?.data?.detail || 'Não foi possível registrar o problema.');
    } finally { setSaving(false); }
  };

  return <div style={{ display: 'grid', gap: 20 }}>
    <section className="card" style={{ padding: 18 }}>
      <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, fontSize: 20 }}><PlusCircle size={20} /> Registrar problema para acompanhar</h2>
      <p className="subtitle" style={{ margin: '8px 0 16px' }}>Use quando a manutenção encontrar algo que precisa de ação, prazo ou verificação posterior. Isso não bloqueia o uso do aplicativo.</p>
      <form onSubmit={create} style={{ display: 'grid', gap: 12 }}>
        <label className="form-group"><span className="form-label">Equipamento</span><select className="form-control" value={form.asset_id} onChange={(event) => setForm({ ...form, asset_id: event.target.value })} required><option value="">Escolha o equipamento</option>{assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.controlled_code || asset.patrimonio} — {asset.description}{asset.sector?.name ? ` (${asset.sector.name})` : ''}</option>)}</select></label>
        <label className="form-group"><span className="form-label">O que foi encontrado?</span><input className="form-control" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Ex.: Vazamento identificado na conexão pneumática" required /></label>
        <label className="form-group"><span className="form-label">Descrição para quem vai resolver</span><textarea className="form-control" rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Explique o local, o risco percebido e o que precisa ser verificado." required /></label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          <label className="form-group"><span className="form-label">Urgência</span><select className="form-control" value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })}><option value="low">Baixa</option><option value="medium">Média</option><option value="high">Alta</option><option value="critical">Crítica</option></select></label>
          <label className="form-group"><span className="form-label">Quem deve acompanhar</span><input className="form-control" value={form.action_owner_name} onChange={(event) => setForm({ ...form, action_owner_name: event.target.value })} placeholder="Nome da pessoa" /></label>
          <label className="form-group"><span className="form-label">Prazo desejado</span><input className="form-control" type="date" value={form.due_date} onChange={(event) => setForm({ ...form, due_date: event.target.value })} /></label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Registrando...' : 'Registrar para acompanhamento'}</button>
      </form>
    </section>
    <section className="card" style={{ padding: 18 }}>
      <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, fontSize: 20 }}><ClipboardCheck size={20} /> Problemas registrados ({items.length})</h2>
      {loading ? <p>Carregando...</p> : items.length === 0 ? <p style={{ color: 'var(--text-muted)' }}><CheckCircle2 size={16} style={{ verticalAlign: 'text-bottom' }} /> Nenhum problema formal em acompanhamento.</p> : <div style={{ display: 'grid', gap: 10, marginTop: 14 }}>{items.map((item) => <article key={item.id} style={{ padding: 12, border: '1px solid var(--border)', borderLeft: `4px solid ${item.severity === 'critical' ? 'var(--danger)' : 'var(--warning)'}`, borderRadius: 8 }}><div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', flexWrap: 'wrap' }}><strong><AlertTriangle size={15} style={{ verticalAlign: 'text-bottom' }} /> {item.code} — {item.title}</strong><span className="asset-badge">{statusLabel[item.status] || item.status}</span></div><p style={{ margin: '7px 0', fontSize: 13 }}>{item.description}</p><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Urgência: {severityLabel[item.severity] || item.severity} · Responsável: {item.action_owner_name || 'A definir'} · Prazo: {item.due_date || 'Não definido'}</div></article>)}</div>}
    </section>
  </div>;
}
