import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Layers } from 'lucide-react';
import ResponsiveShell, { type ShellTab } from './components/layout/ResponsiveShell';
import { ToastProvider } from './components/Toast';
import UserSelection from './components/UserSelection';

const Historico = lazy(() => import('./pages/Historico'));
const Hoje = lazy(() => import('./pages/Hoje'));
const Mais = lazy(() => import('./pages/Mais'));
const Maquinas = lazy(() => import('./pages/Maquinas'));
const Planejamento = lazy(() => import('./pages/Planejamento'));
const Rodadas = lazy(() => import('./pages/Rodadas'));
const ExecutarOM = lazy(() => import('./pages/ExecutarOM'));
const IniciarChecklist = lazy(() => import('./pages/IniciarChecklist'));
const CmpPrint = lazy(() => import('./pages/CmpPrint'));
const CmpConferencia = lazy(() => import('./pages/CmpConferencia'));
const Instalar = lazy(() => import('./pages/Instalar'));
const ScannerQR = lazy(() => import('./pages/ScannerQR'));
const ManutencoesPendentesRevisar = lazy(() => import('./pages/ManutencoesPendentesRevisar'));

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

const APP_VERSION = '1.0.0-demo';

type Operator = {
  id: string;
  name: string;
  photo_thumbnail_url?: string | null;
  is_active?: boolean;
};

type PlanningSection = 'agenda' | 'rodadas';

function PageFallback() {
  return (
    <main className="page-shell" aria-busy="true">
      <p>Carregando...</p>
    </main>
  );
}

/** 404 amigável para rotas inválidas. */
function NotFound() {
  return (
    <main className="page-shell" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
      <h1 style={{ fontSize: '3rem', margin: 0 }}>404</h1>
      <p>Página não encontrada.</p>
      <a href="/" style={{ color: 'var(--primary)' }}>Voltar ao início</a>
    </main>
  );
}

/**
 * Shell com rotas internas — usado dentro de BrowserRouter.
 * As abas de navegação (hoje/maquinas/planejamento/historico/mais)
 * são renderizadas como <Outlet> dentro do ResponsiveShell.
 */
function ShellLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [planningSection, setPlanningSection] = useState<PlanningSection>('agenda');
  const [operators, setOperators] = useState<Operator[]>([]);
  const [activeOperator, setActiveOperator] = useState<string>('');
  const [activeOperatorId, setActiveOperatorId] = useState<string>('');
  const [loadingOperators, setLoadingOperators] = useState(true);
  const [pendingReviewCount, setPendingReviewCount] = useState(0);

  // Deriva a aba ativa a partir da rota atual
  const activeTab = useMemo<ShellTab>(() => {
    const path = location.pathname;
    if (path === '/' || path === '/hoje') return 'hoje';
    if (path.startsWith('/ativos') || path.startsWith('/inativos')) return 'maquinas';
    if (path.startsWith('/planejamento') || path.startsWith('/rodadas')) return 'planejamento';
    if (path.startsWith('/historico')) return 'historico';
    return 'mais';
  }, [location.pathname]);

  const pageTitle = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith('/checklists/iniciar')) return 'Checklist Digital';
    if (path.startsWith('/manutencoes/pendentes-revisar')) return 'Pendências para revisar';
    if (path.startsWith('/cmp')) return 'CMP em papel';
    if (path.startsWith('/scanner')) return 'Escanear QR';
    if (path.startsWith('/ordens/')) return 'Execução da manutenção';
    return undefined;
  }, [location.pathname]);

  const fetchOperators = async () => {
    try {
      const res = await axios.get(`${API_URL}/operators`, { params: { selection: 'checklist_reviewer' } });
      const loadedOperators = Array.isArray(res.data) ? res.data : [];
      setOperators(loadedOperators);

      const savedId = sessionStorage.getItem('mec_operator_id');
      const savedName = sessionStorage.getItem('mec_operator_name');
      const savedOperator = loadedOperators.find((operator: Operator) => operator.id === savedId)
        || loadedOperators.find((operator: Operator) => operator.name === savedName);
      if (savedOperator) {
        setActiveOperator(savedOperator.name);
        setActiveOperatorId(savedOperator.id);
        sessionStorage.setItem('mec_operator_id', savedOperator.id);
        sessionStorage.setItem('mec_operator_name', savedOperator.name);
      }
    } catch (err) {
      console.error('Erro ao carregar operadores:', err);
    } finally {
      setLoadingOperators(false);
    }
  };

  useEffect(() => {
    fetchOperators();
    const handleOperatorsChanged = () => fetchOperators();
    window.addEventListener('operators_changed', handleOperatorsChanged);
    return () => window.removeEventListener('operators_changed', handleOperatorsChanged);
  }, []);

  useEffect(() => {
    axios.get(`${API_URL}/v2/execution/drafts`, { params: { alert_from_days: 2 } })
      .then((response) => setPendingReviewCount(Number(response.data?.attention_count || 0)))
      .catch(() => setPendingReviewCount(0));
  }, [location.pathname]);

  // Redirect QR deep-links: /o/:token, /a/:token
  useEffect(() => {
    const path = location.pathname;
    const match = path.match(/^\/(?:o|a|ativos)\/([^/]+)/);
    if (!match) return;
    // Only handle non-UUID tokens (UUID-like strings are direct asset IDs for real routes)
    const token = decodeURIComponent(match[1]);
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(token)) return;

    axios.get(`${API_URL}/resolve-token/${encodeURIComponent(token)}`)
      .then((response) => {
        if (response.data.type === 'order') {
          navigate(`/ordens/${response.data.id}/executar`, { replace: true });
        } else if (response.data.type === 'asset') {
          localStorage.setItem('mec_auto_open_asset', response.data.id);
          navigate('/', { replace: true });
        }
      })
      .catch(() => {
        navigate('/', { replace: true });
      });
  }, [location.pathname, navigate]);

  const handleOperatorChange = (operator: Operator) => {
    setActiveOperator(operator.name);
    setActiveOperatorId(operator.id);
    sessionStorage.setItem('mec_operator_id', operator.id);
    sessionStorage.setItem('mec_operator_name', operator.name);
  };

  const handleOperatorIdChange = (id: string) => {
    const operator = operators.find((candidate) => candidate.id === id);
    if (operator) {
      handleOperatorChange(operator);
    }
  };

  const onTabChange = (tab: ShellTab) => {
    const routeMap: Record<ShellTab, string> = {
      hoje: '/',
      maquinas: '/ativos',
      planejamento: '/planejamento',
      historico: '/historico',
      mais: '/gestao',
    };
    navigate(routeMap[tab]);
  };

  const renderPlanning = () => (
    <section className="planning-shell" aria-label="Planejamento">
      <div className="segmented-control planning-shell__tabs" role="tablist" aria-label="Seções de planejamento">
        <button
          type="button"
          role="tab"
          aria-selected={planningSection === 'agenda'}
          className={planningSection === 'agenda' ? 'active' : ''}
          onClick={() => setPlanningSection('agenda')}
        >
          Agenda
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={planningSection === 'rodadas'}
          className={planningSection === 'rodadas' ? 'active' : ''}
          onClick={() => setPlanningSection('rodadas')}
        >
          <Layers size={16} />
          Rodadas
        </button>
      </div>

      <Suspense fallback={<PageFallback />}>
        {planningSection === 'agenda' ? <Planejamento /> : <Rodadas />}
      </Suspense>
    </section>
  );

  return (
    <ResponsiveShell
      activeTab={activeTab}
      activeOperator={activeOperator}
      activeOperatorId={activeOperatorId}
      appVersion={APP_VERSION}
      pageTitle={pageTitle}
      loadingOperators={loadingOperators}
      operators={operators}
      onOperatorChange={handleOperatorIdChange}
      onTabChange={onTabChange}
    >
      {pendingReviewCount > 0 && !location.pathname.startsWith('/manutencoes/pendentes-revisar') && (
        <button type="button" className="pending-review-banner" onClick={() => navigate('/manutencoes/pendentes-revisar')}>
          Há {pendingReviewCount} manutenção(ões) pendente(s) para revisar há 2 dias ou mais. Abrir revisão.
        </button>
      )}
      <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* Executar OM — sobreposição full-screen */}
          <Route path="/ordens/:orderId/executar" element={
            <ExecutarOMRouteWrapper />
          } />

          {/* Rotas de abas — renderizadas dentro do shell */}
          <Route path="/" element={<Hoje />} />
          <Route path="/hoje" element={<Navigate to="/" replace />} />
          <Route path="/ativos" element={<Maquinas />} />
          <Route path="/ativos/:assetId" element={<Maquinas />} />
          <Route path="/inativos" element={<InativosPage />} />
          <Route path="/inativos/:assetId" element={<InativosPage />} />
          <Route path="/planejamento" element={renderPlanning()} />
          <Route path="/rodadas" element={<Navigate to="/planejamento" replace />} />
          <Route path="/historico" element={<Historico />} />
          <Route path="/mais" element={<Mais />} />
          <Route path="/gestao" element={<Mais />} />

          {/* Rotas operacionais reais */}
          <Route path="/ordens/:orderId" element={<OrderDetailRedirect />} />
          <Route path="/qr/escanear" element={<ScannerQR />} />
          <Route path="/checklists/iniciar" element={<IniciarChecklist />} />
          <Route path="/manutencoes/pendentes-revisar" element={<ManutencoesPendentesRevisar />} />
          <Route path="/documentos/revisao" element={<MaisSubTabRoute subtab="revisao_documental" />} />
          <Route path="/documentos/:documentId" element={<MaisSubTabRoute subtab="revisao_documental" />} />
          <Route path="/cmp/:orderId/imprimir" element={<CmpPrint />} />
          <Route path="/cmp/:orderId/digitalizar" element={<CmpConferencia />} />
          <Route path="/cmp/conferencia" element={<CmpConferencia />} />
          <Route path="/sistema/diagnostico" element={<MaisSubTabRoute subtab="sistema" />} />
          <Route path="/instalar" element={<Instalar />} />

          {/* 404 */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </ResponsiveShell>
  );
}

