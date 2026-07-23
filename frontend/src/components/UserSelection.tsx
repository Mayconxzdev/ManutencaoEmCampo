import { useMemo, useState } from 'react';

type Operator = {
  id: string;
  name: string;
  photo_thumbnail_url?: string | null;
};

type UserSelectionProps = {
  operators: Operator[];
  loading: boolean;
  onSelect: (operator: Operator) => void;
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || '?';

export default function UserSelection({ operators, loading, onSelect }: UserSelectionProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return operators;
    return operators.filter((operator) => operator.name.toLowerCase().includes(q));
  }, [operators, query]);

  return (
    <main style={{ minHeight: '100vh', background: '#f8fafc', padding: '32px 16px', display: 'grid', placeItems: 'center' }}>
      <section style={{ width: '100%', maxWidth: '760px' }}>
        <div style={{ marginBottom: '24px' }}>
          <p style={{ margin: '0 0 6px', color: '#64748b', fontSize: '14px', fontWeight: 700 }}>Manutenção em Campo</p>
          <h1 style={{ margin: 0, fontSize: '30px', color: '#0f172a' }}>Quem vai registrar e conferir?</h1>
          <p style={{ margin: '8px 0 0', color: '#475569' }}>
            Selecione Camila ou Rafael. Quem executou a manutenção será informado no resumo final.
          </p>
        </div>

        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar pessoa"
          aria-label="Buscar pessoa"
          style={{ width: '100%', padding: '14px 16px', borderRadius: '10px', border: '1px solid #cbd5e1', marginBottom: '16px' }}
        />

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '18px' }}>
          {loading ? (
            <div style={{ color: '#475569' }}>Carregando pessoas...</div>
          ) : filtered.length > 0 ? (
            filtered.map((operator) => (
              <button
                key={operator.id}
                type="button"
                onClick={() => onSelect(operator)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '14px',
                  borderRadius: '10px',
                  border: '1px solid #dbe3ee',
                  background: '#fff',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{ width: '42px', height: '42px', borderRadius: '50%', background: '#1d4ed8', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800, overflow: 'hidden' }}>
                  {operator.photo_thumbnail_url ? (
                    <img src={operator.photo_thumbnail_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    initials(operator.name)
                  )}
                </span>
                <span style={{ fontWeight: 700, color: '#0f172a' }}>{operator.name}</span>
              </button>
            ))
          ) : (
            <div style={{ color: '#475569' }}>Nenhum responsável por checklist encontrado. Cadastre ou ajuste as pessoas na área de Gestão.</div>
          )}
        </div>
      </section>
    </main>
  );
}
