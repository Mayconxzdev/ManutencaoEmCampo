/* oxlint-disable react-hooks/exhaustive-deps */
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { formatManutencaoEmCampoDateTime, formatManutencaoEmCampoTime } from '../utils/dateTime';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import {
  Search, Plus, Printer, X, Edit, Save, AlertTriangle, HelpCircle, File, ChevronRight, Activity, Cpu, FileCheck, Hammer, Camera, Award, ShieldCheck, FileSpreadsheet, ChevronLeft, FileText
} from 'lucide-react';

import QRCode from 'qrcode';

import { useToast } from '../components/toastContext';

import SearchCombobox from '../components/SearchCombobox';

import StatusBadge from '../components/StatusBadge';
import AssetDossierPanel from '../components/AssetDossierPanel';



interface Sector {

  id: string;

  name: string;

}



interface Asset {

  id: string;

  patrimonio: string;

  type: string; // 'machine' ou 'equipment'

  description: string;

  manufacturer: string;

  model: string;

  serial_number: string;

  status: string; // 'active' ou 'inactive'

  is_operable: boolean;

  notes: string;

  opaque_token?: string;

  sector_id?: string;

  sector?: Sector;

  manual?: string;

  ficha_tecnica?: string;

  foto?: string;

  caminho_documentos?: string;

  thumbnail_url?: string | null;

  primary_photo_id?: string | null;

  legacy_patrimonio?: string | null;
  controlled_code?: string | null;
  asset_class?: string | null;
  maintenance_strategy?: string | null;
  show_in_daily_list?: boolean;

}



interface ChecklistItem {

  id: string;

  item_number: string;

  description: string;

}



interface ChecklistTemplate {

  id: string;

  name: string;

  asset_type: string;

  versions: Array<{

    id: string;

    version: number;

    items: ChecklistItem[];

  }>;

}



interface Order {

  id: string;

  friendly_number: number;

  asset_id: string;

  status: string;

  execution_status: string;

  opaque_token?: string;

  checklist_version_id?: string | null;

  planned_year?: number | null;

  planned_month?: number | null;

  original_competence?: string | null;

}



interface MaintenancePlan {

  id: string;

  name: string;

  asset_id: string;

  periodicity: string;

  frequency_days?: number | null;

  frequency_months?: number | null;

  planned_month?: number | null;

  next_due_date?: string | null;

  checklist_template_version_id?: string | null;

  estimated_duration_mins: number;

  calculation_basis: string;

  recurrence_status: string;

  recurrence_confirmed_by?: string | null;

  recurrence_confirmed_at?: string | null;

  is_active: boolean;

  safety_instructions?: string | null;

  is_monthly_competency: boolean;

}



interface AssetMeter {

  id: string;

  asset_id: string;

  meter_type: string;

  unit: string;

  current_reading: number;

  last_reading_at?: string | null;

  maintenance_interval: number;

  next_maintenance_at: number;

  notes?: string | null;

}



interface LinkedDocument {
  id: string;
  asset_id: string;
  name: string;
  original_name: string;
  extension: string;
  file_size: number;
  file_hash: string;
  mime_type: string;
  category: string;
  thumbnail_url?: string | null;
  content_url: string;
  download_url: string;
  is_primary_photo: boolean;
  created_at?: string | null;
  imported_at?: string | null;
  status: string;
  notes?: string | null;
}

interface FileLimits {
  bytes: Record<string, number>;
  mb: Record<string, number>;
}



const API_URL = window.location.port === '5173'

  ? `http://${window.location.hostname}:8000`

  : window.location.origin;

const UPLOAD_EXTENSIONS = {
  image: ['.jpg', '.jpeg', '.png', '.webp'],
  document: ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.pptx', '.txt', '.csv'],
  audio: ['.ogg', '.mp3', '.wav', '.m4a'],
  video: ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
};

const ACCEPTED_UPLOAD_EXTENSIONS = [
  'image/*',
  ...UPLOAD_EXTENSIONS.document,
  ...UPLOAD_EXTENSIONS.audio,
  ...UPLOAD_EXTENSIONS.video,
].join(',');

function formatBytes(bytes?: number) {
  if (!bytes || bytes <= 0) return 'limite nao configurado';
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / (1024 * 1024))} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

function extensionOf(fileName: string) {
  const dot = fileName.lastIndexOf('.');
  return dot >= 0 ? fileName.slice(dot).toLowerCase() : '';
}

function uploadLimitCategory(file: File) {
  const ext = extensionOf(file.name);
  if (UPLOAD_EXTENSIONS.image.includes(ext) || file.type.startsWith('image/')) return 'image';
  if (UPLOAD_EXTENSIONS.audio.includes(ext) || file.type.startsWith('audio/')) return 'audio';
  if (UPLOAD_EXTENSIONS.video.includes(ext) || file.type.startsWith('video/')) return 'video';
  if (UPLOAD_EXTENSIONS.document.includes(ext)) return 'document';
  return 'other';
}



type MaquinasProps = {
  inactiveMode?: boolean;
};

