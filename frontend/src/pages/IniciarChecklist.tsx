import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { AlertTriangle, CheckSquare, Search } from 'lucide-react';
import { formatManutencaoEmCampoDateTime } from '../utils/dateTime';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type OrderRow = {
  id: string;
  friendly_number?: number;
  status?: string;
  execution_status?: string;
  asset_id?: string;
  planned_date?: string | null;
  completed_at?: string | null;
  started_at?: string | null;
  checklist_version_id?: string | null;
  operator_name?: string | null;
  performed_by_name?: string | null;
  final_condition?: string | null;
};

type AssetRow = {
  id: string;
  patrimonio?: string;
  description?: string;
  manufacturer?: string | null;
  model?: string | null;
  type?: 'machine' | 'equipment' | string;
  status?: string;
  is_operable?: boolean;
  show_in_daily_list?: boolean;
  sector?: { name?: string | null } | null;
};

type AssetsPage = {
  items?: AssetRow[];
  total_pages?: number;
};

type ExecutionCandidate = {
  asset: AssetRow;
  lastOrder?: OrderRow;
};

const openStatuses = ['scheduled', 'today', 'overdue', 'in_progress'];

const statusLabel: Record<string, string> = {
  overdue: 'Vencida',
  today: 'Do dia',
  scheduled: 'Aberta',
  in_progress: 'Em andamento',
  completed: 'Manutenção concluída',
  completed_with_issues: 'Concluída com pendência',
  demo_completed: 'Teste/demonstração concluído',
  cancelled: 'Registro encerrado',
};

function orderPriority(order?: OrderRow): number {
  if (!order) return 9;
  if (order.status === 'overdue') return 0;
  if (order.status === 'today') return 1;
  if (order.status === 'in_progress') return 2;
  if (order.status === 'scheduled') return 3;
  return 8;
}

function latestOrder(orders: OrderRow[]): OrderRow | undefined {
  return [...orders].sort((a, b) => {
    const aDate = a.completed_at || a.started_at || a.planned_date || '';
    const bDate = b.completed_at || b.started_at || b.planned_date || '';
    return bDate.localeCompare(aDate) || (b.friendly_number || 0) - (a.friendly_number || 0);
  })[0];
}

async function fetchAllOperationalAssets(): Promise<AssetRow[]> {
  const first = await axios.get<AssetsPage>(`${API_URL}/v2/assets`, {
    params: { status: 'active', daily_only: true, page: 1, page_size: 50 },
  });
  const firstItems = first.data.items || [];
  const totalPages = Math.max(1, Number(first.data.total_pages || 1));
  if (totalPages === 1) return firstItems;

  const remaining = await Promise.all(
    Array.from({ length: totalPages - 1 }, (_, index) => axios.get<AssetsPage>(`${API_URL}/v2/assets`, {
      params: { status: 'active', daily_only: true, page: index + 2, page_size: 50 },
    })),
  );
  return [...firstItems, ...remaining.flatMap((response) => response.data.items || [])];
}

