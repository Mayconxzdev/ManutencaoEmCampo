/**
 * StatusBadge — Badge de status com texto em português.
 * Traduz status internos (inglês) para linguagem humana (seção 45).
 */
import React from 'react';

const STATUS_MAP: Record<string, { label: string; bg: string; color: string; dot?: string }> = {
  // Ordens — status de prazo/deadline
  scheduled:    { label: 'Programada',       bg: 'var(--primary-light)',  color: 'var(--primary)' },
  today:        { label: 'Deste mês',        bg: 'hsl(220, 90%, 94%)',    color: 'var(--primary)' },
  overdue:      { label: 'Atrasada',         bg: 'var(--danger-light)',   color: 'var(--danger)',  dot: 'var(--danger)' },
  needs_review: { label: 'A conferir',       bg: 'hsl(45, 90%, 94%)',     color: '#854d0e' },
  in_progress:  { label: 'Em andamento',     bg: 'hsl(200, 80%, 94%)',    color: 'hsl(200, 80%, 35%)' },
  completed:    { label: 'Concluída',        bg: 'var(--success-light)',  color: 'var(--success)' },
  completed_with_issues: { label: 'Concluída c/ pendência', bg: 'var(--warning-light)', color: '#856404' },
  cancelled:    { label: 'Cancelada',        bg: 'hsl(0, 0%, 94%)',       color: 'var(--text-muted)' },
  not_started:  { label: 'Não iniciada',     bg: 'hsl(0, 0%, 96%)',       color: 'var(--text-muted)' },
  // Ordens — execution_status
  // Ativos
  active:       { label: 'Ativo',            bg: 'var(--success-light)',  color: 'var(--success)' },
  inactive:     { label: 'Inativo',          bg: 'hsl(0, 0%, 94%)',       color: 'var(--text-muted)' },
  stopped:      { label: 'Parado',           bg: 'var(--danger-light)',   color: 'var(--danger)',  dot: 'var(--danger)' },
  // Planos
  confirmed:    { label: 'Confirmado',       bg: 'var(--success-light)',  color: 'var(--success)' },
  suggested:    { label: 'Sugerido',         bg: 'var(--primary-light)',  color: 'var(--primary)' },
  to_review:    { label: 'A confirmar',      bg: 'hsl(45, 90%, 94%)',     color: '#854d0e' },
  none:         { label: 'Sem plano',        bg: 'hsl(0, 0%, 96%)',       color: 'var(--text-muted)' },
  // Prioridades
  low:          { label: 'Baixa',            bg: 'var(--success-light)',  color: 'var(--success)' },
  medium:       { label: 'Média',            bg: 'var(--warning-light)',  color: '#856404' },
  high:         { label: 'Alta',             bg: 'var(--danger-light)',   color: 'var(--danger)' },
  critical:     { label: 'Crítica',          bg: 'var(--danger-light)',   color: 'var(--danger)',  dot: 'var(--danger)' },
  // Problemas/Issues
  open:         { label: 'Aberto',           bg: 'var(--danger-light)',   color: 'var(--danger)' },
  resolved:     { label: 'Resolvido',        bg: 'var(--success-light)',  color: 'var(--success)' },
  // Checklists — items
  ok:           { label: 'OK',              bg: 'var(--success-light)',  color: 'var(--success)' },
  attention:    { label: 'Atenção',          bg: 'var(--warning-light)',  color: '#856404' },
  not_applicable: { label: 'N/A',           bg: 'hsl(0, 0%, 94%)',       color: 'var(--text-muted)' },
  unanswered:   { label: 'Não respondido',  bg: 'hsl(0, 0%, 96%)',       color: 'var(--text-muted)' },
  // Histórico legado
  legacy_confirmed:    { label: 'Concluída (legado)', bg: 'var(--success-light)', color: 'var(--success)' },
  legacy_to_review:    { label: 'A conferir (legado)', bg: 'hsl(45, 90%, 94%)', color: '#854d0e' },
  legacy_superseded:   { label: 'Superada', bg: 'hsl(0, 0%, 96%)', color: 'var(--text-muted)' },
};

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
  pulseDot?: boolean;
}

const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'md', pulseDot }) => {
  const cfg = STATUS_MAP[status] || {
    label: status,
    bg: 'hsl(0, 0%, 94%)',
    color: 'var(--text-muted)',
  };

  const fontSize = size === 'sm' ? '10px' : '11px';
  const padding  = size === 'sm' ? '2px 6px' : '3px 10px';

  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: '5px',
        backgroundColor: cfg.bg, color: cfg.color,
        fontSize, fontWeight: '700', padding, borderRadius: '20px',
        letterSpacing: '0.3px', textTransform: 'uppercase', lineHeight: '1',
        whiteSpace: 'nowrap',
      }}
    >
      {(pulseDot || cfg.dot) && (
        <span
          style={{
            width: size === 'sm' ? '5px' : '6px',
            height: size === 'sm' ? '5px' : '6px',
            backgroundColor: cfg.dot || cfg.color,
            borderRadius: '50%',
            display: 'inline-block',
            animation: pulseDot ? 'pulse 1.5s infinite' : 'none',
          }}
        />
      )}
      {cfg.label}
    </span>
  );
};

export { STATUS_MAP };
export default StatusBadge;
