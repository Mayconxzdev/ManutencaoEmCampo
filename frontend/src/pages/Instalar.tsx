import { Download, ExternalLink, Monitor, ShieldCheck, Smartphone } from 'lucide-react';
import { useEffect, useState } from 'react';

type DeviceKind = 'windows' | 'android' | 'ios' | 'other';

function detectDevice(): DeviceKind {
  const userAgent = navigator.userAgent || '';
  if (/iPad|iPhone|iPod/.test(userAgent)) return 'ios';
  if (/Android/i.test(userAgent)) return 'android';
  if (/Windows/i.test(userAgent)) return 'windows';
  return 'other';
}

/**
 * Página deliberadamente portátil: o projeto de portfólio não contém URL,
 * IP, certificado ou instrução de rede de qualquer ambiente corporativo.
 */
export default function Instalar() {
  const [device, setDevice] = useState<DeviceKind>(detectDevice());
  const [installPrompt, setInstallPrompt] = useState<any>(null);
  const [online, setOnline] = useState<'checking' | 'online' | 'offline'>('checking');

  useEffect(() => {
    fetch('/health', { cache: 'no-store' })
      .then((response) => setOnline(response.ok ? 'online' : 'offline'))
      .catch(() => setOnline('offline'));

    const handler = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  const installPwa = async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice.catch(() => null);
    setInstallPrompt(null);
  };

  return (
    <main className="page-shell" style={{ maxWidth: 960 }}>
      <div className="card" style={{ padding: 24, display: 'grid', gap: 18 }}>
        <div>
          <h1 style={{ marginBottom: 6 }}>Usar como aplicativo em campo</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            Esta é uma demonstração pública. Ela funciona no navegador e pode ser instalada como PWA em dispositivos compatíveis.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" type="button" onClick={() => setDevice('windows')}><Monitor size={18} /> Estou no PC</button>
          <button className="btn btn-secondary" type="button" onClick={() => setDevice('android')}><Smartphone size={18} /> Tablet Android</button>
          <button className="btn btn-secondary" type="button" onClick={() => setDevice('ios')}><Smartphone size={18} /> iPhone/iPad</button>
          <a className="btn btn-primary" href="/"><ExternalLink size={18} /> Abrir demonstração</a>
        </div>

        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          <div className="card" style={{ padding: 16, border: '1px solid var(--border)' }}>
            <strong>Servidor local</strong>
            <p>{online === 'checking' ? 'Verificando...' : online === 'online' ? 'Disponível' : 'Indisponível'}</p>
          </div>
          <div className="card" style={{ padding: 16, border: '1px solid var(--border)' }}>
            <strong>Dados demonstrativos</strong>
            <p>Ativos, pessoas e ordens apresentados aqui são fictícios e recriáveis.</p>
          </div>
          <div className="card" style={{ padding: 16, border: '1px solid var(--border)' }}>
            <strong>Privacidade</strong>
            <p>Não há conexão automática com redes, bancos ou repositórios externos.</p>
          </div>
        </section>

        {installPrompt && (
          <button className="btn btn-primary" type="button" onClick={installPwa}>
            <Download size={18} /> Instalar Manutenção em Campo neste dispositivo
          </button>
        )}

        <DeviceInstructions device={device} />
      </div>
    </main>
  );
}

function DeviceInstructions({ device }: { device: DeviceKind }) {
  if (device === 'windows') {
    return <section className="card" style={{ padding: 18, border: '1px solid var(--border)' }}>
      <h2><Monitor size={20} /> Windows</h2>
      <p>Execute o backend e o frontend conforme o README. Em navegadores Chromium, use o ícone de instalação na barra de endereço para adicionar a demo como aplicativo.</p>
    </section>;
  }
  if (device === 'android' || device === 'ios') {
    return <section className="card" style={{ padding: 18, border: '1px solid var(--border)' }}>
      <h2><Smartphone size={20} /> Dispositivo móvel</h2>
      <ol>
        <li>Abra a URL da demonstração em navegador atualizado.</li>
        <li>Em Android, use “Instalar app” ou “Adicionar à tela inicial”.</li>
        <li>Em iPhone/iPad, abra no Safari e use Compartilhar &gt; Adicionar à Tela de Início.</li>
        <li>Para testar câmera ou microfone fora de localhost, publique a demo em HTTPS.</li>
      </ol>
    </section>;
  }
  return <section className="card" style={{ padding: 18, border: '1px solid var(--border)' }}>
    <h2><ShieldCheck size={20} /> Navegador moderno</h2>
    <p>Use Chrome, Edge, Firefox ou Safari atualizado. Para recursos de mídia em produção, utilize HTTPS.</p>
  </section>;
}
