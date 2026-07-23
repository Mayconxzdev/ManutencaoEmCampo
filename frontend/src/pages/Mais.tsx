/* oxlint-disable react-hooks/exhaustive-deps */
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { useToast } from '../components/toastContext';

import axios from 'axios';

import {

  UserPlus,

  Trash2,

  Edit3,

  Download,

  Database,

  AlertTriangle,

  CheckCircle,



} from 'lucide-react';

import Indicadores from './Indicadores';

import CMP from './CMP';

import ConferirProgramacoes from './ConferirProgramacoes';
import SystemDiagnostics from '../components/SystemDiagnostics';
import OfflineSyncPanel from '../components/OfflineSyncPanel';
import DocumentReviewPanel from '../components/DocumentReviewPanel';
import QualityActionsPanel from '../components/QualityActionsPanel';



interface Operator {

  id: string;

  name: string;

  photo_thumbnail_url?: string | null;

  is_active?: boolean;

  can_record_checklist?: boolean;

  can_execute_maintenance?: boolean;

}



interface Backup {

  filename: string;

  size_bytes: number;

  created_at: string;

}



const API_URL = window.location.port === '5173'

  ? `http://${window.location.hostname}:8000`

  : window.location.origin;



export default function Mais() {
  const navigate = useNavigate();

  const toast = useToast();

  const [activeSubTab, setActiveSubTab] = useState<'operadores' | 'relatorios' | 'backup' | 'conflitos' | 'indicadores' | 'cmp' | 'conferir_programacoes' | 'materiais_compras' | 'assistencia_tecnica' | 'paradas_maquina' | 'fila_notificacoes' | 'checklists_importados' | 'sistema' | 'offline_sync' | 'revisao_documental' | 'epi' | 'qualidade'>(() => (localStorage.getItem('mec_mais_subtab') as any) || 'operadores');



  // --- ESTADOS OPERADORES ---

  const [operators, setOperators] = useState<Operator[]>([]);

  const [newOpName, setNewOpName] = useState('');

  const [newCanRecordChecklist, setNewCanRecordChecklist] = useState(false);

  const [newCanExecuteMaintenance, setNewCanExecuteMaintenance] = useState(true);

  const [editingOp, setEditingOp] = useState<Operator | null>(null);

  const [editingName, setEditingName] = useState('');

  const [editingCanRecordChecklist, setEditingCanRecordChecklist] = useState(false);

  const [editingCanExecuteMaintenance, setEditingCanExecuteMaintenance] = useState(true);



  // --- ESTADOS BACKUP ---

  const [backups, setBackups] = useState<Backup[]>([]);

  const [backupLoading, setBackupLoading] = useState(false);



  // --- ESTADOS CONFLITOS ---

  const [conflictAssets, setConflictAssets] = useState<any[]>([]);

  const [conflictLoading, setConflictLoading] = useState(false);

  const [manualPatrimonios, setManualPatrimonios] = useState<{[key: string]: string}>({});



  // --- Estados operacionais ---

  const [materialRequests, setMaterialRequests] = useState<any[]>([]);

  const [externalRequests, setExternalRequests] = useState<any[]>([]);

  const [downtimeRecords, setDowntimeRecords] = useState<any[]>([]);

  const [notificationsQueue, setNotificationsQueue] = useState<any[]>([]);

  const [checklistLibrary, setChecklistLibrary] = useState<any[]>([]);

  const [loadingV2, setLoadingV2] = useState(false);



  // --- ANCORAS DE DADOS DE RELATÓRIO ---

  const [exportLoading, setExportLoading] = useState(false);



  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {

    if (activeSubTab === 'operadores') {

      fetchOperators();

    } else if (activeSubTab === 'backup') {

      fetchBackups();

    } else if (activeSubTab === 'conflitos') {

      // oxlint-disable-next-line react-hooks/exhaustive-deps
      fetchConflicts();

    } else if (activeSubTab === 'materiais_compras') {

      fetchMaterialRequests();

    } else if (activeSubTab === 'assistencia_tecnica') {

      fetchExternalRequests();

    } else if (activeSubTab === 'paradas_maquina') {

      fetchDowntimeRecords();

    } else if (activeSubTab === 'fila_notificacoes') {

      fetchNotificationsQueue();

    } else if (activeSubTab === 'checklists_importados') {

      fetchChecklistLibrary();

    }

  }, [activeSubTab]);

  useEffect(() => {
    localStorage.setItem('mec_mais_subtab', activeSubTab);
  }, [activeSubTab]);



  // --- OPERADORES CRUD ---

  const fetchOperators = async () => {

    try {

      const res = await axios.get(`${API_URL}/operators`);

      setOperators(res.data);

    } catch (err) {

      console.error(err);

    }

  };



  const handleAddOperator = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!newOpName.trim()) return;

    try {

      await axios.post(`${API_URL}/operators`, {
        name: newOpName.trim(),
        can_record_checklist: newCanRecordChecklist,
        can_execute_maintenance: newCanExecuteMaintenance,
      });

      setNewOpName('');
      setNewCanRecordChecklist(false);
      setNewCanExecuteMaintenance(true);

      fetchOperators();

      // Notificar outros componentes (como o seletor no App.tsx)

      window.dispatchEvent(new Event('operators_changed'));

    } catch (err: any) {

      toast.error('Erro', err.response?.data?.detail || 'Erro ao adicionar responsável.');

    }

  };



  const handleEditOperator = (op: Operator) => {

    setEditingOp(op);

    setEditingName(op.name);
    setEditingCanRecordChecklist(Boolean(op.can_record_checklist));
    setEditingCanExecuteMaintenance(op.can_execute_maintenance !== false);

  };



  const handleUpdateOperator = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!editingOp || !editingName.trim()) return;

    try {

      await axios.put(`${API_URL}/operators/${editingOp.id}`, {
        name: editingName.trim(),
        can_record_checklist: editingCanRecordChecklist,
        can_execute_maintenance: editingCanExecuteMaintenance,
      });

      setEditingOp(null);

      fetchOperators();

      window.dispatchEvent(new Event('operators_changed'));

    } catch (err: any) {

      toast.error('Erro', err.response?.data?.detail || 'Erro ao atualizar responsável.');

    }

  };



  const handleArchiveOperator = async (id: string, name: string) => {

    const confirmed = await toast.confirm('Arquivar pessoa', `Deseja arquivar "${name}"? O histórico permanece preservado.`);

    if (!confirmed) return;

    try {

      await axios.delete(`${API_URL}/operators/${id}`, {
        params: { archived_by: sessionStorage.getItem('mec_operator_name') || undefined }
      });

      fetchOperators();

      window.dispatchEvent(new Event('operators_changed'));

    } catch (err: any) {

      toast.error('Erro', err.response?.data?.detail || 'Erro ao arquivar pessoa.');

    }

  };

  const handleUploadOperatorPhoto = async (id: string, file?: File | null) => {

    if (!file) return;

    const formData = new FormData();

    formData.append('file', file);

    try {

      await axios.post(`${API_URL}/operators/${id}/photo`, formData, {
        params: { operator_name: sessionStorage.getItem('mec_operator_name') || undefined },
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      fetchOperators();

      window.dispatchEvent(new Event('operators_changed'));

    } catch (err: any) {

      toast.error('Erro', err.response?.data?.detail || 'Erro ao salvar foto da pessoa.');

    }

  };



  // --- BACKUP & RESTAURAÇÃO ---

  const fetchBackups = async () => {

    setBackupLoading(true);

    try {

      const res = await axios.get(`${API_URL}/backup/list`);

      setBackups(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setBackupLoading(false);

    }

  };



  const handleCreateBackup = async () => {

    setBackupLoading(true);

    try {

      await axios.post(`${API_URL}/backup/create`);

      toast.success('Backup Gerado', 'Backup gerado com sucesso na pasta backups/.');

      fetchBackups();

    } catch (err: any) {

      toast.error('Erro', 'Erro ao criar backup: ' + (err.response?.data?.detail || err.message));

    } finally {

      setBackupLoading(false);

    }

  };



  const handleRestoreBackup = async (filename: string) => {

    const confirmed = await toast.confirm('Atenção', `Deseja realmente restaurar o backup "${filename}"? Os dados atuais e fotos serão substituídos.`);

    if (!confirmed) {

      return;

    }

    setBackupLoading(true);

    try {

      const res = await axios.post(`${API_URL}/backup/restore`, null, {

        params: { filename }

      });

      toast.success('Restaurado', res.data.message || 'Backup restaurado com sucesso!');

      window.dispatchEvent(new Event('operators_changed')); // atualizar seletor do topo

    } catch (err: any) {

      toast.error('Erro', 'Erro ao restaurar backup: ' + (err.response?.data?.detail || err.message));

    } finally {

      setBackupLoading(false);

    }

  };



  // --- RELATÓRIOS EXCEL/CSV COMPATÍVEL ---

  const downloadCSV = (headers: string[], rows: string[][], filename: string) => {

    const csvContent = "\uFEFF" + [

      headers.join(";"),

      ...rows.map(e => e.map(val => `"${(val || '').toString().replace(/"/g, '""')}"`).join(";"))

    ].join("\n");



    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });

    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");

    link.setAttribute("href", url);

    link.setAttribute("download", filename);

    link.style.visibility = 'hidden';

    document.body.appendChild(link);

    link.click();

    document.body.removeChild(link);

  };



  const handleExportSchedule = async () => {

    setExportLoading(true);

    try {

      // Carregar ativos e planos indiretos do backend

      const assetsRes = await axios.get(`${API_URL}/assets`);

      // Simulação estruturada da programação com base nas datas de manutenção futura

      const headers = ["Patrimônio", "Descrição", "Tipo", "Setor", "Última Manutenção", "Próxima Manutenção", "Operável"];

      const rows = assetsRes.data.map((a: any) => [

        a.patrimonio,

        a.description,

        a.type === 'machine' ? 'Máquina' : 'Equipamento',

        a.sector?.name || 'Geral',

        a.last_maintenance_date ? new Date(a.last_maintenance_date).toLocaleDateString('pt-BR') : 'Não realizada',

        a.next_maintenance_date ? new Date(a.next_maintenance_date).toLocaleDateString('pt-BR') : 'Não agendada',

        a.is_operable ? 'Apta' : 'Parada'

      ]);

      downloadCSV(headers, rows, `programacao_mec_${new Date().getFullYear()}.csv`);

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao exportar cronograma.');

    } finally {

      setExportLoading(false);

    }

  };



  const handleExportHistory = async () => {

    setExportLoading(true);

    try {

      const res = await axios.get(`${API_URL}/orders`);

      const completed = res.data.filter((o: any) => o.status === 'completed' || o.status === 'completed_with_issues');

      const headers = ["OM", "Patrimônio", "Descrição Ativo", "Finalizado Em", "Responsável", "Condição Final", "Notas"];

      const rows = completed.map((o: any) => [

        o.friendly_number.toString(),

        o.asset.patrimonio,

        o.asset.description,

        o.completed_at ? new Date(o.completed_at).toLocaleDateString('pt-BR') : '',

        o.operator_name || '',

        o.final_condition === 'released' ? 'Apta (Normal)' : o.final_condition === 'released_with_attention' ? 'Apta c/ Atenção' : 'Parada (Crítico)',

        o.notes || ''

      ]);

      downloadCSV(headers, rows, `historico_manutencoes_mec.csv`);

    } catch (err) {

      console.error(err);

      alert('Erro ao exportar histórico.');

    } finally {

      setExportLoading(false);

    }

  };



  const handleExportIssues = async () => {

    setExportLoading(true);

    try {

      const res = await axios.get(`${API_URL}/issues`);

      // Obter ativos para mapear patrimônio

      const assetsRes = await axios.get(`${API_URL}/assets`);

      const assetMap = new Map(assetsRes.data.map((a: any) => [a.id, a]));



      const headers = ["ID Ocorrência", "Patrimônio", "Descrição Ativo", "Descrição do Problema", "Prioridade", "Afeta Operação", "Status", "Criado Em", "Resolvido Em"];

      const rows = res.data.map((i: any) => {

        const asset = assetMap.get(i.asset_id) as any;

        return [

          i.id.substring(0, 8),

          asset ? asset.patrimonio : '',

          asset ? asset.description : '',

          i.description,

          i.priority === 'critical' ? 'Crítico' : 'Alto',

          i.is_operable_affected ? 'Sim (Parada)' : 'Não',

          i.status === 'open' ? 'Aberto' : 'Resolvido',

          new Date(i.created_at).toLocaleDateString('pt-BR'),

          i.resolved_at ? new Date(i.resolved_at).toLocaleDateString('pt-BR') : ''

        ];

      });

      downloadCSV(headers, rows, `pendencias_ocorrencias_mec.csv`);

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao exportar ocorrências.');

    } finally {

      setExportLoading(false);

    }

  };



  const fetchConflicts = async () => {

    setConflictLoading(true);

    try {

      const res = await axios.get(`${API_URL}/assets/conflicts`);

      setConflictAssets(res.data);

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao carregar conflitos.');

    } finally {

      setConflictLoading(false);

    }

  };



  const handleResolveConflict = async (assetId: string, resolutionType: 'suggested' | 'manual' | 'keep') => {

    try {

      const payload: any = { resolution_type: resolutionType };

      if (resolutionType === 'manual') {

        const val = manualPatrimonios[assetId]?.trim();

        if (!val) {

          toast.warning('Aviso', 'Por favor, digite um código de patrimônio.');

          return;

        }

        payload.new_patrimonio = val;

      }



      await axios.post(`${API_URL}/assets/${assetId}/resolve-conflict`, payload);

      toast.success('Sucesso', 'Conflito resolvido com sucesso!');

      fetchConflicts();

    } catch (err: any) {

      toast.error('Erro', 'Erro ao resolver conflito: ' + (err.response?.data?.detail || err.message));

    }

  };



  const fetchMaterialRequests = async () => {

    setLoadingV2(true);

    try {

      const res = await axios.get(`${API_URL}/v2/material-requests`);

      setMaterialRequests(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setLoadingV2(false);

    }

  };



  const fetchExternalRequests = async () => {

    setLoadingV2(true);

    try {

      const res = await axios.get(`${API_URL}/v2/external-services`);

      setExternalRequests(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setLoadingV2(false);

    }

  };



  const fetchDowntimeRecords = async () => {

    setLoadingV2(true);

    try {

      const res = await axios.get(`${API_URL}/v2/downtime`);

      setDowntimeRecords(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setLoadingV2(false);

    }

  };



  const fetchNotificationsQueue = async () => {

    setLoadingV2(true);

    try {

      const res = await axios.get(`${API_URL}/v2/notifications/queue`);

      setNotificationsQueue(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setLoadingV2(false);

    }

  };



  const fetchChecklistLibrary = async () => {

    setLoadingV2(true);

    try {

      const res = await axios.get(`${API_URL}/v2/checklist-library`);

      setChecklistLibrary(res.data);

    } catch (err) {

      console.error(err);

    } finally {

      setLoadingV2(false);

    }

  };



  const handleUpdateMaterialStatus = async (mrId: string, status: string) => {

    try {

      await axios.patch(`${API_URL}/v2/material-requests/${mrId}/status`, null, {

        params: { status_val: status }

      });

      fetchMaterialRequests();

      toast.success('Sucesso', 'Status da solicitação de material atualizado.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao atualizar solicitação.');

    }

  };



  const handleUpdateExternalStatus = async (esId: string, status: string) => {

    try {

      await axios.patch(`${API_URL}/v2/external-services/${esId}/status`, null, {

        params: { status_val: status }

      });

      fetchExternalRequests();

      toast.success('Sucesso', 'Status da assistência técnica atualizado.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao atualizar assistência.');

    }

  };



  const handleEndDowntimeRecord = async (downtimeId: string) => {

    const notes = window.prompt("Observações sobre a liberação da máquina:");

    if (notes === null) return;

    const operator = sessionStorage.getItem('mec_operator_name') || 'Operador Padrão';

    try {

      await axios.post(`${API_URL}/v2/downtime/${downtimeId}/end`, {

        released_by: operator,

        condition_after: 'released',

        notes: notes

      });

      fetchDowntimeRecords();

      toast.success('Sucesso', 'Máquina liberada e parada encerrada.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao liberar a máquina.');

    }

  };



  const handleRetryNotification = async (notifId: string) => {

    try {

      await axios.post(`${API_URL}/v2/notifications/retry/${notifId}`);

      fetchNotificationsQueue();

      toast.success('Sucesso', 'Notificação re-enfileirada para envio.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao re-enfileirar notificação.');

    }

  };



  const formatBytes = (bytes: number) => {

    if (bytes === 0) return '0 Bytes';

    const k = 1024;

    const sizes = ['Bytes', 'KB', 'MB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];

  };



  return (

    <div>

      <h1>Gestão e Administração</h1>

      <p className="subtitle">Configurações, qualidade, relatórios e ferramentas de apoio. Para o trabalho diário, use Início, Equipamentos e Histórico.</p>



      {/* O uso diário fica em poucos caminhos; os recursos técnicos continuam disponíveis abaixo. */}
      <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '24px' }}>
        <div style={{ fontWeight: 700, marginBottom: '8px' }}>Uso e acompanhamento</div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/manutencoes/pendentes-revisar')}
            style={{ padding: '8px 14px', fontSize: '14px' }}
          >
            <AlertTriangle size={16} style={{ verticalAlign: 'text-bottom', marginRight: '5px' }} />
            Manutenções pendentes para revisar
          </button>
          {([
            ['operadores', 'Pessoas'], ['qualidade', 'Problemas e Qualidade'],
            ['epi', 'Orientações de segurança'], ['materiais_compras', 'Materiais e compras'],
            ['paradas_maquina', 'Paradas de máquina'], ['relatorios', 'Relatórios'],
          ] as const).map(([tab, label]) => (
            <button key={tab} className={`btn ${activeSubTab === tab ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveSubTab(tab)} style={{ padding: '8px 14px', fontSize: '14px' }}>
              {tab === 'qualidade' && <AlertTriangle size={16} style={{ verticalAlign: 'text-bottom', marginRight: '5px' }} />}{label}
            </button>
          ))}
          <button className="btn btn-secondary" onClick={() => navigate('/ativos?inventario=complementar')} style={{ padding: '8px 14px', fontSize: '14px' }}>Ferramentas e componentes</button>
          <button className="btn btn-secondary" onClick={() => navigate('/inativos')} style={{ padding: '8px 14px', fontSize: '14px' }}>Itens fora de uso</button>
        </div>
        <p style={{ margin: '12px 0 0', color: 'var(--text-muted)', fontSize: '13px', maxWidth: 850 }}>
          Use <strong>Manutenções pendentes para revisar</strong> para tratar checklists iniciados em teste ou que ficaram em andamento:
          escolha se deve continuar como manutenção real, registrar como teste do aplicativo ou informar que a manutenção não foi realizada.
          Nenhum registro é apagado.
        </p>
        <details style={{ marginTop: '16px' }} open={['backup', 'conflitos', 'indicadores', 'cmp', 'conferir_programacoes', 'assistencia_tecnica', 'fila_notificacoes', 'offline_sync', 'revisao_documental', 'sistema', 'checklists_importados'].includes(activeSubTab)}>
          <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontWeight: 600 }}>Ferramentas avançadas, auditoria e administração técnica</summary>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '12px' }}>
            {([
              ['backup', 'Backup e restauração'], ['conflitos', 'Conferir códigos duplicados'], ['indicadores', 'Indicadores'],
              ['cmp', 'Modelos de checklist'], ['conferir_programacoes', 'Situações a conferir'], ['assistencia_tecnica', 'Assistência técnica'],
              ['fila_notificacoes', 'Fila de notificações'], ['offline_sync', 'Conexão e sincronização'], ['revisao_documental', 'Revisão documental'],
              ['sistema', 'Sistema e diagnóstico'], ['checklists_importados', 'Checklists importados'],
            ] as const).map(([tab, label]) => (
              <button key={tab} className={`btn ${activeSubTab === tab ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveSubTab(tab)} style={{ padding: '8px 14px', fontSize: '14px' }}>{label}</button>
            ))}
          </div>
        </details>
      </div>



      {/* --- ABA 1: CRUD OPERADORES --- */}

      {activeSubTab === 'operadores' && (

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '32px', flexWrap: 'wrap' }}>



          {/* Cadastro / Edição */}

          <div className="card" style={{ height: 'fit-content' }}>

            <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>

              <UserPlus size={18} style={{ color: 'var(--primary)' }} />

              {editingOp ? 'Editar pessoa' : 'Cadastrar pessoa'}

            </h3>



            <form onSubmit={editingOp ? handleUpdateOperator : handleAddOperator} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

              <div className="form-group">

                <label className="form-label">Nome Completo</label>

                <input

                  type="text"

                  className="form-control"

                  value={editingOp ? editingName : newOpName}

                  onChange={e => editingOp ? setEditingName(e.target.value) : setNewOpName(e.target.value)}

                  placeholder="Ex: Camila Duarte..."

                  required

                />

              </div>

              <fieldset style={{ border: '1px solid var(--border)', borderRadius: '8px', padding: '12px', display: 'grid', gap: '10px' }}>
                <legend style={{ padding: '0 6px', fontSize: '13px', fontWeight: 700 }}>Uso da pessoa no processo</legend>
                <label style={{ display: 'flex', gap: '9px', alignItems: 'flex-start', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={editingOp ? editingCanRecordChecklist : newCanRecordChecklist}
                    onChange={(event) => editingOp ? setEditingCanRecordChecklist(event.target.checked) : setNewCanRecordChecklist(event.target.checked)}
                  />
                  <span><strong>Registra e confere checklist no tablet</strong><br /><small style={{ color: 'var(--text-muted)' }}>Aparece na primeira tela do tablet. Use somente para Camila, Rafael ou futuros conferentes.</small></span>
                </label>
                <label style={{ display: 'flex', gap: '9px', alignItems: 'flex-start', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={editingOp ? editingCanExecuteMaintenance : newCanExecuteMaintenance}
                    onChange={(event) => editingOp ? setEditingCanExecuteMaintenance(event.target.checked) : setNewCanExecuteMaintenance(event.target.checked)}
                  />
                  <span><strong>Pode ser selecionada como executante da manutenção</strong><br /><small style={{ color: 'var(--text-muted)' }}>Aparece somente no resumo final para informar quem realizou o serviço físico.</small></span>
                </label>
              </fieldset>



              <div style={{ display: 'flex', gap: '12px' }}>

                <button type="submit" className="btn btn-primary" style={{ flex: 1 }}>

                  {editingOp ? 'Salvar Alteração' : 'Adicionar pessoa'}

                </button>

                {editingOp && (

                  <button type="button" className="btn btn-secondary" onClick={() => setEditingOp(null)}>

                    Cancelar

                  </button>

                )}

              </div>

            </form>

          </div>



          {/* Lista de Cadastrados */}

          <div>

            <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '16px' }}>

              Pessoas ativas ({operators.length})

            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {operators.length === 0 ? (

                <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>

                  Nenhuma pessoa cadastrada no momento.

                </div>

              ) : (

                operators.map(op => (

                  <div key={op.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 18px', backgroundColor: 'white', gap: '12px' }}>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>

                      <span style={{ width: '36px', height: '36px', borderRadius: '50%', background: '#e2e8f0', overflow: 'hidden', display: 'grid', placeItems: 'center', fontWeight: 700, color: '#334155', flex: '0 0 auto' }}>

                        {op.photo_thumbnail_url ? <img src={op.photo_thumbnail_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : op.name.slice(0, 1).toUpperCase()}

                      </span>

                      <div style={{ minWidth: 0 }}>
                        <span style={{ display: 'block', fontWeight: '600', fontSize: '15px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{op.name}</span>
                        <small style={{ color: 'var(--text-muted)' }}>
                          {op.can_record_checklist ? 'Confere no tablet' : ''}
                          {op.can_record_checklist && op.can_execute_maintenance ? ' · ' : ''}
                          {op.can_execute_maintenance ? 'Executa manutenção' : ''}
                          {!op.can_record_checklist && !op.can_execute_maintenance ? 'Sem uso operacional definido' : ''}
                        </small>
                      </div>

                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>

                      <label className="btn" style={{ padding: '6px 10px', color: 'var(--primary)', backgroundColor: 'transparent', border: '1px solid var(--border)', cursor: 'pointer' }}>

                        Foto

                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          style={{ display: 'none' }}
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            event.currentTarget.value = '';
                            handleUploadOperatorPhoto(op.id, file);
                          }}
                        />

                      </label>

                      <button

                        className="btn"

                        style={{ padding: '6px', color: 'var(--primary)', backgroundColor: 'transparent', border: 'none' }}

                        onClick={() => handleEditOperator(op)}

                      >

                        <Edit3 size={16} />

                      </button>

                      <button

                        className="btn"

                        style={{ padding: '6px', color: 'var(--danger)', backgroundColor: 'transparent', border: 'none' }}

                        onClick={() => handleArchiveOperator(op.id, op.name)}

                        title="Arquivar pessoa"

                      >

                        <Trash2 size={16} />

                      </button>

                    </div>

                  </div>

                ))

              )}

            </div>

          </div>



        </div>

      )}



      {/* --- ABA 2: RELATÓRIOS --- */}

      {activeSubTab === 'relatorios' && (

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>



          <div className="card">

            <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '12px' }}>Exportações Diretas (Formato CSV compatível com Excel)</h3>

            <p className="subtitle" style={{ marginBottom: '24px' }}>Dados prontos para exportar e analisar</p>



            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>



              <div className="card" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border)' }}>

                <h4 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '8px' }}>Cronograma de Manutenção</h4>

                <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>Lista de todos os ativos com suas respectivas datas planejadas, setores e operabilidade.</p>

                <button className="btn btn-primary" onClick={handleExportSchedule} disabled={exportLoading} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>

                  <Download size={16} /> Exportar Programação

                </button>

              </div>



              <div className="card" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border)' }}>

                <h4 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '8px' }}>Histórico Completo</h4>

                <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>Resumo detalhado de todas as ordens executadas, datas de término, responsáveis e anotações.</p>

                <button className="btn btn-primary" onClick={handleExportHistory} disabled={exportLoading} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>

                  <Download size={16} /> Exportar Histórico

                </button>

              </div>



              <div className="card" style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--border)' }}>

                <h4 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '8px' }}>Pendências & Problemas</h4>

                <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>Registro de todas as quebras, ocorrências e máquinas paradas que estão em aberto na fábrica.</p>

                <button className="btn btn-primary" onClick={handleExportIssues} disabled={exportLoading} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>

                  <Download size={16} /> Exportar Ocorrências

                </button>

              </div>



            </div>

          </div>



        </div>

      )}



      {/* --- ABA 3: BACKUP --- */}

      {activeSubTab === 'backup' && (

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>



          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>

            <div>

              <h3 style={{ fontSize: '18px', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '8px' }}>

                <Database size={20} style={{ color: 'var(--primary)' }} />

                Gerenciador de Backups Local (SQLite + Fotos)

              </h3>

              <p className="subtitle" style={{ marginTop: '4px' }}>Crie pontos de restauração física para salvar o banco e todas as fotos de evidências.</p>

            </div>

            <button className="btn btn-primary" onClick={handleCreateBackup} disabled={backupLoading}>

              Criar Backup Agora

            </button>

          </div>



          <div>

            <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '16px' }}>Backups Encontrados (Retenção máxima de 7 arquivos)</h3>



            {backupLoading ? (

              <p>Processando backup...</p>

            ) : (

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

                {backups.length === 0 ? (

                  <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>

                    Nenhum arquivo de backup gerado ainda.

                  </div>

                ) : (

                  backups.map((b, i) => (

                    <div key={i} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 20px', backgroundColor: 'white' }}>

                      <div>

                        <strong style={{ fontSize: '15px' }}>{b.filename}</strong>

                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                          Tamanho: {formatBytes(b.size_bytes)} | Criado em: {new Date(b.created_at).toLocaleString('pt-BR')}

                        </div>

                      </div>

                      <button

                        className="btn btn-secondary"

                        style={{ fontSize: '13px', padding: '6px 12px' }}

                        onClick={() => handleRestoreBackup(b.filename)}

                      >

                        Restaurar

                      </button>

                    </div>

                  ))

                )}

              </div>

            )}

          </div>



        </div>

      )}



      {/* --- ABA 4: CONFLITOS DE PATRIMÔNIO --- */}

      {activeSubTab === 'conflitos' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>

            <AlertTriangle size={20} style={{ color: 'var(--warning)' }} />

            Resolução de Conflitos de Patrimônio ({conflictAssets.length})

          </h3>

          <p className="subtitle" style={{ marginBottom: '24px' }}>

            Ativos com códigos duplicados na planilha foram importados como registros separados. Resolva-os abaixo.

          </p>



          {conflictLoading ? (

            <p>Carregando conflitos...</p>

          ) : conflictAssets.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '40px', color: 'var(--success)' }}>

              <CheckCircle size={40} style={{ margin: '0 auto 12px', display: 'block' }} />

              <strong style={{ fontSize: '16px' }}>Nenhum conflito de patrimônio pendente!</strong>

              <p style={{ fontSize: '14px', color: 'var(--text-muted)', marginTop: '4px' }}>Todos os ativos possuem códigos de patrimônio exclusivos.</p>

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

              {conflictAssets.map((asset) => (

                <div key={asset.id} className="card" style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '20px', alignItems: 'center', backgroundColor: 'white' }}>

                  <div>

                    <span className="badge" style={{ backgroundColor: 'var(--warning-light)', color: 'var(--warning)', marginRight: '8px' }}>

                      {asset.type === 'machine' ? 'Máquina' : 'Equipamento'}

                    </span>

                    <strong style={{ fontSize: '16px' }}>{asset.description}</strong>

                    <div style={{ display: 'flex', gap: '16px', fontSize: '13px', color: 'var(--text-muted)', marginTop: '6px', flexWrap: 'wrap' }}>

                      <div>Setor: <strong>{asset.sector?.name || 'Geral'}</strong></div>

                      <div>Cód. Atual: <strong style={{ color: 'var(--danger)' }}>{asset.patrimonio}</strong></div>

                      {asset.serial_number && <div>Nº Série: <strong>{asset.serial_number}</strong></div>}

                    </div>

                  </div>



                  <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>

                    {/* Botão Aceitar Sugestão */}

                    {asset.conflict_patrimonio_suggested && (

                      <button

                        className="btn btn-secondary"

                        style={{ fontSize: '13px', padding: '8px 12px', borderColor: 'var(--success)', color: 'var(--success)' }}

                        onClick={() => handleResolveConflict(asset.id, 'suggested')}

                      >

                        Usar Sugerido ({asset.conflict_patrimonio_suggested})

                      </button>

                    )}



                    {/* Campo Manual */}

                    <div style={{ display: 'flex', gap: '4px' }}>

                      <input

                        type="text"

                        className="form-control"

                        style={{ width: '120px', padding: '6px 10px', fontSize: '13px' }}

                        placeholder="Novo código..."

                        value={manualPatrimonios[asset.id] || ''}

                        onChange={(e) => setManualPatrimonios({ ...manualPatrimonios, [asset.id]: e.target.value })}

                      />

                      <button

                        className="btn btn-primary"

                        style={{ fontSize: '13px', padding: '6px 12px' }}

                        onClick={() => handleResolveConflict(asset.id, 'manual')}

                      >

                        Definir

                      </button>

                    </div>



                    {/* Manter original */}

                    <button

                      className="btn btn-secondary"

                      style={{ fontSize: '13px', padding: '8px 12px' }}

                      onClick={() => handleResolveConflict(asset.id, 'keep')}

                    >

                      Manter Original

                    </button>

                  </div>

                </div>

              ))}

            </div>

          )}

      </div>

    )}

      {activeSubTab === 'indicadores' && <Indicadores />}

      {activeSubTab === 'qualidade' && <QualityActionsPanel />}

      {activeSubTab === 'cmp' && <CMP />}

      {activeSubTab === 'conferir_programacoes' && <ConferirProgramacoes />}



      {/* --- ABA: MATERIAIS & COMPRAS --- */}

      {activeSubTab === 'materiais_compras' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>Solicitações de Peças e Materiais</h3>

          <p className="subtitle" style={{ marginBottom: '20px' }}>Fila de requisições enviadas ao Almoxarifado/Compras via checklists.</p>



          {loadingV2 ? (

            <p>Carregando solicitações...</p>

          ) : materialRequests.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

              Nenhuma solicitação de material no momento.

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {materialRequests.map((req) => (

                <div key={req.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'white' }}>

                  <div>

                    <strong style={{ fontSize: '15px' }}>{req.item_name}</strong>

                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                      Status: <span style={{ fontWeight: '600' }}>{req.status}</span> | Prioridade: <span style={{ fontWeight: '600' }}>{req.priority}</span> | Solicitado em: {new Date(req.requested_at).toLocaleString('pt-BR')}

                    </div>

                  </div>

                  <div style={{ display: 'flex', gap: '8px' }}>

                    {req.status === 'requested' && (

                      <>

                        <button className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => handleUpdateMaterialStatus(req.id, 'approved')}>

                          Aprovar

                        </button>

                        <button className="btn btn-secondary" style={{ fontSize: '12px', padding: '6px 12px', color: 'var(--danger)' }} onClick={() => handleUpdateMaterialStatus(req.id, 'cancelled')}>

                          Cancelar

                        </button>

                      </>

                    )}

                    {req.status === 'approved' && (

                      <button className="btn btn-secondary" style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => handleUpdateMaterialStatus(req.id, 'delivered')}>

                        Marcar como Entregue

                      </button>

                    )}

                  </div>

                </div>

              ))}

            </div>

          )}

        </div>

      )}



      {/* --- ABA: ASSISTÊNCIA TÉCNICA --- */}

      {activeSubTab === 'assistencia_tecnica' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>Solicitações de Assistência Técnica Externa</h3>

          <p className="subtitle" style={{ marginBottom: '20px' }}>Controle de laudos, garantias e visitas de fornecedores externos.</p>



          {loadingV2 ? (

            <p>Carregando solicitações...</p>

          ) : externalRequests.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

              Nenhuma solicitação de assistência externa no momento.

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {externalRequests.map((req) => (

                <div key={req.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'white' }}>

                  <div>

                    <strong style={{ fontSize: '15px' }}>{req.service_type} ({req.supplier})</strong>

                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                      Status: <span style={{ fontWeight: '600' }}>{req.status}</span> | Solicitado por: {req.requested_by} | Solicitado em: {new Date(req.requested_at).toLocaleString('pt-BR')}

                    </div>

                  </div>

                  <div style={{ display: 'flex', gap: '8px' }}>

                    {req.status === 'requested' && (

                      <button className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => handleUpdateExternalStatus(req.id, 'scheduled')}>

                        Agendar Visita

                      </button>

                    )}

                    {req.status === 'scheduled' && (

                      <button className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => handleUpdateExternalStatus(req.id, 'completed')}>

                        Concluir e Liberar

                      </button>

                    )}

                  </div>

                </div>

              ))}

            </div>

          )}

        </div>

      )}



      {/* --- ABA: PARADAS DE MÁQUINA --- */}

      {activeSubTab === 'paradas_maquina' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>Histórico e Status de Paradas</h3>

          <p className="subtitle" style={{ marginBottom: '20px' }}>Lista de ativos fora de operação e registros históricos de indisponibilidade.</p>



          {loadingV2 ? (

            <p>Carregando paradas...</p>

          ) : downtimeRecords.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

              Nenhuma parada registrada.

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {downtimeRecords.map((req) => (

                <div key={req.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'white' }}>

                  <div>

                    <strong style={{ fontSize: '15px' }}>{req.reason}</strong>

                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                      Status: <span style={{ fontWeight: '600', color: req.is_active ? 'var(--danger)' : 'var(--success)' }}>{req.is_active ? 'Ativa' : 'Encerrada'}</span>{' '}

                      {req.duration_mins && <span>| Duração: {req.duration_mins} min</span>} | Iniciado em: {new Date(req.started_at).toLocaleString('pt-BR')}

                    </div>

                  </div>

                  {req.is_active && (

                    <button className="btn btn-primary" style={{ fontSize: '12px', padding: '6px 12px', backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={() => handleEndDowntimeRecord(req.id)}>

                      Liberar Ativo

                    </button>

                  )}

                </div>

              ))}

            </div>

          )}

        </div>

      )}



      {/* --- ABA: FILA DE NOTIFICAÇÕES --- */}

      {activeSubTab === 'fila_notificacoes' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>Fila de Notificações</h3>

          <p className="subtitle" style={{ marginBottom: '20px' }}>Histórico e status de envios de mensagens para manutenção preventiva e alertas.</p>



          {loadingV2 ? (

            <p>Carregando fila...</p>

          ) : notificationsQueue.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

              Fila de notificações vazia.

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {notificationsQueue.map((req) => (

                <div key={req.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'white' }}>

                  <div>

                    <strong style={{ fontSize: '15px' }}>{req.subject} ({req.recipient})</strong>

                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                      Status: <span style={{ fontWeight: '600' }}>{req.status}</span> | Tentativas: {req.attempt_count} | Criado em: {new Date(req.created_at).toLocaleString('pt-BR')}

                    </div>

                    {req.error_msg && (

                      <div style={{ fontSize: '11px', color: 'var(--danger)', marginTop: '4px' }}>

                        Erro: {req.error_msg}

                      </div>

                    )}

                  </div>

                  {req.status === 'failed' && (

                    <button className="btn btn-secondary" style={{ fontSize: '12px', padding: '6px 12px' }} onClick={() => handleRetryNotification(req.id)}>

                      Retentar

                    </button>

                  )}

                </div>

              ))}

            </div>

          )}

        </div>

      )}



      {/* --- ABA: CHECKLISTS IMPORTADOS --- */}

      {activeSubTab === 'checklists_importados' && (

        <div>

          <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '8px' }}>Biblioteca de Checklists Importados</h3>

          <p className="subtitle" style={{ marginBottom: '20px' }}>Log e integridade dos arquivos DOCX da pasta 'Check List Manutencao Preventiva'.</p>



          {loadingV2 ? (

            <p>Carregando biblioteca...</p>

          ) : checklistLibrary.length === 0 ? (

            <div className="card" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

              Nenhum checklist importado registrado no banco.

            </div>

          ) : (

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

              {checklistLibrary.map((req) => (

                <div key={req.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px', backgroundColor: 'white' }}>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>

                    <div>

                      <strong style={{ fontSize: '15px' }}>{req.title} ({req.rq_cmp_number})</strong>

                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>

                        Arquivo: {req.file_name} | Ano: {req.year} | Status: <span style={{ fontWeight: '600', color: req.status === 'success' ? 'var(--success)' : 'var(--warning)' }}>{req.status}</span>

                      </div>

                    </div>

                    <span style={{ fontSize: '11px', fontWeight: '700', padding: '2px 8px', borderRadius: '12px', backgroundColor: 'var(--border)' }}>

                      {req.classification}

                    </span>

                  </div>

                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', gap: '16px', borderTop: '1px solid var(--border)', paddingTop: '8px', marginTop: '4px' }}>

                    <div>Itens: <strong>{req.items_count}</strong></div>

                    <div>EPIs: <strong>{req.epi_count}</strong></div>

                    <div>Importado em: {new Date(req.imported_at).toLocaleString('pt-BR')}</div>

                  </div>

                  {req.conflicts && req.conflicts.length > 0 && (

                    <div style={{ fontSize: '11px', color: 'var(--warning)', backgroundColor: 'var(--warning-light)', padding: '8px', borderRadius: '6px', marginTop: '4px' }}>

                      <strong>Conflitos / Alertas detectados:</strong>

                      <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>

                        {req.conflicts.map((conf: any, idx: number) => (

                          <li key={idx}>{conf.description || conf}</li>

                        ))}

                      </ul>

                    </div>

                  )}

                </div>

              ))}

            </div>

          )}

        </div>

      )}



      {activeSubTab === 'offline_sync' && <OfflineSyncPanel />}

      {activeSubTab === 'revisao_documental' && <DocumentReviewPanel />}

      {activeSubTab === 'sistema' && <SystemDiagnostics />}

      {activeSubTab === 'epi' && <EpiManagement />}

    </div>

  );

}



