/**
 * SearchCombobox — Combobox pesquisável universal para listas > 8 itens.
 * Normaliza a busca: ignora acentos, maiúsculas, hífens e espaços extras.
 * Combobox de busca com navegação por teclado.
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Search, X } from 'lucide-react';

export interface ComboboxOption {
  value: string;
  label: string;
  sublabel?: string;
  badge?: string;
  badgeColor?: string;
  icon?: React.ReactNode;
  disabled?: boolean;
}

interface SearchComboboxProps {
  options: ComboboxOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  maxResults?: number;
  required?: boolean;
  disabled?: boolean;
  emptyMessage?: string;
  className?: string;
  id?: string;
  /** Ordenação de relevância personalizada */
  sortOptions?: (a: ComboboxOption, b: ComboboxOption, query: string) => number;
}

/** Normaliza string: remove acentos, maiúsculas, hífens, espaços extras */
function normalize(str: string): string {
  return str
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '') // remove acentos
    .replace(/[-_.]/g, ' ')          // hífens, underscores, pontos → espaço
    .replace(/\s+/g, ' ')            // múltiplos espaços → um
    .trim();
}

/** Score de relevância para uma opção */
function relevanceScore(option: ComboboxOption, query: string): number {
  const nq = normalize(query);
  const nv = normalize(option.value);
  const nl = normalize(option.label);
  const ns = option.sublabel ? normalize(option.sublabel) : '';
  const nb = option.badge ? normalize(option.badge) : '';

  if (nv === nq || nl === nq) return 100;        // correspondência exata
  if (nv.startsWith(nq) || nl.startsWith(nq)) return 90; // começa com
  if (nv.includes(nq) || nl.includes(nq)) return 70;     // contém
  if (ns.includes(nq) || nb.includes(nq)) return 50;     // sublabel/badge
  return 0;
}

const SearchCombobox: React.FC<SearchComboboxProps> = ({
  options,
  value,
  onChange,
  placeholder = 'Buscar...',
  label,
  maxResults = 8,
  required,
  disabled,
  emptyMessage = 'Nenhum resultado encontrado.',
  className = '',
  id,
  sortOptions,
}) => {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Label atual da opção selecionada
  const selectedOption = options.find(o => o.value === value);

  // Filtrar e ordenar opções
  const filteredOptions = useCallback(() => {
    if (!query.trim()) {
      return options.slice(0, maxResults);
    }
    const scored = options
      .map(o => ({ option: o, score: relevanceScore(o, query) }))
      .filter(x => x.score > 0)
      .sort((a, b) => {
        if (sortOptions) return sortOptions(a.option, b.option, query);
        return b.score - a.score;
      });
    return scored.slice(0, maxResults).map(x => x.option);
  }, [options, query, maxResults, sortOptions]);

  const results = filteredOptions();

  // Fechar ao clicar fora
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // Scroll para item destacado
  useEffect(() => {
    if (listRef.current && isOpen) {
      const item = listRef.current.children[highlightedIndex] as HTMLElement;
      item?.scrollIntoView({ block: 'nearest' });
    }
  }, [highlightedIndex, isOpen]);

  const handleSelect = (option: ComboboxOption) => {
    if (option.disabled) return;
    onChange(option.value);
    setQuery('');
    setIsOpen(false);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
    setIsOpen(true);
    setHighlightedIndex(0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case 'ArrowDown':
        setHighlightedIndex(i => Math.min(i + 1, results.length - 1));
        e.preventDefault();
        break;
      case 'ArrowUp':
        setHighlightedIndex(i => Math.max(i - 1, 0));
        e.preventDefault();
        break;
      case 'Enter':
        if (results[highlightedIndex]) handleSelect(results[highlightedIndex]);
        e.preventDefault();
        break;
      case 'Escape':
        setIsOpen(false);
        setQuery('');
        break;
    }
  };

  const handleClear = () => {
    onChange('');
    setQuery('');
    inputRef.current?.focus();
  };

  const displayValue = isOpen ? query : (selectedOption?.label || '');

  return (
    <div ref={containerRef} className={`search-combobox ${className}`} style={{ position: 'relative' }}>
      {label && (
        <label
          htmlFor={id || 'combo-input'}
          style={{ display: 'block', fontSize: '13px', fontWeight: '600', marginBottom: '4px', color: 'var(--text-main)' }}
        >
          {label}{required && <span style={{ color: 'var(--danger)', marginLeft: '2px' }}>*</span>}
        </label>
      )}
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <Search
          size={14}
          style={{
            position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)',
            color: 'var(--text-muted)', pointerEvents: 'none', zIndex: 1
          }}
        />
        <input
          ref={inputRef}
          id={id || 'combo-input'}
          type="text"
          className="form-control"
          value={displayValue}
          onChange={handleInputChange}
          onFocus={() => { setIsOpen(true); setQuery(''); }}
          onKeyDown={handleKeyDown}
          placeholder={selectedOption ? selectedOption.label : placeholder}
          disabled={disabled}
          required={required}
          autoComplete="off"
          style={{ paddingLeft: '32px', paddingRight: value ? '32px' : '10px' }}
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          role="combobox"
          aria-autocomplete="list"
        />
        {value && !disabled && (
          <button
            type="button"
            onClick={handleClear}
            style={{
              position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)',
              background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)',
              display: 'flex', alignItems: 'center', padding: '2px'
            }}
            aria-label="Limpar seleção"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {isOpen && (
        <ul
          ref={listRef}
          role="listbox"
          style={{
            position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 9999,
            backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: '8px', boxShadow: 'var(--shadow-lg)', listStyle: 'none',
            margin: 0, padding: '4px 0', maxHeight: '280px', overflowY: 'auto'
          }}
        >
          {results.length === 0 ? (
            <li style={{ padding: '12px 16px', color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center' }}>
              {emptyMessage}
            </li>
          ) : results.map((option, index) => (
            <li
              key={option.value}
              role="option"
              aria-selected={option.value === value}
              onClick={() => handleSelect(option)}
              onMouseEnter={() => setHighlightedIndex(index)}
              style={{
                padding: '10px 16px', cursor: option.disabled ? 'not-allowed' : 'pointer',
                backgroundColor: index === highlightedIndex
                  ? 'var(--primary-light)' : 'transparent',
                borderLeft: option.value === value
                  ? '3px solid var(--primary)' : '3px solid transparent',
                display: 'flex', alignItems: 'center', gap: '10px',
                transition: 'background-color 0.1s',
                opacity: option.disabled ? 0.5 : 1
              }}
            >
              {option.icon && <span style={{ flexShrink: 0 }}>{option.icon}</span>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '14px', fontWeight: option.value === value ? '600' : '500',
                  color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {option.label}
                </div>
                {option.sublabel && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '1px' }}>
                    {option.sublabel}
                  </div>
                )}
              </div>
              {option.badge && (
                <span style={{
                  fontSize: '10px', fontWeight: '700', padding: '2px 8px', borderRadius: '20px',
                  backgroundColor: option.badgeColor || 'var(--primary-light)',
                  color: option.badgeColor ? 'white' : 'var(--primary)',
                  flexShrink: 0, textTransform: 'uppercase', letterSpacing: '0.5px'
                }}>
                  {option.badge}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default SearchCombobox;
