import { Activity, CheckCircle, Database, RefreshCcw, ShieldAlert, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type Readiness = {
  generated_at: string;
  version: string;
  status: 'ready' | 'attention' | 'blocked' | string;
  score: number;
  blockers: string[];
  warnings: string[];
  database?: {
    alembic_revision?: string | null;
    counts?: Record<string, number | null>;
    integrity?: {
      integrity_ok?: boolean;
      foreign_key_ok?: boolean;
      integrity_check?: string[];
      foreign_key_violations?: unknown[];
    };
  };
  search?: {
    fts5_available?: boolean;
    indexed_rows?: number;
    needs_rebuild?: boolean;
  };
  transcription?: any;
  storage?: any;
  paths?: any;
  backup?: any;
};

function statusLabel(status: string) {
  if (status === 'ready') return 'Pronto';
  if (status === 'attention') return 'Atenção';
  if (status === 'blocked') return 'Bloqueado';
  return status;
}

function statusIcon(status: string) {
  if (status === 'ready') return <ShieldCheck size={20} />;
  if (status === 'blocked') return <ShieldAlert size={20} />;
  return <Activity size={20} />;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '-';
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

export default function SystemDiagnostics() {
  const [report, setReport] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [savedMessage, setSavedMessage] = useState('');
  const [epiMissing, setEpiMissing] = useState<any | null>(null);

  const loadReport = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.get<Readiness>(`${API_URL}/v2/system/readiness`);
      setReport(response.data);
      axios.get(`${API_URL}/v2/quality/epi-missing`)
        .then((epiResponse) => setEpiMissing(epiResponse.data))
        .catch(() => setEpiMissing(null));
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao carregar diagnóstico.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReport();
  }, []);

  const rebuildSearch = async () => {
    setLoading(true);
    try {
      await axios.post(`${API_URL}/v2/search/rebuild`);
      await loadReport();
    } finally {
      setLoading(false);
    }
  };

  const saveValidation = async () => {
    setSaving(true);
    setSavedMessage('');
    try {
      const operator = sessionStorage.getItem('mec_operator_name') || undefined;
      const response = await axios.post(`${API_URL}/v2/system/validation-run`, null, {
        params: { executed_by: operator, kind: 'manual_ui' },
      });
      const saved = response.data?.persistence?.saved;
      setSavedMessage(saved ? 'Validação salva no histórico técnico.' : 'Diagnóstico gerado, mas migration da tabela técnica ainda não foi aplicada.');
      setReport(response.data?.report || report);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Database size={20} /> Diagnóstico e prontidão operacional
          </h3>
          <p className="subtitle">Use antes de liberar uma versão no ambiente real ou antes do Codex auditar.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" type="button" onClick={loadReport} disabled={loading}>
            <RefreshCcw size={16} /> Atualizar
          </button>
          <button className="btn btn-secondary" type="button" onClick={rebuildSearch} disabled={loading}>
            Reindexar busca
          </button>
          <button className="btn btn-primary" type="button" onClick={saveValidation} disabled={saving || loading}>
            Salvar validação
          </button>
        </div>
      </div>

      {error && <div className="card" style={{ color: 'var(--danger)' }}>{error}</div>}
      {savedMessage && <div className="card" style={{ color: 'var(--success)' }}>{savedMessage}</div>}
      {!report && !error && <p>{loading ? 'Carregando diagnóstico...' : 'Nenhum diagnóstico carregado.'}</p>}

      {report && (
        <>
          <div className="system-grid">
            <div className="system-kpi">
              <small>Status</small>
              <strong style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{statusIcon(report.status)} {statusLabel(report.status)}</strong>
            </div>
            <div className="system-kpi">
              <small>Score</small>
              <strong>{report.score}/100</strong>
            </div>
            <div className="system-kpi">
              <small>Versão</small>
              <strong>{report.version}</strong>
            </div>
            <div className="system-kpi">
              <small>Migration</small>
              <strong>{report.database?.alembic_revision || '-'}</strong>
            </div>
            <div className="system-kpi">
              <small>Banco</small>
              <strong style={{ color: report.database?.integrity?.integrity_ok ? 'var(--success)' : 'var(--danger)' }}>
                {report.database?.integrity?.integrity_ok ? 'Integrity OK' : 'Verificar'}
              </strong>
            </div>
            <div className="system-kpi">
              <small>Foreign keys</small>
              <strong style={{ color: report.database?.integrity?.foreign_key_ok ? 'var(--success)' : 'var(--warning)' }}>
                {report.database?.integrity?.foreign_key_ok ? 'OK' : 'Atenção'}
              </strong>
            </div>
            <div className="system-kpi">
              <small>Busca FTS5</small>
              <strong>{report.search?.indexed_rows || 0} linhas</strong>
            </div>
            <div className="system-kpi">
              <small>Transcrição</small>
              <strong>{report.transcription?.enabled ? report.transcription?.backend : 'Desligada'}</strong>
            </div>
            <div className="system-kpi">
              <small>EPIs pendentes</small>
              <strong style={{ color: epiMissing?.plans_without_epi ? 'var(--warning)' : 'var(--success)' }}>
                {epiMissing?.plans_without_epi ?? 0} planos
              </strong>
            </div>
          </div>

          {/* Métricas de Hardware, Banco e NAS */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '18px', marginBottom: '12px' }}>
            {/* Card de Armazenamento NAS / Local */}
            <div className="card" style={{ padding: 20 }}>
              <h4 style={{ margin: '0 0 16px 0', fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Database size={18} /> Armazenamento e NAS
              </h4>
              {report.storage ? (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                    <span>Espaço em disco (Total: {formatBytes(report.storage.total_bytes)})</span>
                    <strong>{Math.round((report.storage.used_bytes / report.storage.total_bytes) * 100)}% usado</strong>
                  </div>
                  {/* Barra de progresso */}
                  <div style={{ width: '100%', height: 10, backgroundColor: 'var(--border)', borderRadius: 5, overflow: 'hidden', marginBottom: 12 }}>
                    <div style={{
                      width: `${(report.storage.used_bytes / report.storage.total_bytes) * 100}%`,
                      height: '100%',
                      backgroundColor: 'var(--primary)'
                    }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                    <span>Livre: <strong style={{ color: 'var(--success)' }}>{formatBytes(report.storage.free_bytes)}</strong></span>
                    <span>Usado: <strong>{formatBytes(report.storage.used_bytes)}</strong></span>
                  </div>
                </div>
              ) : (
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Métricas de disco indisponíveis.</span>
              )}
            </div>

            {/* Card de Banco de Dados e Backups */}
            <div className="card" style={{ padding: 20 }}>
              <h4 style={{ margin: '0 0 16px 0', fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
                <CheckCircle size={18} /> Banco de Dados & Backups
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Tamanho Físico do Banco:</span>
                  <strong>{formatBytes(report.paths?.database?.bytes)}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Status do Backup Externo (NAS):</span>
                  <strong style={{ color: report.backup?.external?.configured && report.backup?.external?.writable ? 'var(--success)' : 'var(--warning)' }}>
                    {report.backup?.external?.configured
                      ? (report.backup?.external?.writable ? 'Operacional (NAS)' : 'Configurado, mas inacessível')
                      : 'Não configurado'}
                  </strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Último Restore-Test automático:</span>
                  <strong style={{ color: report.backup?.latest_restore_test?.restore_test_ok ? 'var(--success)' : 'var(--danger)' }}>
                    {report.backup?.latest_restore_test
                      ? (report.backup?.latest_restore_test?.restore_test_ok ? 'OK' : 'Falhou')
                      : 'Nenhum realizado'}
                  </strong>
                </div>
                {report.paths?.database?.path && (
                  <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)', wordBreak: 'break-all', fontFamily: 'monospace' }}>
                    Caminho: {report.paths.database.path}
                  </div>
                )}
              </div>
            </div>
          </div>

          {epiMissing?.plans_without_epi > 0 && (
            <div className="card">
              <h4 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ShieldAlert size={18} /> Checklists/OMs sem EPI definido
              </h4>
              <p className="subtitle">
                Isto é pendência de cadastro. A execução ainda pode confirmar explicitamente ausência de EPI apenas quando a manutenção realmente não exigir EPI específico.
              </p>
              <ul className="system-list">
                {epiMissing.plans.slice(0, 12).map((item: any) => (
                  <li key={item.plan_id}>
                    {item.patrimonio} · {item.asset_description} · {item.plan_name}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(report.blockers.length > 0 || report.warnings.length > 0) && (
            <div className="card">
              <h4 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><ShieldAlert size={18} /> Pendências reais</h4>
              {report.blockers.length > 0 && (
                <>
                  <strong>Bloqueios</strong>
                  <ul className="system-list">{report.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
                </>
              )}
              {report.warnings.length > 0 && (
                <>
                  <strong>Alertas</strong>
                  <ul className="system-list">{report.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
                </>
              )}
            </div>
          )}

          {report.blockers.length === 0 && report.warnings.length === 0 && (
            <div className="card" style={{ color: 'var(--success)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <CheckCircle size={18} /> Nenhum bloqueio ou alerta detectado neste diagnóstico.
            </div>
          )}

          <div className="card">
            <h4>Resumo bruto para auditoria</h4>
            <pre className="system-pre">{JSON.stringify(report, null, 2)}</pre>
          </div>
        </>
      )}
    </div>
  );
}