type EpiCatalogItem = {
  id: string;
  name: string;
  ca_number?: string;
  validity?: string;
};

type PlanEpiRequirement = {
  id: string;
  item_name: string;
  ca_number?: string;
  is_mandatory: boolean;
  validity?: string;
};

type MissingEpiPlan = {
  plan_id: string;
  plan_name: string;
  asset_id: string;
  patrimonio: string;
  asset_description: string;
  status: string;
};

function EpiManagement() {
  const toast = useToast();
  const [tab, setTab] = useState<'pending' | 'catalog'>('pending');

  const [catalog, setCatalog] = useState<EpiCatalogItem[]>([]);
  const [newEpiName, setNewEpiName] = useState('');
  const [newEpiCa, setNewEpiCa] = useState('');
  const [newEpiValidity, setNewEpiValidity] = useState('');

  const [pendingPlans, setPendingPlans] = useState<MissingEpiPlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<MissingEpiPlan | null>(null);
  const [planRequirements, setPlanRequirements] = useState<PlanEpiRequirement[]>([]);

  const [selectedCatalogId, setSelectedCatalogId] = useState('');
  const [isMandatory, setIsMandatory] = useState(true);

  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadCatalog = async () => {
    try {
      const res = await axios.get(`${API_URL}/v2/quality/epi-catalog`);
      setCatalog(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      console.error(err);
    }
  };

  const loadPending = async () => {
    try {
      const res = await axios.get(`${API_URL}/v2/quality/epi-missing`);
      setPendingPlans(res.data.plans || []);
    } catch (err) {
      console.error(err);
    }
  };

  const loadPlanRequirements = async (planId: string) => {
    try {
      const res = await axios.get(`${API_URL}/v2/plans/${planId}/epi-requirements`);
      setPlanRequirements(res.data || []);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([loadCatalog(), loadPending()]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (selectedPlan) {
      loadPlanRequirements(selectedPlan.plan_id).catch(() => {});
    }
  }, [selectedPlan]);

  const handleAddCatalog = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEpiName.trim()) return;
    setSubmitting(true);
    try {
      await axios.post(`${API_URL}/v2/quality/epi-catalog`, {
        name: newEpiName.trim(),
        ca_number: newEpiCa.trim() || undefined,
        validity: newEpiValidity.trim() || undefined
      });
      toast.success('Sucesso', 'EPI adicionado ao catálogo.');
      setNewEpiName('');
      setNewEpiCa('');
      setNewEpiValidity('');
      await loadCatalog();
    } catch (err: any) {
      toast.error('Erro', err.response?.data?.detail || 'Erro ao adicionar EPI.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddRequirement = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPlan || !selectedCatalogId) return;
    const epiObj = catalog.find(c => c.id === selectedCatalogId);
    if (!epiObj) return;

    setSubmitting(true);
    try {
      await axios.post(`${API_URL}/v2/plans/${selectedPlan.plan_id}/epi-requirements`, {
        item_name: epiObj.name,
        ca_number: epiObj.ca_number || undefined,
        validity: epiObj.validity || undefined,
        is_mandatory: isMandatory,
        added_by: sessionStorage.getItem('mec_operator_name') || 'Qualidade'
      });
      toast.success('Sucesso', 'EPI vinculado ao plano.');
      setSelectedCatalogId('');
      await loadPlanRequirements(selectedPlan.plan_id);
      await loadPending();
    } catch (err: any) {
      toast.error('Erro', err.response?.data?.detail || 'Erro ao vincular EPI.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemoveRequirement = async (reqId: string) => {
    if (!selectedPlan) return;
    const confirm = await toast.confirm('Desvincular EPI', 'Tem certeza que deseja remover este EPI do plano?');
    if (!confirm) return;

    try {
      await axios.delete(`${API_URL}/v2/plans/${selectedPlan.plan_id}/epi-requirements/${reqId}`);
      toast.success('Sucesso', 'EPI removido do plano.');
      await loadPlanRequirements(selectedPlan.plan_id);
      await loadPending();
    } catch (err: any) {
      toast.error('Erro', err.response?.data?.detail || 'Erro ao remover EPI.');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: '18px', fontWeight: '700', margin: 0 }}>Gestão de EPIs de Segurança</h3>
          <p className="subtitle" style={{ margin: 0 }}>Vincule requisitos de EPI a Planos de Manutenção ou gerencie o Catálogo de SST.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn btn-sm ${tab === 'pending' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('pending')}>
            Planos Pendentes ({pendingPlans.length})
          </button>
          <button className={`btn btn-sm ${tab === 'catalog' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('catalog')}>
            Catálogo de EPIs ({catalog.length})
          </button>
        </div>
      </div>

      {loading && <p>Carregando dados de EPI...</p>}

      {!loading && tab === 'pending' && (
        <div style={{ display: 'grid', gridTemplateColumns: selectedPlan ? '1fr 1fr' : '1fr', gap: 20 }}>
          <div>
            <h4 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Planos sem EPI definido</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {pendingPlans.length === 0 ? (
                <div className="card" style={{ color: 'var(--success)', textAlign: 'center' }}>
                  Todos os planos ativos possuem requisitos de EPI configurados!
                </div>
              ) : (
                pendingPlans.map(plan => (
                  <div
                    key={plan.plan_id}
                    className="card"
                    style={{
                      cursor: 'pointer',
                      border: selectedPlan?.plan_id === plan.plan_id ? '2px solid var(--primary)' : '1px solid var(--border)',
                      padding: 12,
                      backgroundColor: selectedPlan?.plan_id === plan.plan_id ? 'var(--bg-card-selected, #f8fafc)' : 'white'
                    }}
                    onClick={() => setSelectedPlan(plan)}
                  >
                    <strong>{plan.patrimonio} — {plan.asset_description}</strong>
                    <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>Plano: {plan.plan_name}</div>
                  </div>
                ))
              )}
            </div>
          </div>

          {selectedPlan && (
            <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h4 style={{ margin: 0, fontSize: 16 }}>EPIs para o Plano</h4>
                <button className="btn btn-secondary btn-sm" onClick={() => setSelectedPlan(null)}>Fechar</button>
              </div>
              <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
                Defina quais EPIs são de uso obrigatório na execução das manutenções do plano <strong>{selectedPlan.plan_name}</strong>.
              </p>

              <div>
                <h5 style={{ margin: '0 0 8px 0', fontSize: 13 }}>EPIs vinculados ({planRequirements.length})</h5>
                {planRequirements.length === 0 ? (
                  <p style={{ fontStyle: 'italic', fontSize: 13, color: 'var(--warning)' }}>Nenhum EPI associado. O sistema assumirá EPI Não Definido.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {planRequirements.map(req => (
                      <div key={req.id} style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '6px 12px', border: '1px solid var(--border)', borderRadius: 6,
                        backgroundColor: '#f8fafc', fontSize: 13
                      }}>
                        <div>
                          <strong>{req.item_name}</strong> {req.ca_number && <span style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}> (CA: {req.ca_number})</span>}
                          {req.is_mandatory && <span style={{ color: 'var(--danger)', fontSize: 11, fontWeight: 'bold', marginLeft: 6 }}>OBRIGATÓRIO</span>}
                        </div>
                        <button className="btn" style={{ padding: '2px 6px', color: 'var(--danger)', border: 'none', background: 'transparent', cursor: 'pointer' }} onClick={() => handleRemoveRequirement(req.id)}>
                          Remover
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <form onSubmit={handleAddRequirement} style={{ borderTop: '1px solid var(--border)', paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <h5 style={{ margin: 0, fontSize: 13 }}>Vincular novo EPI</h5>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8 }}>
                  <select
                    className="form-control"
                    value={selectedCatalogId}
                    onChange={e => setSelectedCatalogId(e.target.value)}
                    required
                  >
                    <option value="">Selecione um EPI do catálogo...</option>
                    {catalog.map(c => (
                      <option key={c.id} value={c.id}>{c.name} {c.ca_number ? `(CA: ${c.ca_number})` : ''}</option>
                    ))}
                  </select>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                    <input type="checkbox" checked={isMandatory} onChange={e => setIsMandatory(e.target.checked)} />
                    Obrigatório
                  </label>
                </div>
                <button type="submit" className="btn btn-primary" style={{ width: '100%' }} disabled={submitting || !selectedCatalogId}>
                  Vincular EPI
                </button>
              </form>
            </div>
          )}
        </div>
      )}

      {!loading && tab === 'catalog' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20 }}>
          <div>
            <h4 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Catálogo SST do Sistema</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {catalog.map(epi => (
                <div key={epi.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', backgroundColor: 'white' }}>
                  <div>
                    <strong>{epi.name}</strong>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                      {epi.ca_number ? `CA: ${epi.ca_number}` : 'CA não informado'}
                      {epi.validity ? ` • Validade: ${epi.validity}` : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="card" style={{ padding: 20, height: 'fit-content' }}>
            <h4 style={{ margin: '0 0 16px 0', fontSize: 15 }}>Cadastrar novo EPI no catálogo</h4>
            <form onSubmit={handleAddCatalog} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <label className="form-group">
                <span className="form-label">Nome do EPI</span>
                <input className="form-control" value={newEpiName} onChange={e => setNewEpiName(e.target.value)} placeholder="Ex: Óculos de Proteção" required disabled={submitting} />
              </label>
              <label className="form-group">
                <span className="form-label">Número do CA</span>
                <input className="form-control" value={newEpiCa} onChange={e => setNewEpiCa(e.target.value)} placeholder="Ex: 12345 (opcional)" disabled={submitting} />
              </label>
              <label className="form-group">
                <span className="form-label">Validade</span>
                <input className="form-control" value={newEpiValidity} onChange={e => setNewEpiValidity(e.target.value)} placeholder="Ex: 2029-12-31 (opcional)" disabled={submitting} />
              </label>
              <button type="submit" className="btn btn-primary" style={{ width: '100%', marginTop: 8 }} disabled={submitting}>
                Cadastrar EPI
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
