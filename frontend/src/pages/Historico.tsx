import { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Search,
  CheckCircle,
  AlertTriangle,
  AlertOctagon,
  ChevronDown,
  ChevronUp,
  Calendar,
  User,
  Image as ImageIcon
} from 'lucide-react';

interface OrderItem {
  id: string;
  item_id: string;
  status: string;
  notes: string;
}

interface ChecklistItemDetail {
  description: string;
  item_number: string;
}

interface Evidence {
  id: string;
  evidence_type: string; // 'form_photo', 'defect_photo', 'before_photo', 'after_photo'
  file_path: string;
  uploaded_at: string;
}

interface Order {
  id: string;
  friendly_number: number;
  priority: string;
  status: string; // 'completed', 'completed_with_issues'
  planned_date?: string | null;
  planned_year?: number | null;
  planned_month?: number | null;
  completed_at: string;
  operator_name: string;

  performed_by_name?: string | null;
  notes?: string;
  final_condition: string; // 'released', 'released_with_attention', 'stopped'
  asset: {
    id: string;
    patrimonio: string;
    description: string;
  };
  items: OrderItem[];
  evidences: Evidence[];
  order_type?: string;
  parent_work_order_id?: string | null;
  relation_type?: string | null;
}

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

export default function Historico() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [checklistMap, setChecklistMap] = useState<Record<string, ChecklistItemDetail>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Filtros
  const [search, setSearch] = useState('');
  const [conditionFilter, setConditionFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  // Accordions abertos (por ID da OM)
  const [expandedOrders, setExpandedOrders] = useState<Record<string, boolean>>({});

  // Lightbox da imagem
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/orders`);
      // Apenas finalizadas
      const completed = res.data.filter((o: any) =>
        o.status === 'completed' || o.status === 'completed_with_issues'
      );
      // Ordenar por data de conclusão decrescente
      completed.sort((a: any, b: any) => {
        return new Date(b.completed_at || 0).getTime() - new Date(a.completed_at || 0).getTime();
      });
      setOrders(completed);

      // Carregar checklists para descrição dos itens
      const checklistsRes = await axios.get(`${API_URL}/checklists`);
      const map: Record<string, ChecklistItemDetail> = {};
      checklistsRes.data.forEach((tpl: any) => {
        tpl.versions.forEach((ver: any) => {
          ver.items.forEach((item: any) => {
            map[item.id] = {
              description: item.description,
              item_number: item.item_number
            };
          });
        });
      });
      setChecklistMap(map);
      setError('');
    } catch (err) {
      console.error(err);
      setError('Erro ao carregar o histórico de manutenções.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const toggleExpand = (orderId: string) => {
    setExpandedOrders(prev => ({
      ...prev,
      [orderId]: !prev[orderId]
    }));
  };

  const getConditionLabel = (condition: string) => {
    switch (condition) {
      case 'released':
        return { text: 'Apta (Normal)', className: 'asset-badge ok', icon: <CheckCircle size={14} /> };
      case 'released_with_attention':
        return { text: 'Apta c/ Atenção', className: 'asset-badge warning', icon: <AlertTriangle size={14} /> };
      case 'stopped':
        return { text: 'Parada (Crítico)', className: 'asset-badge stopped', icon: <AlertOctagon size={14} /> };
      default:
        return { text: 'Finalizada', className: 'asset-badge', icon: null };
    }
  };

  const getEvidenceTypeLabel = (type: string) => {
    switch (type) {
      case 'form_photo':
        return 'Foto da Folha';
      case 'defect_photo':
        return 'Foto do Defeito';
      case 'before_photo':
        return 'Foto Antes';
      case 'after_photo':
        return 'Foto Depois';
      default:
        return 'Evidência';
    }
  };

  const filteredOrders = orders.filter(o => {
    const matchesSearch =
      o.asset.description.toLowerCase().includes(search.toLowerCase()) ||
      o.asset.patrimonio.toLowerCase().includes(search.toLowerCase()) ||
      o.friendly_number.toString().includes(search) ||
      (o.operator_name && o.operator_name.toLowerCase().includes(search.toLowerCase())) ||
      (o.performed_by_name && o.performed_by_name.toLowerCase().includes(search.toLowerCase()));

    const matchesCondition = conditionFilter === 'all' || o.final_condition === conditionFilter;
    const matchesType = typeFilter === 'all' || o.order_type === typeFilter;
    return matchesSearch && matchesCondition && matchesType;
  });

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '-';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <h1>Histórico de Manutenções</h1>
        <button className="btn btn-secondary" onClick={fetchHistory} style={{ padding: '8px 16px' }}>
          Atualizar
        </button>
      </div>
      <p className="subtitle">Relatório detalhado de todas as preventivas realizadas</p>

      {error && (
        <div style={{ backgroundColor: 'var(--danger-light)', color: 'var(--danger)', padding: '16px', borderRadius: '8px', marginBottom: '24px', fontWeight: '500' }}>
          {error}
        </div>
      )}

      {/* Barra de Filtros */}
      <div className="card" style={{ padding: '16px', marginBottom: '24px', display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="form-group" style={{ flex: 1, minWidth: '240px', marginBottom: 0 }}>
          <div style={{ position: 'relative' }}>
            <input
              type="text"
              className="form-control"
              placeholder="Buscar por descrição, patrimônio, responsável ou nº da OM..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ paddingLeft: '40px' }}
            />
            <Search size={18} style={{ position: 'absolute', left: '14px', top: '14px', color: 'var(--text-muted)' }} />
          </div>
        </div>

        <div className="form-group" style={{ width: '200px', marginBottom: 0 }}>
          <select className="form-control" value={conditionFilter} onChange={e => setConditionFilter(e.target.value)}>
            <option value="all">Todas as Condições</option>
            <option value="released">Apta (Normal)</option>
            <option value="released_with_attention">Apta com Atenção</option>
            <option value="stopped">Parada (Crítico)</option>
          </select>
        </div>

        <div className="form-group" style={{ width: '200px', marginBottom: 0 }}>
          <select className="form-control" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
            <option value="all">Todos os Tipos</option>
            <option value="preventive">Preventiva</option>
            <option value="corrective">Corretiva</option>
            <option value="rework">Retrabalho</option>
            <option value="external">Assistência Externa</option>
            <option value="inspection">Rodada/Inspeção</option>
          </select>
        </div>
      </div>

      {loading ? (
        <p>Carregando histórico...</p>
      ) : (
        <div className="asset-list">
          {filteredOrders.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
              Nenhuma ordem de manutenção finalizada encontrada.
            </div>
          ) : (
            filteredOrders.map(order => {
              const cond = getConditionLabel(order.final_condition);
              const isExpanded = !!expandedOrders[order.id];

              return (
                <div key={order.id} className="card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px', borderLeft: '4px solid ' + (order.final_condition === 'released' ? 'var(--success)' : order.final_condition === 'stopped' ? 'var(--danger)' : 'var(--warning)') }}>

                  {/* Linha Superior */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--primary)', textTransform: 'uppercase' }}>
                          OM nº {order.friendly_number}
                        </span>
                        {order.order_type && (
                          <span
                            style={{
                              fontSize: '10px',
                              fontWeight: '700',
                              padding: '2px 6px',
                              borderRadius: '4px',
                              textTransform: 'uppercase',
                              backgroundColor:
                                order.order_type === 'corrective' ? 'rgba(217, 119, 6, 0.15)' :
                                order.order_type === 'rework' ? 'rgba(225, 29, 72, 0.15)' :
                                order.order_type === 'external' ? 'rgba(147, 51, 234, 0.15)' :
                                order.order_type === 'inspection' ? 'rgba(13, 148, 136, 0.15)' :
                                'rgba(37, 99, 235, 0.15)',
                              color:
                                order.order_type === 'corrective' ? '#d97706' :
                                order.order_type === 'rework' ? '#e11d48' :
                                order.order_type === 'external' ? '#9333ea' :
                                order.order_type === 'inspection' ? '#0d9488' :
                                '#2563eb'
                            }}
                          >
                            {order.order_type === 'corrective' ? 'Corretiva' :
                             order.order_type === 'rework' ? 'Retrabalho' :
                             order.order_type === 'external' ? 'Assistência Técnica' :
                             order.order_type === 'inspection' ? 'Inspeção/Rodada' :
                             'Preventiva'}
                          </span>
                        )}
                        {order.parent_work_order_id && (() => {
                          const parentFriendly = orders.find(o => o.id === order.parent_work_order_id)?.friendly_number;
                          return (
                            <span
                              style={{
                                fontSize: '10px',
                                fontWeight: '600',
                                padding: '2px 6px',
                                borderRadius: '4px',
                                backgroundColor: 'var(--bg-app)',
                                border: '1px solid var(--border)',
                                color: 'var(--text-muted)',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px'
                              }}
                            >
                              🔗 Derivada da OM #{parentFriendly || 'Anterior'}
                            </span>
                          );
                        })()}
                      </div>
                      <h3 style={{ fontSize: '18px', fontWeight: '700', marginTop: '2px' }}>
                        {order.asset.description} ({order.asset.patrimonio})
                      </h3>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className={cond.className} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '4px 10px', fontSize: '13px' }}>
                        {cond.icon}
                        {cond.text}
                      </span>
                    </div>
                  </div>

                  {/* Detalhes rápidos */}
                  <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', fontSize: '13px', color: 'var(--text-muted)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', paddingTop: '8px', paddingBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Calendar size={14} />
                      <strong>Concluído em:</strong> {formatDate(order.completed_at)}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <User size={14} />
                      <strong>Conferido por:</strong> {order.operator_name || 'Não informado'}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <User size={14} />
                      <strong>Executado por:</strong> {order.performed_by_name || 'Não informado'}
                    </div>
                  </div>

                  {/* Observações gerais */}
                  {order.notes && (
                    <div style={{ fontSize: '14px', backgroundColor: 'var(--bg-app)', padding: '12px', borderRadius: '8px' }}>
                      <strong>Notas do Encerramento:</strong> {order.notes}
                    </div>
                  )}

                  {/* Evidências anexadas */}
                  {order.evidences && order.evidences.length > 0 && (
                    <div>
                      <strong style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                        <ImageIcon size={14} style={{ color: 'var(--primary)' }} />
                        Evidências e Fotos Anexadas:
                      </strong>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        {order.evidences.map(ev => {
                          const fileUrl = `${API_URL}/${ev.file_path}`;
                          return (
                            <div
                              key={ev.id}
                              onClick={() => setLightboxUrl(fileUrl)}
                              style={{
                                position: 'relative',
                                width: '80px',
                                height: '80px',
                                borderRadius: '6px',
                                overflow: 'hidden',
                                border: '1px solid var(--border)',
                                cursor: 'pointer',
                                boxShadow: 'var(--shadow-sm)'
                              }}
                              title={getEvidenceTypeLabel(ev.evidence_type)}
                            >
                              <img
                                src={fileUrl}
                                alt={ev.evidence_type}
                                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                              />
                              <div style={{
                                position: 'absolute',
                                bottom: 0,
                                left: 0,
                                right: 0,
                                backgroundColor: 'rgba(0,0,0,0.6)',
                                color: 'white',
                                fontSize: '9px',
                                textAlign: 'center',
                                padding: '2px 0',
                                fontWeight: '600'
                              }}>
                                {getEvidenceTypeLabel(ev.evidence_type)}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Botão de Expandir Checklist */}
                  <button
                    className="btn"
                    style={{
                      alignSelf: 'flex-start',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '13px',
                      padding: '4px 8px',
                      backgroundColor: 'transparent',
                      border: 'none',
                      color: 'var(--primary)',
                      fontWeight: '600'
                    }}
                    onClick={() => toggleExpand(order.id)}
                  >
                    {isExpanded ? (
                      <>
                        <ChevronUp size={16} /> Ocultar Checklist Respondido
                      </>
                    ) : (
                      <>
                        <ChevronDown size={16} /> Ver Checklist Respondido ({order.items.length} itens)
                      </>
                    )}
                  </button>

                  {/* Área Expandida do Checklist */}
                  {isExpanded && (
                    <div style={{
                      marginTop: '8px',
                      border: '1px solid var(--border)',
                      borderRadius: '10px',
                      overflow: 'hidden',
                      backgroundColor: 'white'
                    }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                        <thead>
                          <tr style={{ backgroundColor: 'var(--bg-app)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                            <th style={{ padding: '10px 12px', width: '60px' }}>Item</th>
                            <th style={{ padding: '10px 12px' }}>Descrição da Verificação</th>
                            <th style={{ padding: '10px 12px', width: '120px' }}>Status</th>
                            <th style={{ padding: '10px 12px' }}>Observações / Notas</th>
                          </tr>
                        </thead>
                        <tbody>
                          {order.items.map(item => {
                            const detail = checklistMap[item.item_id] || {
                              description: 'Item de verificação',
                              item_number: '-'
                            };

                            return (
                              <tr key={item.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                <td style={{ padding: '10px 12px', fontWeight: '700', color: 'var(--primary)' }}>
                                  {detail.item_number}
                                </td>
                                <td style={{ padding: '10px 12px', fontWeight: '500' }}>
                                  {detail.description}
                                </td>
                                <td style={{ padding: '10px 12px' }}>
                                  {item.status === 'ok' && (
                                    <span className="asset-badge ok" style={{ fontSize: '11px', padding: '2px 6px' }}>Conforme</span>
                                  )}
                                  {item.status === 'attention' && (
                                    <span className="asset-badge warning" style={{ fontSize: '11px', padding: '2px 6px' }}>Defeito</span>
                                  )}
                                  {item.status === 'not_applicable' && (
                                    <span className="asset-badge" style={{ fontSize: '11px', padding: '2px 6px', backgroundColor: 'var(--border)', color: 'var(--text-muted)' }}>N/A</span>
                                  )}
                                </td>
                                <td style={{ padding: '10px 12px', color: 'var(--text-main)', fontStyle: item.notes ? 'normal' : 'italic' }}>
                                  {item.notes || '-'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                </div>
              );
            })
          )}
        </div>
      )}

      {/* Lightbox para Visualizar Fotos em Tamanho Grande */}
      {lightboxUrl && (
        <div
          className="overlay"
          onClick={() => setLightboxUrl(null)}
          style={{
            zIndex: 1000,
            backgroundColor: 'rgba(0, 0, 0, 0.85)',
            cursor: 'zoom-out'
          }}
        >
          <div style={{ position: 'relative', maxWidth: '90%', maxHeight: '90%' }}>
            <img
              src={lightboxUrl}
              alt="Evidência ampliada"
              style={{
                maxWidth: '100%',
                maxHeight: '85vh',
                borderRadius: '12px',
                boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                display: 'block',
                margin: '0 auto'
              }}
            />
            <div style={{
              color: 'white',
              textAlign: 'center',
              marginTop: '16px',
              fontSize: '14px',
              fontWeight: '600'
            }}>
              Clique em qualquer lugar para fechar
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
