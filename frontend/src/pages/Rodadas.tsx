import React, { useCallback, useEffect, useState } from 'react';







import axios from 'axios';
import { useNavigate } from 'react-router-dom';







import {







  ListTodo,







  Play,







  CheckCircle,















  Loader2,







  Calendar,







  Layers,















  Plus







} from 'lucide-react';







import { useToast } from '../components/toastContext';







import ExecutarOM from './ExecutarOM';















interface Round {







  id: string;







  name: string;







  plan_reference?: string;







  competence?: string;







  status: string;







  created_at: string;







}















interface RoundDetail extends Round {







  orders: any[];







  completed_orders: number;







  progress_pct: number;







}















const API_URL = window.location.port === '5173'







  ? `http://${window.location.hostname}:8000`







  : window.location.origin;















export default function Rodadas() {
  const navigate = useNavigate();







  const toast = useToast();







  const [rounds, setRounds] = useState<Round[]>([]);







  const [selectedRound, setSelectedRound] = useState<RoundDetail | null>(null);







  const [loading, setLoading] = useState(true);







  const [loadingDetail, setLoadingDetail] = useState(false);







  const [executingOrderId, setExecutingOrderId] = useState<string | null>(null);















  // Estados para criar nova rodada







  const [showCreateModal, setShowCreateModal] = useState(false);







  const [newRoundName, setNewRoundName] = useState('');







  const [newRoundPlanRef, setNewRoundPlanRef] = useState('');







  const [newRoundCompetence, setNewRoundCompetence] = useState('');







  const [creating, setCreating] = useState(false);






























  const loadRounds = useCallback(async () => {







    setLoading(true);







    try {







      const res = await axios.get(`${API_URL}/v2/rounds`);







      setRounds(res.data);







    } catch (err: any) {







      console.error(err);







      toast.error('Erro', 'Erro ao carregar rodadas de manutenção.');







    } finally {







      setLoading(false);







    }







  }, [toast]);

  useEffect(() => {
    loadRounds();
  }, [loadRounds]);
















  const loadRoundDetail = async (roundId: string) => {







    setLoadingDetail(true);







    try {







      const res = await axios.get(`${API_URL}/v2/rounds/${roundId}`);







      setSelectedRound(res.data);







    } catch (err: any) {







      console.error(err);







      toast.error('Erro', 'Erro ao carregar detalhes da rodada.');







    } finally {







      setLoadingDetail(false);







    }







  };















  const handleCreateRound = async (e: React.FormEvent) => {







    e.preventDefault();







    if (!newRoundName) return;















    setCreating(true);







    try {







      await axios.post(`${API_URL}/v2/rounds`, {







        name: newRoundName,







        plan_reference: newRoundPlanRef || undefined,







        competence: newRoundCompetence || undefined,







        created_by: sessionStorage.getItem('mec_operator_name') || 'Operador Padrão'







      });







      toast.success('Sucesso', 'Rodada agrupada criada com sucesso!');







      setShowCreateModal(false);







      setNewRoundName('');







      setNewRoundPlanRef('');







      setNewRoundCompetence('');







      loadRounds();







    } catch (err: any) {







      console.error(err);







      toast.error('Erro', err.response?.data?.detail || 'Erro ao criar rodada.');







    } finally {







      setCreating(false);







    }







  };















  if (executingOrderId) {







    return (







      <ExecutarOM







        orderId={executingOrderId}







        onCancel={() => setExecutingOrderId(null)}







        onComplete={() => {







          setExecutingOrderId(null);







          if (selectedRound) {







            loadRoundDetail(selectedRound.id);







          }







          loadRounds();







        }}







      />







    );







  }















  return (







    <div className="container" style={{ padding: '16px', maxWidth: '900px', margin: '0 auto' }}>







      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>







        <div>







          <h1 style={{ margin: 0, fontSize: '24px', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '8px' }}>







            <Layers style={{ color: 'var(--primary)' }} />







            <span>Rodadas de Manutenção</span>







          </h1>







          <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>







            RQ-CMP agrupados por competência ou ativo







          </p>







        </div>







        <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>







          <Plus size={16} style={{ marginRight: '6px' }} /> Nova Rodada







        </button>







      </header>















      {loading ? (







        <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>







          <Loader2 className="animate-spin" size={32} style={{ color: 'var(--primary)' }} />







        </div>







      ) : rounds.length === 0 ? (







        <div style={{ backgroundColor: 'var(--bg-light)', padding: '32px', borderRadius: '12px', textAlign: 'center', border: '1px dashed var(--border)' }}>







          <Layers size={48} style={{ color: 'var(--text-muted)', margin: '0 auto 12px auto' }} />







          <h3 style={{ margin: 0, color: 'var(--text-muted)' }}>Nenhuma rodada agrupada ativa</h3>







          <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: '14px' }}>







            Crie uma rodada agrupada para planejar execuções de inspeção em série.







          </p>







        </div>







      ) : (







        <div style={{ display: 'grid', gridTemplateColumns: selectedRound ? '1fr 1fr' : '1fr', gap: '20px' }}>







          {/* Lista de Rodadas */}







          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>







            {rounds.map(round => {







              const isSelected = selectedRound?.id === round.id;







              return (







                <div







                  key={round.id}







                  className={`card ${isSelected ? 'border-primary' : ''}`}







                  style={{







                    padding: '16px',







                    cursor: 'pointer',







                    backgroundColor: isSelected ? 'rgba(var(--primary-rgb), 0.02)' : 'white',







                    transition: 'all 0.2s',







                    border: isSelected ? '2px solid var(--primary)' : '1px solid var(--border)'







                  }}







                  onClick={() => loadRoundDetail(round.id)}







                >







                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>







                    <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600' }}>{round.name}</h3>







                    <span className={`badge ${round.status === 'completed' ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '11px' }}>







                      {round.status === 'completed' ? 'Concluída' : 'Em Andamento'}







                    </span>







                  </div>















                  <div style={{ display: 'flex', gap: '16px', fontSize: '13px', color: 'var(--text-muted)' }}>







                    {round.plan_reference && (







                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>







                        <ListTodo size={14} /> Ref: {round.plan_reference}







                      </span>







                    )}







                    {round.competence && (







                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>







                        <Calendar size={14} /> Competência: {round.competence}







                      </span>







                    )}







                  </div>







                </div>







              );







            })}







          </div>















          {/* Detalhes da Rodada Selecionada */}







          {selectedRound && (







            <div className="card" style={{ padding: '20px', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column' }}>







              {loadingDetail ? (







                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px', flex: 1 }}>







                  <Loader2 className="animate-spin" size={32} style={{ color: 'var(--primary)' }} />







                </div>







              ) : (







                <>







                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border)', paddingBottom: '12px', marginBottom: '16px' }}>







                    <div>







                      <h2 style={{ margin: 0, fontSize: '18px' }}>{selectedRound.name}</h2>







                      <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Progresso: {selectedRound.completed_orders} de {selectedRound.orders.length} OMs</span>







                    </div>







                    <button className="btn btn-secondary btn-sm" onClick={() => setSelectedRound(null)}>Fechar</button>







                  </div>















                  {/* Barra de Progresso */}







                  <div style={{ marginBottom: '20px' }}>







                    <div style={{ height: '8px', backgroundColor: 'var(--border)', borderRadius: '4px', overflow: 'hidden' }}>







                      <div style={{ height: '100%', width: `${selectedRound.progress_pct}%`, backgroundColor: 'var(--success)', transition: 'width 0.3s' }}></div>







                    </div>







                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', fontWeight: '600' }}>







                      <span>Conclusão</span>







                      <span>{selectedRound.progress_pct}%</span>







                    </div>







                  </div>















                  {/* Lista de Ordens Individuais */}







                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', maxHeight: '400px' }}>







                    {selectedRound.orders.map(order => {







                      const isDone = order.execution_status === 'completed';







                      return (







                        <div







                          key={order.id}







                          style={{







                            padding: '12px',







                            border: '1px solid var(--border)',







                            borderRadius: '8px',







                            display: 'flex',







                            justifyContent: 'space-between',







                            alignItems: 'center',







                            backgroundColor: isDone ? 'rgba(34, 197, 94, 0.02)' : 'white'







                          }}







                        >







                          <div>







                            <div style={{ fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>







                              <span>#{order.friendly_number}</span>







                              <span style={{ color: 'var(--text-muted)', fontWeight: 'normal' }}>— {order.asset.patrimonio}</span>







                            </div>







                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{order.asset.description}</div>







                          </div>















                          <div>







                            {isDone ? (







                              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--success)', fontSize: '13px', fontWeight: '600' }}>







                                <CheckCircle size={16} /> <span>Concluído</span>







                              </div>







                            ) : (







                              <button







                                className="btn btn-primary btn-sm"







                                style={{ padding: '6px 10px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}







                                onClick={() => navigate(`/ordens/${order.id}/executar`)}







                              >







                                <Play size={10} /> <span>Iniciar</span>







                              </button>







                            )}







                          </div>







                        </div>







                      );







                    })}







                  </div>







                </>







              )}







            </div>







          )}







        </div>







      )}















      {/* Modal para Criar Nova Rodada */}







      {showCreateModal && (







        <div style={{







          position: 'fixed',







          top: 0,







          left: 0,







          right: 0,







          bottom: 0,







          backgroundColor: 'rgba(0,0,0,0.5)',







          display: 'flex',







          alignItems: 'center',







          justifyContent: 'center',







          zIndex: 1000







        }}>







          <div className="card" style={{ width: '450px', padding: '24px' }}>







            <h3 style={{ margin: '0 0 16px 0', borderBottom: '1px solid var(--border)', paddingBottom: '12px' }}>Criar Rodada Agrupada</h3>















            <form onSubmit={handleCreateRound}>







              <div className="form-group" style={{ marginBottom: '12px' }}>







                <label className="form-label">Nome da Rodada:</label>







                <input







                  type="text"







                  className="form-control"







                  placeholder="Ex: Rodada Mensal Extintores"







                  value={newRoundName}







                  onChange={(e) => setNewRoundName(e.target.value)}







                  required







                />







              </div>















              <div className="form-group" style={{ marginBottom: '12px' }}>







                <label className="form-label">Referência do Plano (Opcional):</label>







                <input







                  type="text"







                  className="form-control"







                  placeholder="Ex: RQ-CMP-011"







                  value={newRoundPlanRef}







                  onChange={(e) => setNewRoundPlanRef(e.target.value)}







                />







              </div>















              <div className="form-group" style={{ marginBottom: '20px' }}>







                <label className="form-label">Competência (Opcional, formato AAAA-MM):</label>







                <input







                  type="text"







                  className="form-control"







                  placeholder="Ex: 2026-06"







                  value={newRoundCompetence}







                  onChange={(e) => setNewRoundCompetence(e.target.value)}







                />







              </div>















              <div style={{ display: 'flex', justifySelf: 'flex-end', gap: '12px' }}>







                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>Cancelar</button>







                <button type="submit" className="btn btn-primary" disabled={creating}>







                  {creating ? 'Criando...' : 'Criar Rodada'}







                </button>







              </div>







            </form>







          </div>







        </div>







      )}







    </div>







  );







}
