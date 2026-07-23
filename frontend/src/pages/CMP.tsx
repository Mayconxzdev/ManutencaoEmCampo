/**
 * CMP — Modelos de Checklist.
 * Cadastro e acompanhamento de CMP.
 * Apresenta modelos cadastrados, versões, itens e confiabilidade.
 */
import { useState, useEffect } from 'react';
import axios from 'axios';
import { Shield, AlertCircle, CheckCircle2 } from 'lucide-react';

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

export default function CMP() {
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [summary, setSummary] = useState({ models: 0, versions: 0, items: 0 });
  const [loading, setLoading] = useState(false);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_URL}/v2/cmp/templates`);
      const nextTemplates = res.data.templates || [];
      setTemplates(nextTemplates);
      setSummary({
        models: res.data.models || nextTemplates.length,
        versions: res.data.versions || 0,
        items: res.data.items || 0,
      });
      if (nextTemplates.length > 0) {
        setSelectedTemplate(nextTemplates[0]);
      }
    } catch (err) {
      console.error("Erro ao carregar checklists:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h1 className="page-title">Modelos de Checklist (CMP)</h1>
        <p className="page-subtitle">Verificação, confiabilidade e detalhamento dos checklists cadastrados</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '12px' }}>
        <div className="card" style={{ padding: '14px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Modelos CMP</div>
          <strong style={{ fontSize: '22px' }}>{summary.models}</strong>
        </div>
        <div className="card" style={{ padding: '14px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Versões oficiais</div>
          <strong style={{ fontSize: '22px' }}>{summary.versions}</strong>
        </div>
        <div className="card" style={{ padding: '14px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Itens digitalizados</div>
          <strong style={{ fontSize: '22px' }}>{summary.items}</strong>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>Carregando checklists...</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '24px', alignItems: 'start' }}>
          {/* Menu Lateral de Checklists */}
          <div className="card" style={{ padding: '0px', display: 'flex', flexDirection: 'column' }}>
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--border)',
              fontWeight: 'bold',
              fontSize: '14px',
              color: 'var(--primary)',
              backgroundColor: 'var(--primary-light)'
            }}>
              Checklists Cadastrados
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', maxHeight: '480px', overflowY: 'auto' }}>
              {templates.map(t => (
                <button
                  key={t.id}
                  onClick={() => setSelectedTemplate(t)}
                  style={{
                    padding: '12px 20px',
                    border: 'none',
                    borderBottom: '1px solid var(--border)',
                    textAlign: 'left',
                    cursor: 'pointer',
                    fontSize: '13px',
                    fontWeight: '600',
                    backgroundColor: selectedTemplate?.id === t.id ? '#EBF8FF' : 'transparent',
                    color: selectedTemplate?.id === t.id ? 'var(--primary)' : 'var(--text-main)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px'
                  }}
                >
                  <span style={{ fontSize: '13px', fontWeight: 'bold' }}>{t.name}</span>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Ref.: {t.code_reference || 'Sem código'} • v{t.latest_version || '-'} • {t.plans_count || 0} plano(s)
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Detalhe do Checklist Selecionado */}
          {selectedTemplate ? (
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>
                <div>
                  <h3 style={{ margin: '0px', fontSize: '16px', fontWeight: 'bold', color: 'var(--primary)' }}>{selectedTemplate.name}</h3>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', display: 'inline-block' }}>
                    Referência Técnica: <b>{selectedTemplate.code_reference || 'Sem referência'}</b> • Ativos: <b>{selectedTemplate.asset_type === 'machine' ? 'Máquinas' : 'Equipamentos'}</b> • Versão atual: <b>{selectedTemplate.latest_version || '-'}</b>
                  </span>
                </div>

                <div style={{
                  backgroundColor: selectedTemplate.code_reference ? '#C6F6D5' : '#FEFCBF',
                  color: selectedTemplate.code_reference ? '#22543D' : '#744210',
                  padding: '6px 12px',
                  borderRadius: '12px',
                  fontSize: '12px',
                  fontWeight: 'bold',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}>
                  {selectedTemplate.code_reference ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}
                  <span>{selectedTemplate.code_reference ? 'Oficial Confirmado' : 'Checklist Sugerido'}</span>
                </div>
              </div>

              {/* Detalhe dos Itens */}
              <div>
                <h4 style={{ fontSize: '14px', fontWeight: 'bold', margin: '0px 0px 12px 0px' }}>Itens de Verificação Obrigatórios</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {selectedTemplate.versions && selectedTemplate.versions.length > 0 ? (
                    selectedTemplate.versions[0].items.map((item: any) => (
                      <div key={item.id} style={{
                        border: '1px solid var(--border)',
                        padding: '12px 16px',
                        borderRadius: '8px',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        backgroundColor: '#F7FAFC'
                      }}>
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '600' }}>
                            <span style={{ color: 'var(--primary)', fontWeight: 'bold', marginRight: '8px' }}>{item.item_number}</span>
                            {item.description}
                          </div>
                          {item.suggested_materials && (
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                              Materiais sugeridos: <b>{item.suggested_materials}</b>
                            </div>
                          )}
                        </div>
                        {item.is_critical && (
                          <span style={{
                            backgroundColor: '#FED7D7',
                            color: '#742A2A',
                            fontSize: '11px',
                            fontWeight: 'bold',
                            padding: '2px 8px',
                            borderRadius: '4px'
                          }}>Crítico</span>
                        )}
                      </div>
                    ))
                  ) : (
                    <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhum item cadastrado para este checklist.</div>
                  )}
                </div>
              </div>

              {/* Rastreabilidade e Confiabilidade */}
              <div style={{
                backgroundColor: 'var(--primary-light)',
                color: 'var(--primary)',
                padding: '16px 20px',
                borderRadius: '10px',
                display: 'flex',
                gap: '12px',
                alignItems: 'center'
              }}>
                <Shield size={24} />
                <div style={{ fontSize: '12px', lineHeight: '1.4' }}>
                  <b>Rastreabilidade ativa:</b> este modelo é versionado. Mudanças nos itens de verificação criam novas versões e não afetam manutenções já concluídas no histórico.
                </div>
              </div>
            </div>
          ) : (
            <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Nenhum checklist cadastrado no sistema.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