export default function IniciarChecklist() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'not_started' | 'overdue' | 'today' | 'in_progress'>('all');
  const [executionCandidate, setExecutionCandidate] = useState<ExecutionCandidate | null>(null);
  const [creatingAssetId, setCreatingAssetId] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [assetsResult, ordersResult] = await Promise.all([
          fetchAllOperationalAssets(),
          axios.get<OrderRow[]>(`${API_URL}/orders`),
        ]);
        setAssets(assetsResult);
        setOrders(Array.isArray(ordersResult.data) ? ordersResult.data : []);
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Não foi possível carregar os equipamentos e as manutenções.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const createExecutionOrder = async (asset: AssetRow) => {
    if (creatingAssetId) return;
    setCreatingAssetId(asset.id);
    setError('');
    try {
      const response = await axios.post(`${API_URL}/v2/assets/${asset.id}/execution-order`, {
        operator_name: sessionStorage.getItem('mec_operator_name') || undefined,
        selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined,
      });
      setExecutionCandidate(null);
      navigate(`/ordens/${response.data.order_id}/executar`);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Não foi possível preparar o checklist deste equipamento. Tente novamente.');
    } finally {
      setCreatingAssetId(null);
    }
  };

  const requestExecution = (asset: AssetRow, lastOrder?: OrderRow) => {
    // O aviso só é necessário quando já há uma execução registrada. Sem
    // histórico, o início permanece direto e simples para o operador.
    if (lastOrder) {
      setExecutionCandidate({ asset, lastOrder });
      return;
    }
    void createExecutionOrder(asset);
  };

  const rows = useMemo(() => {
    const q = query.trim().toLocaleLowerCase('pt-BR');
    const ordersByAsset = new Map<string, OrderRow[]>();
    orders.forEach((order) => {
      if (!order.asset_id) return;
      const assetOrders = ordersByAsset.get(order.asset_id) || [];
      assetOrders.push(order);
      ordersByAsset.set(order.asset_id, assetOrders);
    });

    return assets
      .map((asset) => {
        const assetOrders = ordersByAsset.get(asset.id) || [];
        const openOrder = assetOrders
          .filter((order) => openStatuses.includes(order.status || ''))
          .sort((a, b) => orderPriority(a) - orderPriority(b) || (a.friendly_number || 0) - (b.friendly_number || 0))[0];
        return { asset, openOrder, lastOrder: latestOrder(assetOrders) };
      })
      .filter(({ asset, openOrder }) => {
        if (filter === 'not_started' && !['scheduled', 'today', 'overdue'].includes(openOrder?.status || '')) return false;
        if (filter === 'overdue' && openOrder?.status !== 'overdue') return false;
        if (filter === 'today' && openOrder?.status !== 'today') return false;
        if (filter === 'in_progress' && openOrder?.status !== 'in_progress') return false;
        if (!q) return true;
        return [
          asset.patrimonio || '',
          asset.description || '',
          asset.manufacturer || '',
          asset.model || '',
          asset.sector?.name || '',
          String(openOrder?.friendly_number || ''),
        ].some((value) => value.toLocaleLowerCase('pt-BR').includes(q));
      })
      .sort((a, b) => orderPriority(a.openOrder) - orderPriority(b.openOrder)
        || (a.asset.patrimonio || '').localeCompare(b.asset.patrimonio || '', 'pt-BR'));
  }, [assets, filter, orders, query]);

  return (
    <section className="page-shell">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h1>Iniciar Checklist Digital</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            Todos os equipamentos e máquinas ativos com rotina aparecem aqui. Você pode iniciar uma OM aberta ou uma nova execução rastreável; se já houver histórico, ele será mostrado apenas como aviso e será preservado.
          </p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => navigate(-1)}>Voltar</button>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) auto', gap: 12 }}>
          <label className="form-group" style={{ margin: 0 }}>
            <span className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Search size={15} /> Buscar por código, nome, modelo, setor ou OM
            </span>
            <input
              className="form-control"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ex.: M-116, impressora 3D, compressor..."
            />
          </label>
          <label className="form-group" style={{ margin: 0, minWidth: 205 }}>
            <span className="form-label">Exibir</span>
            <select className="form-control" value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
              <option value="all">Todos os ativos</option>
              <option value="not_started">Com OM aberta</option>
              <option value="overdue">Com OM vencida</option>
              <option value="today">Com OM do dia</option>
              <option value="in_progress">Em andamento</option>
            </select>
          </label>
        </div>
      </div>

      {loading && <p>Carregando equipamentos e máquinas...</p>}
      {error && <div className="card" style={{ borderLeft: '4px solid var(--danger)', padding: 16 }}>{error}</div>}
      {!loading && !error && rows.length === 0 && (
        <div className="card" style={{ padding: 22 }}>
          <h2 style={{ marginTop: 0 }}>Nenhum ativo encontrado</h2>
          <p style={{ color: 'var(--text-muted)' }}>Tente buscar pelo código do equipamento, nome, modelo ou setor.</p>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
        {rows.map(({ asset, openOrder, lastOrder }) => {
          const blocked = Boolean(openOrder && !openOrder.checklist_version_id);
          const identity = [asset.sector?.name, asset.manufacturer, asset.model].filter(Boolean).join(' · ');
          return (
            <article key={asset.id} className="card" style={{ padding: 16, borderLeft: `4px solid ${openOrder ? (blocked ? 'var(--warning)' : 'var(--primary)') : 'var(--border)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
                <strong>{asset.patrimonio || 'Código não informado'}</strong>
                <span style={{ fontSize: 12, fontWeight: 700, color: openOrder ? 'var(--primary)' : 'var(--text-muted)' }}>
                  {openOrder ? statusLabel[openOrder.status || ''] || 'OM aberta' : 'Sem OM aberta'}
                </span>
              </div>
              <div style={{ fontWeight: 700 }}>{asset.description || 'Ativo sem descrição'}</div>
              <p style={{ margin: '4px 0 12px', color: 'var(--text-muted)', minHeight: 18 }}>{identity || 'Setor, fabricante e modelo não informados'}</p>

              {openOrder ? (
                blocked ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--warning-text)' }}>
                    <AlertTriangle size={16} /> OM #{openOrder.friendly_number || openOrder.id.slice(0, 8)} sem checklist definido.
                  </div>
                ) : (
                  <button className="btn btn-primary" type="button" onClick={() => navigate(`/ordens/${openOrder.id}/executar`)}>
                    <CheckSquare size={16} /> {openOrder.status === 'in_progress' ? 'Continuar checklist' : 'Iniciar checklist'}
                  </button>
                )
              ) : (
                <div style={{ display: 'grid', gap: 10 }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                    {lastOrder
                      ? `Último registro: ${statusLabel[lastOrder.status || ''] || 'registrado'}${lastOrder.friendly_number ? ` · OM #${lastOrder.friendly_number}` : ''}`
                      : 'Não há OM aberta no momento.'}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary" type="button" disabled={creatingAssetId === asset.id} onClick={() => requestExecution(asset, lastOrder)}>
                      <CheckSquare size={16} /> {creatingAssetId === asset.id ? 'Preparando checklist...' : 'Iniciar novo checklist'}
                    </button>
                    <button className="btn btn-secondary" type="button" onClick={() => navigate(`/ativos/${asset.id}`)}>
                      Ver detalhes e histórico
                    </button>
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {executionCandidate && (
        <div className="overlay" role="presentation">
          <section className="modal-content" role="dialog" aria-modal="true" aria-labelledby="previous-execution-title" style={{ maxWidth: 560 }}>
            <div style={{ display: 'grid', gap: 8 }}>
              <h2 id="previous-execution-title" style={{ margin: 0 }}>Registro anterior encontrado</h2>
              <p style={{ margin: 0, color: 'var(--text-muted)' }}>
                {executionCandidate.asset.patrimonio || 'Ativo'} — {executionCandidate.asset.description || 'Equipamento'} já possui uma execução registrada. Ela continuará preservada no histórico e no servidor.
              </p>
            </div>
            <div className="card" style={{ padding: 16, display: 'grid', gap: 7, background: 'var(--bg-app)' }}>
              <strong>{statusLabel[executionCandidate.lastOrder?.status || ''] || 'Registro anterior'}</strong>
              <span>Data: {formatManutencaoEmCampoDateTime(executionCandidate.lastOrder?.completed_at || executionCandidate.lastOrder?.started_at)}</span>
              <span>Conferiu no tablet: {executionCandidate.lastOrder?.operator_name || 'Não informado'}</span>
              <span>Executou a manutenção: {executionCandidate.lastOrder?.performed_by_name || 'Não informado'}</span>
              {executionCandidate.lastOrder?.friendly_number && <span>OM anterior: #{executionCandidate.lastOrder.friendly_number}</span>}
            </div>
            <p style={{ margin: 0, color: 'var(--text-muted)' }}>
              Ao continuar, será criada uma nova OM para este ativo usando o checklist vinculado ao plano dele. A OM anterior, PDF, fotos e responsáveis não serão alterados.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" type="button" disabled={Boolean(creatingAssetId)} onClick={() => setExecutionCandidate(null)}>Cancelar</button>
              <button className="btn btn-primary" type="button" disabled={Boolean(creatingAssetId)} onClick={() => void createExecutionOrder(executionCandidate.asset)}>
                <CheckSquare size={16} /> {creatingAssetId ? 'Preparando...' : 'Continuar e iniciar novo checklist'}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
