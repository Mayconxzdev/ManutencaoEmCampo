/**
 * Toast — Sistema de notificações sem alert nativo.
 * Substitui window.alert, window.confirm e window.prompt.
 * Componente de notificações temporárias.
 */
import React, { useState, useCallback } from 'react';
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { ToastContext, type Toast, type ToastType } from './toastContext';

// ─── Icons por tipo ──────────────────────────────────────────────────────────
const icons: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle size={18} />,
  error: <XCircle size={18} />,
  warning: <AlertTriangle size={18} />,
  info: <Info size={18} />,
};

const colors: Record<ToastType, { bg: string; border: string; icon: string }> = {
  success: { bg: 'var(--success-light)', border: 'var(--success)', icon: 'var(--success)' },
  error:   { bg: 'var(--danger-light)', border: 'var(--danger)', icon: 'var(--danger)' },
  warning: { bg: 'var(--warning-light)', border: 'var(--warning)', icon: '#856404' },
  info:    { bg: 'var(--primary-light)', border: 'var(--primary)', icon: 'var(--primary)' },
};

// ─── ConfirmModal ─────────────────────────────────────────────────────────────
interface ConfirmState {
  title: string;
  message?: string;
  resolve: (v: boolean) => void;
}

interface PromptState {
  title: string;
  message?: string;
  defaultValue?: string;
  resolve: (v: string | null) => void;
}

// ─── Provider ────────────────────────────────────────────────────────────────
export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [promptState, setPromptState] = useState<PromptState | null>(null);
  const [promptValue, setPromptValue] = useState('');

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const showToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = `toast_${Date.now()}_${Math.random()}`;
    const duration = toast.duration ?? (toast.type === 'error' ? 6000 : 4000);
    setToasts(prev => [...prev.slice(-4), { ...toast, id, duration }]); // máximo 5 toasts
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration);
    }
  }, [removeToast]);

  const success = useCallback((title: string, message?: string) => showToast({ type: 'success', title, message }), [showToast]);
  const error   = useCallback((title: string, message?: string) => showToast({ type: 'error',   title, message }), [showToast]);
  const warning = useCallback((title: string, message?: string) => showToast({ type: 'warning', title, message }), [showToast]);
  const info    = useCallback((title: string, message?: string) => showToast({ type: 'info',    title, message }), [showToast]);

  const confirm = useCallback((title: string, message?: string): Promise<boolean> => {
    return new Promise(resolve => {
      setConfirmState({ title, message, resolve });
    });
  }, []);

  const prompt = useCallback((title: string, message?: string, defaultValue = ''): Promise<string | null> => {
    return new Promise(resolve => {
      setPromptValue(defaultValue);
      setPromptState({ title, message, defaultValue, resolve });
    });
  }, []);

  const handleConfirm = (result: boolean) => {
    confirmState?.resolve(result);
    setConfirmState(null);
  };

  return (
    <ToastContext.Provider value={{ showToast, success, error, warning, info, confirm, prompt }}>
      {children}

      {/* ── Toast Container ── */}
      <div
        style={{
          position: 'fixed', bottom: '24px', right: '24px', zIndex: 10000,
          display: 'flex', flexDirection: 'column', gap: '10px',
          maxWidth: '380px', width: '100%',
          pointerEvents: 'none',
        }}
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map(toast => {
          const c = colors[toast.type];
          return (
            <div
              key={toast.id}
              role="alert"
              style={{
                backgroundColor: c.bg,
                border: `1px solid ${c.border}`,
                borderRadius: '10px',
                padding: '14px 16px',
                boxShadow: 'var(--shadow-lg)',
                display: 'flex', alignItems: 'flex-start', gap: '12px',
                animation: 'slideInRight 0.25s ease-out',
                pointerEvents: 'all',
              }}
            >
              <span style={{ color: c.icon, flexShrink: 0, marginTop: '1px' }}>{icons[toast.type]}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: '700', fontSize: '14px', color: 'var(--text-main)' }}>
                  {toast.title}
                </div>
                {toast.message && (
                  <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '3px' }}>
                    {toast.message}
                  </div>
                )}
              </div>
              <button
                onClick={() => removeToast(toast.id)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text-muted)', padding: '2px', flexShrink: 0
                }}
                aria-label="Fechar notificação"
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>

      {/* ── Confirm Modal ── */}
      {confirmState && (
        <div
          className="overlay"
          style={{ zIndex: 10001 }}
          onClick={e => { if (e.target === e.currentTarget) handleConfirm(false); }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
        >
          <div
            className="modal-content"
            style={{ maxWidth: '420px', borderRadius: '16px', padding: '32px', textAlign: 'center' }}
          >
            <AlertTriangle size={32} style={{ color: 'var(--warning)', marginBottom: '16px' }} />
            <h2 id="confirm-title" style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>
              {confirmState.title}
            </h2>
            {confirmState.message && (
              <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '24px', lineHeight: '1.5' }}>
                {confirmState.message}
              </p>
            )}
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button className="btn btn-secondary" onClick={() => handleConfirm(false)}>
                Cancelar
              </button>
              <button
                className="btn btn-primary"
                style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }}
                onClick={() => handleConfirm(true)}
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Prompt Modal ── */}
      {promptState && (
        <div
          className="overlay"
          style={{ zIndex: 10001 }}
          onClick={e => { if (e.target === e.currentTarget) { promptState.resolve(null); setPromptState(null); } }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="prompt-title"
        >
          <div
            className="modal-content"
            style={{ maxWidth: '420px', borderRadius: '16px', padding: '32px', textAlign: 'left' }}
          >
            <h2 id="prompt-title" style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px', textAlign: 'center' }}>
              {promptState.title}
            </h2>
            {promptState.message && (
              <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '16px', lineHeight: '1.5' }}>
                {promptState.message}
              </p>
            )}
            <div className="form-group" style={{ marginBottom: '20px' }}>
              <input
                type="text"
                className="form-control"
                value={promptValue}
                onChange={e => setPromptValue(e.target.value)}
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    promptState.resolve(promptValue);
                    setPromptState(null);
                  } else if (e.key === 'Escape') {
                    promptState.resolve(null);
                    setPromptState(null);
                  }
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button className="btn btn-secondary" onClick={() => { promptState.resolve(null); setPromptState(null); }}>
                Cancelar
              </button>
              <button
                className="btn btn-primary"
                onClick={() => { promptState.resolve(promptValue); setPromptState(null); }}
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(24px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </ToastContext.Provider>
  );
};

export default ToastProvider;
