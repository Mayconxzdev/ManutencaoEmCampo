import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { Camera, FileImage, RefreshCcw, Upload, RotateCw } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type ScanItem = {
  id: string;
  status: string;
  created_at: string;
  original_name: string;
  order_id?: string | null;
  suggested_order_id?: string | null;
  suggested_asset_id?: string | null;
  confidence?: number | null;
  extraction?: any;
  files?: Array<{ content_url?: string; name?: string }>;
  operator_name?: string | null;
};

type OrderOption = {
  id: string;
  friendly_number?: number;
  status?: string;
  asset?: {
    patrimonio?: string;
    description?: string;
  };
};

function parseServerDate(value?: string | null) {
  if (!value) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  // Backend timestamps are stored as UTC-naive. Treat timezone-less values as UTC
  // so tablets in Sao Paulo do not show +3h in the conference screen.
  const withZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(raw) ? raw : `${raw}Z`;
  const parsed = new Date(withZone);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatServerDateTime(value?: string | null) {
  const parsed = parseServerDate(value);
  return parsed ? parsed.toLocaleString('pt-BR') : 'data não informada';
}

function dateInputFromServerDate(value?: string | null) {
  const parsed = parseServerDate(value);
  if (!parsed) return new Date().toISOString().slice(0, 10);
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function mediaDiagnosis() {
  const secure = window.isSecureContext || ['localhost', '127.0.0.1'].includes(window.location.hostname);
  if (!secure) {
    return 'Câmera e microfone podem ser bloqueados porque o sistema está em HTTP por IP. Use HTTPS/certificado local ou envie arquivo da galeria.';
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return 'Este navegador não expõe câmera via getUserMedia. Use upload de imagem/PDF.';
  }
  return 'Câmera disponível quando o navegador permitir; upload de imagem/PDF continua disponível.';
}

export default function CmpConferencia() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [scans, setScans] = useState<ScanItem[]>([]);
  const [selectedScan, setSelectedScan] = useState<ScanItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [cameraError, setCameraError] = useState('');
  const [cameraActive, setCameraActive] = useState(false);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [previewUrl, setPreviewUrl] = useState('');
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const selectedUserId = sessionStorage.getItem('mec_operator_id') || '';
  const selectedUserName = sessionStorage.getItem('mec_operator_name') || '';
  const diagnosis = useMemo(mediaDiagnosis, []);

  const loadScans = useCallback(async () => {
    const response = await axios.get(`${API_URL}/v2/cmp/scans`, { params: { order_id: orderId || undefined, limit: 20 } });
    setScans(response.data.items || []);
  }, [orderId]);

  useEffect(() => {
    loadScans().catch(() => setScans([]));
  }, [loadScans]);

  useEffect(() => {
    if (!files[0] || !files[0].type.startsWith('image/')) {
      setPreviewUrl('');
      return;
    }
    const url = URL.createObjectURL(files[0]);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [files]);

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
  };

  useEffect(() => stopCamera, []);

  useEffect(() => {
    if (!cameraActive || !videoRef.current || !streamRef.current) return;
    videoRef.current.srcObject = streamRef.current;
    videoRef.current.play().catch(() => {
      setCameraError('A câmera abriu, mas o navegador não iniciou o preview. Tente novamente ou use escolher foto/PDF.');
    });
  }, [cameraActive]);

  const openCamera = async (mode: 'environment' | 'user' = facingMode) => {
    setCameraError('');
    setError('');
    if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(window.location.hostname)) {
      setCameraError('O navegador bloqueou câmera porque o sistema está em HTTP por IP. Acesse por HTTPS na porta 8443 ou use galeria/PDF.');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('Este navegador não oferece câmera por getUserMedia. Use escolher foto/PDF.');
      return;
    }
    try {
      stopCamera();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: mode },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      setFacingMode(mode);
      setCameraActive(true);
    } catch (err: any) {
      stopCamera();
      if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
        setCameraError('Permissão de câmera negada ou bloqueada pelo navegador. Libere a câmera ou use escolher foto/PDF.');
      } else if (err?.name === 'NotFoundError') {
        setCameraError('Nenhuma câmera foi encontrada neste dispositivo. Use escolher foto/PDF.');
      } else {
        setCameraError(err?.message || 'Não foi possível abrir a câmera. Use escolher foto/PDF.');
      }
    }
  };

  const switchCamera = () => {
    const next = facingMode === 'environment' ? 'user' : 'environment';
    openCamera(next).catch(() => {});
  };

  const capturePhoto = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) {
      setCameraError('Câmera ainda não está pronta. Aguarde a imagem aparecer.');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext('2d');
    if (!context) {
      setCameraError('Não foi possível capturar a imagem da câmera.');
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (!blob) {
      setCameraError('Não foi possível gerar a foto capturada.');
      return;
    }
    const file = new File([blob], `cmp_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`, { type: 'image/jpeg' });
    setFiles([file]);
    stopCamera();
  };

  const submit = async () => {
    if (files.length === 0) {
      setError('Escolha uma imagem ou PDF do CMP preenchido.');
      return;
    }
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file, file.name));
      if (orderId) formData.append('order_id', orderId);
      if (selectedUserId) formData.append('selected_user_id', selectedUserId);
      if (selectedUserName) formData.append('operator_name', selectedUserName);
      formData.append('device_id', navigator.userAgent.slice(0, 120));
      const response = await axios.post(`${API_URL}/v2/cmp/scans`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setMessage(response.data.message || 'Imagem salva para conferência manual.');
      setFiles([]);
      await loadScans();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Não foi possível salvar o CMP fotografado.');
    } finally {
      setLoading(false);
    }
  };

  if (selectedScan) {
    return (
      <CmpReviewPanel
        scan={selectedScan}
        onClose={() => {
          setSelectedScan(null);
          loadScans().catch(() => {});
        }}
      />
    );
  }

  return (
    <section className="page-shell">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <h1>CMPs digitalizados para conferência</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            A foto do papel cria rascunho auditável. Confira antes de aplicar; ela nunca conclui a OM automaticamente.
          </p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => navigate(-1)}>Voltar</button>
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 18, display: 'grid', gap: 14 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', color: 'var(--text-muted)' }}>
          <Camera size={16} /> {diagnosis}
        </div>
        <div style={{ padding: 12, borderRadius: 8, background: '#fff7ed', color: '#9a3412', fontWeight: 600 }}>
          Mesmo quando QR ou marcações forem detectados, a leitura precisa ser conferida por uma pessoa antes de virar rascunho da OM.
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf"
          capture="environment"
          multiple
          style={{ display: 'none' }}
          onChange={(event) => {
            stopCamera();
            setFiles(Array.from(event.target.files || []));
            event.currentTarget.value = '';
          }}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" type="button" onClick={() => openCamera('environment')}>
            <Camera size={16} /> Abrir câmera
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => fileInputRef.current?.click()}>
            <FileImage size={16} /> Escolher foto/PDF
          </button>
          {cameraActive && (
            <button className="btn btn-secondary" type="button" onClick={switchCamera}>
              Trocar câmera
            </button>
          )}
        </div>
        {cameraError && <div style={{ color: 'var(--danger)' }}>{cameraError}</div>}
        {previewUrl && (
          <div style={{ display: 'grid', gap: 10 }}>
            <img src={previewUrl} alt="Preview do CMP" style={{ maxWidth: 420, maxHeight: 300, borderRadius: 8, border: '1px solid var(--border)', objectFit: 'contain' }} />
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => openCamera('environment')}>Tirar novamente</button>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => fileInputRef.current?.click()}>Trocar arquivo</button>
            </div>
          </div>
        )}
        <button className="btn btn-primary" type="button" onClick={submit} disabled={loading}>
          <Upload size={16} /> {loading ? 'Enviando...' : 'Salvar para conferência'}
        </button>
        {message && <div style={{ color: 'var(--success)' }}>{message}</div>}
        {error && <div style={{ color: 'var(--danger)' }}>{error}</div>}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Pendentes e recentes</h2>
        <button className="btn btn-secondary btn-sm" type="button" onClick={loadScans}><RefreshCcw size={14} /> Atualizar</button>
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {scans.length === 0 && <div className="card" style={{ padding: 16 }}>Nenhum CMP digitalizado encontrado.</div>}
        {scans.map((scan) => (
          <article key={scan.id} className="card" style={{ padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <strong><FileImage size={16} /> {scan.original_name || scan.id}</strong>
              <span style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: scan.status === 'approved' ? 'var(--success)' : scan.status === 'rejected' ? 'var(--danger)' : '#b45309' }}>
                {scan.status === 'needs_review' ? 'A conferir' : scan.status === 'draft_saved' ? 'Rascunho' : scan.status === 'approved' ? 'Aprovado' : scan.status}
              </span>
            </div>
            <p style={{ color: 'var(--text-muted)', marginBottom: 8 }}>
              Criado em {formatServerDateTime(scan.created_at)} · confiança {Math.round((scan.confidence || 0) * 100)}%
            </p>
            <p style={{ margin: '0 0 10px 0' }}>
              {scan.extraction?.qr_status === 'not_configured'
                ? 'QR/OCR real não configurado: arquivo salvo para conferência manual.'
                : 'Extração registrada para revisão.'}
            </p>
            {['needs_review', 'draft_saved'].includes(scan.status) && (
              <button
                className="btn btn-secondary btn-sm"
                type="button"
                onClick={() => setSelectedScan(scan)}
              >
                Revisar extração
              </button>
            )}
          </article>
        ))}
      </div>

      {cameraActive && (
        <div style={{
          position: 'fixed',
          inset: 0,
          zIndex: 2000,
          background: '#020617',
          color: 'white',
          display: 'grid',
          gridTemplateRows: 'auto 1fr auto'
        }}>
          <header style={{ padding: 14, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 20 }}>Fotografar CMP preenchido</h2>
              <p style={{ margin: '4px 0 0', color: '#cbd5e1' }}>Enquadre a folha inteira, com o QR visível e sem cortar as bordas.</p>
            </div>
            <button className="btn btn-secondary" type="button" onClick={stopCamera}>Cancelar</button>
          </header>
          <div style={{ position: 'relative', overflow: 'hidden', background: '#0f172a' }}>
            <video
              ref={videoRef}
              playsInline
              muted
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            />
            <div style={{
              position: 'absolute',
              inset: '7% 5%',
              border: '3px solid rgba(255,255,255,0.92)',
              borderRadius: 16,
              boxShadow: '0 0 0 999px rgba(2,6,23,0.22)',
              pointerEvents: 'none'
            }} />
          </div>
          <footer style={{ padding: 14, display: 'grid', gap: 10, background: '#0f172a' }}>
            <button className="btn btn-primary" type="button" style={{ minHeight: 56, fontSize: 18 }} onClick={capturePhoto}>
              Usar esta foto
            </button>
            <div style={{ display: 'flex', gap: 10 }}>
              <button className="btn btn-secondary" type="button" style={{ flex: 1 }} onClick={switchCamera}>Trocar câmera</button>
              <button className="btn btn-secondary" type="button" style={{ flex: 1 }} onClick={() => fileInputRef.current?.click()}>Galeria/PDF</button>
            </div>
          </footer>
        </div>
      )}
    </section>
  );
}

