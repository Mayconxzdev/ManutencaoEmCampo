import {
  Calendar,
  CalendarDays,
  Clock,
  Menu,
  User,
  Wrench,
} from 'lucide-react';
import type { ComponentType, ReactNode } from 'react';
import GlobalSearch from '../GlobalSearch';

export type ShellTab = 'hoje' | 'maquinas' | 'planejamento' | 'historico' | 'mais';

type Operator = {
  id: string;
  name: string;
  photo_thumbnail_url?: string | null;
};

type ResponsiveShellProps = {
  activeTab: ShellTab;
  activeOperator: string;
  activeOperatorId: string;
  appVersion: string;
  pageTitle?: string;
  children: ReactNode;
  loadingOperators: boolean;
  operators: Operator[];
  onOperatorChange: (id: string) => void;
  onTabChange: (tab: ShellTab) => void;
};

const navItems: Array<{
  id: ShellTab;
  label: string;
  shortLabel: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
}> = [
  { id: 'hoje', label: 'Início', shortLabel: 'Início', icon: Calendar },
  { id: 'maquinas', label: 'Máquinas e Equipamentos', shortLabel: 'Itens', icon: Wrench },
  { id: 'planejamento', label: 'Agenda de Manutenção', shortLabel: 'Agenda', icon: CalendarDays },
  { id: 'historico', label: 'Histórico', shortLabel: 'Hist.', icon: Clock },
  { id: 'mais', label: 'Gestão', shortLabel: 'Gestão', icon: Menu },
];

function OperatorSelect({
  activeOperator,
  activeOperatorId,
  loadingOperators,
  operators,
  onOperatorChange,
}: Pick<
  ResponsiveShellProps,
  'activeOperator' | 'activeOperatorId' | 'loadingOperators' | 'operators' | 'onOperatorChange'
>) {
  return (
    <label className="operator-picker" aria-label={`Pessoa selecionada: ${activeOperator || 'nenhuma'}`} title="Trocar pessoa">
      <span className="operator-picker__icon" aria-hidden="true">
        <User size={16} />
      </span>
      <select
        value={activeOperatorId}
        onChange={(event) => onOperatorChange(event.target.value)}
        disabled={loadingOperators}
        aria-label="Trocar pessoa"
      >
        {loadingOperators && <option value="">Carregando...</option>}
        {!loadingOperators && operators.length === 0 && <option value="">Nenhuma pessoa</option>}
        {!loadingOperators &&
          operators.map((operator) => (
            <option key={operator.id} value={operator.id}>
              {operator.name}
            </option>
          ))}
      </select>
    </label>
  );
}

function NavigationButton({
  item,
  active,
  variant,
  onClick,
}: {
  item: (typeof navItems)[number];
  active: boolean;
  variant: 'desktop' | 'tablet' | 'mobile';
  onClick: () => void;
}) {
  const Icon = item.icon;
  const label = variant === 'mobile' ? item.shortLabel : item.label;

  return (
    <button
      type="button"
      className={`shell-nav__item shell-nav__item--${variant} ${active ? 'is-active' : ''}`}
      aria-current={active ? 'page' : undefined}
      aria-label={item.label}
      onClick={onClick}
    >
      <Icon size={variant === 'desktop' ? 18 : 20} strokeWidth={2.1} />
      <span>{label}</span>
    </button>
  );
}

export default function ResponsiveShell({
  activeTab,
  activeOperator,
  activeOperatorId,
  appVersion,
  pageTitle,
  children,
  loadingOperators,
  operators,
  onOperatorChange,
  onTabChange,
}: ResponsiveShellProps) {
  return (
    <div className="responsive-shell">
      <aside className="desktop-sidebar" data-testid="desktop-sidebar" aria-label="Navegação principal">
        <div className="shell-brand">
          <span className="shell-brand__mark" aria-hidden="true">
            <Wrench size={22} />
          </span>
          <div>
            <strong>Manutenção</strong>
            <span>Em Campo</span>
          </div>
        </div>

        <nav className="shell-nav shell-nav--desktop">
          {navItems.map((item) => (
            <NavigationButton
              key={item.id}
              item={item}
              active={activeTab === item.id}
              variant="desktop"
              onClick={() => onTabChange(item.id)}
            />
          ))}
        </nav>

        <div className="shell-sidebar-footer">
          <span>Versão {appVersion}</span>
        </div>
      </aside>

      <nav className="tablet-rail" data-testid="tablet-rail" aria-label="Navegação principal">
        <div className="tablet-rail__brand" aria-hidden="true">
          <Wrench size={22} />
        </div>
        {navItems.map((item) => (
          <NavigationButton
            key={item.id}
            item={item}
            active={activeTab === item.id}
            variant="tablet"
            onClick={() => onTabChange(item.id)}
          />
        ))}
      </nav>

      <div className="shell-workspace">
        <header className="shell-topbar">
          <div className="shell-topbar__title">
            <span className="shell-topbar__eyebrow">Manutenção em Campo</span>
            <strong>{pageTitle || navItems.find((item) => item.id === activeTab)?.label || 'Início'}</strong>
          </div>
          <GlobalSearch />
          <OperatorSelect
            activeOperator={activeOperator}
            activeOperatorId={activeOperatorId}
            loadingOperators={loadingOperators}
            operators={operators}
            onOperatorChange={onOperatorChange}
          />
        </header>

        <main className="shell-main" id="main-content">
          {children}
        </main>
      </div>

      <nav className="mobile-bottom-nav" data-testid="mobile-bottom-nav" aria-label="Navegação principal">
        {navItems.map((item) => (
          <NavigationButton
            key={item.id}
            item={item}
            active={activeTab === item.id}
            variant="mobile"
            onClick={() => onTabChange(item.id)}
          />
        ))}
      </nav>
    </div>
  );
}
