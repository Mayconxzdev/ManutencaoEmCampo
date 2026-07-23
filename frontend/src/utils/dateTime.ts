/** Datas históricas da API são UTC sem o sufixo Z. Trate-as como UTC antes
 * de mostrar no navegador; sem isso Chrome/Android exibem +3 horas no Brasil. */
export function parseManutencaoEmCampoDate(value?: string | null): Date | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatManutencaoEmCampoDateTime(value?: string | null): string {
  const date = parseManutencaoEmCampoDate(value);
  return date ? date.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' }) : 'Não informado';
}

export function formatManutencaoEmCampoTime(value?: string | null): string {
  const date = parseManutencaoEmCampoDate(value);
  return date ? date.toLocaleTimeString('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit' }) : '—';
}
