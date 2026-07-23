export interface OfflineDraft {
  order_id: string;
  operator_name: string;
  selected_user_id?: string;
  device_id?: string;
  final_condition: string;
  notes: string;
  items: Array<{
    item_id: string;
    status: string;
    notes: string;
    defect_found?: string;
    corrected_in_place?: boolean;
    correction_description?: string;
    needs_part?: boolean;
    part_name?: string;
    can_operate?: boolean;
    not_applicable_reason?: string;
    audio_transcript?: string;
    photo_path?: string;
  }>;
  idempotency_key: string;
  evidence_id?: string | null;
  performed_by_operator_id?: string;
  performed_by_participant_ids?: string[];
  completion_queued?: boolean;
  uploaded_evidences?: Record<string, string>; // base64 images stored offline (maps evidence_type -> base64)
  updated_at?: string;
}

export interface OfflineOperation {
  id: string;
  order_id: string;
  type:
    | 'epi_confirm'
    | 'start_order'
    | 'answer_item'
    | 'complete_order'
    | 'photo_upload'
    | 'document_upload'
    | 'audio_upload'
    | 'material_request'
    | 'corrective_create'
    | 'rework_create'
    | 'downtime_start'
    | 'downtime_release'
    | 'observation_save'
    | 'conflict_resolution'
    | string;
  endpoint: string;
  method: 'POST';
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  attempts: number;
  last_error?: string;
}

const DB_NAME = 'mec_offline_db';
const DB_VERSION = 2;

export function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains('drafts')) {
        db.createObjectStore('drafts', { keyPath: 'order_id' });
      }
      if (!db.objectStoreNames.contains('cache')) {
        db.createObjectStore('cache');
      }
      if (!db.objectStoreNames.contains('operations')) {
        db.createObjectStore('operations', { keyPath: 'id' });
      }
    };
  });
}

export async function enqueueOperation(operation: OfflineOperation): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('operations', 'readwrite');
    const store = tx.objectStore('operations');
    const request = store.put(operation);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function getQueuedOperations(orderId?: string): Promise<OfflineOperation[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('operations', 'readonly');
    const store = tx.objectStore('operations');
    const request = store.getAll();
    request.onsuccess = () => {
      const result = (request.result || []) as OfflineOperation[];
      resolve(orderId ? result.filter((operation) => operation.order_id === orderId) : result);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function deleteQueuedOperation(operationId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('operations', 'readwrite');
    const store = tx.objectStore('operations');
    const request = store.delete(operationId);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function saveDraft(draft: OfflineDraft): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('drafts', 'readwrite');
    const store = tx.objectStore('drafts');
    const request = store.put(draft);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function getDraft(orderId: string): Promise<OfflineDraft | null> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('drafts', 'readonly');
    const store = tx.objectStore('drafts');
    const request = store.get(orderId);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

export async function deleteDraft(orderId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('drafts', 'readwrite');
    const store = tx.objectStore('drafts');
    const request = store.delete(orderId);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function getAllDrafts(): Promise<OfflineDraft[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('drafts', 'readonly');
    const store = tx.objectStore('drafts');
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

export async function setCache(key: string, value: any): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('cache', 'readwrite');
    const store = tx.objectStore('cache');
    const request = store.put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

export async function getCache(key: string): Promise<any | null> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('cache', 'readonly');
    const store = tx.objectStore('cache');
    const request = store.get(key);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

const API_URL = window.location.port === '5173'
  ? `http://${window.location.hostname}:8000`
  : window.location.origin;

export async function syncQueuedOperations(): Promise<{ synced: number; failed: number; results: any[] }> {
  const operations = await getQueuedOperations();
  if (operations.length === 0) return { synced: 0, failed: 0, results: [] };
  const selected_user_id = sessionStorage.getItem('mec_operator_id') || undefined;
  const operator_name = sessionStorage.getItem('mec_operator_name') || undefined;
  const device_id = localStorage.getItem('mec_device_id') || (() => {
    const id = `device-${crypto.randomUUID()}`;
    localStorage.setItem('mec_device_id', id);
    return id;
  })();
  const response = await fetch(`${API_URL}/v2/offline/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selected_user_id,
      operator_name,
      device_id,
      operations: operations.map((op) => ({
        id: op.id,
        type: op.type,
        order_id: op.order_id,
        payload: op.payload,
        created_at: op.created_at,
      })),
    }),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const data = await response.json();
  let synced = 0;
  let failed = 0;
  for (const result of data.results || []) {
    if (['applied', 'duplicate', 'dry_run_ok'].includes(result.status)) {
      await deleteQueuedOperation(result.id);
      synced += 1;
    } else {
      failed += 1;
    }
  }
  return { synced, failed, results: data.results || [] };
}

export async function queuedOperationCount(): Promise<number> {
  return (await getQueuedOperations()).length;
}
