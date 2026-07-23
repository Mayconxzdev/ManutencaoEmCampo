import { Search, RotateCcw, ExternalLink } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type SearchItem = {
  entity_type: string;
  entity_id: string;
  title: string;
  snippet?: string | null;
  metadata?: string | null;
  // Enriched fields from search_global (1.9.1+)
  asset_status?: string | null;
  asset_operable?: boolean | null;
  patrimonio?: string | null;
  is_exact_patrimonio_match?: boolean | null;
  parent_asset_status?: string | null;
  parent_asset_name?: string | null;
  parent_asset_patrimonio?: string | null;
  file_name?: string | null;
  file_kind?: string | null;
  mime_type?: string | null;
};

type SearchResponse = {
  backend: string;
  query: string;
  items: SearchItem[];
  total: number;
};

type Props = {
  /* Kept for backward compatibility but no longer used for navigation */
  onNavigateTab?: (tab: string) => void;
};

const TYPE_LABELS: Record<string, string> = {
  asset: 'Ativo',
  asset_file: 'Arquivo do ativo',
  legacy_document: 'Documento legado',
  plan: 'Plano',
  order: 'OM',
  checklist_item: 'Checklist',
};

function cleanSnippet(value?: string | null) {
  if (!value) return '';
  return value.replace(/<\/?b>/g, '').replace(/…/g, '…');
}

function assetStatusLabel(status: string | null | undefined): string {
  if (status === 'active') return 'ATIVO';
  if (status === 'inactive') return 'INATIVO';
  return (status || '').toUpperCase();
}

function badgeForStatus(status: string | null | undefined, prefix?: string): React.ReactNode | null {
  if (!status) return null;
  const label = prefix ? `${prefix} ${assetStatusLabel(status)}` : assetStatusLabel(status);
  const isActive = status === 'active';
  return (
    <span
      style={{
        fontSize: '0.65rem',
        padding: '1px 6px',
        borderRadius: '3px',
        fontWeight: 600,
        marginLeft: 6,
        backgroundColor: isActive ? 'var(--success-bg, #d4edda)' : 'var(--warning-bg, #fff3cd)',
        color: isActive ? 'var(--success, #155724)' : 'var(--warning-text, #856404)',
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
}

function fileTypeLabel(mime?: string | null, kind?: string | null): string {
  if (!mime && !kind) return 'arquivo';
  if (mime?.startsWith('image/')) return 'foto';
  if (mime?.startsWith('audio/')) return 'áudio';
  if (mime === 'application/pdf' || kind === 'document') return 'PDF';
  return 'documento';
}

export default function GlobalSearch({ onNavigateTab: _unused }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<SearchItem[]>([]);
  const [backend, setBackend] = useState('');
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [rebuilding, setRebuilding] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const canSearch = useMemo(() => query.trim().length >= 2, [query]);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  useEffect(() => {
    if (!canSearch) {
      setItems([]);
      setError('');
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError('');
      try {
        const response = await axios.get<SearchResponse>(`${API_URL}/v2/search/global`, {
          params: { q: query.trim(), limit: 12 },
          signal: controller.signal,
        });
        setItems(response.data.items || []);
        setBackend(response.data.backend || '');
        setOpen(true);
      } catch (err: any) {
        if (err?.name !== 'CanceledError') {
          setError(err.response?.data?.detail || 'Erro na busca global.');
        }
      } finally {
        setLoading(false);
      }
    }, 260);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, canSearch]);

  const rebuildIndex = async () => {
    setRebuilding(true);
    try {
      await axios.post(`${API_URL}/v2/search/rebuild`);
      if (query.trim().length >= 2) {
        const response = await axios.get<SearchResponse>(`${API_URL}/v2/search/global`, {
          params: { q: query.trim(), limit: 12, rebuild_if_empty: false },
        });
        setItems(response.data.items || []);
        setBackend(response.data.backend || '');
        setOpen(true);
      }
    } finally {
      setRebuilding(false);
    }
  };

  const openItem = (item: SearchItem) => {
    setOpen(false);
    setQuery('');

    if (item.entity_type === 'order') {
      navigate(`/ordens/${item.entity_id}/executar`);
      return;
    }

    if (item.entity_type === 'asset') {
      // Navigate by ID to /ativos or /inativos based on status
      if (item.asset_status === 'inactive') {
        navigate(`/inativos/${item.entity_id}`);
      } else {
        navigate(`/ativos/${item.entity_id}`);
      }
      // Also set localStorage for Maquinas auto-open
      localStorage.setItem('mec_auto_open_asset', item.entity_id);
      return;
    }

    if (item.entity_type === 'asset_file' || item.entity_type === 'legacy_document') {
      // Navigate to parent asset or directly to document
      const targetAssetId = item.metadata || item.entity_id;
      if (item.parent_asset_status === 'inactive') {
        navigate(`/inativos/${targetAssetId}`);
      } else {
        navigate(`/ativos/${targetAssetId}`);
      }
      localStorage.setItem('mec_auto_open_asset', targetAssetId);
      localStorage.setItem('mec_search_context', JSON.stringify(item));
      return;
    }

    if (item.entity_type === 'checklist_item') {
      navigate('/mais');
      localStorage.setItem('mec_mais_subtab', 'cmp');
      localStorage.setItem('mec_search_context', JSON.stringify(item));
      return;
    }

    if (item.entity_type === 'plan') {
      navigate('/mais');
      localStorage.setItem('mec_search_context', JSON.stringify(item));
      return;
    }

    // Fallback
    navigate('/');
  };

  return (
    <div className="global-search" ref={boxRef}>
      <Search size={16} aria-hidden="true" />
      <input
        value={query}
        onFocus={() => canSearch && setOpen(true)}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Buscar ativo, OM, documento, checklist..."
        aria-label="Busca global"
      />
      {loading && <span className="global-search__loading">...</span>}
      {open && canSearch && (
        <div className="global-search__panel" role="listbox">
          <div className="global-search__meta">
            <span>{items.length} resultado(s) · {backend || 'busca'}</span>
            <button type="button" onClick={rebuildIndex} disabled={rebuilding}>
              <RotateCcw size={13} /> {rebuilding ? 'Indexando...' : 'Reindexar'}
            </button>
          </div>
          {error && <div className="global-search__empty">{error}</div>}
          {!error && items.length === 0 && !loading && (
            <div className="global-search__empty">Nenhum resultado encontrado.</div>
          )}
          {!error && items.map((item) => (
            <button key={`${item.entity_type}-${item.entity_id}`} type="button" className="global-search__item" onClick={() => openItem(item)}>
              <span className="global-search__type">
                {TYPE_LABELS[item.entity_type] || item.entity_type}
                {/* Asset badge */}
                {item.entity_type === 'asset' && badgeForStatus(item.asset_status)}
                {/* Document/file badge with parent status */}
                {item.entity_type !== 'asset' && badgeForStatus(item.parent_asset_status, 'ARQUIVO DO ATIVO')}
              </span>
              <strong>{item.title}</strong>
              {item.entity_type !== 'asset' && (item.file_name || item.parent_asset_name) && (
                <small style={{ opacity: 0.7, display: 'block' }}>
                  {item.parent_asset_patrimonio && `${item.parent_asset_patrimonio} · `}
                  {item.parent_asset_name || ''}
                  {item.file_kind && ` · ${fileTypeLabel(item.mime_type, item.file_kind)}`}
                </small>
              )}
              {cleanSnippet(item.snippet) && <small>{cleanSnippet(item.snippet)}</small>}
              <ExternalLink size={13} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
