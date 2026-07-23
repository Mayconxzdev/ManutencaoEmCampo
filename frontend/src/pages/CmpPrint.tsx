import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { FileText, Printer } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

export default function CmpPrint() {
  const { orderId = '' } = useParams();
  const navigate = useNavigate();
  const [order, setOrder] = useState<any>(null);
  const [responsible, setResponsible] = useState(sessionStorage.getItem('mec_operator_name') || '');
  const [executionDate, setExecutionDate] = useState(new Date().toISOString().slice(0, 10));
  const [pdfUrl, setPdfUrl] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!orderId) return;
    axios.get(`${API_URL}/v2/orders/${encodeURIComponent(orderId)}`)
      .then((response) => setOrder(response.data))
      .catch((err) => setError(err.response?.data?.detail || 'Não foi possível carregar a OM.'));
  }, [orderId]);

  const generate = () => {
    const params = new URLSearchParams();
    if (responsible.trim()) params.set('responsible', responsible.trim());
    if (executionDate) params.set('execution_date', executionDate);
    const url = `${API_URL}/v2/orders/${encodeURIComponent(orderId)}/cmp.pdf?${params.toString()}`;
    setPdfUrl(url);
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  const asset = order?.asset || {};
  const om = order?.order || order || {};

  return (
    <section className="page-shell">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h1>Imprimir CMP</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            PDF gerado pelo backend, sem cabeçalho/rodapé do navegador e sem imprimir a SPA.
          </p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => navigate(-1)}>Voltar</button>
      </div>

      {error && <div className="card" style={{ borderLeft: '4px solid var(--danger)', padding: 16 }}>{error}</div>}

      <div className="card" style={{ padding: 18, display: 'grid', gap: 14, maxWidth: 760 }}>
        <div>
          <strong>OM #{om.friendly_number || orderId.slice(0, 8)}</strong>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)' }}>
            {asset.patrimonio || 'Patrimônio não informado'} · {asset.description || 'Ativo não informado'}
          </p>
        </div>

        <label className="form-group">
          <span className="form-label">Responsável impresso</span>
          <input className="form-control" value={responsible} onChange={(event) => setResponsible(event.target.value)} />
        </label>
        <label className="form-group">
          <span className="form-label">Data de execução impressa</span>
          <input className="form-control" type="date" value={executionDate} onChange={(event) => setExecutionDate(event.target.value)} />
        </label>

        <button className="btn btn-primary" type="button" onClick={generate} disabled={!orderId}>
          <Printer size={16} /> Gerar PDF para imprimir
        </button>

        {pdfUrl && (
          <a className="btn btn-secondary" href={pdfUrl} target="_blank" rel="noreferrer" style={{ justifyContent: 'center' }}>
            <FileText size={16} /> Abrir PDF gerado novamente
          </a>
        )}
      </div>
    </section>
  );
}
