import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Camera, Search, X, RotateCcw, QrCode } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

type ScanState = 'idle' | 'starting' | 'scanning' | 'detected' | 'error';

type AssetCandidate = {
  id: string;
  patrimonio?: string | null;
  controlled_code?: string | null;
  description?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  sector?: { name?: string | null } | null;
};

const isUuid = (value: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);

function parseJsonPayload(raw: string): any | null {
  try {
    const decoded = decodeURIComponent(raw);
    const parsed = JSON.parse(decoded);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

export default function ScannerQR() {
  const navigate = useNavigate();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const frameRef = useRef<number | null>(null);
  const resolvingRef = useRef(false);
  const [state, setState] = useState<ScanState>('idle');
  const [error, setError] = useState('');
  const [manualValue, setManualValue] = useState('');
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const [lastDetected, setLastDetected] = useState('');
  const [candidates, setCandidates] = useState<AssetCandidate[]>([]);

  const stopCamera = useCallback(() => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const navigateFromCode = useCallback(async (rawCode: string) => {
    const raw = rawCode.trim();
    if (!raw || resolvingRef.current) return;
    resolvingRef.current = true;
    setLastDetected(raw);
    setState('detected');

    const go = (path: string) => {
      stopCamera();
      navigate(path);
    };

    try {
      const payload = parseJsonPayload(raw);
      if (payload) {
        const orderId = String(payload.order_id || payload.orderId || '').trim();
        const assetId = String(payload.asset_id || payload.assetId || '').trim();
        const kind = String(payload.kind || payload.type || '').toLowerCase();
        if (orderId && (kind.includes('cmp') || kind.includes('form'))) {
          go(`/cmp/${encodeURIComponent(orderId)}/digitalizar`);
          return;
        }
        if (orderId) {
          go(`/ordens/${encodeURIComponent(orderId)}/executar`);
          return;
        }
        if (assetId) {
          go(`/ativos/${encodeURIComponent(assetId)}`);
          return;
        }
      }

      try {
        const parsedUrl = new URL(raw, window.location.origin);
        const path = parsedUrl.pathname;
        if (parsedUrl.hash) {
          const fragmentPayload = parseJsonPayload(parsedUrl.hash.replace(/^#/, ''));
          const orderId = String(fragmentPayload?.order_id || fragmentPayload?.orderId || '').trim();
          const kind = String(fragmentPayload?.kind || fragmentPayload?.type || '').toLowerCase();
          if (orderId && (kind.includes('cmp') || kind.includes('form'))) {
            go(`/cmp/${encodeURIComponent(orderId)}/digitalizar`);
            return;
          }
        }
        const cmpMatch = path.match(/^\/cmp\/([^/]+)\/(?:imprimir|print|digitalizar)/i);
        if (cmpMatch?.[1]) {
          go(`/cmp/${encodeURIComponent(decodeURIComponent(cmpMatch[1]))}/digitalizar`);
          return;
        }
        const orderMatch = path.match(/^\/ordens\/([^/]+)(?:\/executar)?/i);
        if (orderMatch?.[1]) {
          go(`/ordens/${encodeURIComponent(decodeURIComponent(orderMatch[1]))}/executar`);
          return;
        }
        const assetMatch = path.match(/^\/(?:ativos|inativos)\/([^/]+)/i);
        if (assetMatch?.[1]) {
          go(`/ativos/${encodeURIComponent(decodeURIComponent(assetMatch[1]))}`);
          return;
        }
        const tokenMatch = path.match(/^\/([oa])\/([^/]+)/i);
        if (tokenMatch?.[2]) {
          const response = await axios.get(`${API_URL}/resolve-token/${encodeURIComponent(tokenMatch[2])}`);
          if (response.data?.type === 'order') {
            go(`/ordens/${response.data.id}/executar`);
            return;
          }
          if (response.data?.type === 'asset') {
            go(`/ativos/${response.data.id}`);
            return;
          }
        }
      } catch {
        // Não era URL. Tenta como token/patrimônio abaixo.
      }

      if (isUuid(raw)) {
        go(`/ordens/${encodeURIComponent(raw)}/executar`);
        return;
      }

      const resolution = await axios.get(`${API_URL}/assets/resolve-identifier`, { params: { value: raw } });
      if (resolution.data?.status === 'unique' && resolution.data?.candidates?.[0]?.id) {
        go(`/ativos/${encodeURIComponent(resolution.data.candidates[0].id)}`);
        return;
      }
      if (resolution.data?.status === 'ambiguous' && Array.isArray(resolution.data.candidates)) {
        stopCamera();
        setCandidates(resolution.data.candidates);
        setState('idle');
        resolvingRef.current = false;
        return;
      }

      localStorage.setItem('mec_global_search_prefill', raw);
      go(`/ativos?search=${encodeURIComponent(raw)}`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'QR lido, mas não foi possível abrir o destino.');
      resolvingRef.current = false;
      setState('scanning');
    }
  }, [navigate, stopCamera]);

  const scanLoop = useCallback(async () => {
    const detectorCtor = (window as any).BarcodeDetector;
    const video = videoRef.current;
    if (!detectorCtor || !video || video.readyState < 2 || resolvingRef.current) {
      frameRef.current = requestAnimationFrame(scanLoop);
      return;
    }
    try {
      const detector = new detectorCtor({ formats: ['qr_code'] });
      const codes = await detector.detect(video);
      const raw = codes?.[0]?.rawValue;
      if (raw) {
        await navigateFromCode(raw);
        return;
      }
    } catch {
      setError('Este navegador abriu a câmera, mas não consegue ler QR automaticamente. Use a busca manual abaixo.');
    }
    frameRef.current = requestAnimationFrame(scanLoop);
  }, [navigateFromCode]);

  const openCamera = useCallback(async (mode: 'environment' | 'user') => {
    setError('');
    resolvingRef.current = false;
    if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(window.location.hostname)) {
      setError('Câmera bloqueada porque o acesso não está em HTTPS. Abra a demonstração em HTTPS ou use localhost para testar.');
      setState('error');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Este navegador não permite abrir câmera pelo sistema. Digite o código, patrimônio ou use a busca.');
      setState('error');
      return;
    }
    if (!(window as any).BarcodeDetector) {
      setError('A câmera pode abrir, mas este navegador não tem leitor QR automático. Se o QR não ler, digite o código ou patrimônio.');
    }
    setState('starting');
    stopCamera();
    try {
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
      setState('scanning');
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      frameRef.current = requestAnimationFrame(scanLoop);
    } catch (err: any) {
      stopCamera();
      setState('error');
      if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
        setError('Permissão de câmera negada. Libere a câmera no navegador ou use a busca manual.');
      } else if (err?.name === 'NotFoundError') {
        setError('Nenhuma câmera foi encontrada neste dispositivo. Use a busca manual.');
      } else {
        setError(err?.message || 'Não foi possível abrir a câmera.');
      }
    }
  }, [scanLoop, stopCamera]);

  useEffect(() => {
    openCamera('environment').catch(() => {});
    return () => stopCamera();
  }, [openCamera, stopCamera]);

  const submitManual = () => {
    if (manualValue.trim()) navigateFromCode(manualValue).catch(() => {});
  };

  const switchCamera = () => {
    openCamera(facingMode === 'environment' ? 'user' : 'environment').catch(() => {});
  };

  return (
    <main style={{ minHeight: 'calc(100vh - 72px)', background: '#020617', color: 'white', display: 'grid', gridTemplateRows: 'auto 1fr auto' }}>
      <header style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22 }}>Escanear QR</h1>
          <p style={{ margin: '4px 0 0', color: '#cbd5e1' }}>Aponte para QR de OM, CMP impresso ou ativo.</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={() => { stopCamera(); navigate(-1); }}>
          <X size={18} /> Fechar
        </button>
      </header>

      <section style={{ position: 'relative', minHeight: 360, overflow: 'hidden', background: '#0f172a' }}>
        <video
          ref={videoRef}
          playsInline
          muted
          style={{ width: '100%', height: '100%', minHeight: '58vh', objectFit: 'cover', display: state === 'scanning' || state === 'starting' ? 'block' : 'none' }}
        />
        {(state === 'idle' || state === 'error') && (
          <div style={{ minHeight: '58vh', display: 'grid', placeItems: 'center', padding: 24, textAlign: 'center' }}>
            <div>
              <QrCode size={56} />
              <p>{error || 'Câmera pronta para leitura de QR.'}</p>
              <button className="btn btn-primary" type="button" onClick={() => openCamera('environment')}>
                <Camera size={18} /> Abrir câmera
              </button>
            </div>
          </div>
        )}
        <div style={{
          position: 'absolute',
          inset: '12%',
          border: '3px solid rgba(255,255,255,0.9)',
          borderRadius: 18,
          boxShadow: '0 0 0 999px rgba(2,6,23,0.28)',
          pointerEvents: 'none'
        }} />
        {lastDetected && (
          <div style={{ position: 'absolute', left: 16, right: 16, bottom: 16, background: 'rgba(15,23,42,0.9)', borderRadius: 12, padding: 12 }}>
            QR detectado: {lastDetected.slice(0, 100)}
          </div>
        )}
      </section>

      <footer style={{ padding: 16, background: '#0f172a', display: 'grid', gap: 12 }}>
        {candidates.length > 0 && (
          <section style={{ background: '#fff', color: '#0f172a', borderRadius: 14, padding: 14, display: 'grid', gap: 10 }} aria-live="polite">
            <div>
              <strong>Este código existe em mais de um item.</strong>
              <p style={{ margin: '4px 0 0', fontSize: 14 }}>Escolha pela descrição, setor e fabricante. Assim o aplicativo nunca abre o equipamento errado.</p>
            </div>
            {candidates.map((asset) => (
              <button
                key={asset.id}
                type="button"
                className="btn btn-secondary"
                style={{ justifyContent: 'flex-start', textAlign: 'left', minHeight: 58 }}
                onClick={() => { setCandidates([]); navigate(`/ativos/${encodeURIComponent(asset.id)}`); }}
              >
                <span>
                  <strong>{asset.description || 'Item sem descrição'}</strong><br />
                  <small>Código: {asset.patrimonio || asset.controlled_code || 'não informado'} · {asset.sector?.name || 'Setor não informado'}{asset.manufacturer ? ` · ${asset.manufacturer}` : ''}{asset.model ? ` ${asset.model}` : ''}</small>
                </span>
              </button>
            ))}
            <button type="button" className="btn btn-link" onClick={() => { setCandidates([]); setLastDetected(''); openCamera('environment'); }}>Ler outro código</button>
          </section>
        )}
        {error && <div style={{ background: '#7f1d1d', color: 'white', borderRadius: 10, padding: 12 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" type="button" onClick={switchCamera}>
            <RotateCcw size={18} /> Trocar câmera
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => navigate('/checklists/iniciar')}>
            <Search size={18} /> Buscar OM manualmente
          </button>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-control"
            value={manualValue}
            onChange={(event) => setManualValue(event.target.value)}
            placeholder="Digite QR, código da OM ou patrimônio"
            style={{ minHeight: 48 }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submitManual();
            }}
          />
          <button className="btn btn-primary" type="button" onClick={submitManual}>Abrir</button>
        </div>
      </footer>
    </main>
  );
}
