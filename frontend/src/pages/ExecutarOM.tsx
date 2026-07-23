/* oxlint-disable react-hooks/exhaustive-deps */
import React, { useState, useEffect, useRef } from 'react';







import axios from 'axios';
import { deleteDraft, deleteQueuedOperation, enqueueOperation, getDraft, getQueuedOperations, saveDraft } from '../db';







import {







  Shield,







  Check,







  X,







  AlertTriangle,







  Camera,







  ChevronLeft,







  ChevronRight,







  Loader2,















  Mic,







  MicOff,







  Sparkles,







  Info







} from 'lucide-react';







import { useToast } from '../components/toastContext';















interface ExecutarOMProps {







  orderId: string;







  onCancel: () => void;







  onComplete: () => void;







}















interface ChecklistItem {







  id: string;







  item_number: string;







  description: string;







  is_mandatory: boolean;







  allow_photo: boolean;







  is_critical: boolean;







  suggested_materials?: string;







  item_type?: string;







}















interface EpiRequirement {







  id: string;







  item_name: string;







  ca_number?: string;







  validity?: string;







  is_mandatory: boolean;







}















const API_URL = window.location.port === '5173'







  ? `http://${window.location.hostname}:8000`







  : window.location.origin;















function getManutencaoEmCampoDeviceId(): string {
  const key = 'mec_device_id';
  try {
    const existing = localStorage.getItem(key);
    if (existing) return existing;
    const generated = crypto.randomUUID ? crypto.randomUUID() : `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(key, generated);
    return generated;
  } catch {
    return `device-session-${Date.now()}`;
  }
}

interface MaintenanceExecutor {
  id: string;
  name: string;
}

export default function ExecutarOM({ orderId, onCancel, onComplete }: ExecutarOMProps) {







  const toast = useToast();







  const operatorName = sessionStorage.getItem('mec_operator_name') || 'Operador Padrão';
  const operatorId = sessionStorage.getItem('mec_operator_id') || undefined;
  const deviceId = getManutencaoEmCampoDeviceId();















  // Etapas: 'loading' | 'epi' | 'executing' | 'finalizing' | 'success'







  const [step, setStep] = useState<'loading' | 'epi' | 'executing' | 'finalizing' | 'success'>('loading');







  const [order, setOrder] = useState<any>(null);
  const [epiConfirmed, setEpiConfirmed] = useState(false);







  const [epis, setEpis] = useState<EpiRequirement[]>([]);







  const [items, setItems] = useState<ChecklistItem[]>([]);







  const [currentIndex, setCurrentIndex] = useState(0);















  // Respostas locais







  const [answers, setAnswers] = useState<Record<string, {







    status?: 'ok' | 'attention' | 'not_applicable';







    notes?: string;







    defect_found?: string;







    corrected_in_place?: boolean;







    correction_description?: string;







    needs_part?: boolean;







    part_name?: string;







    can_operate?: boolean;







    not_applicable_reason?: string;







    photo_path?: string;







    photo_file?: File;
    audio_transcript?: string;







  }>>({});

  const [saveStatusByItem, setSaveStatusByItem] = useState<Record<string, 'idle' | 'saving' | 'saved' | 'queued' | 'error'>>({});
  const saveTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const [offlineQueueCount, setOfflineQueueCount] = useState(0);
  const [offlineDraftSavedAt, setOfflineDraftSavedAt] = useState<string | null>(null);















  // Gravação de Áudio







  const [recordingItemId, setRecordingItemId] = useState<string | null>(null);







  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);







  const [, setAudioChunks] = useState<Blob[]>([]);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef<number>(0);
  const [pendingAudioByItem, setPendingAudioByItem] = useState<Record<string, { blob: Blob; url: string; mimeType: string; durationSec: number }>>({});
  const pendingAudioRef = useRef<Record<string, { blob: Blob; url: string; mimeType: string; durationSec: number }>>({});
  const recognitionRef = useRef<any>(null);
  const [dictatingItemId, setDictatingItemId] = useState<string | null>(null);







  const [isTranscribing, setIsTranscribing] = useState(false);

  useEffect(() => {
    pendingAudioRef.current = pendingAudioByItem;
  }, [pendingAudioByItem]);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop?.();
      } catch {
        // Sessão já encerrada pelo navegador.
      }
      Object.values(pendingAudioRef.current).forEach((audio) => URL.revokeObjectURL(audio.url));
    };
  }, []);















  // Estados da finalização







  const [notes, setNotes] = useState('');







  const [finalCondition, setFinalCondition] = useState<'released' | 'released_with_attention' | 'stopped'>('released');







  const [downtimeReason, setDowntimeReason] = useState('');







  const [submitting, setSubmitting] = useState(false);







  const [sha256, setSha256] = useState('');







  const [pdfPath, setPdfPath] = useState('');

  const [finalPdfSha256, setFinalPdfSha256] = useState('');

  const [executors, setExecutors] = useState<MaintenanceExecutor[]>([]);

  const [performedByOperatorId, setPerformedByOperatorId] = useState('');

  const [performedByName, setPerformedByName] = useState('');
  const [performedByParticipantIds, setPerformedByParticipantIds] = useState<string[]>([]);

  const [dossierSync, setDossierSync] = useState<{ status?: string; target_path?: string; error?: string } | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [showEvidenceSuggestion, setShowEvidenceSuggestion] = useState(false);
  const [evidenceSuggestionAccepted, setEvidenceSuggestionAccepted] = useState(false);















  // Upload de Foto







  const fileInputRef = useRef<HTMLInputElement>(null);







  const [uploadingPhoto, setUploadingPhoto] = useState(false);















  useEffect(() => {







    // oxlint-disable-next-line react-hooks/exhaustive-deps
    loadOrderDetails();







  }, [orderId]);



  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {

    if (step === 'epi') {

    }

  }, [step]);

  useEffect(() => {
    return () => {
      Object.values(saveTimersRef.current).forEach(clearTimeout);
      saveTimersRef.current = {};
    };
  }, []);

  useEffect(() => {
    void refreshOfflineQueueCount();
    void replayQueuedOperations();
    const syncWhenOnline = () => {
      void replayQueuedOperations();
    };
    window.addEventListener('online', syncWhenOnline);
    return () => window.removeEventListener('online', syncWhenOnline);
  }, [orderId]);















  const loadOrderDetails = async () => {







    try {







      // 1. Carrega dados da OM







      const orderRes = await axios.get(`${API_URL}/v2/orders/${orderId}`);







      const detailData = orderRes.data;
      const orderData = detailData.order
        ? {
            ...detailData.order,
            asset: detailData.asset,
            plan: detailData.plan,
            items: detailData.items || [],
          }
        : detailData;







      setOrder(orderData);
      setEpiConfirmed(Boolean(orderData.epi_confirmed));
      if (orderData.performed_by_operator_id) {
        setPerformedByOperatorId(orderData.performed_by_operator_id);
        setPerformedByName(orderData.performed_by_name || '');
        try {
          const rawParticipants = orderData.performed_by_participants_json || '[]';
          setPerformedByParticipantIds(JSON.parse(rawParticipants).map((person: { id?: string }) => person.id).filter(Boolean));
        } catch { setPerformedByParticipantIds([]); }
      }

      const executorsRes = await axios.get<MaintenanceExecutor[]>(`${API_URL}/operators`, {
        params: { selection: 'maintenance_executor' },
      });
      setExecutors(Array.isArray(executorsRes.data) ? executorsRes.data : []);















      // 2. Carrega itens do checklist associado







      if (detailData.items && detailData.items.length > 0) {
        setItems(detailData.items);
      } else if (orderData.checklist_version_id) {







        const checkRes = await axios.get(`${API_URL}/checklists/${orderData.checklist_version_id}`);







        setItems(checkRes.data.items || []);







      }















      // 3. Carrega EPIs se houver plano associado







      if (detailData.epi_requirements) {
        setEpis(detailData.epi_requirements.requirements || []);
      } else if (orderData.plan_id) {
        const epiRes = await axios.get(`${API_URL}/plans/${orderData.plan_id}/epi-requirements`);
        setEpis(epiRes.data || []);







      }















      // Inicializa respostas com as existentes se houver







      const initialAnswers: any = {};







      if (orderData.items && orderData.items.length > 0) {







        orderData.items.forEach((oi: any) => {







          if (oi.status !== 'unanswered') {







            initialAnswers[oi.item_id] = {







              status: oi.status,







              notes: oi.notes || '',







              defect_found: oi.defect_found || '',







              corrected_in_place: oi.corrected_in_place || false,







              correction_description: oi.correction_description || '',







              needs_part: oi.needs_part || false,







              part_name: oi.part_name || '',







              can_operate: oi.can_operate !== undefined ? oi.can_operate : true,







              not_applicable_reason: oi.not_applicable_reason || '',







            };







          }







        });







      }







      const localDraft = await getDraft(orderId);
      if (localDraft?.items?.length) {
        localDraft.items.forEach((item) => {
          if (!initialAnswers[item.item_id]?.status) {
            initialAnswers[item.item_id] = {
              status: item.status as any,
              notes: item.notes || '',
              defect_found: item.defect_found || '',
              corrected_in_place: item.corrected_in_place,
              correction_description: item.correction_description || '',
              needs_part: item.needs_part,
              part_name: item.part_name || '',
              can_operate: item.can_operate,
              not_applicable_reason: item.not_applicable_reason || '',
              audio_transcript: item.audio_transcript || '',
              photo_path: item.photo_path || '',
            };
          }
        });
        setOfflineDraftSavedAt(localDraft.updated_at || null);
        if (localDraft.performed_by_operator_id) {
          setPerformedByOperatorId(localDraft.performed_by_operator_id);
          setPerformedByParticipantIds(localDraft.performed_by_participant_ids || []);
        }
      }

      setAnswers(initialAnswers);















      // Direciona para etapa correta







      if (orderData.execution_status === 'in_progress') {







        setStep('executing');







      } else {







        setStep('epi');







      }







    } catch (err: any) {







      console.error(err);







      toast.error('Erro', 'Erro ao carregar detalhes da Ordem de Manutenção.');







      onCancel();







    }







  };















  const handleConfirmEpi = async () => {







    setSubmitting(true);







    try {







      await axios.post(`${API_URL}/v2/orders/${orderId}/epi-confirm`, {







        operator_name: operatorName,
        selected_user_id: operatorId,
        confirmed: true, updated_items: epis.map(e => e.item_name), save_as_default: false







      });







      setEpiConfirmed(true);
      setOrder((current: any) => current ? {
        ...current,
        epi_confirmed: true,
        epi_confirmed_by: operatorName,
        epi_confirmed_at: new Date().toISOString(),
      } : current);

      toast.success('Sucesso', 'EPIs confirmados. Toque em começar execução para iniciar a OM.');







    } catch (err: any) {







      console.error(err);







      toast.error('Erro', 'Erro ao registrar confirmação de EPI.');







    } finally {







      setSubmitting(false);







    }







  };















  const handleSelectAnswer = (itemId: string, status: 'ok' | 'attention' | 'not_applicable') => {
    const nextAnswer = {
      ...(answers[itemId] || {}),
      status,
      can_operate: status === 'attention' ? (answers[itemId]?.can_operate ?? true) : undefined
    };
    setAnswers(prev => ({
      ...prev,
      [itemId]: nextAnswer
    }));
    scheduleSaveAnswer(itemId, nextAnswer, 100);
  };

  const handleStartExecution = async (asDemo = false) => {
    setSubmitting(true);
    try {
      await axios.post(`${API_URL}/v2/orders/${orderId}/start`, {
        operator_name: operatorName,
        selected_user_id: operatorId,
        device_id: deviceId,
        record_kind: asDemo ? 'demo_test' : 'official'
      });
      setOrder((current: any) => current ? {
        ...current,
        execution_status: 'in_progress',
        status: 'in_progress',
        started_at: new Date().toISOString(),
        operator_name: operatorName,
        selected_user_id: operatorId,
      } : current);
      setStep('executing');
      setDemoMode(asDemo);
      toast.success('Sucesso', asDemo ? 'Demonstração iniciada. Ela não contará como manutenção real.' : 'Execução iniciada. Responda os itens do checklist.');
    } catch (err: any) {
      console.error(err);
      toast.error('Erro', err?.response?.data?.detail || 'Erro ao iniciar a execução.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleExit = async () => {
    if (order?.execution_status === 'in_progress') {
      try {
        await axios.post(`${API_URL}/v2/orders/${orderId}/reservation/release`, {
          operator_name: operatorName,
          selected_user_id: operatorId,
          device_id: deviceId,
          reason: 'Saída voluntária da tela de execução'
        });
      } catch (err) {
        console.warn('Não foi possível liberar a reserva antes de sair:', err);
      }
    }
    onCancel();
  };

  const handleAnswerChange = (itemId: string, key: string, value: any) => {
    const nextAnswer = {
      ...(answers[itemId] || {}),
      [key]: value
    };
    setAnswers(prev => ({
      ...prev,
      [itemId]: nextAnswer
    }));
    scheduleSaveAnswer(itemId, nextAnswer);
  };

  const appendItemNote = (itemId: string, text: string) => {
    const value = (text || '').trim();
    if (!value) return;
    const current = answers[itemId] || {};
    const currentNotes = (current.notes || '').trim();
    const nextNotes = currentNotes ? `${currentNotes}\n${value}` : value;
    const nextAnswer = {
      ...current,
      notes: nextNotes,
      audio_transcript: [current.audio_transcript, value].filter(Boolean).join('\n')
    };
    setAnswers(prev => ({
      ...prev,
      [itemId]: nextAnswer
    }));
    scheduleSaveAnswer(itemId, nextAnswer);
  };
  const handlePhotoClick = () => {







    if (fileInputRef.current) {







      fileInputRef.current.click();







    }







  };















  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>, itemId: string) => {







    if (!e.target.files || e.target.files.length === 0) return;







    const file = e.target.files[0];















    setUploadingPhoto(true);







    const formData = new FormData();







    formData.append('file', file);
    formData.append('operator_name', operatorName);
    if (operatorId) formData.append('selected_user_id', operatorId);
    formData.append('device_id', deviceId);















    try {







      const res = await axios.post(`${API_URL}/v2/orders/${orderId}/items/${itemId}/photo`, formData, {







        headers: { 'Content-Type': 'multipart/form-data' }







      });







      const relativePath = res.data.file_path; // ex: data/uploads/uuid.jpg















      setAnswers(prev => ({







        ...prev,







        [itemId]: {







          ...prev[itemId],







          photo_path: relativePath







        }







      }));







      toast.success('Sucesso', 'Evidência fotográfica adicionada com sucesso!');







    } catch (err: any) {







      console.error(err);







      const detail = err.response?.data?.detail || err.message || 'Falha ao processar e salvar imagem.';
      toast.error('Erro', detail);







    } finally {







      setUploadingPhoto(false);







    }







  };















  // --- AUDIO TRANSCRIÇÃO (SST) ---







  const getAudioDiagnostic = () => {
    const secureOrigin = window.isSecureContext || ['localhost', '127.0.0.1'].includes(window.location.hostname);
    if (!secureOrigin) {
      return 'O navegador bloqueou microfone/câmera porque o sistema está em HTTP. Para gravar áudio no tablet/celular, acesse via HTTPS ou instale o certificado local.';
    }
    if (!navigator.mediaDevices) {
      return 'Este navegador não expõe navigator.mediaDevices. Use upload de áudio ou observação por texto.';
    }
    if (!navigator.mediaDevices.getUserMedia) {
      return 'Este navegador não expõe getUserMedia para microfone. Use upload de áudio ou observação por texto.';
    }
    if (!window.MediaRecorder) {
      return 'Este navegador não possui MediaRecorder. Use upload de áudio ou observação por texto.';
    }
    return '';
  };

  const getSpeechRecognitionCtor = () => (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

  const stopLiveDictation = () => {
    try {
      recognitionRef.current?.stop?.();
    } catch {
      // Browser already stopped the recognition session.
    }
    recognitionRef.current = null;
    setDictatingItemId(null);
  };

  const startLiveDictation = (itemId: string) => {
    const SpeechRecognition = getSpeechRecognitionCtor();
    if (!SpeechRecognition) {
      toast.warning('Ditado indisponível', 'Este navegador não oferece ditado ao vivo. Use observação por texto ou grave o áudio como evidência.');
      return;
    }
    const diagnostic = getAudioDiagnostic();
    if (diagnostic) {
      toast.error('Microfone bloqueado', diagnostic);
      return;
    }
    stopLiveDictation();
    const recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event: any) => {
      let finalText = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) {
          finalText += `${result[0]?.transcript || ''} `;
        }
      }
      if (finalText.trim()) {
        appendItemNote(itemId, finalText.trim());
      }
    };
    recognition.onerror = (event: any) => {
      toast.warning('Ditado interrompido', event?.error === 'not-allowed'
        ? 'Permissão de microfone negada. Libere o microfone ou use texto.'
        : 'O ditado foi interrompido pelo navegador.');
      stopLiveDictation();
    };
    recognition.onend = () => {
      setDictatingItemId(null);
      recognitionRef.current = null;
    };
    recognitionRef.current = recognition;
    setDictatingItemId(itemId);
    recognition.start();
    toast.success('Ditado ligado', 'Fale normalmente. O texto confirmado será adicionado nas observações do item.');
  };

  const normalizeAudioMime = (value?: string) => (value || '').split(';')[0].trim().toLowerCase();

  const audioExtensionForMime = (value?: string) => {
    const mime = normalizeAudioMime(value);
    if (mime === 'audio/webm' || mime === 'video/webm') return 'webm';
    if (mime === 'audio/ogg' || mime === 'application/ogg') return 'ogg';
    if (mime === 'audio/mpeg' || mime === 'audio/mp3') return 'mp3';
    if (mime === 'audio/mp4' || mime === 'audio/x-m4a' || mime === 'audio/m4a') return 'm4a';
    if (mime === 'audio/wav' || mime === 'audio/x-wav' || mime === 'audio/wave') return 'wav';
    return 'webm';
  };

  const startRecording = async (itemId: string) => {
    try {
      const diagnostic = getAudioDiagnostic();
      if (diagnostic) {
        toast.error('Gravação indisponível', diagnostic);
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : undefined;
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      audioChunksRef.current = [];
      setAudioChunks([]);

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current = [...audioChunksRef.current, event.data];
          setAudioChunks(audioChunksRef.current);
        }
      };

      recorder.onstop = async () => {
        const type = recorder.mimeType || 'audio/webm';
        const audioBlob = new Blob(audioChunksRef.current, { type });
        audioChunksRef.current = [];
        setAudioChunks([]);
        if (audioBlob.size > 0) {
          const url = URL.createObjectURL(audioBlob);
          const durationSec = recordingStartedAtRef.current ? Math.max(1, Math.round((Date.now() - recordingStartedAtRef.current) / 1000)) : 0;
          setPendingAudioByItem(prev => {
            const previous = prev[itemId];
            if (previous) URL.revokeObjectURL(previous.url);
            return {
              ...prev,
              [itemId]: { blob: audioBlob, url, mimeType: type, durationSec }
            };
          });
          toast.success('Áudio gravado', 'Ouça a gravação. Depois envie ou apague antes de salvar.');
        }
      };

      recorder.start();
      recordingStartedAtRef.current = Date.now();
      setMediaRecorder(recorder);
      setRecordingItemId(itemId);
    } catch (err: any) {
      console.error("Falha na gravação de áudio:", err);
      if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
        toast.error('Microfone bloqueado', getAudioDiagnostic() || 'Permissão de microfone negada pelo navegador. Libere a permissão ou use upload de áudio/texto.');
      } else if (err?.name === 'NotFoundError') {
        toast.error('Microfone não encontrado', 'Nenhum microfone foi encontrado neste dispositivo. Use upload de áudio ou observação por texto.');
      } else {
        toast.error('Erro de áudio', err?.message || 'Não foi possível iniciar a gravação. Use upload de áudio ou observação por texto.');
      }
    }
  };


  const stopRecording = () => {







    if (mediaRecorder && mediaRecorder.state !== 'inactive') {







      mediaRecorder.stop();







      // Parar todas as tracks do microfone







      mediaRecorder.stream.getTracks().forEach(track => track.stop());







    }







    setRecordingItemId(null);
    recordingStartedAtRef.current = 0;







  };















  const sendAudioForTranscription = async (blob: Blob, itemId: string, mimeType = blob.type || 'audio/webm', durationSec?: number) => {
    setIsTranscribing(true);
    const formData = new FormData();
    const normalizedMime = normalizeAudioMime(mimeType) || normalizeAudioMime(blob.type) || 'audio/webm';
    const extension = audioExtensionForMime(normalizedMime);
    const uploadBlob = blob.type === normalizedMime ? blob : new Blob([blob], { type: normalizedMime });
    formData.append('file', uploadBlob, `audio_${Date.now()}.${extension}`);
    formData.append('operator_name', operatorName);
    if (operatorId) formData.append('selected_user_id', operatorId);
    formData.append('device_id', deviceId);
    if (durationSec) formData.append('duration_sec', String(durationSec));

    try {
      const res = await axios.post(`${API_URL}/v2/orders/${orderId}/items/${itemId}/audio`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      const text = res.data?.transcription?.text;

      if (text) {
        appendItemNote(itemId, text);
        toast.success('Áudio transcrito', 'O texto foi adicionado nas observações do item.');
      } else {
        const status = res.data?.transcription?.status;
        const error = res.data?.transcription?.error;
        toast.warning('Áudio salvo sem transcrição', error || status || 'A evidência foi salva, mas nenhum texto foi retornado.');
      }

      await loadOrderDetails();
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail || err.message || 'erro desconhecido';
      toast.error('Erro', `Não foi possível salvar o áudio: ${detail}`);
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleAudioFileUpload = async (file: File | undefined, itemId: string) => {
    if (!file) return;
    await sendAudioForTranscription(file, itemId, file.type || 'audio/webm');
  };

  const discardPendingAudio = (itemId: string) => {
    setPendingAudioByItem(prev => {
      const current = prev[itemId];
      if (current) URL.revokeObjectURL(current.url);
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
  };

  const submitPendingAudio = async (itemId: string) => {
    const current = pendingAudioByItem[itemId];
    if (!current) return;
    await sendAudioForTranscription(current.blob, itemId, current.mimeType, current.durationSec);
    discardPendingAudio(itemId);
  };


  const buildAnswerPayload = (itemId: string, answer: (typeof answers)[string]) => ({
    item_id: itemId,
    operator_name: operatorName,
    selected_user_id: operatorId,
    device_id: deviceId,
    status: answer.status,
    result: answer.status,
    notes: answer.notes || '',
    defect_found: answer.defect_found || '',
    corrected_in_place: answer.corrected_in_place || false,
    correction_description: answer.correction_description || '',
    needs_part: answer.needs_part || false,
    part_name: answer.part_name || '',
    can_operate: answer.can_operate !== undefined ? answer.can_operate : true,
    not_applicable_reason: answer.not_applicable_reason || '',
    photo_path: answer.photo_path || ''
  });

  const refreshOfflineQueueCount = async () => {
    const queued = await getQueuedOperations(orderId);
    setOfflineQueueCount(queued.length);
  };

  const queueAnswerOperation = async (itemId: string, payload: ReturnType<typeof buildAnswerPayload>, error: unknown) => {
    const now = new Date().toISOString();
    await enqueueOperation({
      id: `answer-${orderId}-${itemId}`,
      order_id: orderId,
      type: 'answer_item',
      endpoint: `/v2/orders/${orderId}/answer-item`,
      method: 'POST',
      payload,
      created_at: now,
      updated_at: now,
      attempts: 0,
      last_error: error instanceof Error ? error.message : String(error || 'Falha ao salvar no servidor'),
    });
    await refreshOfflineQueueCount();
  };

  const replayQueuedOperations = async () => {
    const queued = await getQueuedOperations(orderId);
    if (queued.length === 0) {
      setOfflineQueueCount(0);
      return;
    }

    let replayed = 0;
    for (const operation of queued.sort((a, b) => a.created_at.localeCompare(b.created_at))) {
      if (operation.type !== 'answer_item' && operation.type !== 'complete_order') continue;
      try {
        await axios.post(`${API_URL}${operation.endpoint}`, operation.payload);
        await deleteQueuedOperation(operation.id);
        replayed += 1;
      } catch (err) {
        console.warn('Operação offline ainda pendente:', err);
      }
    }

    await refreshOfflineQueueCount();
    if (replayed > 0) {
      await loadOrderDetails();
        toast.success('Sincronizado', `${replayed} registro(s) pendente(s) foram enviados ao servidor.`);
    }
  };

  const saveLocalExecutionDraft = async (nextAnswers = answers) => {
    const savedAt = new Date().toISOString();
    await saveDraft({
      order_id: orderId,
      operator_name: operatorName,
      selected_user_id: operatorId,
      device_id: deviceId,
      final_condition: finalCondition,
      notes,
      idempotency_key: `draft-${orderId}`,
      performed_by_operator_id: performedByOperatorId,
      performed_by_participant_ids: performedByParticipantIds,
      updated_at: savedAt,
      items: Object.entries(nextAnswers)
        .filter(([, answer]) => answer?.status || answer?.notes)
        .map(([itemId, answer]) => ({
          item_id: itemId,
          status: answer.status || 'unanswered',
          notes: answer.notes || '',
          defect_found: answer.defect_found || '',
          corrected_in_place: answer.corrected_in_place,
          correction_description: answer.correction_description || '',
          needs_part: answer.needs_part,
          part_name: answer.part_name || '',
          can_operate: answer.can_operate,
          not_applicable_reason: answer.not_applicable_reason || '',
          audio_transcript: answer.audio_transcript || '',
          photo_path: answer.photo_path || '',
        })),
    });
    setOfflineDraftSavedAt(savedAt);
  };

  const saveAnswerNow = async (itemId: string, answer: (typeof answers)[string]) => {
    if (!answer?.status) return;
    setSaveStatusByItem(prev => ({ ...prev, [itemId]: 'saving' }));
    const payload = buildAnswerPayload(itemId, answer);
    try {
      await axios.post(`${API_URL}/v2/orders/${orderId}/answer-item`, payload);
      setSaveStatusByItem(prev => ({ ...prev, [itemId]: 'saved' }));
      await refreshOfflineQueueCount();
    } catch (err) {
      console.error(err);
      await queueAnswerOperation(itemId, payload, err);
      await saveLocalExecutionDraft({ ...answers, [itemId]: answer });
      setSaveStatusByItem(prev => ({ ...prev, [itemId]: 'queued' }));
      toast.warning('Offline', 'Resposta preservada na fila deste dispositivo e será reenviada quando possível.');
    }
  };

  const scheduleSaveAnswer = (itemId: string, answer: (typeof answers)[string], delay = 500) => {
    if (!answer?.status) return;
    if (saveTimersRef.current[itemId]) {
      clearTimeout(saveTimersRef.current[itemId]);
    }
    setSaveStatusByItem(prev => ({ ...prev, [itemId]: 'saving' }));
    saveTimersRef.current[itemId] = setTimeout(() => {
      void saveAnswerNow(itemId, answer);
    }, delay);
  };

  const reviewExecution = () => {
    const hasStopped = Object.values(answers).some(a => a.status === 'attention' && a.can_operate === false);
    const hasAttention = Object.values(answers).some(a => a.status === 'attention' && a.can_operate === true);
    const attentionWithoutEvidence = Object.values(answers).some(answer => answer.status === 'attention' && !(answer.photo_path || answer.notes?.trim() || answer.audio_transcript?.trim()));

    if (attentionWithoutEvidence && !evidenceSuggestionAccepted) {
      setShowEvidenceSuggestion(true);
      return;
    }

    if (hasStopped) {
      setFinalCondition('stopped');
    } else if (hasAttention) {
      setFinalCondition('released_with_attention');
    } else {
      setFinalCondition('released');
    }

    setStep('finalizing');
  };

  const handleNext = () => {
    if (currentIndex < items.length - 1) {
      setCurrentIndex(prev => prev + 1);
    } else {
      reviewExecution();
    }
  };
const handleBack = () => {







    if (currentIndex > 0) {







      setCurrentIndex(prev => prev - 1);







    }







  };















  const queueCompletionOperation = async () => {
    const now = new Date().toISOString();
    await enqueueOperation({
      id: `complete-${orderId}`,
      order_id: orderId,
      type: 'complete_order',
      endpoint: `/v2/orders/${orderId}/complete`,
      method: 'POST',
      payload: {
        operator_name: operatorName, selected_user_id: operatorId, device_id: deviceId,
        notes, final_condition: finalCondition, performed_by_operator_id: performedByOperatorId,
        performed_by_participant_ids: performedByParticipantIds, idempotency_key: `complete-${orderId}`,
      },
      created_at: now, updated_at: now, attempts: 0,
      last_error: 'Conclusão aguardando conexão com o servidor',
    });
    await saveLocalExecutionDraft();
    await refreshOfflineQueueCount();
  };

  const handleSubmitAll = async () => {
    if (!performedByOperatorId) {
      toast.error('Informe quem executou', 'No resumo, selecione a pessoa que realizou a manutenção antes de finalizar.');
      return;
    }
    const unansweredItems = items.filter(item => !answers[item.id]?.status);
    if (unansweredItems.length > 0) {
      setCurrentIndex(items.findIndex(item => !answers[item.id]?.status));
      setStep('executing');
      toast.error('Checklist incompleto', `Responda os ${unansweredItems.length} item(ns) que ainda estão sem resposta antes de finalizar.`);
      return;
    }

    setSubmitting(true);
    try {
      await replayQueuedOperations();

      for (const item of items) {
        const ans = answers[item.id];
        if (!ans?.status) continue;
        await saveAnswerNow(item.id, ans);
      }

      const completeRes = await axios.post(`${API_URL}/v2/orders/${orderId}/complete`, {
        operator_name: operatorName,
        selected_user_id: operatorId,
        device_id: deviceId,
        notes: notes,
        final_condition: finalCondition,
        downtime_reason: finalCondition === 'stopped' ? downtimeReason : '',
        performed_by_operator_id: performedByOperatorId,
        performed_by_participant_ids: performedByParticipantIds,
        idempotency_key: `complete-${orderId}`,
      });

      setSha256(completeRes.data.sha256);
      setPdfPath(completeRes.data.pdf_path);
      setFinalPdfSha256(completeRes.data.final_pdf_sha256 || '');
      setPerformedByName(completeRes.data.performed_by_name || executors.find((person) => person.id === performedByOperatorId)?.name || '');
      setDossierSync(completeRes.data.dossier_sync || null);
      await deleteDraft(orderId);
      setOfflineDraftSavedAt(null);
      setStep('success');
      if (completeRes.data.dossier_sync?.status === 'synced') {
        toast.success('Manutenção concluída', 'PDF, checklist e evidências foram arquivados no servidor.');
      } else {
        toast.success('Manutenção concluída', 'O registro foi preservado e a cópia no servidor ficará pendente até a rede voltar.');
      }
    } catch (err: any) {
      console.error(err);
      if (!err?.response) {
        await queueCompletionOperation();
        setPerformedByName(executors.find((person) => person.id === performedByOperatorId)?.name || '');
        setDossierSync({ status: 'pending' });
        setStep('success');
        toast.success('Checklist concluído no tablet', 'Assim que o tablet reconectar, o PDF e a pasta oficial serão gerados automaticamente.');
      } else {
        toast.error('Não foi possível concluir', err.response?.data?.detail || 'Revise as informações e tente novamente.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const currentItem = items[currentIndex];
  const currentAnswer = currentItem ? answers[currentItem.id] : undefined;
  const answeredCount = Object.values(answers).filter(answer => !!answer.status).length;

if (step === 'loading') {







    return (







      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', gap: '16px' }}>







        <Loader2 className="animate-spin" size={48} style={{ color: 'var(--primary)' }} />







        <span style={{ fontWeight: '600', color: 'var(--text-muted)' }}>Carregando ciclo operacional da OM...</span>







      </div>







    );







  }















  if (step === 'epi') {







    return (







      <div className="card" style={{ maxWidth: '600px', margin: '40px auto', padding: '24px' }}>







        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', borderBottom: '1px solid var(--border)', paddingBottom: '16px' }}>







          <Shield size={32} style={{ color: 'var(--primary)' }} />







          <div>







            <h2 style={{ margin: 0, fontSize: '20px' }}>Orientações de segurança</h2>







            <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Ordem #{order?.friendly_number} — {order?.asset?.patrimonio}</span>







          </div>







        </div>















        {epis.length === 0 ? (







          <div style={{ backgroundColor: 'var(--bg-light)', padding: '16px', borderRadius: '8px', marginBottom: '24px', textAlign: 'center' }}>







            <p style={{ margin: 0, fontWeight: '600', color: 'var(--text-muted)' }}>EPI não definido</p>







            <p style={{ margin: '6px 0 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>Não há orientação específica cadastrada. Consulte o procedimento da área e comunique qualquer risco antes de iniciar.</p>







          </div>







        ) : (







          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '24px' }}>







            <p style={{ margin: '0 0 8px 0', fontSize: '14px', fontWeight: '500' }}>Certifique-se de estar portando e utilizando os seguintes EPIs:</p>







            {epis.map((epi, idx) => (

              <div key={epi.id || idx} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px', border: '1px solid var(--border)', borderRadius: '8px', backgroundColor: 'white' }}>

                <Check size={18} style={{ color: 'var(--success)' }} />

                <div style={{ flex: 1 }}>

                  <div style={{ fontWeight: '600', fontSize: '14px' }}>{epi.item_name}</div>


                </div>

              </div>

            ))}







          </div>







        )}















        {epiConfirmed && (
          <div style={{ backgroundColor: 'rgba(22, 163, 74, 0.08)', border: '1px solid rgba(22, 163, 74, 0.25)', color: 'var(--success)', borderRadius: '8px', padding: '12px', marginBottom: '16px', fontSize: '13px', fontWeight: 600 }}>
            Orientações registradas. A manutenção ainda não foi iniciada; toque em “Começar manutenção” para registrar o início.
          </div>
        )}
        {demoMode && <div style={{ backgroundColor: 'rgba(245, 158, 11, 0.12)', border: '1px solid var(--warning)', color: 'var(--text-main)', borderRadius: '8px', padding: '12px', marginBottom: '16px', fontSize: '13px', fontWeight: 700 }}>MODO DEMONSTRAÇÃO: fotos, PDF e histórico serão guardados, mas este registro não contará como preventiva real.</div>}

        <div style={{ display: 'flex', gap: '12px' }}>







          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={handleExit}>







            Voltar







          </button>







          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={handleConfirmEpi} disabled={submitting || epiConfirmed}>
            {epiConfirmed ? 'Orientações registradas' : 'Registrar que li'}
          </button>
          <button className="btn btn-primary" style={{ flex: 2 }} onClick={() => handleStartExecution(false)} disabled={submitting}>
            {submitting ? 'Iniciando...' : 'Começar manutenção'}
          </button>
          <button className="btn btn-secondary" style={{ flex: 2 }} onClick={() => handleStartExecution(true)} disabled={submitting}>
            Fazer teste / demonstração
          </button>







        </div>







      </div>







    );







  }















  if (step === 'executing' && currentItem) {







    const isAnswered = !!currentAnswer?.status;















    return (







      <div style={{ maxWidth: '1180px', margin: '0 auto', padding: '12px' }}>
        {offlineDraftSavedAt && (
          <div style={{ marginBottom: '12px', border: '1px solid var(--warning)', backgroundColor: 'rgba(245, 158, 11, 0.08)', color: 'var(--text-main)', borderRadius: '8px', padding: '10px 12px', fontSize: '13px', fontWeight: 600 }}>
            Rascunho local preservado neste dispositivo. Sincronize antes de trocar de equipamento ou concluir a OM.
          </div>
        )}
        {offlineQueueCount > 0 && (
          <div style={{ marginBottom: '12px', border: '1px solid var(--warning)', backgroundColor: 'rgba(245, 158, 11, 0.08)', color: 'var(--text-main)', borderRadius: '8px', padding: '10px 12px', fontSize: '13px', fontWeight: 600 }}>
            {offlineQueueCount} resposta(s) aguardando sincronização neste dispositivo.
          </div>
        )}







        {/* Progresso */}







        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>







          <span style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-muted)' }}>







            Item {currentIndex + 1} de {items.length}







          </span>







          <div style={{ flex: 1, height: '6px', backgroundColor: 'var(--border)', borderRadius: '3px', margin: '0 16px', overflow: 'hidden' }}>







            <div style={{ height: '100%', width: `${((currentIndex + 1) / items.length) * 100}%`, backgroundColor: 'var(--primary)', transition: 'width 0.3s' }}></div>







          </div>







          <button className="btn btn-secondary btn-sm" onClick={handleExit}>Sair</button>







        </div>















        <div className="card" style={{ padding: '16px', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px' }}>Todos os itens do checklist</h3>
              <p style={{ margin: '4px 0 0 0', color: 'var(--text-muted)', fontSize: '13px' }}>
                Selecione qualquer item para responder fora de ordem. Respostas são salvas automaticamente.
              </p>
            </div>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 600 }}>
              {answeredCount}/{items.length} respondidos
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '8px' }}>
            {items.map((item, index) => {
              const itemAnswer = answers[item.id];
              const itemSaveStatus = saveStatusByItem[item.id];
              const selected = index === currentIndex;
              const statusLabel = itemAnswer?.status === 'ok'
                ? 'Normal'
                : itemAnswer?.status === 'attention'
                  ? 'Problema'
                  : itemAnswer?.status === 'not_applicable'
                    ? 'Não se aplica'
                    : 'Em aberto';
              return (
                <button
                  key={item.id}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setCurrentIndex(index)}
                  style={{
                    justifyContent: 'flex-start',
                    textAlign: 'left',
                    borderColor: selected ? 'var(--primary)' : itemAnswer?.status ? 'var(--success)' : 'var(--border)',
                    backgroundColor: selected ? 'var(--primary-light)' : itemAnswer?.status ? 'rgba(34, 197, 94, 0.06)' : 'var(--surface)',
                    color: 'var(--text)',
                    minHeight: '72px',
                    padding: '10px'
                  }}
                  aria-current={selected ? 'step' : undefined}
                >
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                      <strong>{item.item_number || index + 1}</strong>
                      <span style={{ fontSize: '12px', color: itemAnswer?.status ? 'var(--success)' : 'var(--text-muted)' }}>
                        {statusLabel}
                      </span>
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.description}
                    </div>
                    {itemSaveStatus && itemAnswer?.status && (
                      <div style={{ fontSize: '11px', color: itemSaveStatus === 'error' ? 'var(--danger)' : itemSaveStatus === 'queued' ? 'var(--warning)' : 'var(--text-muted)', marginTop: '4px' }}>
                        {itemSaveStatus === 'saving'
                          ? 'Salvando...'
                          : itemSaveStatus === 'saved'
                            ? 'Salvo automaticamente'
                            : itemSaveStatus === 'queued'
                              ? 'Na fila offline'
                              : 'Falha ao salvar'}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {showEvidenceSuggestion && (
          <div role="dialog" aria-modal="true" style={{ border: '1px solid var(--warning)', background: '#fffbeb', borderRadius: 10, padding: 16, marginBottom: 16 }}>
            <strong>Há item com problema sem foto ou observação.</strong>
            <p style={{ margin: '7px 0 12px' }}>Se possível, inclua uma foto, áudio ou observação para ajudar quem consultar esta manutenção depois. Você pode continuar sem isso.</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" type="button" onClick={() => { setShowEvidenceSuggestion(false); setCurrentIndex(0); setStep('executing'); }}>Voltar ao checklist</button>
              <button className="btn btn-primary" type="button" onClick={() => { setEvidenceSuggestionAccepted(true); setShowEvidenceSuggestion(false); reviewExecution(); }}>Continuar sem evidência</button>
            </div>
          </div>
        )}

        {/* Card do Item */}







        <div className="card" style={{ padding: '24px', marginBottom: '20px', minHeight: '300px', display: 'flex', flexDirection: 'column' }}>







          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>







            <span style={{







              backgroundColor: 'var(--primary-light)',







              color: 'var(--primary)',







              fontWeight: '700',







              fontSize: '18px',







              padding: '6px 12px',







              borderRadius: '8px'







            }}>







              {currentItem.item_number}







            </span>







            <div style={{ flex: 1 }}>







              <h3 style={{ margin: 0, fontSize: '18px', lineHeight: '1.4' }}>{currentItem.description}</h3>







              {currentItem.suggested_materials && (







                <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--warning)', fontWeight: '500' }}>







                  <Sparkles size={14} />







                  <span>Insumo sugerido: {currentItem.suggested_materials}</span>







                </div>







              )}







            </div>







          </div>















          {/* Botões Grandes de Resposta */}







          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', margin: '20px 0' }}>







            <button







              className={`btn ${currentAnswer?.status === 'ok' ? 'btn-success' : 'btn-secondary'}`}







              style={{ padding: '20px 12px', fontSize: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', height: 'auto' }}







              onClick={() => handleSelectAnswer(currentItem.id, 'ok')}







            >







              <Check size={24} />







              <span>Está normal</span>







            </button>







            <button







              className={`btn ${currentAnswer?.status === 'attention' ? 'btn-danger' : 'btn-secondary'}`}







              style={{ padding: '20px 12px', fontSize: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', height: 'auto' }}







              onClick={() => handleSelectAnswer(currentItem.id, 'attention')}







            >







              <AlertTriangle size={24} />







              <span>Encontrei um problema</span>







            </button>







            <button







              className={`btn ${currentAnswer?.status === 'not_applicable' ? 'btn-warning' : 'btn-secondary'}`}







              style={{ padding: '20px 12px', fontSize: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', height: 'auto' }}







              onClick={() => handleSelectAnswer(currentItem.id, 'not_applicable')}







            >







              <X size={24} />







              <span>N. A.</span>







            </button>







          </div>















          {/* Form Extra se houver problema */}







          {currentAnswer?.status === 'attention' && (







            <div style={{ border: '1px solid var(--danger)', borderRadius: '8px', padding: '16px', backgroundColor: 'rgba(239, 68, 68, 0.03)', marginBottom: '16px' }}>







              <h4 style={{ margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--danger)' }}>







                <AlertTriangle size={16} /> Detalhes da Reprovação







              </h4>















              <div className="form-group" style={{ marginBottom: '12px' }}>







                <label className="form-label" style={{ fontWeight: '600' }}>Descrição da avaria encontrada:</label>







                <textarea







                  className="form-control"







                  rows={2}







                  placeholder="Explique o problema encontrado no componente..."







                  value={currentAnswer.defect_found || ''}







                  onChange={(e) => handleAnswerChange(currentItem.id, 'defect_found', e.target.value)}







                />







              </div>















              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '12px' }}>







                <div className="form-group">







                  <label className="form-label" style={{ fontWeight: '600' }}>Corrigido no local?</label>







                  <select







                    className="form-control"







                    value={currentAnswer.corrected_in_place ? 'true' : 'false'}







                    onChange={(e) => handleAnswerChange(currentItem.id, 'corrected_in_place', e.target.value === 'true')}







                  >







                    <option value="false">Não (Gera Corretiva)</option>







                    <option value="true">Sim (Corrigido agora)</option>







                  </select>







                </div>







                <div className="form-group">







                  <label className="form-label" style={{ fontWeight: '600' }}>Ativo pode operar?</label>







                  <select







                    className="form-control"







                    value={currentAnswer.can_operate ? 'true' : 'false'}







                    onChange={(e) => handleAnswerChange(currentItem.id, 'can_operate', e.target.value === 'true')}







                  >







                    <option value="true">Sim (Operação normal/alerta)</option>







                    <option value="false">Não (Máquina Parada!)</option>







                  </select>







                </div>







              </div>















              {currentAnswer.corrected_in_place && (







                <div className="form-group" style={{ marginBottom: '12px' }}>







                  <label className="form-label" style={{ fontWeight: '600' }}>Descrição da correção efetuada:</label>







                  <input







                    type="text"







                    className="form-control"







                    placeholder="O que foi feito para corrigir?"







                    value={currentAnswer.correction_description || ''}







                    onChange={(e) => handleAnswerChange(currentItem.id, 'correction_description', e.target.value)}







                  />







                </div>







              )}















              <div className="form-group" style={{ marginBottom: '12px' }}>







                <label className="form-label" style={{ fontWeight: '600' }}>Solicitar Peça/Material de Compras?</label>







                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>







                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', cursor: 'pointer' }}>







                    <input







                      type="radio"







                      name={`needs_part_${currentItem.id}`}







                      checked={currentAnswer.needs_part === true}







                      onChange={() => handleAnswerChange(currentItem.id, 'needs_part', true)}







                    /> Sim







                  </label>







                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', cursor: 'pointer' }}>







                    <input







                      type="radio"







                      name={`needs_part_${currentItem.id}`}







                      checked={currentAnswer.needs_part !== true}







                      onChange={() => handleAnswerChange(currentItem.id, 'needs_part', false)}







                    /> Não







                  </label>







                </div>







              </div>















              {currentAnswer.needs_part && (







                <div className="form-group" style={{ marginBottom: '12px' }}>







                  <label className="form-label" style={{ fontWeight: '600' }}>Nome da peça/material e quantidade:</label>







                  <input







                    type="text"







                    className="form-control"







                    placeholder="Ex: 1x Rolamento 6204 DDU"







                    value={currentAnswer.part_name || ''}







                    onChange={(e) => handleAnswerChange(currentItem.id, 'part_name', e.target.value)}







                  />







                </div>







              )}







            </div>







          )}















          {/* Form Extra se não se aplica */}







          {currentAnswer?.status === 'not_applicable' && (







            <div style={{ border: '1px solid var(--warning)', borderRadius: '8px', padding: '16px', backgroundColor: 'rgba(245, 158, 11, 0.03)', marginBottom: '16px' }}>







              <h4 style={{ margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--warning)' }}>







                <Info size={16} /> Justificativa de não se aplica







              </h4>







              <div className="form-group">







                <label className="form-label" style={{ fontWeight: '600' }}>Selecione ou digite o motivo:</label>







                <select







                  className="form-control"







                  style={{ marginBottom: '8px' }}







                  value={currentAnswer.not_applicable_reason || ''}







                  onChange={(e) => handleAnswerChange(currentItem.id, 'not_applicable_reason', e.target.value)}







                >







                  <option value="">-- Selecione um motivo rápido --</option>







                  <option value="Ativo não possui este acessório">Ativo não possui este acessório</option>







                  <option value="Acessório desativado temporariamente">Acessório desativado temporariamente</option>







                  <option value="Condições ambientais impedem teste">Condições ambientais impedem teste</option>







                </select>







                <input







                  type="text"







                  className="form-control"







                  placeholder="Ou descreva outro motivo..."







                  value={currentAnswer.not_applicable_reason || ''}







                  onChange={(e) => handleAnswerChange(currentItem.id, 'not_applicable_reason', e.target.value)}







                />







              </div>







            </div>







          )}















          {/* Campo de notas com áudio opcional. */}







          {isAnswered && (







            <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border)', paddingTop: '16px' }}>







              <div className="form-group">







                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>







                  <label className="form-label" style={{ margin: 0, fontWeight: '600' }}>Observações do item (opcional):</label>















                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>







                    {isTranscribing ? (







                      <span style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>







                        <Loader2 className="animate-spin" size={12} /> Transcrevendo...







                      </span>







                    ) : recordingItemId === currentItem.id ? (







                      <button className="btn btn-danger btn-sm" style={{ padding: '4px 8px', borderRadius: '16px', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={stopRecording}>







                        <MicOff size={12} /> Parar Áudio







                      </button>







                    ) : (







                      <button className="btn btn-secondary btn-sm" style={{ padding: '4px 8px', borderRadius: '16px', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={() => startRecording(currentItem.id)}>







                        <Mic size={12} /> Gravar Áudio







                      </button>







                    )}
                    {dictatingItemId === currentItem.id ? (
                      <button className="btn btn-danger btn-sm" style={{ padding: '4px 8px', borderRadius: '16px', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={stopLiveDictation}>
                        <MicOff size={12} /> Parar ditado
                      </button>
                    ) : (
                      <button className="btn btn-secondary btn-sm" style={{ padding: '4px 8px', borderRadius: '16px', display: 'flex', alignItems: 'center', gap: '4px' }} onClick={() => startLiveDictation(currentItem.id)}>
                        <Mic size={12} /> Ditado ao vivo
                      </button>
                    )}
                    <label className="btn btn-secondary btn-sm" style={{ padding: '4px 8px', borderRadius: '16px', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
                      Anexar áudio
                      <input
                        type="file"
                        accept="audio/*"
                        style={{ display: 'none' }}
                        onChange={(event) => {
                          handleAudioFileUpload(event.target.files?.[0], currentItem.id);
                          event.currentTarget.value = '';
                        }}
                      />
                    </label>
                    {pendingAudioByItem[currentItem.id] && (
                      <div style={{ width: '100%', display: 'grid', gap: 8, padding: 10, border: '1px solid var(--border)', borderRadius: 10, background: '#f8fafc' }}>
                        <strong style={{ fontSize: 12 }}>Áudio gravado aguardando envio ({pendingAudioByItem[currentItem.id].durationSec}s)</strong>
                        <audio controls src={pendingAudioByItem[currentItem.id].url} style={{ width: '100%' }} />
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <button className="btn btn-primary btn-sm" type="button" onClick={() => submitPendingAudio(currentItem.id)} disabled={isTranscribing}>
                            Enviar áudio
                          </button>
                          <button className="btn btn-secondary btn-sm" type="button" onClick={() => discardPendingAudio(currentItem.id)} disabled={isTranscribing}>
                            Apagar áudio
                          </button>
                        </div>
                      </div>
                    )}







                  </div>







                </div>















                <textarea







                  className="form-control"







                  rows={2}







                  placeholder="Digite observações do item..."







                  value={currentAnswer.notes || ''}







                  onChange={(e) => handleAnswerChange(currentItem.id, 'notes', e.target.value)}







                />







              </div>















              {/* Upload de Foto */}







              {currentItem.allow_photo && (







                <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '12px' }}>







                  <button className="btn btn-secondary btn-sm" onClick={handlePhotoClick} disabled={uploadingPhoto}>







                    <Camera size={14} style={{ marginRight: '6px' }} />







                    {uploadingPhoto ? 'Carregando...' : 'Adicionar Foto'}







                  </button>







                  <input







                    type="file"







                    ref={fileInputRef}







                    style={{ display: 'none' }}







                    accept="image/*"







                    onChange={(e) => handleFileChange(e, currentItem.id)}







                  />







                  {currentAnswer.photo_path && (







                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--success)', fontWeight: '500' }}>







                      <Check size={14} /> Foto vinculada!







                    </div>







                  )}







                </div>







              )}







            </div>







          )}







        </div>















        {/* Navegação Inferior */}







        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px' }}>







          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={handleBack} disabled={currentIndex === 0}>







            <ChevronLeft size={16} style={{ marginRight: '6px' }} /> Anterior







          </button>







          <button className="btn btn-primary" style={{ flex: 2 }} onClick={handleNext} disabled={!isAnswered}>







            {currentIndex === items.length - 1 ? 'Revisar e Concluir' : 'Próximo'} <ChevronRight size={16} style={{ marginLeft: '6px' }} />







          </button>

          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={reviewExecution} disabled={answeredCount === 0}>
            Revisar execução
          </button>







        </div>







      </div>







    );







  }















  if (step === 'finalizing') {







    const totalItems = items.length;







    const okCount = Object.values(answers).filter(a => a.status === 'ok').length;







    const attentionCount = Object.values(answers).filter(a => a.status === 'attention').length;







    const naCount = Object.values(answers).filter(a => a.status === 'not_applicable').length;















    return (







      <div className="card" style={{ maxWidth: '600px', margin: '20px auto', padding: '24px' }}>







        <h2 style={{ borderBottom: '1px solid var(--border)', paddingBottom: '12px', marginBottom: '20px' }}>Resumo da Execução</h2>















        {/* Painel Numérico */}







        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px', marginBottom: '24px', textAlign: 'center' }}>







          <div style={{ border: '1px solid var(--border)', padding: '12px', borderRadius: '8px', backgroundColor: 'var(--bg-light)' }}>







            <div style={{ fontSize: '20px', fontWeight: '700' }}>{totalItems}</div>







            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600' }}>Itens</div>







          </div>







          <div style={{ border: '1px solid var(--success)', padding: '12px', borderRadius: '8px', backgroundColor: 'rgba(34, 197, 94, 0.05)', color: 'var(--success)' }}>







            <div style={{ fontSize: '20px', fontWeight: '700' }}>{okCount}</div>







            <div style={{ fontSize: '11px', fontWeight: '600' }}>Normal</div>







          </div>







          <div style={{ border: '1px solid var(--danger)', padding: '12px', borderRadius: '8px', backgroundColor: 'rgba(239, 68, 68, 0.05)', color: 'var(--danger)' }}>







            <div style={{ fontSize: '20px', fontWeight: '700' }}>{attentionCount}</div>







            <div style={{ fontSize: '11px', fontWeight: '600' }}>Problema</div>







          </div>







          <div style={{ border: '1px solid var(--warning)', padding: '12px', borderRadius: '8px', backgroundColor: 'rgba(245, 158, 11, 0.05)', color: 'var(--warning)' }}>







            <div style={{ fontSize: '20px', fontWeight: '700' }}>{naCount}</div>







            <div style={{ fontSize: '11px', fontWeight: '600' }}>Não se aplica</div>







          </div>







        </div>















        <div className="form-group" style={{ marginBottom: '20px', padding: '14px', border: '1px solid var(--primary)', borderRadius: '8px', background: 'rgba(37, 99, 235, 0.04)' }}>
          <label className="form-label" style={{ fontWeight: '700', fontSize: '15px' }}>Registrado e conferido por:</label>
          <div style={{ fontWeight: 700, color: 'var(--primary)', marginBottom: '14px' }}>{operatorName}</div>
          <label className="form-label" htmlFor="performed-by" style={{ fontWeight: '700', fontSize: '15px' }}>Quem realizou a manutenção?</label>
          <select
            id="performed-by"
            className="form-control"
            value={performedByOperatorId}
            onChange={(event) => {
              const selectedId = event.target.value;
              setPerformedByOperatorId(selectedId);
              setPerformedByName(executors.find((person) => person.id === selectedId)?.name || '');
              setPerformedByParticipantIds(current => current.filter(id => id !== selectedId));
            }}
            required
          >
            <option value="">Selecione quem executou o serviço</option>
            {executors.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
          </select>
          <small style={{ display: 'block', marginTop: '8px', color: 'var(--text-muted)' }}>
            Este nome ficará no histórico, PDF final e pasta da manutenção no servidor.
          </small>
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: 'pointer' }}>Outras pessoas que participaram (opcional)</summary>
            <div style={{ display: 'grid', gap: 7, marginTop: 10 }}>
              {executors.filter(person => person.id !== performedByOperatorId).map(person => (
                <label key={person.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={performedByParticipantIds.includes(person.id)} onChange={(event) => setPerformedByParticipantIds(current => event.target.checked ? [...current, person.id] : current.filter(id => id !== person.id))} />
                  {person.name}
                </label>
              ))}
            </div>
          </details>
        </div>

        {/* Condição Final do Ativo */}







        <div className="form-group" style={{ marginBottom: '20px' }}>







          <label className="form-label" style={{ fontWeight: '600', fontSize: '15px' }}>Condição Final do Ativo:</label>







          <select







            className="form-control"







            value={finalCondition}







            onChange={(e: any) => setFinalCondition(e.target.value)}







            style={{ fontWeight: '600' }}







          >







            <option value="released">Liberado para operação normal</option>







            <option value="released_with_attention">Liberado com atenção/restrições</option>







            <option value="stopped">Parado (Máquina Parada!)</option>







          </select>







        </div>















        {finalCondition === 'stopped' && (







          <div className="form-group" style={{ marginBottom: '20px', border: '1px solid var(--danger)', padding: '16px', borderRadius: '8px', backgroundColor: 'rgba(239, 68, 68, 0.02)' }}>







            <label className="form-label" style={{ fontWeight: '600', color: 'var(--danger)' }}>Motivo da Parada / Avaria impeditiva:</label>







            <input







              type="text"







              className="form-control"







              placeholder="Ex: Racha no barramento principal"







              value={downtimeReason}







              onChange={(e) => setDowntimeReason(e.target.value)}







              required







            />







          </div>







        )}















        {/* Notas Gerais */}







        <div className="form-group" style={{ marginBottom: '24px' }}>







          <label className="form-label" style={{ fontWeight: '600', fontSize: '15px' }}>Observações Gerais da Ordem:</label>







          <textarea







            className="form-control"







            rows={3}







            placeholder="Relate observações gerais sobre a execução desta manutenção..."







            value={notes}







            onChange={(e) => setNotes(e.target.value)}







          />







        </div>















        {/* Ações */}







        <div style={{ display: 'flex', gap: '12px' }}>







          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => setStep('executing')}>







            Voltar ao checklist







          </button>







          <button className="btn btn-primary" style={{ flex: 2 }} onClick={() => handleSubmitAll()} disabled={submitting || (finalCondition === 'stopped' && !downtimeReason)}>







            {submitting ? 'Gravando auditoria...' : 'Finalizar e Arquivar'}







          </button>







        </div>







      </div>







    );







  }















  if (step === 'success') {







    return (







      <div className="card" style={{ maxWidth: '500px', margin: '40px auto', padding: '32px', textAlign: 'center' }}>







        <div style={{







          width: '64px',







          height: '64px',







          borderRadius: '50%',







          backgroundColor: 'rgba(34, 197, 94, 0.1)',







          color: 'var(--success)',







          display: 'flex',







          alignItems: 'center',







          justifyContent: 'center',







          margin: '0 auto 20px auto'







        }}>







          <Check size={36} />







        </div>















        <h2 style={{ marginBottom: '8px' }}>Manutenção Concluída!</h2>







        <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '24px' }}>







          Ordem #{order?.friendly_number} concluída. O checklist foi congelado como registro oficial.







        </p>

        <div style={{ margin: '0 0 24px', padding: '12px', borderRadius: '8px', textAlign: 'left', background: 'var(--bg-light)', fontSize: '13px' }}>
          <div><strong>Registrado e conferido por:</strong> {operatorName}</div>
          <div><strong>Manutenção executada por:</strong> {performedByName || 'Não informado'}</div>
          <div style={{ marginTop: 8, color: dossierSync?.status === 'synced' ? 'var(--success)' : 'var(--warning)' }}>
            {dossierSync?.status === 'synced'
              ? '✓ PDF, checklist e evidências foram copiados para o servidor.'
              : '⚠ Registro concluído e preservado localmente; a cópia para o servidor está pendente e será reenviada automaticamente.'}
          </div>
          {dossierSync?.target_path && <code style={{ display: 'block', marginTop: 8, fontSize: 10, overflowWrap: 'anywhere' }}>{dossierSync.target_path}</code>}
        </div>















        {/* Caixa de SHA-256 e Auditoria */}







        <div style={{ backgroundColor: 'var(--bg-light)', padding: '16px', borderRadius: '8px', textAlign: 'left', marginBottom: '24px' }}>







          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--primary)', fontWeight: '600', fontSize: '12px', textTransform: 'uppercase', marginBottom: '8px' }}>







            <Shield size={14} />







            <span>Assinatura Digital de Auditoria</span>







          </div>







          <code style={{ fontSize: '11px', wordBreak: 'break-all', display: 'block', backgroundColor: 'white', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>







            {sha256}







          </code>







          {pdfPath && (







            <a







              href={`${API_URL}/v2/orders/${orderId}/final-pdf?revision=1&sha=${encodeURIComponent(finalPdfSha256 || sha256)}`}







              target="_blank"







              rel="noreferrer"







              className="btn btn-secondary btn-sm"







              style={{ width: '100%', marginTop: '12px', textAlign: 'center', display: 'block' }}







            >







              Abrir PDF Final Arquivado







            </a>







          )}







        </div>















        <button className="btn btn-primary" style={{ width: '100%' }} onClick={onComplete}>







          Voltar para Início







        </button>







      </div>







    );







  }















  return null;







}