export default function Maquinas({ inactiveMode = false }: MaquinasProps) {

  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { assetId } = useParams();
  const complementaryInventoryMode = new URLSearchParams(location.search).get('inventario') === 'complementar';



  // Dados Principais

  const [assets, setAssets] = useState<Asset[]>([]);

  const [sectors, setSectors] = useState<Sector[]>([]);

  const [checklists, setChecklists] = useState<ChecklistTemplate[]>([]);

  const [orders, setOrders] = useState<Order[]>([]);

  const [plans, setPlans] = useState<MaintenancePlan[]>([]);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState('');
  const [assetPage, setAssetPage] = useState(1);
  const [assetPageSize, setAssetPageSize] = useState(20);
  const [assetTotal, setAssetTotal] = useState(0);
  const [assetTotalPages, setAssetTotalPages] = useState(1);



  // Abas e Filtros

  const [activeTab, setActiveTab] = useState<'machine' | 'equipment'>('machine');

  const [search, setSearch] = useState('');

  const [sectorFilter, setSectorFilter] = useState('');

  const [statusFilter, setStatusFilter] = useState('all'); // all, active, inactive, operable, stopped

  const [controlFilter, setControlFilter] = useState('all'); // all, fixed, floating_days, floating_months, meter, none

  const [checklistFilter, setChecklistFilter] = useState('all'); // all, with, without

  const [managerFilter, setManagerFilter] = useState(''); // filter by confirmed_by operator



  // Estado de Detalhe (Drawer)

  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);

  const [assetPlans, setAssetPlans] = useState<MaintenancePlan[]>([]);

  const [assetMeters, setAssetMeters] = useState<AssetMeter[]>([]);

  const [assetDocs, setAssetDocs] = useState<LinkedDocument[]>([]);

  const [loadingDetails, setLoadingDetails] = useState(false);

  const [detailTab, setDetailTab] = useState<'info' | 'plan' | 'meters' | 'docs' | 'history' | 'dossier'>('info');

  const [assetTimeline, setAssetTimeline] = useState<any[]>([]);

  const [timelineTypeFilter, setTimelineTypeFilter] = useState('all');

  const [timelineStatusFilter, setTimelineStatusFilter] = useState('all');

  const [timelineOperatorFilter, setTimelineOperatorFilter] = useState('all');

  const [expandedOrderId, setExpandedOrderId] = useState<string | null>(null);

  // Estados de galeria, lazy loading e upload de arquivos.
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [zoomScale, setZoomScale] = useState(1);
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const [submittingDoc, setSubmittingDoc] = useState(false);
  const [fileLimits, setFileLimits] = useState<FileLimits | null>(null);
  const [uploadValidationError, setUploadValidationError] = useState('');

  // Estado de Edição do Ativo no Drawer

  const [isEditingAsset, setIsEditingAsset] = useState(false);

  const [editAssetForm, setEditAssetForm] = useState<Partial<Asset>>({});



  // Estado de Configuração de Plano

  const [isConfiguringPlan, setIsConfiguringPlan] = useState(false);

  const [planForm, setPlanForm] = useState<Partial<MaintenancePlan>>({

    name: '',

    periodicity: 'monthly',

    calculation_basis: 'fixed_calendar',

    estimated_duration_mins: 60,

    checklist_template_version_id: '',

    safety_instructions: '',

    is_monthly_competency: true

  });



  // Estado para Cadastro de Ativo

  const [showAddModal, setShowAddModal] = useState(false);
  const [addAssetStep, setAddAssetStep] = useState<1 | 2 | 3>(1);

  const [newAsset, setNewAsset] = useState({

    patrimonio: '',

    type: 'machine',

    description: '',

    manufacturer: '',

    model: '',

    serial_number: '',

    sector_id: '',
    status: 'active',
    is_operable: true,

    notes: '',

    manual: '',

    ficha_tecnica: '',

    foto: '',

    caminho_documentos: ''

  });
  const [newAssetPlan, setNewAssetPlan] = useState({
    periodicity: 'monthly',
    checklist_template_version_id: '',
    planned_month: String(new Date().getMonth() + 1)
  });



  // Estado para Medidores e Leituras

  const [showAddMeter, setShowAddMeter] = useState(false);

  const [newMeterForm, setNewMeterForm] = useState({

    meter_type: 'hours',

    unit: 'h',

    current_reading: 0,

    maintenance_interval: 200,

    notes: ''

  });

  const [readingInputs, setReadingInputs] = useState<Record<string, string>>({});



  // Estado para Linkar Documento

  const [showAddDoc, setShowAddDoc] = useState(false);

  const [newDocForm, setNewDocForm] = useState({

    file_path: '',

    document_type: 'manual',

    notes: ''

  });



  // Estado para Liberação de Ativo (Modal Personalizado)

  const [releasingAssetId, setReleasingAssetId] = useState<string | null>(null);

  const [releaseDescription, setReleaseDescription] = useState('');



  // Estado de Impressão de Folha Física

  const [printAsset, setPrintAsset] = useState<Asset | null>(null);

  const [printChecklistItems, setPrintChecklistItems] = useState<ChecklistItem[]>([]);

  const [printOrderNumber, setPrintOrderNumber] = useState<string>('-------');

  const [printQRData, setPrintQRData] = useState<string>('');

  const [qrCodeUrl, setQrCodeUrl] = useState<string>('');



  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {

    if (printQRData) {

      QRCode.toDataURL(printQRData, { width: 150, margin: 1 })

        .then(url => setQrCodeUrl(url))

        .catch(err => console.error(err));

    } else {

      setQrCodeUrl('');

    }

  }, [printQRData]);

  useEffect(() => {
    axios.get(`${API_URL}/v2/file-limits`)
      .then(res => setFileLimits(res.data))
      .catch(err => {
        console.warn('Não foi possível carregar limites de upload:', err);
        setFileLimits(null);
      });
  }, []);

  const validateUploadFiles = (files: File[]) => {
    if (files.length === 0) return '';
    for (const file of files) {
      const category = uploadLimitCategory(file);
      const limit = fileLimits?.bytes?.[category];
      if (category === 'other') {
        return `Arquivo não permitido: ${file.name}. Use imagens, PDFs, Office, texto, CSV, áudio ou vídeo compatível.`;
      }
      if (limit && file.size > limit) {
        return `${file.name} excede o limite de ${formatBytes(limit)} para ${category}.`;
      }
    }
    return '';
  };

  // Voltar para a primeira página quando filtros principais mudarem.
  useEffect(() => {
    setAssetPage(1);
  }, [activeTab, search, sectorFilter, statusFilter, controlFilter, checklistFilter, managerFilter]);

  const fetchData = async () => {

    setLoading(true);

    try {

      const assetParams: Record<string, string | number | boolean> = {
        page: assetPage,
        page_size: assetPageSize
      };

      if (inactiveMode) {
        // Inactive mode: use dedicated endpoint, filter only by search
        if (search.trim()) assetParams.q = search.trim();
      } else if (complementaryInventoryMode) {
        // Ferramentas e componentes seguem localizáveis, mas fora da rotina de
        // máquina. Esta tela é a consulta simples de inventário complementar.
        assetParams.non_daily_only = true;
        if (search.trim()) assetParams.q = search.trim();
      } else {
        assetParams.type = activeTab;
        // A lista do dia mostra somente máquinas/equipamentos que realmente
        // recebem rotina. Ferramentas e componentes continuam no inventário
        // administrativo, sem confundir quem executa a manutenção.
        assetParams.daily_only = true;
        if (search.trim()) assetParams.q = search.trim();
        if (sectorFilter) assetParams.sector_id = sectorFilter;
        if (statusFilter === 'active') assetParams.status = 'active';
        if (statusFilter === 'inactive') assetParams.status = 'inactive';
        if (statusFilter === 'operable') assetParams.is_operable = true;
        if (statusFilter === 'stopped') assetParams.is_operable = false;
      }

      const [assetsRes, sectorsRes, checklistsRes, ordersRes, plansRes] = await Promise.all([

        axios.get(
          inactiveMode ? `${API_URL}/v2/assets/inactive` : `${API_URL}/v2/assets`,
          { params: assetParams }
        ),

        axios.get(`${API_URL}/sectors`),

        axios.get(`${API_URL}/checklists`),

        axios.get(`${API_URL}/orders`),

        axios.get(`${API_URL}/plans`)

      ]);



      setAssets(assetsRes.data.items || []);
      setAssetTotal(assetsRes.data.total || 0);
      setAssetTotalPages(assetsRes.data.total_pages || 1);

      setSectors(sectorsRes.data);

      setChecklists(checklistsRes.data);

      setOrders(ordersRes.data);

      setPlans(plansRes.data);

      setError('');

    } catch (err) {

      console.error(err);

      setError('Erro ao carregar os dados. Certifique-se de que o backend está ativo.');

    } finally {

      setLoading(false);

    }

  };



  useEffect(() => {
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    fetchData();
  }, [activeTab, search, sectorFilter, statusFilter, assetPage, assetPageSize, complementaryInventoryMode]);



  // Buscar detalhes do ativo selecionado

  const fetchAssetDetails = async (assetId: string) => {

    setLoadingDetails(true);

    try {

      const [plansRes, metersRes, docsRes, timelineRes] = await Promise.all([
        axios.get(`${API_URL}/assets/${assetId}/plans`),
        axios.get(`${API_URL}/assets/${assetId}/meters`),
        axios.get(`${API_URL}/v2/assets/${assetId}/files?page_size=50&include_archived=true`),
        axios.get(`${API_URL}/v2/assets/${assetId}/timeline`)
      ]);

      setAssetPlans(plansRes.data);
      setAssetMeters(metersRes.data);
      setAssetDocs(docsRes.data.items || []);
      setAssetTimeline(timelineRes.data.orders || []);

    } catch (err) {

      console.error('Erro ao carregar detalhes do ativo:', err);

      toast.error('Erro', 'Não foi possível carregar os detalhes do ativo.');

    } finally {

      setLoadingDetails(false);

    }

  };



  const handleSelectAsset = (asset: Asset) => {

    setSelectedAsset(asset);

    setDetailTab('info');

    setIsEditingAsset(false);

    setIsConfiguringPlan(false);

    setShowAddMeter(false);

    setShowAddDoc(false);

    setEditAssetForm(asset);

    setExpandedOrderId(null);

    setTimelineTypeFilter('all');

    setTimelineStatusFilter('all');

    setTimelineOperatorFilter('all');

    fetchAssetDetails(asset.id);

    const targetPath = asset.status === 'inactive' ? `/inativos/${asset.id}` : `/ativos/${asset.id}`;
    if (window.location.pathname !== targetPath) {
      navigate(targetPath);
    }

  };

  const handleCloseDrawer = () => {
    setSelectedAsset(null);
    navigate(inactiveMode ? '/inativos' : '/ativos');
  };

  useEffect(() => {
    const pendingAssetId = assetId || localStorage.getItem('mec_auto_open_asset');
    if (!pendingAssetId) {
      setSelectedAsset(null);
      return;
    }
    localStorage.removeItem('mec_auto_open_asset');
    axios.get(`${API_URL}/assets/${pendingAssetId}`)
      .then((res) => {
        const asset = res.data as Asset;
        setActiveTab(asset.type === 'equipment' ? 'equipment' : 'machine');
        const targetPath = asset.status === 'inactive' ? `/inativos/${asset.id}` : `/ativos/${asset.id}`;
        if (window.location.pathname !== targetPath) {
          navigate(targetPath, { replace: true });
        }
        handleSelectAsset(asset);
      })
      .catch((err) => {
        console.error('Não foi possível abrir ativo vindo da busca global:', err);
        toast.warning('Busca global', 'Resultado encontrado, mas o ativo não pôde ser aberto automaticamente.');
      });
  }, [assetId]);

  const handleAddAsset = async (e: React.FormEvent) => {

    e.preventDefault();

    try {
      const selectedUserId = sessionStorage.getItem('mec_operator_id') || undefined;
      const duplicateRes = await axios.get<{ items: Asset[] }>(`${API_URL}/v2/assets/patrimonio-check`, {
        params: { patrimonio: newAsset.patrimonio.trim() }
      });
      const duplicateAssets = duplicateRes.data.items || [];
      if (duplicateAssets.length > 0) {
        const duplicateSummary = duplicateAssets
          .slice(0, 3)
          .map(asset => `${asset.patrimonio} — ${asset.description}`)
          .join('\n');
        const keepSeparate = await toast.confirm(
          'Patrimônio duplicado',
          `Já encontramos outro ativo com este patrimônio.\n\n${duplicateSummary}\n\nDois ativos ficarão com o mesmo patrimônio. Deseja manter separado mesmo assim?`
        );
        if (!keepSeparate) return;
      }

      const assetRes = await axios.post(`${API_URL}/assets`, newAsset, {
        params: { selected_user_id: selectedUserId }
      });
      const createdAsset = assetRes.data;

      if (newAssetPlan.periodicity) {
        const frequencyMonthsByPeriodicity: Record<string, number> = {
          monthly: 1,
          bimonthly: 2,
          trimonthly: 3,
          semiannual: 6,
          annual: 12
        };
        await axios.post(`${API_URL}/assets/${createdAsset.id}/plans`, {
          asset_id: createdAsset.id,
          name: `Preventiva - ${createdAsset.patrimonio}`,
          periodicity: newAssetPlan.periodicity,
          frequency_months: frequencyMonthsByPeriodicity[newAssetPlan.periodicity] || 1,
          planned_month: Number(newAssetPlan.planned_month) || null,
          checklist_template_version_id: newAssetPlan.checklist_template_version_id || null,
          estimated_duration_mins: 60,
          calculation_basis: 'fixed_calendar',
          plan_type: 'fixed_calendar',
          generation_horizon_months: 12,
          confidence: 'medium',
          recurrence_status: newAssetPlan.checklist_template_version_id ? 'confirmed' : 'to_review',
          recurrence_confirmed_by: sessionStorage.getItem('mec_operator_name') || undefined,
          recurrence_confirmed_at: new Date().toISOString(),
          is_active: true,
          safety_instructions: '',
          is_monthly_competency: true
        }, {
          params: { selected_user_id: selectedUserId }
        });
      }

      setShowAddModal(false);
      setAddAssetStep(1);

      setNewAsset({

        patrimonio: '',

        type: activeTab,

        description: '',

        manufacturer: '',

        model: '',

        serial_number: '',

        sector_id: '',
        status: 'active',
        is_operable: true,

        notes: '',

        manual: '',

        ficha_tecnica: '',

        foto: '',

        caminho_documentos: ''

      });
      setNewAssetPlan({
        periodicity: 'monthly',
        checklist_template_version_id: '',
        planned_month: String(new Date().getMonth() + 1)
      });

      const createdDetailRes = await axios.get<Asset>(`${API_URL}/assets/${createdAsset.id}`);
      const createdDetail = createdDetailRes.data;
      setSelectedAsset(createdDetail);
      setDetailTab('info');
      await fetchAssetDetails(createdAsset.id);
      await fetchData();

      toast.success('Sucesso', 'Ativo cadastrado com plano preventivo e TAG disponíveis no detalhe.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao cadastrar o ativo.');

    }

  };



  const handleUpdateAsset = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!selectedAsset) return;

    try {

      const res = await axios.put(`${API_URL}/assets/${selectedAsset.id}`, editAssetForm, {
        params: { selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined }
      });

      setSelectedAsset(res.data);

      setIsEditingAsset(false);

      fetchData();

      toast.success('Sucesso', 'Informações do ativo atualizadas!');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Erro ao atualizar informações do ativo.');

    }

  };



  const handleConfigurePlan = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!selectedAsset) return;

    const operatorName = sessionStorage.getItem('mec_operator_name') || 'Supervisor';

    try {

      const payload = {

        ...planForm,

        asset_id: selectedAsset.id,

        name: planForm.name || `Plano de Manutenção - ${selectedAsset.patrimonio}`,

        recurrence_status: 'confirmed',

        recurrence_confirmed_by: operatorName,

        recurrence_confirmed_at: new Date().toISOString()

      };

      await axios.post(`${API_URL}/assets/${selectedAsset.id}/plans`, payload, {
        params: { selected_user_id: sessionStorage.getItem('mec_operator_id') || undefined }
      });

      setIsConfiguringPlan(false);

      fetchAssetDetails(selectedAsset.id);

      fetchData();

      toast.success('Sucesso', 'Plano de manutenção configurado com sucesso!');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Não foi possível configurar o plano.');

    }

  };



  const handleAddMeter = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!selectedAsset) return;

    try {

      await axios.post(`${API_URL}/assets/${selectedAsset.id}/meters`, {

        ...newMeterForm,

        asset_id: selectedAsset.id

      });

      setShowAddMeter(false);

      setNewMeterForm({

        meter_type: 'hours',

        unit: 'h',

        current_reading: 0,

        maintenance_interval: 200,

        notes: ''

      });

      fetchAssetDetails(selectedAsset.id);

      toast.success('Sucesso', 'Medidor adicionado com sucesso!');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Não foi possível criar o medidor.');

    }

  };



  const handleAddReading = async (meterId: string) => {

    if (!selectedAsset) return;

    const value = readingInputs[meterId];

    if (!value || isNaN(parseFloat(value))) {

      toast.warning('Aviso', 'Insira uma leitura numérica válida.');

      return;

    }

    try {

      await axios.post(`${API_URL}/assets/${selectedAsset.id}/meters/${meterId}/reading`, {

        reading: parseFloat(value),

        notes: 'Leitura manual'

      });

      setReadingInputs(prev => ({ ...prev, [meterId]: '' }));

      fetchAssetDetails(selectedAsset.id);

      toast.success('Sucesso', 'Leitura do medidor registrada!');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Falha ao registrar leitura.');

    }

  };



  const handleLinkDocument = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAsset) return;
    const validationError = validateUploadFiles(selectedUploadFiles);
    if (validationError) {
      setUploadValidationError(validationError);
      toast.warning('Arquivo inválido', validationError);
      return;
    }
    setSubmittingDoc(true);
    try {
      if (selectedUploadFiles.length > 0) {
        const formData = new FormData();
        selectedUploadFiles.forEach(file => formData.append('files', file));

        await axios.post(`${API_URL}/v2/assets/${selectedAsset.id}/files/batch`, formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          params: {
            category: newDocForm.document_type,
            uploaded_by: sessionStorage.getItem('mec_operator_name') || 'Operador'
          }
        });
      } else {
        toast.warning('Arquivo obrigatório', 'Selecione um arquivo para enviar.');
        return;
      }
      setShowAddDoc(false);
      setNewDocForm({ file_path: '', document_type: 'manual', notes: '' });
      setSelectedUploadFiles([]);
      setUploadValidationError('');
      fetchAssetDetails(selectedAsset.id);
      toast.success('Sucesso', `${selectedUploadFiles.length} arquivo(s) enviado(s) com sucesso!`);
    } catch (err) {
      console.error(err);
      toast.error('Erro', 'Não foi possível enviar ou vincular o arquivo.');
    } finally {
      setSubmittingDoc(false);
    }
  };



  const handleReleaseAssetSubmit = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!releasingAssetId || !releaseDescription.trim()) return;

    const operatorName = sessionStorage.getItem('mec_operator_name') || 'Responsável';

    try {

      const issuesRes = await axios.get(`${API_URL}/issues`, { params: { status: 'open' } });

      const issue = issuesRes.data.find((item: any) => item.asset_id === releasingAssetId && item.is_operable_affected);

      if (!issue) {

        toast.warning('Aviso', 'Não existe uma ocorrência de parada ativa para este ativo.');

        setReleasingAssetId(null);

        return;

      }



      await axios.post(`${API_URL}/assets/${releasingAssetId}/release`, {

        issue_id: issue.id,

        repair_description: releaseDescription.trim(),

        operator_name: operatorName,

        final_condition: 'released',

        resolution_date: new Date().toISOString().slice(0, 10),

        evidence_file_path: null

      });



      setReleasingAssetId(null);

      setReleaseDescription('');

      fetchData();

      if (selectedAsset?.id === releasingAssetId) {

        setSelectedAsset(prev => prev ? { ...prev, is_operable: true } : null);

        fetchAssetDetails(releasingAssetId);

      }

      toast.success('Sucesso', 'Máquina liberada e reparo registrado no histórico.');

    } catch (err) {

      console.error(err);

      toast.error('Erro', 'Não foi possível liberar a máquina.');

    }

  };



  // --- IMPRESSÃO DE FOLHA FÍSICA ---

  const handlePrintSheet = (asset: Asset) => {

    const openOrder = orders.find(o =>

      o.asset_id === asset.id &&

      ['scheduled', 'today', 'overdue', 'in_progress'].includes(o.status)

    );

    if (!openOrder) {

      toast.warning('Impossível Imprimir', 'Não existe uma manutenção preventiva em aberto para este ativo.');

      return;

    }

    if (!openOrder.checklist_version_id) {

      toast.warning('Sem Checklist', 'Esta manutenção ainda não possui um checklist vinculado. Vincule nas configurações do plano.');

      return;

    }

    const version = checklists

      .flatMap(template => template.versions)

      .find(item => item.id === openOrder.checklist_version_id);

    if (!version) {

      toast.error('Erro', 'O checklist vinculado a esta ordem não foi encontrado.');

      return;

    }

    setPrintChecklistItems(version.items);
    setPrintOrderNumber(openOrder.friendly_number.toString());
    setPrintQRData(openOrder.opaque_token ? `${window.location.origin}/o/${openOrder.opaque_token}` : '');
    setPrintAsset(null);

    navigate(`/cmp/${openOrder.id}/imprimir`);

  };

  const openAssetPdf = (asset: Asset, kind: 'tag' | 'labels' | 'sheet') => {
    window.open(`${API_URL}/v2/assets/${asset.id}/${kind}.pdf`, '_blank', 'noopener,noreferrer');
  };



  // Resetar Filtros

  const handleResetFilters = () => {

    setSearch('');

    setSectorFilter('');

    setStatusFilter('all');

    setControlFilter('all');

    setChecklistFilter('all');

    setManagerFilter('');

  };



  // Filtragem local dos Ativos

  const filteredAssets = assets.filter(asset => {

    // Tipo (Aba Ativa)

    if (!complementaryInventoryMode && asset.type !== activeTab) return false;



    // Busca (Descrição, Patrimônio, Fabricante, Modelo)

    if (search.trim()) {

      const q = search.toLowerCase();

      const match = asset.description.toLowerCase().includes(q) ||

                    asset.patrimonio.toLowerCase().includes(q) ||

                    (asset.manufacturer && asset.manufacturer.toLowerCase().includes(q)) ||

                    (asset.model && asset.model.toLowerCase().includes(q));

      if (!match) return false;

    }



    // Setor

    if (sectorFilter && asset.sector_id !== sectorFilter) return false;



    // Status

    if (statusFilter !== 'all') {

      if (statusFilter === 'active' && asset.status !== 'active') return false;

      if (statusFilter === 'inactive' && asset.status !== 'inactive') return false;

      if (statusFilter === 'operable' && (asset.status !== 'active' || !asset.is_operable)) return false;

      if (statusFilter === 'stopped' && (asset.status !== 'active' || asset.is_operable)) return false;

    }



    // Plano e Controle (Cruza com a tabela de planos)

    const assetPlan = plans.find(p => p.asset_id === asset.id && p.is_active);



    if (controlFilter !== 'all') {

      if (!assetPlan && controlFilter !== 'none') return false;

      if (controlFilter === 'none' && assetPlan) return false;

      if (controlFilter === 'fixed' && assetPlan?.calculation_basis !== 'fixed_calendar') return false;

      if (controlFilter === 'floating_days' && assetPlan?.calculation_basis !== 'floating_days') return false;

      if (controlFilter === 'floating_months' && assetPlan?.calculation_basis !== 'floating_months') return false;

      if (controlFilter === 'meter' && assetPlan?.calculation_basis !== 'meter_hours') return false;

    }



    // Checklist vinculado

    if (checklistFilter !== 'all') {

      if (checklistFilter === 'with' && (!assetPlan || !assetPlan.checklist_template_version_id)) return false;

      if (checklistFilter === 'without' && assetPlan && assetPlan.checklist_template_version_id) return false;

    }



    // Responsável (Quem confirmou o plano)

    if (managerFilter && assetPlan?.recurrence_confirmed_by !== managerFilter) return false;



    return true;

  });



  const activeAssetDocs = assetDocs.filter(doc => doc.status !== 'archived');
  const archivedAssetDocs = assetDocs.filter(doc => doc.status === 'archived');

  // Lista de Operadores únicos que confirmaram planos para filtros

  const planManagers = Array.from(new Set(plans.map(p => p.recurrence_confirmed_by).filter(Boolean))) as string[];



  // Setores mapeados para SearchCombobox

  const sectorOptions = [

    { value: '', label: 'Todos os setores' },

    ...sectors.map(s => ({ value: s.id, label: s.name }))
  ];

  const visibleAssets = filteredAssets;

  return (

    <div>

      {/* Estilos específicos para Impressão */}

      <style>{`

        @media print {

          body * {

            visibility: hidden;

            background: none !important;

          }

          .print-container, .print-container * {

            visibility: visible;

          }

          .print-container {

            position: absolute;

            left: 0;

            top: 0;

            width: 100%;

            height: 100%;

            padding: 20px;

            box-sizing: border-box;

            background: white !important;

            color: black !important;

            font-family: 'Inter', sans-serif;

          }

          table, th, td {

            border: 1px solid black !important;

          }

        }



        /* Drawer Styling */

        .drawer-overlay {

          position: fixed;

          top: 0;

          left: 0;

          right: 0;

          bottom: 0;

          background: rgba(0,0,0,0.4);

          z-index: 1000;

          display: flex;

          justify-content: flex-end;

          animation: fadeIn 0.2s ease-out;

        }

        .drawer-content {

          width: 600px;

          height: 100%;

          background: var(--bg-card);

          box-shadow: -4px 0 24px rgba(0,0,0,0.15);

          overflow-y: auto;

          display: flex;

          flex-direction: column;

          animation: slideInRight 0.3s ease-out;

        }

        @keyframes fadeIn {

          from { opacity: 0; }

          to { opacity: 1; }

        }

        @keyframes slideInRight {

          from { transform: translateX(100%); }

          to { transform: translateX(0); }

        }



        .drawer-tab {

          padding: 10px 16px;

          font-weight: 600;

          font-size: 13px;

          border: none;

          background: none;

          color: var(--text-muted);

          border-bottom: 2px solid transparent;

          cursor: pointer;

        }

        .drawer-tab.active {

          color: var(--primary);

          border-bottom: 2px solid var(--primary);

        }

      `}</style>



      {/* --- LAYOUT DA FOLHA FÍSICA PARA IMPRESSÃO --- */}

      {printAsset && (

        <div className="print-container" style={{ display: 'none' }}>

          <style>{`

            .print-container {

              display: block !important;

              position: relative;

              font-family: sans-serif;

              color: #000;

              margin: 0;

              padding: 40px;

              height: 297mm;

              width: 210mm;

              box-sizing: border-box;

            }

            .corner-marker {

              position: absolute;

              width: 20px;

              height: 20px;

              border: 3px solid black;

            }

            .top-left { top: 20px; left: 20px; border-right: none; border-bottom: none; }

            .top-right { top: 20px; right: 20px; border-left: none; border-bottom: none; }

            .bottom-left { bottom: 20px; left: 20px; border-right: none; border-top: none; }

            .bottom-right { bottom: 20px; right: 20px; border-left: none; border-top: none; }



            .header-table {

              width: 100%;

              border-collapse: collapse;

              margin-bottom: 20px;

            }

            .header-table td {

              border: 1px solid #000;

              padding: 8px;

              vertical-align: middle;

            }

            .items-table {

              width: 100%;

              border-collapse: collapse;

              margin-bottom: 25px;

            }

            .items-table th, .items-table td {

              border: 1px solid #000;

              padding: 6px 8px;

              text-align: left;

              font-size: 11px;

            }

            .items-table th {

              background-color: #f2f2f2;

              font-weight: bold;

            }

            .checkbox-square {

              width: 18px;

              height: 18px;

              border: 1px solid #000;

              margin: 0 auto;

            }

          `}</style>



          <div className="corner-marker top-left"></div>

          <div className="corner-marker top-right"></div>

          <div className="corner-marker bottom-left"></div>

          <div className="corner-marker bottom-right"></div>



          <table className="header-table">

            <tbody>

              <tr>

                <td style={{ width: '120px', textAlign: 'center' }}>

                  <div style={{ fontSize: '13px', fontWeight: 'bold' }}>MANUTENÇÃO</div>

                  <div style={{ fontSize: '9px', color: '#666', marginTop: '2px' }}>EM CAMPO</div>

                </td>

                <td style={{ textAlign: 'center' }}>

                  <h2 style={{ margin: 0, fontSize: '15px', fontWeight: 'bold', letterSpacing: '0.5px' }}>

                    CMP - CONTROLE DE MANUTENÇÃO PREVENTIVA

                  </h2>

                </td>

                <td style={{ width: '120px', textAlign: 'center', padding: '4px' }}>

                  {qrCodeUrl && (

                    <img

                      src={qrCodeUrl}

                      alt="QR Code"

                      style={{ width: '70px', height: '70px', display: 'block', margin: '0 auto' }}

                    />

                  )}

                </td>

              </tr>

            </tbody>

          </table>



          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '11px', marginBottom: '20px', border: '1px solid #000', padding: '10px', borderRadius: '4px' }}>

            <div><strong>EQUIPAMENTO/MÁQUINA:</strong> {printAsset.description}</div>

            <div><strong>CÓDIGO (PATRIMÔNIO):</strong> {printAsset.patrimonio}</div>

            <div><strong>Nº DA ORDEM (OM):</strong> {printOrderNumber}</div>

            <div><strong>SETOR:</strong> {printAsset.sector?.name || 'Geral'}</div>

            <div><strong>RESPONSÁVEL:</strong> ___________________________</div>

            <div><strong>DATA DE EXECUÇÃO:</strong> ____/____/________</div>

          </div>



          <table className="items-table">

            <thead>

              <tr>

                <th style={{ width: '40px', textAlign: 'center' }}>Item</th>

                <th>Serviços / Verificações a Realizar</th>

                <th style={{ width: '35px', textAlign: 'center' }}>OK</th>

                <th style={{ width: '35px', textAlign: 'center' }}>DEF</th>

                <th style={{ width: '35px', textAlign: 'center' }}>N/A</th>

                <th style={{ width: '180px' }}>Observações / Materiais Utilizados</th>

              </tr>

            </thead>

            <tbody>

              {printChecklistItems.map((item) => (

                <tr key={item.id}>

                  <td style={{ textAlign: 'center', fontWeight: 'bold' }}>{item.item_number}</td>

                  <td>{item.description}</td>

                  <td><div className="checkbox-square"></div></td>

                  <td><div className="checkbox-square"></div></td>

                  <td><div className="checkbox-square"></div></td>

                  <td style={{ height: '24px' }}></td>

                </tr>

              ))}

            </tbody>

          </table>



          <div style={{ marginTop: '30px', fontSize: '11px' }}>

            <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>CONDIÇÃO OPERACIONAL DO ATIVO APÓS PREVENTIVA:</div>

            <div style={{ display: 'flex', gap: '20px', marginBottom: '30px' }}>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                <div className="checkbox-square" style={{ display: 'inline-block', verticalAlign: 'middle' }}></div>

                <span>APTA (LIBERADA PARA OPERAÇÃO NORMAL)</span>

              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                <div className="checkbox-square" style={{ display: 'inline-block', verticalAlign: 'middle' }}></div>

                <span>APTA COM ATENÇÃO (DEFEITOS NÃO IMPEDÍTIVOS)</span>

              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                <div className="checkbox-square" style={{ display: 'inline-block', verticalAlign: 'middle' }}></div>

                <span>PARADA (BLOQUEIO FÍSICO DA MÁQUINA)</span>

              </div>

            </div>



            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginTop: '40px', textAlign: 'center' }}>

              <div>

                <div style={{ borderBottom: '1px solid black', width: '200px', margin: '0 auto 5px auto' }}></div>

                Assinatura do Responsável

              </div>

              <div>

                <div style={{ borderBottom: '1px solid black', width: '200px', margin: '0 auto 5px auto' }}></div>

                Assinatura da Supervisão

              </div>

            </div>



            <div style={{ marginTop: '40px', fontSize: '9px', color: '#666', textAlign: 'center', borderTop: '1px solid #ccc', paddingTop: '10px' }}>

              Manutenção em Campo Industrial - Documento Controlado - Código CMP-{printAsset.type === 'machine' ? 'MAC' : 'EQP'}

            </div>

          </div>

        </div>

      )}



      {/* Interface Web Normal */}

      <div className="web-content-view">

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>

          <div>

            <h1>{inactiveMode ? 'Itens fora de uso' : complementaryInventoryMode ? 'Ferramentas e componentes' : 'Máquinas e Equipamentos'}</h1>

            <p className="subtitle" style={{ margin: 0 }}>
              {inactiveMode
                ? 'Consulta dos itens que não estão em operação no momento.'
                : complementaryInventoryMode
                  ? 'Consulta de ferramentas, instrumentos e componentes. Eles continuam com histórico, mas não entram na rotina diária de máquinas.'
                  : 'Encontre o equipamento, consulte o histórico e faça a manutenção sem termos técnicos desnecessários.'}
            </p>

          </div>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <button className={inactiveMode ? 'btn btn-secondary' : 'btn btn-primary'} type="button" onClick={() => navigate('/ativos')}>
              Ativos
            </button>
            <button className={inactiveMode ? 'btn btn-primary' : 'btn btn-secondary'} type="button" onClick={() => navigate('/inativos')}>
              Inativos
            </button>
            {!inactiveMode && (
          <button className="btn btn-primary" onClick={() => setShowAddModal(true)} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>

            <Plus size={18} /> Novo Ativo

          </button>
            )}
          </div>

        </div>



        {error && (

          <div style={{ backgroundColor: 'var(--danger-light)', color: 'var(--danger)', padding: '16px', borderRadius: '8px', marginBottom: '24px', fontWeight: '500' }}>

            {error}

          </div>

        )}



        {/* ── Tabs "Máquinas" e "Equipamentos" ── */}

        {!complementaryInventoryMode && <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border)', marginBottom: '20px' }}>

          <button

            className={`tab-btn`}

            onClick={() => { setActiveTab('machine'); handleResetFilters(); }}

            style={{

              padding: '12px 24px',

              fontWeight: '600',

              fontSize: '15px',

              border: 'none',

              background: 'none',

              borderBottom: activeTab === 'machine' ? '3px solid var(--primary)' : '3px solid transparent',

              color: activeTab === 'machine' ? 'var(--primary)' : 'var(--text-muted)',

              cursor: 'pointer',

              display: 'flex',

              alignItems: 'center',

              gap: '8px'

            }}

          >

            <Cpu size={16} /> Máquinas

          </button>

          <button

            className={`tab-btn`}

            onClick={() => { setActiveTab('equipment'); handleResetFilters(); }}

            style={{

              padding: '12px 24px',

              fontWeight: '600',

              fontSize: '15px',

              border: 'none',

              background: 'none',

              borderBottom: activeTab === 'equipment' ? '3px solid var(--primary)' : '3px solid transparent',

              color: activeTab === 'equipment' ? 'var(--primary)' : 'var(--text-muted)',

              cursor: 'pointer',

              display: 'flex',

              alignItems: 'center',

              gap: '8px'

            }}

          >

            <Activity size={16} /> Equipamentos

          </button>

        </div>}



        {/* Barra de Filtros Avançados */}

        <div className="card" style={{ padding: '20px', marginBottom: '24px' }}>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', alignItems: 'end' }}>



            {/* Busca livre */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                <Search size={14} /> Busca Livre

              </label>

              <input

                type="text"

                className="form-control"

                placeholder="Nome, código, fabricante..."

                value={search}

                onChange={e => setSearch(e.target.value)}

              />

            </div>



            {/* Setor com SearchCombobox */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <SearchCombobox

                label="Setor"

                options={sectorOptions}

                value={sectorFilter}

                onChange={setSectorFilter}

                placeholder="Selecione o setor"

              />

            </div>



            {/* Status do ativo */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <label className="form-label">Status / Operabilidade</label>

              <select className="form-control" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>

                <option value="all">Todos os Status</option>

                {!inactiveMode ? (
                  <>
                    <option value="active">Ativo no Sistema</option>
                    <option value="operable">Apto (Operando)</option>
                    <option value="stopped">Parado (Defeito)</option>
                  </>
                ) : (
                  <option value="inactive">Inativo</option>
                )}

              </select>

            </div>



            {/* Tipo de controle */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <label className="form-label">Controle de Manutenção</label>

              <select className="form-control" value={controlFilter} onChange={e => setControlFilter(e.target.value)}>

                <option value="all">Todos os Controles</option>

                <option value="fixed">Calendário Fixo</option>

                <option value="floating_days">Calendário Flutuante (Dias)</option>

                <option value="floating_months">Calendário Flutuante (Meses)</option>

                <option value="none">Sem Plano Ativo</option>

              </select>

            </div>



            {/* Checklist */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <label className="form-label">Checklists (CMP)</label>

              <select className="form-control" value={checklistFilter} onChange={e => setChecklistFilter(e.target.value)}>

                <option value="all">Todos</option>

                <option value="with">Com Checklist Vinculado</option>

                <option value="without">Sem Checklist Vinculado</option>

              </select>

            </div>



            {/* Confirmação/Responsável */}

            <div className="form-group" style={{ marginBottom: 0 }}>

              <label className="form-label">Responsável pelo Plano</label>

              <select className="form-control" value={managerFilter} onChange={e => setManagerFilter(e.target.value)}>

                <option value="">Todos os Responsáveis</option>

                {planManagers.map(mgr => (

                  <option key={mgr} value={mgr}>{mgr}</option>

                ))}

              </select>

            </div>



            {/* Botão de Limpar */}

            <div style={{ display: 'flex', gap: '8px' }}>

              <button className="btn btn-secondary" onClick={handleResetFilters} style={{ width: '100%', height: '42px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                Limpar Filtros

              </button>

            </div>

          </div>

        </div>



        {/* Estatísticas rápidas da aba */}

        <div style={{ display: 'flex', gap: '16px', marginBottom: '20px', fontSize: '13px', color: 'var(--text-muted)', fontWeight: '500' }}>

          <span>Exibindo <strong>{filteredAssets.length}</strong> nesta página de {assetTotal} {complementaryInventoryMode ? 'itens de inventário' : activeTab === 'machine' ? 'máquinas' : 'equipamentos'}</span>

          <span>•</span>

          <span>{assets.filter(a => (complementaryInventoryMode || a.type === activeTab) && !a.is_operable).length} parados</span>

          <span>•</span>

          <span>{assets.filter(a => (complementaryInventoryMode || a.type === activeTab) && !plans.some(p => p.asset_id === a.id && p.is_active)).length} sem plano preventivo</span>

        </div>



        {/* Grid de Ativos */}

        {loading ? (

          <p>Carregando inventário de ativos...</p>

        ) : (

          <div>

            {filteredAssets.length === 0 ? (

              <div className="card" style={{ textAlign: 'center', padding: '60px', color: 'var(--text-muted)' }}>

                Nenhum ativo corresponde aos filtros selecionados.

              </div>

            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
                {visibleAssets.map(asset => {

                  const hasPlan = plans.some(p => p.asset_id === asset.id && p.is_active);

                  const assetDisplayStatus = asset.status === 'inactive'
                    ? 'inactive'
                    : (!asset.is_operable ? 'stopped' : 'active');

                  const isStopped = assetDisplayStatus === 'stopped';



                  return (

                    <div

                      key={asset.id}

                      className="card"

                      onClick={() => handleSelectAsset(asset)}

                      style={{

                        display: 'flex',

                        flexDirection: 'column',

                        gap: '16px',

                        position: 'relative',

                        cursor: 'pointer',

                        borderLeft: assetDisplayStatus === 'inactive'
                          ? '5px solid var(--text-muted)'
                          : (isStopped ? '5px solid var(--danger)' : '1px solid var(--border)'),

                        transition: 'transform 0.2s, box-shadow 0.2s'

                      }}

                    >

                      {/* Badges de Estado */}

                      <div style={{ position: 'absolute', top: '16px', right: '16px', display: 'flex', gap: '6px' }}>

                        {assetDisplayStatus === 'inactive' ? (

                          <StatusBadge status="inactive" size="sm" />

                        ) : isStopped ? (

                          <StatusBadge status="stopped" size="sm" pulseDot />

                        ) : (

                          <StatusBadge status="active" size="sm" />

                        )}

                      </div>


                      <div style={{ height: '130px', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border)', backgroundColor: 'var(--bg-app)', display: 'grid', placeItems: 'center' }}>
                        {asset.thumbnail_url ? (
                          <img
                            src={`${API_URL}${asset.thumbnail_url}`}
                            alt={asset.description}
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                            loading="lazy"
                          />
                        ) : (
                          <div style={{ color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px', fontSize: '12px' }}>
                            <Camera size={24} />
                            Sem foto principal
                          </div>
                        )}
                      </div>



                      {/* Header do Card */}

                      <div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '11px', fontWeight: '700', textTransform: 'uppercase' }}>

                          {asset.type === 'machine' ? <Cpu size={14} /> : <Activity size={14} />}

                          {asset.type === 'machine' ? 'Máquina' : 'Equipamento'}

                        </div>



                        <h3 style={{ fontSize: '18px', fontWeight: '700', marginTop: '6px', paddingRight: '75px', color: 'var(--text-main)' }}>

                          {asset.description}

                        </h3>



                        <div style={{ color: 'var(--primary)', fontWeight: '700', fontSize: '13px', marginTop: '4px', fontFamily: 'monospace' }}>

                          IDENTIFICAÇÃO: {asset.controlled_code || asset.patrimonio}

                        </div>
                        {asset.legacy_patrimonio && asset.legacy_patrimonio !== asset.controlled_code && (
                          <div style={{ color: 'var(--muted)', fontSize: '11px', marginTop: '2px' }}>
                            Código original: {asset.legacy_patrimonio}
                          </div>
                        )}

                      </div>



                      {/* Informações Rápidas */}

                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '12px', display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '13px' }}>

                        <div><strong>Fabricante/Modelo:</strong> {asset.manufacturer || 'Não informado'} {asset.model ? `/ ${asset.model}` : ''}</div>

                        <div><strong>Setor:</strong> {asset.sector?.name || 'Não informado'}</div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                          <strong>Rotina preventiva:</strong>

                          {hasPlan ? (

                            <span style={{ color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '3px', fontWeight: '600' }}><FileCheck size={14} /> Configurado</span>

                          ) : (

                            <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '3px' }}><HelpCircle size={14} /> Não cadastrado</span>

                          )}

                        </div>

                      </div>



                      {/* Botões de Ação do Card */}

                      <div

                        style={{ marginTop: 'auto', display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '8px', paddingTop: '10px' }}

                        onClick={e => e.stopPropagation()} // impede abrir o drawer ao clicar nos botões

                      >

                        <button

                          className="btn btn-secondary"

                          style={{ fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px' }}

                          onClick={() => handlePrintSheet(asset)}

                        >

                          <Printer size={14} /> Imprimir checklist

                        </button>

                        <button
                          className="btn btn-secondary"
                          style={{ fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px' }}
                          onClick={() => openAssetPdf(asset, 'tag')}
                        >
                          <FileText size={14} /> Etiqueta QR
                        </button>



                        <button

                          className="btn btn-secondary"

                          style={{ fontSize: '12px', padding: '8px' }}

                          onClick={() => handleSelectAsset(asset)}

                        >

                          Detalhes <ChevronRight size={14} />

                        </button>

                      </div>

                    </div>

                  );

                })}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginTop: '24px', marginBottom: '24px', flexWrap: 'wrap' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                  Página {assetPage} de {assetTotalPages} | {assetTotal} ativo(s) encontrados
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <select className="form-control" value={assetPageSize} onChange={e => { setAssetPageSize(Number(e.target.value)); setAssetPage(1); }} style={{ width: '90px' }}>
                    <option value={10}>10</option>
                    <option value={20}>20</option>
                    <option value={50}>50</option>
                  </select>
                  <button className="btn btn-secondary" disabled={assetPage <= 1} onClick={() => setAssetPage(prev => Math.max(1, prev - 1))}>
                    Anterior
                  </button>
                  <button className="btn btn-secondary" disabled={assetPage >= assetTotalPages} onClick={() => setAssetPage(prev => Math.min(assetTotalPages, prev + 1))}>
                    Próxima
                  </button>
                </div>
              </div>
            </>
          )}

          </div>

        )}



        {/* ── DRAWER DE DETALHES DO ATIVO (DIREITA) ── */}

        {selectedAsset && (

          <div className="drawer-overlay" onClick={handleCloseDrawer}>

            <div className="drawer-content" onClick={e => e.stopPropagation()}>



              {/* Header do Drawer */}

              <div style={{ padding: '24px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg-app)' }}>

                <div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>

                    <StatusBadge status={selectedAsset.status === 'inactive' ? 'inactive' : (selectedAsset.is_operable ? 'active' : 'stopped')} />

                    <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-muted)', fontFamily: 'monospace' }}>

                      ID: {selectedAsset.id.substring(0, 8)}...

                    </span>

                  </div>

                  <h2 style={{ fontSize: '20px', fontWeight: '800', marginTop: '6px', color: 'var(--text-main)' }}>

                    {selectedAsset.description}

                  </h2>

                  <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--primary)', fontFamily: 'monospace' }}>

                    IDENTIFICAÇÃO: {selectedAsset.controlled_code || selectedAsset.patrimonio}

                  </div>
                  {selectedAsset.legacy_patrimonio && selectedAsset.legacy_patrimonio !== selectedAsset.controlled_code && (
                    <div style={{ color: 'var(--muted)', fontSize: '12px', marginTop: '2px' }}>
                      Código original: {selectedAsset.legacy_patrimonio}
                    </div>
                  )}

                </div>

                <button

                  onClick={handleCloseDrawer}

                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: '6px' }}

                >

                  <X size={24} />

                </button>

              </div>



              {/* Tabs de navegação interna do Drawer */}

              <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', backgroundColor: 'var(--bg-app)', padding: '0 16px' }}>

                <button className={`drawer-tab ${detailTab === 'info' ? 'active' : ''}`} onClick={() => setDetailTab('info')}>

                  Geral

                </button>

                <button className={`drawer-tab ${detailTab === 'plan' ? 'active' : ''}`} onClick={() => setDetailTab('plan')}>

                  Rotina preventiva

                </button>

                <button className={`drawer-tab ${detailTab === 'dossier' ? 'active' : ''}`} onClick={() => setDetailTab('dossier')}>

                  Prontuário

                </button>

                <button className={`drawer-tab ${detailTab === 'docs' ? 'active' : ''}`} onClick={() => setDetailTab('docs')}>

                  Documentos

                </button>

                <button className={`drawer-tab ${detailTab === 'history' ? 'active' : ''}`} onClick={() => setDetailTab('history')}>

                  Histórico

                </button>

              </div>



              {/* Conteúdo das Tabs */}

              <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>



                {/* ── TAB GERAL ── */}

                {detailTab === 'info' && (

                  <div>

                    {!isEditingAsset ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {/* Imagem Principal do Ativo */}
                        {(() => {
                          const primaryPhoto = activeAssetDocs.find(d => d.category === 'photo' && d.is_primary_photo) || activeAssetDocs.find(d => d.category === 'photo');
                          if (primaryPhoto) {
                            return (
                              <div
                                style={{
                                  position: 'relative',
                                  width: '100%',
                                  height: '200px',
                                  borderRadius: '8px',
                                  overflow: 'hidden',
                                  border: '1px solid var(--border)',
                                  cursor: 'pointer',
                                  marginBottom: '8px'
                                }}
                                onClick={() => {
                                  const photoList = activeAssetDocs.filter(d => d.category === 'photo');
                                  const realIndex = photoList.findIndex(ph => ph.id === primaryPhoto.id);
                                  setCurrentImageIndex(realIndex >= 0 ? realIndex : 0);
                                  setGalleryOpen(true);
                                }}
                              >
                                <img
                                  src={`${API_URL}${primaryPhoto.content_url}`}
                                  alt={selectedAsset.description}
                                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                />
                                <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '8px 12px', background: 'linear-gradient(to top, rgba(0,0,0,0.7), transparent)', color: '#fff', fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Camera size={14} /> Clique para ampliar ({activeAssetDocs.filter(d => d.category === 'photo').length} fotos)</span>
                                  {primaryPhoto.is_primary_photo && <span style={{ backgroundColor: 'var(--primary)', color: '#fff', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 'bold' }}>Principal</span>}
                                </div>
                              </div>
                            );
                          }
                          return null;
                        })()}

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

                          <div>

                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Fabricante</span>

                            <div style={{ fontWeight: '600', fontSize: '14px' }}>{selectedAsset.manufacturer || 'Não cadastrado'}</div>

                          </div>

                          <div>

                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Modelo</span>

                            <div style={{ fontWeight: '600', fontSize: '14px' }}>{selectedAsset.model || 'Não cadastrado'}</div>

                          </div>

                          <div>

                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nº de Série</span>

                            <div style={{ fontWeight: '600', fontSize: '14px' }}>{selectedAsset.serial_number || 'Não cadastrado'}</div>

                          </div>

                          <div>

                            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Setor</span>

                            <div style={{ fontWeight: '600', fontSize: '14px' }}>{selectedAsset.sector?.name || 'Não cadastrado'}</div>

                          </div>

                        </div>



                        <div>

                          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Notas Técnicas</span>

                          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: '8px', fontSize: '13px', marginTop: '4px' }}>

                            {selectedAsset.notes || 'Sem observações cadastradas.'}

                          </div>

                        </div>



                        {/* Botões contextuais rápidos */}

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '20px' }}>

                          <div style={{ display: 'flex', gap: '10px' }}>

                            <button className="btn btn-secondary" onClick={() => setIsEditingAsset(true)} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                              <Edit size={16} /> Editar Informações

                            </button>

                            {!selectedAsset.is_operable ? (

                              <button

                                className="btn btn-primary"

                                style={{ flex: 1, backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }}

                                onClick={() => setReleasingAssetId(selectedAsset.id)}

                              >

                                <Hammer size={16} /> Liberar Operação

                              </button>

                            ) : (

                              <button

                                className="btn btn-secondary"

                                style={{ flex: 1, color: 'var(--danger)' }}

                                onClick={() => {

                                  // Abre o modal de registrar problema de Hoje.tsx

                                  toast.info('Info', 'Para registrar uma ocorrência de defeito, use o botão "Registrar Ocorrência" ou a aba "Hoje".');

                                }}

                              >

                                <AlertTriangle size={16} /> Registrar Parada

                              </button>

                            )}

                          </div>

                          <button className="btn btn-primary" onClick={() => handlePrintSheet(selectedAsset)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                            <Printer size={16} /> Imprimir Folha de Preventiva (CMP)

                          </button>

                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                            <button className="btn btn-secondary" onClick={() => openAssetPdf(selectedAsset, 'tag')} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                              <FileText size={16} /> TAG PDF
                            </button>
                            <button className="btn btn-secondary" onClick={() => openAssetPdf(selectedAsset, 'labels')} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                              <FileText size={16} /> Etiquetas
                            </button>
                          </div>

                        </div>

                      </div>

                    ) : (

                      // Formulário de Edição

                      <form onSubmit={handleUpdateAsset} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                        <div className="form-group">

                          <label className="form-label">Descrição</label>

                          <input type="text" className="form-control" value={editAssetForm.description} onChange={e => setEditAssetForm({ ...editAssetForm, description: e.target.value })} required />

                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

                          <div className="form-group">

                            <label className="form-label">Patrimônio</label>

                            <input type="text" className="form-control" value={editAssetForm.patrimonio} onChange={e => setEditAssetForm({ ...editAssetForm, patrimonio: e.target.value })} required />

                          </div>

                          <div className="form-group">

                            <label className="form-label">Fabricante</label>

                            <input type="text" className="form-control" value={editAssetForm.manufacturer} onChange={e => setEditAssetForm({ ...editAssetForm, manufacturer: e.target.value })} />

                          </div>

                          <div className="form-group">

                            <label className="form-label">Modelo</label>

                            <input type="text" className="form-control" value={editAssetForm.model} onChange={e => setEditAssetForm({ ...editAssetForm, model: e.target.value })} />

                          </div>

                          <div className="form-group">

                            <label className="form-label">Nº Série</label>

                            <input type="text" className="form-control" value={editAssetForm.serial_number} onChange={e => setEditAssetForm({ ...editAssetForm, serial_number: e.target.value })} />

                          </div>

                        </div>

                        <div className="form-group">

                          <label className="form-label">Setor</label>

                          <select className="form-control" value={editAssetForm.sector_id} onChange={e => setEditAssetForm({ ...editAssetForm, sector_id: e.target.value })} required>

                            <option value="">-- Escolha o Setor --</option>

                            {sectors.map(s => (

                              <option key={s.id} value={s.id}>{s.name}</option>

                            ))}

                          </select>

                        </div>

                        <div className="form-group">

                          <label className="form-label">Notas</label>

                          <textarea className="form-control" value={editAssetForm.notes} onChange={e => setEditAssetForm({ ...editAssetForm, notes: e.target.value })} rows={3} />

                        </div>



                        <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>

                          <button type="submit" className="btn btn-primary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                            <Save size={16} /> Salvar Edições

                          </button>

                          <button type="button" className="btn btn-secondary" onClick={() => setIsEditingAsset(false)} style={{ flex: 1 }}>

                            Cancelar

                          </button>

                        </div>

                      </form>

                    )}

                  </div>

                )}



                {/* ── TAB PLANO PREVENTIVO ── */}

                {detailTab === 'plan' && (

                  <div>

                    {loadingDetails ? (

                      <p>Carregando planos...</p>

                    ) : (

                      <div>

                        {assetPlans.length > 0 && !isConfiguringPlan ? (

                          // Exibe plano ativo

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                            {assetPlans.map(plan => (

                              <div key={plan.id} className="card" style={{ padding: '16px', backgroundColor: 'var(--bg-app)' }}>

                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '12px' }}>

                                  <h4 style={{ fontSize: '16px', fontWeight: '700', margin: 0 }}>{plan.name}</h4>

                                  <StatusBadge status={plan.recurrence_status} />

                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '13px', marginBottom: '12px' }}>

                                  <div><strong>Controle/Base:</strong> {

                                    plan.calculation_basis === 'fixed_calendar' ? 'Calendário Fixo' :

                                    plan.calculation_basis === 'floating_days' ? 'Flutuante (Dias)' :

                                    plan.calculation_basis === 'floating_months' ? 'Flutuante (Meses)' :

                                    plan.calculation_basis === 'meter_hours' ? 'Medidor' : plan.calculation_basis

                                  }</div>

                                  <div><strong>Periodicidade:</strong> {plan.periodicity}</div>

                                  {plan.next_due_date && <div><strong>Próximo Vencimento:</strong> {new Date(plan.next_due_date).toLocaleDateString()}</div>}

                                  <div><strong>Duração Estimada:</strong> {plan.estimated_duration_mins} min</div>

                                  <div><strong>Responsável:</strong> {plan.recurrence_confirmed_by || 'Não definido'}</div>

                                  <div><strong>Checklist Vinculado:</strong> {

                                    checklists.find(t => t.versions.some(v => v.id === plan.checklist_template_version_id))?.name || 'Não vinculado'

                                  }</div>

                                </div>

                                {plan.safety_instructions && (

                                  <div style={{ fontSize: '12px', borderTop: '1px solid var(--border)', paddingTop: '8px', color: 'var(--text-muted)' }}>

                                    <strong>Instruções de Segurança:</strong> {plan.safety_instructions}

                                  </div>

                                )}

                              </div>

                            ))}



                            <button

                              className="btn btn-secondary"

                              onClick={() => {

                                const currentPlan = assetPlans[0];

                                setPlanForm(currentPlan);

                                setIsConfiguringPlan(true);

                              }}

                              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}

                            >

                              <Edit size={16} /> Alterar Configurações do Plano

                            </button>

                          </div>

                        ) : isConfiguringPlan ? (

                          // Formulário de Configuração de Plano

                          <form onSubmit={handleConfigurePlan} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                            <h4 style={{ fontSize: '16px', fontWeight: '700' }}>Configurar Plano de Manutenção</h4>

                            <div className="form-group">

                              <label className="form-label">Nome do Plano</label>

                              <input type="text" className="form-control" value={planForm.name} onChange={e => setPlanForm({ ...planForm, name: e.target.value })} placeholder="Ex: Preventiva Trimestral Schulz" />

                            </div>



                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

                              <div className="form-group">

                                <label className="form-label">Periodicidade</label>

                                <select className="form-control" value={planForm.periodicity} onChange={e => setPlanForm({ ...planForm, periodicity: e.target.value })}>

                                  <option value="weekly">Semanal</option>

                                  <option value="biweekly">Quinzenal</option>

                                  <option value="monthly">Mensal</option>

                                  <option value="bimonthly">Bimestral</option>

                                  <option value="trimonthly">Trimestral</option>

                                  <option value="semiannual">Semestral</option>

                                  <option value="annual">Anual</option>

                                  <option value="custom">Personalizada</option>

                                </select>

                              </div>



                              <div className="form-group">

                                <label className="form-label">Base de Cálculo</label>

                                <select className="form-control" value={planForm.calculation_basis} onChange={e => setPlanForm({ ...planForm, calculation_basis: e.target.value })}>

                                  <option value="fixed_calendar">Calendário Fixo (competência)</option>

                                  <option value="floating_days">Flutuante (dias desde a última)</option>

                                  <option value="floating_months">Flutuante (meses desde a última)</option>

                                </select>

                              </div>

                            </div>



                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

                              <div className="form-group">

                                <label className="form-label">Duração Estimada (minutos)</label>

                                <input type="number" className="form-control" value={planForm.estimated_duration_mins} onChange={e => setPlanForm({ ...planForm, estimated_duration_mins: parseInt(e.target.value) || 60 })} required />

                              </div>



                              {planForm.calculation_basis === 'fixed_calendar' && (

                                <div className="form-group" style={{ display: 'flex', alignItems: 'center', marginTop: '30px' }}>

                                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px' }}>

                                    <input

                                      type="checkbox"

                                      checked={planForm.is_monthly_competency}

                                      onChange={e => setPlanForm({ ...planForm, is_monthly_competency: e.target.checked })}

                                    />

                                    Competência Mensal Fechada

                                  </label>

                                </div>

                              )}

                            </div>



                            <div className="form-group">

                              <label className="form-label">Checklist Modelo (CMP)</label>

                              <select className="form-control" value={planForm.checklist_template_version_id || ''} onChange={e => setPlanForm({ ...planForm, checklist_template_version_id: e.target.value })} required>

                                <option value="">-- Vincule um Modelo --</option>

                                {checklists.map(tmpl => (

                                  <optgroup key={tmpl.id} label={tmpl.name}>

                                    {tmpl.versions.map(v => (

                                      <option key={v.id} value={v.id}>Versão {v.version} ({v.items.length} itens)</option>

                                    ))}

                                  </optgroup>

                                ))}

                              </select>

                            </div>



                            <div className="form-group">

                              <label className="form-label">Instruções de Segurança</label>

                              <textarea className="form-control" value={planForm.safety_instructions || ''} onChange={e => setPlanForm({ ...planForm, safety_instructions: e.target.value })} placeholder="Ex: Desligar disjuntor principal, utilizar EPI..." rows={3} />

                            </div>



                            <div style={{ display: 'flex', gap: '12px' }}>

                              <button type="submit" className="btn btn-primary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                                <Save size={16} /> Salvar Plano

                              </button>

                              <button type="button" className="btn btn-secondary" onClick={() => setIsConfiguringPlan(false)} style={{ flex: 1 }}>

                                Cancelar

                              </button>

                            </div>

                          </form>

                        ) : (

                          // Ativo sem plano cadastrado

                          <div style={{ textAlign: 'center', padding: '40px 20px', border: '2px dashed var(--border)', borderRadius: '12px' }}>

                            <HelpCircle size={40} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />

                            <h4 style={{ fontSize: '15px', fontWeight: '700', color: 'var(--text-main)' }}>Nenhum plano ativo</h4>

                            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>Este ativo não gera planejamentos automáticos.</p>

                            <button className="btn btn-primary" onClick={() => setIsConfiguringPlan(true)}>

                              Cadastrar Plano de Manutenção

                            </button>

                          </div>

                        )}

                      </div>

                    )}

                  </div>

                )}

                {/* ── PRONTUÁRIO: tudo o que já ocorreu neste ativo ── */}
                {detailTab === 'dossier' && <AssetDossierPanel assetId={selectedAsset.id} />}



                {/* ── TAB MEDIDORES ── */}

                {detailTab === 'meters' && (

                  <div>

                    {loadingDetails ? (

                      <p>Carregando medidores...</p>

                    ) : (

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>



                        {/* Listagem de medidores */}

                        {assetMeters.length > 0 ? (

                          assetMeters.map(meter => (

                            <div key={meter.id} className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', backgroundColor: 'var(--bg-app)' }}>

                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>

                                <div>

                                  <span style={{ fontSize: '12px', textTransform: 'uppercase', fontWeight: '700', color: 'var(--text-muted)' }}>

                                    Medidor ({meter.meter_type === 'hours' ? 'Horímetro' : 'Ciclos'})

                                  </span>

                                  <div style={{ fontSize: '20px', fontWeight: '800', color: 'var(--text-main)' }}>

                                    {meter.current_reading} <span style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-muted)' }}>{meter.unit}</span>

                                  </div>

                                </div>

                                <div style={{ textAlign: 'right', fontSize: '12px' }}>

                                  <div>Próxima Preventiva: <strong>{meter.next_maintenance_at} {meter.unit}</strong></div>

                                  <div style={{ color: 'var(--text-muted)' }}>Intervalo: {meter.maintenance_interval} {meter.unit}</div>

                                </div>

                              </div>



                              {/* Formulário para atualizar valor */}

                              <div style={{ display: 'flex', gap: '8px', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>

                                <input

                                  type="number"

                                  className="form-control"

                                  style={{ height: '36px', fontSize: '13px' }}

                                  placeholder={`Nova leitura (${meter.unit})`}

                                  value={readingInputs[meter.id] || ''}

                                  onChange={e => setReadingInputs({ ...readingInputs, [meter.id]: e.target.value })}

                                />

                                <button className="btn btn-primary" style={{ height: '36px', padding: '0 12px', fontSize: '12px' }} onClick={() => handleAddReading(meter.id)}>

                                  Lançar

                                </button>

                              </div>

                            </div>

                          ))

                        ) : (

                          <div style={{ textAlign: 'center', padding: '24px', border: '1px dashed var(--border)', borderRadius: '8px', color: 'var(--text-muted)' }}>

                            Nenhum horímetro ou contador vinculado a este ativo.

                          </div>

                        )}



                        {/* Cadastro de Medidor */}

                        {!showAddMeter ? (

                          <button className="btn btn-secondary" onClick={() => setShowAddMeter(true)} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>

                            <Plus size={16} /> Novo Medidor (Horas / Ciclos)

                          </button>

                        ) : (

                          <form onSubmit={handleAddMeter} className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>

                            <h4 style={{ fontSize: '14px', fontWeight: '700', margin: 0 }}>Adicionar Medidor</h4>



                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

                              <div className="form-group">

                                <label className="form-label">Tipo</label>

                                <select className="form-control" value={newMeterForm.meter_type} onChange={e => setNewMeterForm({ ...newMeterForm, meter_type: e.target.value })}>

                                  <option value="hours">Horímetro (Horas)</option>

                                  <option value="cycles">Contador (Ciclos/Golpes)</option>

                                </select>

                              </div>

                              <div className="form-group">

                                <label className="form-label">Unidade</label>

                                <input type="text" className="form-control" value={newMeterForm.unit} onChange={e => setNewMeterForm({ ...newMeterForm, unit: e.target.value })} required />

                              </div>

                            </div>



                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

                              <div className="form-group">

                                <label className="form-label">Leitura Inicial</label>

                                <input type="number" className="form-control" value={newMeterForm.current_reading} onChange={e => setNewMeterForm({ ...newMeterForm, current_reading: parseFloat(e.target.value) || 0 })} required />

                              </div>

                              <div className="form-group">

                                <label className="form-label">Intervalo de Preventiva</label>

                                <input type="number" className="form-control" value={newMeterForm.maintenance_interval} onChange={e => setNewMeterForm({ ...newMeterForm, maintenance_interval: parseFloat(e.target.value) || 200 })} required />

                              </div>

                            </div>



                            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>

                              <button type="submit" className="btn btn-primary" style={{ flex: 1, fontSize: '13px' }}>Criar</button>

                              <button type="button" className="btn btn-secondary" style={{ flex: 1, fontSize: '13px' }} onClick={() => setShowAddMeter(false)}>Cancelar</button>

                            </div>

                          </form>

                        )}

                      </div>

                    )}

                  </div>

                )}



                {/* ── TAB DOCUMENTOS ── */}

                {detailTab === 'docs' && (
                  <div>
                    {loadingDetails ? (
                      <p>Carregando arquivos...</p>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {/* Listagem de documentos por categorias */}
                        {assetDocs.length > 0 ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            {/* Categoria: Fotos */}
                            {(() => {
                              const photos = activeAssetDocs.filter(d => d.category === 'photo');
                              if (photos.length === 0) return null;
                              return (
                                <div>
                                  <h4 style={{ fontSize: '13px', fontWeight: 'bold', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Camera size={16} /> Fotos do Ativo ({photos.length})
                                  </h4>
                                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: '8px' }}>
                                    {photos.map((p) => {
                                      const photoList = activeAssetDocs.filter(d => d.category === 'photo');
                                      const realIndex = photoList.findIndex(ph => ph.id === p.id);
                                      return (
                                        <div
                                          key={p.id}
                                          style={{ position: 'relative', width: '80px', height: '80px', borderRadius: '4px', overflow: 'hidden', border: '1px solid var(--border)', cursor: 'pointer' }}
                                          onClick={() => {
                                            setCurrentImageIndex(realIndex >= 0 ? realIndex : 0);
                                            setGalleryOpen(true);
                                          }}
                                        >
                                          <img src={`${API_URL}${p.thumbnail_url || p.content_url}`} alt={p.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                                          {p.is_primary_photo && (
                                            <div style={{ position: 'absolute', top: '2px', right: '2px', backgroundColor: 'var(--primary)', color: '#fff', borderRadius: '50%', width: '16px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '9px', fontWeight: 'bold' }}>
                                              ★
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })()}

                            {/* Categorias de Documentos */}
                            {[
                              { key: 'manual', label: 'Manuais de Instrução', icon: <FileText size={16} /> },
                              { key: 'certificate', label: 'Laudos e Certificados', icon: <Award size={16} /> },
                              { key: 'warranty', label: 'Termos de Garantia', icon: <ShieldCheck size={16} /> },
                              { key: 'receipt', label: 'Notas Fiscais e Recibos', icon: <FileSpreadsheet size={16} /> },
                              { key: 'other', label: 'Outros Documentos', icon: <File size={16} /> }
                            ].map(cat => {
                              const docs = activeAssetDocs.filter(d => d.category === cat.key || (cat.key === 'other' && (!d.category || d.category === 'outro')));
                              if (docs.length === 0) return null;
                              return (
                                <div key={cat.key}>
                                  <h4 style={{ fontSize: '13px', fontWeight: 'bold', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    {cat.icon} {cat.label} ({docs.length})
                                  </h4>
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                    {docs.map(doc => (
                                      <div key={doc.id} className="card" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border)' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                                          <FileText size={20} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                          <div style={{ minWidth: 0 }}>
                                            <a
                                              href={`${API_URL}${doc.content_url}`}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)', textDecoration: 'none' }}
                                              onMouseOver={(e) => (e.currentTarget.style.textDecoration = 'underline')}
                                              onMouseOut={(e) => (e.currentTarget.style.textDecoration = 'none')}
                                            >
                                              {doc.original_name || doc.name}
                                            </a>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                              Tamanho: {Math.round(doc.file_size / 1024)} KB | Hash: {doc.file_hash.substring(0, 8)}...
                                            </div>
                                          </div>
                                        </div>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                          <a
                                            href={`${API_URL}${doc.download_url}`}
                                            className="btn btn-secondary"
                                            style={{ padding: '4px 8px', fontSize: '11px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                                          >
                                            Download
                                          </a>
                                          <button
                                            onClick={async () => {
                                              if (!confirm('Deseja realmente arquivar este documento?')) return;
                                              try {
                                                await axios.post(`${API_URL}/v2/files/${doc.id}/archive`, null, {
                                                  params: {
                                                    operator_name: sessionStorage.getItem('mec_operator_name') || 'Operador'
                                                  }
                                                });
                                                toast.success('Sucesso', 'Documento arquivado com sucesso!');
                                                if (selectedAsset) {
                                                  fetchAssetDetails(selectedAsset.id);
                                                }
                                              } catch (err) {
                                                console.error(err);
                                                toast.error('Erro', 'Não foi possível arquivar o documento.');
                                              }
                                            }}
                                            className="btn btn-secondary"
                                            style={{ padding: '4px 8px', fontSize: '11px', color: 'var(--danger)', borderColor: 'var(--danger)' }}
                                          >
                                            Arquivar
                                          </button>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            })}
                            {archivedAssetDocs.length > 0 && (
                              <div>
                                <h4 style={{ fontSize: '13px', fontWeight: 'bold', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                  <File size={16} /> Arquivados ({archivedAssetDocs.length})
                                </h4>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                  {archivedAssetDocs.map(doc => (
                                    <div key={doc.id} className="card" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg-app)', border: '1px dashed var(--border)', opacity: 0.82 }}>
                                      <div style={{ minWidth: 0 }}>
                                        <div style={{ fontWeight: '600', fontSize: '13px' }}>{doc.original_name || doc.name}</div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                          Arquivado | Hash: {doc.file_hash.substring(0, 8)}...
                                        </div>
                                      </div>
                                      <button
                                        className="btn btn-secondary"
                                        style={{ padding: '4px 8px', fontSize: '11px' }}
                                        onClick={async () => {
                                          try {
                                            await axios.post(`${API_URL}/v2/files/${doc.id}/restore`, null, {
                                              params: {
                                                operator_name: sessionStorage.getItem('mec_operator_name') || 'Operador'
                                              }
                                            });
                                            toast.success('Sucesso', 'Arquivo restaurado.');
                                            if (selectedAsset) {
                                              fetchAssetDetails(selectedAsset.id);
                                            }
                                          } catch (err) {
                                            console.error(err);
                                            toast.error('Erro', 'Não foi possível restaurar o arquivo.');
                                          }
                                        }}
                                      >
                                        Restaurar
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div style={{ textAlign: 'center', padding: '24px', border: '1px dashed var(--border)', borderRadius: '8px', color: 'var(--text-muted)' }}>
                            Nenhum arquivo local indexado a este ativo.
                          </div>
                        )}

                        {/* Linkar/Upload Documento */}
                        {!showAddDoc ? (
                          <button className="btn btn-secondary" onClick={() => { setUploadValidationError(''); setSelectedUploadFiles([]); setShowAddDoc(true); }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                            <Plus size={16} /> Vincular ou Enviar Arquivo
                          </button>
                        ) : (
                          <form onSubmit={handleLinkDocument} className="card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <h4 style={{ fontSize: '14px', fontWeight: '700', margin: 0 }}>Vincular ou Enviar Arquivo Técnico</h4>

                            <div className="form-group">
                              <label className="form-label">Selecionar arquivo</label>
                              <input
                                type="file"
                                className="form-control"
                                accept={ACCEPTED_UPLOAD_EXTENSIONS}
                                multiple
                                onChange={e => {
                                  const files = e.target.files ? Array.from(e.target.files) : [];
                                  const validationError = validateUploadFiles(files);
                                  setSelectedUploadFiles(files);
                                  setUploadValidationError(validationError);
                                }}
                                required
                              />
                              <p style={{ margin: '6px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                                Os arquivos serão copiados para o armazenamento controlado do ManutencaoEmCampo. Limites: imagens {formatBytes(fileLimits?.bytes?.image)}, documentos {formatBytes(fileLimits?.bytes?.document)}, áudio {formatBytes(fileLimits?.bytes?.audio)}, vídeo {formatBytes(fileLimits?.bytes?.video)}.
                              </p>
                              {selectedUploadFiles.length > 0 && (
                                <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
                                  {selectedUploadFiles.length} arquivo(s) selecionado(s): {selectedUploadFiles.slice(0, 3).map(file => file.name).join(', ')}
                                  {selectedUploadFiles.length > 3 ? '...' : ''}
                                </div>
                              )}
                              {uploadValidationError && (
                                <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--danger)', fontWeight: 600 }}>
                                  {uploadValidationError}
                                </div>
                              )}
                            </div>

                            <div className="form-group">
                              <label className="form-label">Tipo / Categoria de Arquivo</label>
                              <select className="form-control" value={newDocForm.document_type} onChange={e => setNewDocForm({ ...newDocForm, document_type: e.target.value })}>
                                <option value="manual">Manual de Instruções</option>
                                <option value="photo">Foto do Ativo</option>
                                <option value="certificate">Certificado / Laudo de Calibração</option>
                                <option value="warranty">Termo de Garantia</option>
                                <option value="receipt">Nota Fiscal / Comprovante</option>
                                <option value="other">Outro Documento</option>
                              </select>
                            </div>

                            <div className="form-group">
                              <label className="form-label">Observações</label>
                              <input type="text" className="form-control" placeholder="Notas sobre o arquivo..." value={newDocForm.notes} onChange={e => setNewDocForm({ ...newDocForm, notes: e.target.value })} />
                            </div>

                            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                              <button type="submit" className="btn btn-primary" style={{ flex: 1, fontSize: '13px' }} disabled={submittingDoc || !!uploadValidationError}>
                                {submittingDoc ? 'Enviando...' : 'Enviar / Vincular'}
                              </button>
                              <button type="button" className="btn btn-secondary" style={{ flex: 1, fontSize: '13px' }} onClick={() => { setShowAddDoc(false); setSelectedUploadFiles([]); setUploadValidationError(''); }} disabled={submittingDoc}>
                                Cancelar
                              </button>
                            </div>
                          </form>
                        )}
                      </div>
                    )}
                  </div>
                )}



                {/* ── TAB HISTÓRICO DE OM ── */}

                {detailTab === 'history' && (() => {

                  const uniqueOps = Array.from(new Set(assetTimeline.map(o => o.operator_name).filter(Boolean))) as string[];

                  const filteredOrders = assetTimeline.filter(o => {

                    if (timelineTypeFilter !== 'all' && o.order_type !== timelineTypeFilter) return false;

                    if (timelineStatusFilter !== 'all' && o.status !== timelineStatusFilter) return false;

                    if (timelineOperatorFilter !== 'all' && o.operator_name !== timelineOperatorFilter) return false;

                    return true;

                  });



                  return (

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>



                      {/* Filtros da Linha do Tempo */}

                      <div className="card" style={{ padding: '12px', display: 'flex', flexWrap: 'wrap', gap: '8px', backgroundColor: 'var(--bg-app)', fontSize: '12px' }}>

                        <div style={{ flex: '1 1 120px' }}>

                          <label style={{ fontWeight: '600', display: 'block', marginBottom: '4px' }}>Tipo</label>

                          <select className="form-control" style={{ height: '32px', fontSize: '12px', padding: '4px' }} value={timelineTypeFilter} onChange={e => setTimelineTypeFilter(e.target.value)}>

                            <option value="all">Todos</option>

                            <option value="preventive">Preventiva</option>

                            <option value="corrective">Corretiva</option>

                            <option value="rework">Retrabalho</option>

                            <option value="external">Assistência Externa</option>

                          </select>

                        </div>

                        <div style={{ flex: '1 1 120px' }}>

                          <label style={{ fontWeight: '600', display: 'block', marginBottom: '4px' }}>Resultado</label>

                          <select className="form-control" style={{ height: '32px', fontSize: '12px', padding: '4px' }} value={timelineStatusFilter} onChange={e => setTimelineStatusFilter(e.target.value)}>

                            <option value="all">Todos</option>

                            <option value="completed">Concluída OK</option>

                            <option value="completed_with_issues">Com Pendências</option>

                            <option value="today">Agendada/Atrasada</option>

                          </select>

                        </div>

                        <div style={{ flex: '1 1 120px' }}>

                          <label style={{ fontWeight: '600', display: 'block', marginBottom: '4px' }}>Responsável</label>

                          <select className="form-control" style={{ height: '32px', fontSize: '12px', padding: '4px' }} value={timelineOperatorFilter} onChange={e => setTimelineOperatorFilter(e.target.value)}>

                            <option value="all">Todos</option>

                            {uniqueOps.map(op => (

                              <option key={op} value={op}>{op}</option>

                            ))}

                          </select>

                        </div>

                      </div>



                      {/* Lista de OMs */}

                      {filteredOrders.length > 0 ? (

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>

                          {filteredOrders.map(order => {

                            const isExpanded = expandedOrderId === order.id;

                            const typeLabels: Record<string, string> = {

                              preventive: 'Preventiva',

                              corrective: 'Corretiva',

                              rework: 'Retrabalho',

                              external: 'Ext. Técnica'

                            };

                            return (

                              <div

                                key={order.id}

                                className="card"

                                style={{

                                  padding: '14px',

                                  backgroundColor: 'var(--bg-app)',

                                  borderLeft: order.order_type === 'corrective' ? '4px solid var(--danger)' :

                                             order.order_type === 'rework' ? '4px solid #f59e0b' : '4px solid var(--primary)',

                                  cursor: 'pointer'

                                }}

                                onClick={() => setExpandedOrderId(isExpanded ? null : order.id)}

                              >

                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>

                                  <div>

                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>

                                      <strong style={{ fontSize: '14px' }}>OM #{order.friendly_number}</strong>

                                      <span style={{

                                        fontSize: '10px',

                                        fontWeight: '700',

                                        backgroundColor: 'var(--border)',

                                        padding: '2px 6px',

                                        borderRadius: '8px',

                                        textTransform: 'uppercase'

                                      }}>

                                        {typeLabels[order.order_type] || order.order_type}

                                      </span>

                                    </div>

                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>

                                      Competência: {order.competence || 'Manual'}

                                    </div>

                                  </div>

                                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'end', gap: '4px' }}>

                                    <StatusBadge status={order.status} size="sm" />

                                  </div>

                                </div>



                                {isExpanded && (

                                  <div

                                    style={{

                                      marginTop: '12px',

                                      paddingTop: '12px',

                                      borderTop: '1px solid var(--border)',

                                      fontSize: '12px',

                                      display: 'flex',

                                      flexDirection: 'column',

                                      gap: '8px'

                                    }}

                                    onClick={e => e.stopPropagation()} // impede colapsar ao clicar nas informações

                                  >

                                    <div><strong>Responsável:</strong> {order.operator_name || 'Não atribuído'}</div>

                                    {order.started_at && <div><strong>Início:</strong> {formatManutencaoEmCampoDateTime(order.started_at)}</div>}

                                    {order.completed_at && <div><strong>Término:</strong> {formatManutencaoEmCampoDateTime(order.completed_at)}</div>}

                                    {order.final_condition && (

                                      <div>

                                        <strong>Condição Final:</strong>{' '}

                                        <span style={{

                                          fontWeight: '600',

                                          color: order.final_condition === 'released' ? 'var(--success)' :

                                                 order.final_condition === 'released_with_attention' ? '#f59e0b' : 'var(--danger)'

                                        }}>

                                          {order.final_condition === 'released' ? 'Liberada para Operação' :

                                           order.final_condition === 'released_with_attention' ? 'Liberada com Restrição' : 'Máquina Parada / Bloqueada'}

                                        </span>

                                      </div>

                                    )}

                                    {order.machine_stopped && (

                                      <div style={{ color: 'var(--danger)', fontWeight: '600' }}>

                                        ⚠️ Esta manutenção causou parada operacional do ativo.

                                      </div>

                                    )}

                                    {order.relation_type && (

                                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>

                                        Vinculada como: <strong>{order.relation_type}</strong>

                                      </div>

                                    )}

                                    <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>

                                      {order.status.startsWith('completed') && (

                                        <button

                                          className="btn btn-secondary"

                                          style={{ height: '30px', padding: '0 10px', fontSize: '11px', flex: 1 }}

                                          onClick={() => window.open(`${API_URL}/v2/orders/${order.id}/final-pdf?revision=${order.final_revision || 1}`, '_blank', 'noopener,noreferrer')}

                                        >

                                          Visualizar PDF Final

                                        </button>

                                      )}

                                      <button

                                        className="btn btn-secondary"

                                        style={{ height: '30px', padding: '0 10px', fontSize: '11px', flex: 1 }}

                                        onClick={() => {

                                          axios.get(`${API_URL}/v2/orders/${order.id}/events`)

                                            .then(res => {

                                              const evs = res.data;

                                              const labels: Record<string, string> = {
                                                started: 'Iniciou o checklist', completed: 'Concluiu a manutenção',
                                                answer_updated: 'Atualizou uma resposta', evidence_attached: 'Anexou uma evidência',
                                                execution_reviewed: 'Classificou o registro', epi_guidance_not_confirmed: 'Recebeu orientações de EPI',
                                              };
                                              const lines = evs.map((e: any) => `${formatManutencaoEmCampoTime(e.created_at)} — ${e.operator_name || 'Não informado'}: ${labels[e.event_type] || e.event_type}`).join('\n');
                                              alert(`Linha do tempo da OM #${order.friendly_number}:\n\n${lines || 'Nenhum evento registrado.'}\n\nOs detalhes técnicos e hashes permanecem guardados no dossiê.`);

                                            })

                                            .catch(() => alert('Erro ao carregar log de eventos de auditoria.'));

                                        }}

                                      >

                                        Ver Auditoria

                                      </button>

                                    </div>

                                  </div>

                                )}

                              </div>

                            );

                          })}

                        </div>

                      ) : (

                        <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>

                          Nenhuma ordem de manutenção corresponde aos filtros selecionados.

                        </div>

                      )}

                    </div>

                  );

                })()}



              </div>

            </div>

          </div>

        )}



        {/* ── MODAL CADASTRO DE ATIVO (NOVO) ── */}

        {showAddModal && (

          <div className="overlay">

            <div className="modal-content" style={{ maxWidth: '650px', maxHeight: '90vh', overflowY: 'auto' }}>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', marginBottom: '16px' }}>
                <div>
                  <h3 style={{ fontSize: '20px', fontWeight: '800', margin: 0 }}>Cadastrar ativo</h3>
                  <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: '13px' }}>Etapa {addAssetStep} de 3 — {addAssetStep === 1 ? 'Essencial' : addAssetStep === 2 ? 'Mais detalhes' : 'Manutenção e arquivos'}</p>
                </div>
                <button type="button" className="btn btn-secondary" onClick={() => { setShowAddModal(false); setAddAssetStep(1); }}>Cancelar</button>
              </div>

              <div style={{ height: '6px', background: 'var(--border)', borderRadius: '999px', overflow: 'hidden', marginBottom: '20px' }}>
                <div style={{ width: `${(addAssetStep / 3) * 100}%`, height: '100%', background: 'var(--primary)' }} />
              </div>

              <form onSubmit={handleAddAsset} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {addAssetStep === 1 && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div className="form-group">
                      <label className="form-label">Tipo</label>
                      <select className="form-control" value={newAsset.type} onChange={e => setNewAsset({ ...newAsset, type: e.target.value })}>
                        <option value="machine">Máquina</option>
                        <option value="equipment">Equipamento</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label className="form-label">Situação</label>
                      <select className="form-control" value={newAsset.status} onChange={e => setNewAsset({ ...newAsset, status: e.target.value })}>
                        <option value="active">Ativo</option>
                        <option value="inactive">Inativo</option>
                        <option value="parada">Parada</option>
                      </select>
                    </div>
                    <div className="form-group" style={{ gridColumn: 'span 2' }}>
                      <label className="form-label">Nome do ativo</label>
                      <input type="text" className="form-control" value={newAsset.description} onChange={e => setNewAsset({ ...newAsset, description: e.target.value })} placeholder="Ex: Compressor de Ar Schulz" required />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Patrimônio</label>
                      <input type="text" className="form-control" value={newAsset.patrimonio} onChange={e => setNewAsset({ ...newAsset, patrimonio: e.target.value })} placeholder="Ex: M-42 ou E-15" required />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Setor</label>
                      <select className="form-control" value={newAsset.sector_id} onChange={e => setNewAsset({ ...newAsset, sector_id: e.target.value })} required>
                        <option value="">-- Escolha o setor --</option>
                        {sectors.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </div>
                    <div className="form-group" style={{ gridColumn: 'span 2' }}>
                      <label className="form-label">Periodicidade preventiva</label>
                      <select className="form-control" value={newAssetPlan.periodicity} onChange={e => setNewAssetPlan({ ...newAssetPlan, periodicity: e.target.value })}>
                        <option value="monthly">Mensal</option>
                        <option value="bimonthly">Bimestral</option>
                        <option value="trimonthly">Trimestral</option>
                        <option value="semiannual">Semestral</option>
                        <option value="annual">Anual</option>
                      </select>
                    </div>
                  </div>
                )}

                {addAssetStep === 2 && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div className="form-group">
                      <label className="form-label">Fabricante</label>
                      <input type="text" className="form-control" value={newAsset.manufacturer} onChange={e => setNewAsset({ ...newAsset, manufacturer: e.target.value })} placeholder="Ex: Schulz" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Modelo</label>
                      <input type="text" className="form-control" value={newAsset.model} onChange={e => setNewAsset({ ...newAsset, model: e.target.value })} placeholder="Ex: MSV 20" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Número de série</label>
                      <input type="text" className="form-control" value={newAsset.serial_number} onChange={e => setNewAsset({ ...newAsset, serial_number: e.target.value })} placeholder="Ex: 994827" />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Responsável</label>
                      <input type="text" className="form-control" value={sessionStorage.getItem('mec_operator_name') || ''} disabled />
                    </div>
                    <div className="form-group" style={{ gridColumn: 'span 2' }}>
                      <label className="form-label">Observações</label>
                      <textarea className="form-control" value={newAsset.notes} onChange={e => setNewAsset({ ...newAsset, notes: e.target.value })} placeholder="Outras informações do ativo" rows={3} />
                    </div>
                    <div style={{ gridColumn: 'span 2', padding: '12px', border: '1px dashed var(--border)', borderRadius: '8px', color: 'var(--text-muted)', fontSize: '13px' }}>
                      Dados complementares podem ser incluídos no prontuário do ativo após salvar.
                    </div>
                  </div>
                )}

                {addAssetStep === 3 && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div className="form-group">
                      <label className="form-label">Primeira competência</label>
                      <select className="form-control" value={newAssetPlan.planned_month} onChange={e => setNewAssetPlan({ ...newAssetPlan, planned_month: e.target.value })}>
                        {Array.from({ length: 12 }, (_, index) => (
                          <option key={index + 1} value={String(index + 1)}>{String(index + 1).padStart(2, '0')}</option>
                        ))}
                      </select>
                    </div>
                    <div className="form-group">
                      <label className="form-label">Checklist</label>
                      <select className="form-control" value={newAssetPlan.checklist_template_version_id} onChange={e => setNewAssetPlan({ ...newAssetPlan, checklist_template_version_id: e.target.value })}>
                        <option value="">Checklist ainda não definido</option>
                        {checklists.map(tmpl => (
                          <optgroup key={tmpl.id} label={tmpl.name}>
                            {tmpl.versions.map(v => <option key={v.id} value={v.id}>Versão {v.version} ({v.items.length} itens)</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </div>
                    <div style={{ gridColumn: 'span 2', padding: '12px', border: '1px dashed var(--border)', borderRadius: '8px', color: 'var(--text-muted)', fontSize: '13px' }}>
                      Fotos, manual, garantia, ficha técnica e outros documentos podem ser anexados pela galeria do ativo após salvar. Nenhum caminho técnico precisa ser digitado.
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: '12px', marginTop: '12px', flexWrap: 'wrap' }}>
                  {addAssetStep > 1 && <button type="button" className="btn btn-secondary" onClick={() => setAddAssetStep((addAssetStep - 1) as 1 | 2 | 3)}>Voltar</button>}
                  <button type="submit" className="btn btn-primary">Salvar agora</button>
                  {addAssetStep < 3 && <button type="button" className="btn btn-primary" onClick={() => setAddAssetStep((addAssetStep + 1) as 1 | 2 | 3)}>Salvar e continuar</button>}
                  <button type="button" className="btn btn-secondary" onClick={() => { setShowAddModal(false); setAddAssetStep(1); }}>Cancelar</button>
                </div>
              </form>

            </div>

          </div>

        )}



        {/* ── MODAL DE LIBERAÇÃO DE MÁQUINA (CONVERSÃO DE PROMPT/ALERT) ── */}

        {releasingAssetId && (

          <div className="overlay" style={{ zIndex: 10002 }}>

            <div className="modal-content" style={{ maxWidth: '450px' }}>

              <h3 style={{ fontSize: '18px', fontWeight: '800', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>

                <Hammer style={{ color: 'var(--primary)' }} /> Liberar Máquina Parada

              </h3>

              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>

                Para retornar a máquina ao estado operacional normal, informe o reparo ou a ação corretiva realizada.

              </p>

              <form onSubmit={handleReleaseAssetSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

                <div className="form-group" style={{ marginBottom: 0 }}>

                  <label className="form-label">O que foi corrigido / reparado?</label>

                  <textarea

                    className="form-control"

                    value={releaseDescription}

                    onChange={e => setReleaseDescription(e.target.value)}

                    placeholder="Descreva a ação corretiva aplicada..."

                    rows={3}

                    required

                  />

                </div>

                <div style={{ display: 'flex', gap: '12px' }}>

                  <button type="submit" className="btn btn-primary" style={{ flex: 1 }}>Confirmar Liberação</button>

                  <button type="button" className="btn btn-secondary" style={{ flex: 1 }} onClick={() => setReleasingAssetId(null)}>Cancelar</button>

                </div>

              </form>

            </div>

          </div>

        )}

        {/* ── MODAL GALERIA DE FOTOS COM CARROSSEL E ZOOM ── */}
        {galleryOpen && (
          <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'rgba(0, 0, 0, 0.95)',
              zIndex: 9999,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
              padding: '20px'
            }}
            onClick={() => {
              setGalleryOpen(false);
              setZoomScale(1);
            }}
          >
            {/* Header do Modal */}
            <div
              style={{
                position: 'absolute',
                top: '20px',
                left: '20px',
                right: '20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                color: '#fff',
                zIndex: 10000
              }}
              onClick={e => e.stopPropagation()}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 'bold' }}>{selectedAsset?.description}</h3>
                <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'rgba(255, 255, 255, 0.7)' }}>
                  Foto {currentImageIndex + 1} de {activeAssetDocs.filter(d => d.category === 'photo').length}
                </p>
              </div>
              <button
                onClick={() => {
                  setGalleryOpen(false);
                  setZoomScale(1);
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#fff',
                  cursor: 'pointer',
                  padding: '8px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                <X size={28} />
              </button>
            </div>

            {/* Imagem Principal */}
            {activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex] && (
              <div
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flex: 1,
                  width: '100%',
                  maxHeight: '75vh',
                  overflow: 'hidden'
                }}
                onClick={e => e.stopPropagation()}
              >
                {/* Seta Esquerda */}
                {activeAssetDocs.filter(d => d.category === 'photo').length > 1 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      const photos = activeAssetDocs.filter(d => d.category === 'photo');
                      setCurrentImageIndex((currentImageIndex - 1 + photos.length) % photos.length);
                      setZoomScale(1);
                    }}
                    style={{
                      position: 'absolute',
                      left: '20px',
                      backgroundColor: 'rgba(255, 255, 255, 0.1)',
                      border: 'none',
                      borderRadius: '50%',
                      width: '48px',
                      height: '48px',
                      color: '#fff',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      zIndex: 10001
                    }}
                  >
                    <ChevronLeft size={24} />
                  </button>
                )}

                {/* Container de Zoom */}
                <div
                  style={{
                    transform: `scale(${zoomScale})`,
                    transition: 'transform 0.2s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    maxWidth: '85%',
                    maxHeight: '100%'
                  }}
                >
                  <img
                    src={`${API_URL}${activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex].content_url}`}
                    alt="Ampliada"
                    style={{
                      maxWidth: '100%',
                      maxHeight: '100%',
                      objectFit: 'contain',
                      borderRadius: '4px',
                      boxShadow: '0 4px 20px rgba(0,0,0,0.5)'
                    }}
                  />
                </div>

                {/* Seta Direita */}
                {activeAssetDocs.filter(d => d.category === 'photo').length > 1 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      const photos = activeAssetDocs.filter(d => d.category === 'photo');
                      setCurrentImageIndex((currentImageIndex + 1) % photos.length);
                      setZoomScale(1);
                    }}
                    style={{
                      position: 'absolute',
                      right: '20px',
                      backgroundColor: 'rgba(255, 255, 255, 0.1)',
                      border: 'none',
                      borderRadius: '50%',
                      width: '48px',
                      height: '48px',
                      color: '#fff',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      zIndex: 10001
                    }}
                  >
                    <ChevronRight size={24} />
                  </button>
                )}
              </div>
            )}

            {/* Rodapé / Controles */}
            <div
              style={{
                marginTop: '20px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
                color: '#fff',
                zIndex: 10000
              }}
              onClick={e => e.stopPropagation()}
            >
              {/* Zoom Slider */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button
                  onClick={() => setZoomScale(Math.max(1, zoomScale - 0.25))}
                  style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  -
                </button>
                <span style={{ fontSize: '13px', minWidth: '40px', textAlign: 'center' }}>{Math.round(zoomScale * 100)}%</span>
                <button
                  onClick={() => setZoomScale(Math.min(3, zoomScale + 0.25))}
                  style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  +
                </button>
                <button
                  onClick={() => setZoomScale(1)}
                  style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                >
                  Reset
                </button>
              </div>

              {/* Ações da Imagem */}
              {activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex] && (
                <div style={{ display: 'flex', gap: '10px' }}>
                  {!activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex].is_primary_photo && (
                    <button
                      onClick={async () => {
                        const currentPhoto = activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex];
                        try {
                          await axios.post(`${API_URL}/v2/files/${currentPhoto.id}/set-primary`);
                          toast.success('Sucesso', 'Foto definida como principal!');
                          if (selectedAsset) {
                            fetchAssetDetails(selectedAsset.id);
                          }
                        } catch (err) {
                          console.error(err);
                          toast.error('Erro', 'Não foi possível definir como principal.');
                        }
                      }}
                      style={{
                        backgroundColor: 'var(--primary)',
                        color: '#fff',
                        border: 'none',
                        padding: '8px 16px',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontWeight: 'bold'
                      }}
                    >
                      Definir como Principal
                    </button>
                  )}
                  <button
                    onClick={async () => {
                      const currentPhoto = activeAssetDocs.filter(d => d.category === 'photo')[currentImageIndex];
                      if (!confirm('Deseja realmente arquivar esta foto?')) return;
                      try {
                        await axios.post(`${API_URL}/v2/files/${currentPhoto.id}/archive`, null, {
                          params: {
                            operator_name: sessionStorage.getItem('mec_operator_name') || 'Operador'
                          }
                        });
                        toast.success('Sucesso', 'Foto arquivada com sucesso!');
                        setZoomScale(1);
                        if (selectedAsset) {
                          fetchAssetDetails(selectedAsset.id);
                        }
                        const remainingPhotos = activeAssetDocs.filter(d => d.category === 'photo').filter(p => p.id !== currentPhoto.id);
                        if (remainingPhotos.length === 0) {
                          setGalleryOpen(false);
                        } else {
                          setCurrentImageIndex(0);
                        }
                      } catch (err) {
                        console.error(err);
                        toast.error('Erro', 'Não foi possível arquivar a foto.');
                      }
                    }}
                    style={{
                      backgroundColor: 'rgba(255,0,0,0.2)',
                      color: '#ff4d4d',
                      border: '1px solid rgba(255,0,0,0.4)',
                      padding: '8px 16px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '13px'
                    }}
                  >
                    Arquivar Foto
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