function CmpReviewPanel({ scan, onClose }: { scan: ScanItem; onClose: () => void }) {
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [orders, setOrders] = useState<OrderOption[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState(scan.order_id || scan.suggested_order_id || '');
  const rawFields = useMemo(() => scan.extraction?.raw_fields || {}, [scan]);
  const [responsible, setResponsible] = useState(rawFields.operator_name || scan.operator_name || sessionStorage.getItem('mec_operator_name') || '');
  const [executionDate, setExecutionDate] = useState(rawFields.date || rawFields.date_raw || dateInputFromServerDate(scan.created_at));
  const [selectedOrderDetails, setSelectedOrderDetails] = useState<any>(null);

  const [itemStatuses, setItemStatuses] = useState<Record<string, 'ok' | 'attention' | 'not_applicable' | 'unanswered'>>({});
  const [itemNotes, setItemNotes] = useState<Record<string, string>>({});

  const [generalNotes, setGeneralNotes] = useState('');
  const [finalCondition, setFinalCondition] = useState<'released' | 'released_with_attention' | 'stopped'>('released');

  const [loadingOrders, setLoadingOrders] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      setLoadingOrders(true);
      try {
        const res = await axios.get(`${API_URL}/orders`);
        const allOrders = Array.isArray(res.data) ? res.data : [];
        setOrders(allOrders.filter((o: any) => ['scheduled', 'today', 'overdue', 'in_progress'].includes(o.status || '')));
      } catch (err) {
        console.error("Erro ao carregar OMs:", err);
      } finally {
        setLoadingOrders(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedOrderId) {
      setSelectedOrderDetails(null);
      return;
    }
    (async () => {
      setLoadingDetails(true);
      setError('');
      try {
        const res = await axios.get(`${API_URL}/v2/orders/${encodeURIComponent(selectedOrderId)}`);
        const orderData = res.data;
        setSelectedOrderDetails(orderData);

        const initialStatuses: Record<string, any> = {};
        const initialNotes: Record<string, string> = {};

        const ocrItems = scan.extraction?.items || [];
        const humanCorr = scan.extraction?.human_corrections || {};

        const checklistItems = orderData.items || [];
        checklistItems.forEach((item: any) => {
          let status: any = 'unanswered';
          let note = '';

          const ocrMatch = ocrItems.find((o: any) => o.item_id === item.item_id || o.item_number === item.item_number);
          const confidentEnough = Number(ocrMatch?.confidence ?? 0) >= 0.18;
          if (ocrMatch && ocrMatch.status && ocrMatch.status !== 'ambiguous' && confidentEnough) {
            status = ocrMatch.status;
          }
          if (ocrMatch?.notes) {
            note = ocrMatch.notes;
          }

          if (humanCorr.items && humanCorr.items[item.item_id]) {
            status = humanCorr.items[item.item_id].status || status;
            note = humanCorr.items[item.item_id].notes || note;
          }

          initialStatuses[item.item_id] = status;
          initialNotes[item.item_id] = note;
        });

        setItemStatuses(initialStatuses);
        setItemNotes(initialNotes);
        setGeneralNotes(humanCorr.general_notes || rawFields.materials || '');
        setFinalCondition(humanCorr.final_condition || rawFields.final_condition || 'released');
        if (!responsible) {
          setResponsible(rawFields.operator_name || scan.operator_name || sessionStorage.getItem('mec_operator_name') || '');
        }
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Erro ao carregar detalhes da OM.');
      } finally {
        setLoadingDetails(false);
      }
    })();
  }, [selectedOrderId, scan, responsible, rawFields]);

  const handleReview = async (reviewStatus: 'draft_saved' | 'approved' | 'rejected') => {
    if (!selectedOrderId && reviewStatus === 'approved') {
      setError('Selecione uma OM para confirmar a leitura do CMP.');
      return;
    }

    setSubmitting(true);
    setError('');

    try {
      const correctionsPayload = {
        order_id: selectedOrderId,
        operator_name: responsible,
        execution_date: executionDate,
        items: {},
        general_notes: generalNotes,
        final_condition: finalCondition
      } as any;

      Object.keys(itemStatuses).forEach(itemId => {
        correctionsPayload.items[itemId] = {
          status: itemStatuses[itemId],
          notes: itemNotes[itemId]
        };
      });

      await axios.post(`${API_URL}/v2/cmp/scans/${scan.id}/review`, {
        status: reviewStatus,
        selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined,
        operator_name: sessionStorage.getItem('mec_operator_name') || undefined,
        corrections: correctionsPayload,
        notes: `Revisão de CMP realizada via tela de conferência. Status: ${reviewStatus}. Não conclui OM automaticamente.`
      });

      onClose();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao processar decisão de conferência.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <style>{`
        .cmp-review-shell {
          position: fixed;
          inset: 0;
          z-index: 1000;
          background: var(--bg-app, #f7fafc);
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(360px, 480px);
          height: 100vh;
          width: 100vw;
        }
        .cmp-review-image-side {
          display: flex;
          flex-direction: column;
          height: 100%;
          min-width: 0;
          border-right: 1px solid var(--border);
        }
        .cmp-review-toolbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 18px;
          border-bottom: 1px solid var(--border);
          background: white;
          gap: 12px;
        }
        .cmp-review-toolbar-actions {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          justify-content: flex-end;
        }
        .cmp-review-form-side {
          display: flex;
          flex-direction: column;
          height: 100%;
          min-width: 0;
          background: white;
        }
        .cmp-review-two-fields {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        @media (max-width: 980px) {
          .cmp-review-shell {
            grid-template-columns: 1fr;
            grid-template-rows: minmax(46vh, 54vh) minmax(0, 1fr);
            overflow-y: auto;
          }
          .cmp-review-image-side {
            height: auto;
            min-height: 46vh;
            border-right: 0;
            border-bottom: 1px solid var(--border);
          }
          .cmp-review-toolbar {
            align-items: flex-start;
            flex-direction: column;
          }
          .cmp-review-toolbar-actions {
            width: 100%;
          }
          .cmp-review-toolbar-actions .btn {
            min-height: 44px;
            flex: 1 1 140px;
          }
          .cmp-review-form-side {
            height: auto;
            min-height: 46vh;
          }
          .cmp-review-image {
            max-width: 94vw !important;
            max-height: 45vh !important;
          }
          .cmp-review-two-fields {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
      <div className="cmp-review-shell">
      <div className="cmp-review-image-side">
        <div className="cmp-review-toolbar" style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 18px', borderBottom: '1px solid var(--border)', backgroundColor: 'white'
        }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>CMP Original Digitalizado</h3>
          <div className="cmp-review-toolbar-actions" style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-secondary btn-sm" onClick={() => setZoom(z => Math.max(0.5, z - 0.25))}>Zoom -</button>
            <button className="btn btn-secondary btn-sm" onClick={() => setZoom(1)}>Original</button>
            <button className="btn btn-secondary btn-sm" onClick={() => setZoom(z => Math.min(4, z + 0.25))}>Zoom +</button>
            <button className="btn btn-secondary btn-sm" style={{ display: 'flex', alignItems: 'center', gap: 4 }} onClick={() => setRotation(r => (r + 90) % 360)}>
              <RotateCw size={12} /> Rotação
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'auto', display: 'flex', justifyContent: 'center', alignItems: 'center', backgroundColor: '#334155', padding: 20 }}>
          <div style={{
            transform: `scale(${zoom}) rotate(${rotation}deg)`,
            transition: 'transform 0.15s ease-out',
            display: 'inline-block'
          }}>
            <img
              src={`${API_URL}/v2/cmp/scans/${scan.id}/files/0`}
              alt="Scan do CMP"
              className="cmp-review-image"
              style={{ maxWidth: '80vw', maxHeight: '75vh', objectFit: 'contain', boxShadow: '0 10px 25px rgba(0,0,0,0.35)' }}
            />
          </div>
        </div>
      </div>

      <div className="cmp-review-form-side">
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, color: 'var(--primary)' }}>Conferência Humana</h3>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Scan ID: {scan.id.substring(0, 8)}...</span>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={submitting}>Fechar</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {error && (
            <div style={{ backgroundColor: 'var(--danger-light)', color: 'var(--danger)', padding: 12, borderRadius: 6, fontWeight: 500, fontSize: 13 }}>
              {error}
            </div>
          )}

          <div style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 12, background: '#f8fafc', display: 'grid', gap: 6 }}>
            <strong style={{ fontSize: 13 }}>Leitura automática do CMP</strong>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              OM sugerida: {scan.suggested_order_id ? 'identificada' : 'não identificada'} ·
              Ativo sugerido: {scan.extraction?.raw_fields?.patrimonio || scan.suggested_asset_id || 'não identificado'} ·
              Método: {scan.extraction?.raw_fields?.provider || scan.extraction?.vision_status || 'manual'}
            </span>
            {Array.isArray(scan.extraction?.warnings) && scan.extraction.warnings.length > 0 && (
              <div style={{ display: 'grid', gap: 4 }}>
                {scan.extraction.warnings.slice(0, 3).map((warning: string, index: number) => (
                  <span key={`${warning}-${index}`} style={{ fontSize: 12, color: '#92400e' }}>• {warning}</span>
                ))}
              </div>
            )}
          </div>

          <label className="form-group">
            <span className="form-label" style={{ fontWeight: 'bold' }}>Vincular a qual Ordem de Manutenção?</span>
            <select
              className="form-control"
              value={selectedOrderId}
              onChange={(e) => setSelectedOrderId(e.target.value)}
              disabled={loadingOrders || submitting}
            >
              <option value="">Selecione uma OM aberta...</option>
              {orders.map((o) => (
                <option key={o.id} value={o.id}>
                  OM #{o.friendly_number} • {o.asset?.patrimonio} — {o.asset?.description?.slice(0, 35)}...
                </option>
              ))}
            </select>
            {loadingOrders && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Carregando ordens...</span>}
          </label>

          <div className="cmp-review-two-fields">
            <label className="form-group">
              <span className="form-label">Responsável</span>
              <input
                className="form-control"
                value={responsible}
                onChange={(e) => setResponsible(e.target.value)}
                placeholder="Nome do executor"
                disabled={submitting}
              />
            </label>
            <label className="form-group">
              <span className="form-label">Data de Execução</span>
              <input
                className="form-control"
                type="date"
                value={executionDate}
                onChange={(e) => setExecutionDate(e.target.value)}
                disabled={submitting}
              />
            </label>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '8px 0' }} />

          <div>
            <h4 style={{ margin: '0 0 12px 0', fontSize: 14 }}>Itens do Checklist</h4>
            {loadingDetails && <p style={{ color: 'var(--text-muted)' }}>Carregando itens do checklist...</p>}
            {!selectedOrderId && !loadingDetails && (
              <p style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: 13 }}>
                Associe a uma Ordem de Manutenção acima para ver os itens de verificação.
              </p>
            )}
            {selectedOrderId && selectedOrderDetails && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {(selectedOrderDetails.items || []).map((item: any, index: number) => {
                  const currentStatus = itemStatuses[item.item_id] || 'unanswered';
                  return (
                    <div key={item.item_id} style={{
                      padding: 12, border: '1px solid var(--border)', borderRadius: 8,
                      backgroundColor: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 8
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>
                          <span style={{ color: 'var(--primary)', marginRight: 6 }}>{item.item_number || (index + 1)}</span>
                          {item.description}
                        </span>
                      </div>

                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{
                            flex: 1, padding: '4px', fontSize: 11, fontWeight: 700,
                            backgroundColor: currentStatus === 'ok' ? 'var(--success)' : 'white',
                            color: currentStatus === 'ok' ? 'white' : 'var(--text-main)',
                            border: '1px solid ' + (currentStatus === 'ok' ? 'var(--success)' : 'var(--border)')
                          }}
                          onClick={() => setItemStatuses(prev => ({ ...prev, [item.item_id]: 'ok' }))}
                          disabled={submitting}
                        >
                          OK
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{
                            flex: 1, padding: '4px', fontSize: 11, fontWeight: 700,
                            backgroundColor: currentStatus === 'attention' ? 'var(--danger)' : 'white',
                            color: currentStatus === 'attention' ? 'white' : 'var(--text-main)',
                            border: '1px solid ' + (currentStatus === 'attention' ? 'var(--danger)' : 'var(--border)')
                          }}
                          onClick={() => setItemStatuses(prev => ({ ...prev, [item.item_id]: 'attention' }))}
                          disabled={submitting}
                        >
                          DEF
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{
                            flex: 1, padding: '4px', fontSize: 11, fontWeight: 700,
                            backgroundColor: currentStatus === 'not_applicable' ? 'var(--text-muted)' : 'white',
                            color: currentStatus === 'not_applicable' ? 'white' : 'var(--text-main)',
                            border: '1px solid ' + (currentStatus === 'not_applicable' ? 'var(--text-muted)' : 'var(--border)')
                          }}
                          onClick={() => setItemStatuses(prev => ({ ...prev, [item.item_id]: 'not_applicable' }))}
                          disabled={submitting}
                        >
                          N/A
                        </button>
                      </div>

                      <input
                        className="form-control"
                        style={{ padding: '4px 8px', fontSize: 12, height: 28 }}
                        placeholder="Observações do item (opcional)"
                        value={itemNotes[item.item_id] || ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          setItemNotes(prev => ({ ...prev, [item.item_id]: val }));
                        }}
                        disabled={submitting}
                      />
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '8px 0' }} />

          <label className="form-group">
            <span className="form-label">Observações gerais / materiais utilizados</span>
            <textarea
              className="form-control"
              style={{ minHeight: 60, resize: 'vertical' }}
              value={generalNotes}
              onChange={(e) => setGeneralNotes(e.target.value)}
              placeholder="Descreva observações gerais..."
              disabled={submitting}
            />
          </label>

          <label className="form-group">
            <span className="form-label">Condição Operacional Final</span>
            <select
              className="form-control"
              value={finalCondition}
              onChange={(e) => setFinalCondition(e.target.value as any)}
              disabled={submitting}
            >
              <option value="released">Apta / Liberada (Apto)</option>
              <option value="released_with_attention">Apta com Atenção (Atenção)</option>
              <option value="stopped">Parada / Bloqueio Físico (Defeito)</option>
            </select>
          </label>
        </div>

        <div style={{
          padding: '16px 20px', borderTop: '1px solid var(--border)',
          display: 'flex', gap: 8, backgroundColor: '#f8fafc'
        }}>
          <button
            className="btn btn-secondary"
            style={{ flex: 1, fontSize: 13 }}
            onClick={() => handleReview('rejected')}
            disabled={submitting}
          >
            Rejeitar
          </button>
          <button
            className="btn btn-secondary"
            style={{ flex: 1, fontSize: 13 }}
            onClick={() => handleReview('draft_saved')}
            disabled={submitting}
          >
            Rascunho
          </button>
          <button
            className="btn btn-primary"
            style={{ flex: 2, fontSize: 13 }}
            onClick={() => handleReview('approved')}
            disabled={submitting || !selectedOrderId}
          >
            {submitting ? 'Salvando...' : 'Confirmar leitura'}
          </button>
        </div>
      </div>
    </div>
    </>
  );
}