/** Wrapper para /ordens/:orderId/executar dentro do ShellLayout.
 *  ExecutarOM recebe onCancel/onComplete que navegam de volta.
 */
function ExecutarOMRouteWrapper() {
  const navigate = useNavigate();
  const location = useLocation();
  const orderId = location.pathname.match(/^\/ordens\/([^/]+)\/executar/)?.[1] || '';

  const close = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/');
    }
  };

  return (
    <ExecutarOM
      orderId={decodeURIComponent(orderId)}
      onCancel={close}
      onComplete={close}
    />
  );
}

function OrderDetailRedirect() {
  const location = useLocation();
  const orderId = location.pathname.match(/^\/ordens\/([^/]+)/)?.[1] || '';
  return <Navigate to={`/ordens/${decodeURIComponent(orderId)}/executar`} replace />;
}

function MaisSubTabRoute({ subtab }: { subtab: string }) {
  useEffect(() => {
    localStorage.setItem('mec_mais_subtab', subtab);
  }, [subtab]);
  return <Mais />;
}

/** Placeholder para /inativos até a tela real ser criada (próximo passo). */
function InativosPage() {
  // Will be replaced by the real Inativos.tsx component
  return <Maquinas inactiveMode />;
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <OperatorGate />
      </ToastProvider>
    </BrowserRouter>
  );
}

/**
 * Gate: se não houver operador selecionado, mostra UserSelection.
 * Senão, renderiza o ShellLayout com rotas.
 */
function OperatorGate() {
  const location = useLocation();
  const [operators, setOperators] = useState<Operator[]>([]);
  const [activeOperator, setActiveOperator] = useState<string>('');
  const [loadingOperators, setLoadingOperators] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await axios.get(`${API_URL}/operators`, { params: { selection: 'checklist_reviewer' } });
        const loaded = Array.isArray(res.data) ? res.data : [];
        setOperators(loaded);

        const savedId = sessionStorage.getItem('mec_operator_id');
        const savedName = sessionStorage.getItem('mec_operator_name');
        const selectedStillReviewer = loaded.some((operator: Operator) => operator.id === savedId || operator.name === savedName);
        if (selectedStillReviewer) {
          setActiveOperator('loaded'); // Mark as already selected
        } else if (savedId || savedName) {
          sessionStorage.removeItem('mec_operator_id');
          sessionStorage.removeItem('mec_operator_name');
        }
      } catch (err) {
        console.error('Erro ao carregar operadores:', err);
      } finally {
        setLoadingOperators(false);
      }
    })();
  }, []);

  if (location.pathname === '/instalar') {
    return (
      <Suspense fallback={<PageFallback />}>
        <Instalar />
      </Suspense>
    );
  }

  if (loadingOperators) return <PageFallback />;

  if (activeOperator) {
    return <ShellLayout />;
  }

  const handleSelect = (operator: Operator) => {
    setActiveOperator(operator.name);
    sessionStorage.setItem('mec_operator_id', operator.id);
    sessionStorage.setItem('mec_operator_name', operator.name);
  };

  return (
    <UserSelection
      operators={operators}
      loading={loadingOperators}
      onSelect={handleSelect}
    />
  );
}
