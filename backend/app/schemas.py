from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime, date

# --- SECTOR SCHEMAS ---
class SectorBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None

class SectorCreate(SectorBase):
    pass

class Sector(SectorBase):
    id: str
    model_config = ConfigDict(from_attributes=True)

# --- ASSET SCHEMAS ---
class AssetBase(BaseModel):
    patrimonio: str = Field(..., max_length=50)
    type: Literal['machine', 'equipment'] = Field(..., description="'machine' ou 'equipment'")
    description: str = Field(..., max_length=255)
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    sector_id: Optional[str] = None
    status: Literal['active', 'inactive', 'em_manutencao', 'parada'] = "active"
    is_operable: bool = True
    notes: Optional[str] = None
    manual: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    foto: Optional[str] = None
    caminho_documentos: Optional[str] = None
    has_patrimonio_conflict: bool = False
    conflict_patrimonio_suggested: Optional[str] = None
    opaque_token: Optional[str] = None
    legacy_patrimonio: Optional[str] = None
    controlled_code: Optional[str] = None
    asset_class: Optional[str] = "maintainable_asset"
    maintenance_strategy: Optional[str] = "preventive"
    show_in_daily_list: bool = True
    thumbnail_url: Optional[str] = None
    primary_photo_id: Optional[str] = None

class AssetCreate(AssetBase):
    pass

class Asset(AssetBase):
    id: str
    last_maintenance_date: Optional[datetime] = None
    next_maintenance_date: Optional[datetime] = None
    sector: Optional[Sector] = None
    model_config = ConfigDict(from_attributes=True)

# --- CHECKLIST SCHEMAS ---
class ChecklistItemBase(BaseModel):
    item_number: str
    description: str
    is_mandatory: bool = True
    allow_photo: bool = True
    is_critical: bool = False
    suggested_materials: Optional[str] = None
    item_type: Optional[str] = "inspection"
    not_applicable_reasons: Optional[str] = None

class ChecklistItem(ChecklistItemBase):
    id: str
    model_config = ConfigDict(from_attributes=True)

class ChecklistTemplateVersionBase(BaseModel):
    version: int
    created_at: datetime
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    source_document: Optional[str] = None
    source_document_hash: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

class ChecklistTemplateVersion(ChecklistTemplateVersionBase):
    id: str
    items: List[ChecklistItem] = []
    model_config = ConfigDict(from_attributes=True)

class ChecklistTemplateBase(BaseModel):
    name: str
    code_reference: Optional[str] = None
    asset_type: str
    asset_patrimonio: Optional[str] = None
    asset_manufacturer: Optional[str] = None
    asset_model_ref: Optional[str] = None
    epi_summary: Optional[str] = None
    materials_summary: Optional[str] = None
    maintenance_type: Optional[str] = "preventive"
    rq_cmp_reference: Optional[str] = None

class ChecklistTemplate(ChecklistTemplateBase):
    id: str
    versions: List[ChecklistTemplateVersion] = []
    model_config = ConfigDict(from_attributes=True)

# --- MAINTENANCE ORDER SCHEMAS ---
class MaintenanceOrderBase(BaseModel):
    asset_id: str
    plan_id: Optional[str] = None
    checklist_version_id: Optional[str] = None
    planned_date: Optional[date] = None
    planned_year: Optional[int] = None
    planned_month: Optional[int] = None
    original_competence: Optional[str] = None
    scheduled_day_is_explicit: bool = False
    source_status: Optional[str] = None
    source_note: Optional[str] = None
    priority: Literal['low', 'medium', 'high', 'critical'] = "medium"
    status: Literal['scheduled', 'today', 'in_progress', 'completed', 'completed_with_issues', 'overdue', 'cancelled', 'needs_review', 'demo_completed'] = "scheduled"
    notes: Optional[str] = None
    operator_name: Optional[str] = None
    is_monthly_competency: bool = False
    opaque_token: Optional[str] = None
    execution_status: Literal['not_started', 'in_progress', 'completed', 'cancelled'] = "not_started"
    needs_review: Optional[bool] = False
    review_decision: Optional[Literal['not_started', 'completed_on_time', 'completed_with_delay', 'not_applicable', 'cancelled', 'active_inactive', 'old_cycle_supered', 'to_review', 'regularization', 'continue', 'test_draft', 'not_performed']] = None
    review_operator: Optional[str] = None
    review_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    source_file_hash: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    source_cell: Optional[str] = None
    source_value_130: Optional[str] = None
    rules_engine_version: Optional[str] = None
    deadline_calculated_at: Optional[datetime] = None

    # Campos de execução e relacionamento.
    order_type: Optional[str] = "preventive"
    parent_work_order_id: Optional[str] = None
    relation_type: Optional[str] = None
    occurrence_number: Optional[int] = None
    plan_code: Optional[str] = None
    epi_confirmed: bool = False
    epi_confirmed_at: Optional[datetime] = None
    epi_confirmed_by: Optional[str] = None
    machine_stopped: bool = False
    machine_stopped_at: Optional[datetime] = None
    machine_released_at: Optional[datetime] = None
    final_json: Optional[str] = None
    final_pdf_path: Optional[str] = None
    final_sha256: Optional[str] = None
    final_pdf_sha256: Optional[str] = None
    performed_by_name: Optional[str] = None
    performed_by_operator_id: Optional[str] = None
    performed_by_snapshot: Optional[str] = None
    performed_by_participants_json: Optional[str] = None
    dossier_folder_name: Optional[str] = None
    final_revision: int = 1
    round_id: Optional[str] = None

class MaintenancePlanBase(BaseModel):
    name: str
    asset_id: str
    periodicity: str
    frequency_days: Optional[int] = None
    frequency_months: Optional[int] = None  # Adicionado para frequências em meses
    planned_month: Optional[int] = None
    next_due_date: Optional[date] = None
    checklist_template_version_id: Optional[str] = None
    estimated_duration_mins: int = 60
    calculation_basis: str = "fixed_calendar"
    plan_type: str = "fixed_calendar"
    fixed_months: Optional[str] = None
    generation_horizon_months: int = 12
    confidence: str = "medium"
    source_document: Optional[str] = None
    source_document_hash: Optional[str] = None
    source_document_page: Optional[str] = None
    last_auto_generated_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    recurrence_status: str = "to_review"
    recurrence_confirmed_by: Optional[str] = None
    recurrence_confirmed_at: Optional[datetime] = None
    is_active: bool = True
    safety_instructions: Optional[str] = None
    is_monthly_competency: bool = False

class MaintenancePlan(MaintenancePlanBase):
    id: str
    model_config = ConfigDict(from_attributes=True)

class MaintenanceOrderCreate(MaintenanceOrderBase):
    pass

class MaintenanceOrderItemBase(BaseModel):
    item_id: str
    status: Literal['unanswered', 'ok', 'attention', 'not_applicable'] = "unanswered"
    notes: Optional[str] = None
    operator_name: Optional[str] = None

    # Campos de execução e relacionamento.
    defect_found: Optional[str] = None
    corrected_in_place: Optional[bool] = None
    correction_description: Optional[str] = None
    needs_part: Optional[bool] = None
    part_name: Optional[str] = None
    can_operate: Optional[bool] = None
    not_applicable_reason: Optional[str] = None
    audio_transcript: Optional[str] = None
    photo_category: Optional[str] = None

class MaintenanceOrderItemCreate(MaintenanceOrderItemBase):
    pass

class MaintenanceOrderItem(MaintenanceOrderItemBase):
    id: str
    answered_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)

# --- EVIDENCE SCHEMAS ---
class MaintenanceEvidence(BaseModel):
    id: str
    order_id: Optional[str] = None
    order_item_id: Optional[str] = None
    asset_id: Optional[str] = None
    evidence_type: str
    file_path: str
    uploaded_at: datetime
    model_config = ConfigDict(from_attributes=True)

class MaintenanceOrder(MaintenanceOrderBase):
    id: str
    friendly_number: Optional[int] = None
    original_date: Optional[date] = None
    rescheduled_date: Optional[date] = None
    reschedule_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_mins: Optional[int] = None
    final_condition: Optional[Literal['released', 'released_with_attention', 'stopped']] = None
    asset: Asset
    items: List[MaintenanceOrderItem] = []
    evidences: List[MaintenanceEvidence] = []
    model_config = ConfigDict(from_attributes=True)

# --- ISSUE / OCORRÊNCIA SCHEMAS ---
class MaintenanceIssueBase(BaseModel):
    asset_id: str
    order_id: Optional[str] = None
    description: str
    priority: str = "medium"
    is_operable_affected: bool = False
    status: str = "open"
    operator_name: Optional[str] = None
    repair_description: Optional[str] = None
    final_condition: Optional[str] = None
    resolution_date: Optional[date] = None
    evidence_file_path: Optional[str] = None

class MaintenanceIssueCreate(MaintenanceIssueBase):
    pass

class MaintenanceIssue(MaintenanceIssueBase):
    id: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# --- AUDIT LOG SCHEMA ---
class AuditLog(BaseModel):
    id: str
    action: str
    entity_name: str
    entity_id: str
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    origin: str
    operator_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- OPERATOR / RESPONSÁVEL SCHEMAS ---
class OperatorBase(BaseModel):
    name: str
    nickname: Optional[str] = None
    sector_id: Optional[str] = None
    origin: Optional[str] = "manual"
    role: Optional[str] = "operator"
    can_record_checklist: Optional[bool] = None
    can_execute_maintenance: Optional[bool] = None

class OperatorCreate(OperatorBase):
    pass

class Operator(OperatorBase):
    id: str
    normalized_name: Optional[str] = None
    photo_url: Optional[str] = None
    photo_thumbnail_url: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    archived_by: Optional[str] = None
    role: Optional[str] = "operator"
    can_record_checklist: bool = False
    can_execute_maintenance: bool = True
    model_config = ConfigDict(from_attributes=True)

# --- ASSET CONFLICT RESOLUTION SCHEMA ---
class AssetConflictResolve(BaseModel):
    resolution_type: str  # 'suggested', 'manual', 'keep'
    new_patrimonio: Optional[str] = None

class AssociatePhotoRequest(BaseModel):
    evidence_id: str
    order_id: str

class AssetReleaseRequest(BaseModel):
    issue_id: str
    repair_description: str
    operator_name: str
    final_condition: Literal['released', 'released_with_attention', 'stopped']
    resolution_date: date
    evidence_file_path: Optional[str] = None

# --- Schemas de planejamento e histórico ---
class LegacyHistory(BaseModel):
    id: str
    asset_id: str
    planned_year: Optional[int] = None
    planned_month: Optional[int] = None
    planned_date: Optional[str] = None
    source_value: Optional[str] = None
    source_file: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None
    source_cell: Optional[str] = None
    interpretation: Optional[str] = None
    interpretation_confidence: Optional[str] = None
    operator_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AssetMeterBase(BaseModel):
    asset_id: str
    meter_type: str
    unit: str
    current_reading: float = 0.0
    maintenance_interval: float
    next_maintenance_at: float
    notes: Optional[str] = None

class AssetMeter(AssetMeterBase):
    id: str
    last_reading_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AssetMeterReadingCreate(BaseModel):
    reading: float
    notes: Optional[str] = None

class QualityConfig(BaseModel):
    key: str
    value: str
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AssetDocumentIndex(BaseModel):
    id: str
    asset_id: str
    file_path: str
    file_name: str
    file_extension: str
    file_size: int
    file_hash: str
    document_type: str
    confidence: Optional[str] = None
    extracted_text: Optional[str] = None
    extraction_method: Optional[str] = None
    needs_review: bool = False
    indexed_at: datetime
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# --- Schemas operacionais de execução ---

class WorkOrderEventBase(BaseModel):
    order_id: str
    event_type: str
    operator_name: Optional[str] = None
    payload: Optional[str] = None

class WorkOrderEventCreate(WorkOrderEventBase):
    pass

class WorkOrderEvent(WorkOrderEventBase):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkOrderSnapshotBase(BaseModel):
    order_id: str
    snapshot_json: str

class WorkOrderSnapshotCreate(WorkOrderSnapshotBase):
    pass

class WorkOrderSnapshot(WorkOrderSnapshotBase):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WorkOrderCorrectionBase(BaseModel):
    order_id: str
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    operator_name: Optional[str] = None
    document_path: Optional[str] = None
    document_sha256: Optional[str] = None
    document_revision: Optional[int] = None

class WorkOrderCorrectionCreate(WorkOrderCorrectionBase):
    pass

class WorkOrderCorrection(WorkOrderCorrectionBase):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EpiRequirementBase(BaseModel):
    plan_id: Optional[str] = None
    checklist_template_id: Optional[str] = None
    item_name: str
    ca_number: Optional[str] = None
    validity: Optional[str] = None
    is_mandatory: bool = True
    added_by: Optional[str] = None

class EpiRequirementCreate(EpiRequirementBase):
    pass

class EpiRequirement(EpiRequirementBase):
    id: str
    added_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class EpiConfirmationBase(BaseModel):
    order_id: str
    operator_name: str
    epi_rule_version: Optional[str] = None
    items_json: Optional[str] = None
    status: str = 'confirmed'
    blocker_reason: Optional[str] = None

class EpiConfirmationCreate(EpiConfirmationBase):
    pass

class EpiConfirmation(EpiConfirmationBase):
    id: str
    confirmed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MaintenanceRoundBase(BaseModel):
    name: str
    plan_reference: Optional[str] = None
    competence: Optional[str] = None
    status: str = 'in_progress'
    created_by: Optional[str] = None
    notes: Optional[str] = None

class MaintenanceRoundCreate(MaintenanceRoundBase):
    pass

class MaintenanceRound(MaintenanceRoundBase):
    id: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class RoundOrderBase(BaseModel):
    round_id: str
    order_id: str
    sequence: Optional[int] = None

class RoundOrderCreate(RoundOrderBase):
    pass

class RoundOrder(RoundOrderBase):
    id: str
    model_config = ConfigDict(from_attributes=True)


class MaterialRequestBase(BaseModel):
    order_id: Optional[str] = None
    asset_id: Optional[str] = None
    item_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    priority: Optional[str] = 'medium'
    status: str = 'requested'
    requested_by: Optional[str] = None
    supplier: Optional[str] = None
    purchase_order: Optional[str] = None
    notes: Optional[str] = None
    defect_description: Optional[str] = None
    photo_path: Optional[str] = None

class MaterialRequestCreate(MaterialRequestBase):
    pass

class MaterialRequest(MaterialRequestBase):
    id: str
    requested_at: datetime
    received_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ExternalServiceRequestBase(BaseModel):
    order_id: Optional[str] = None
    asset_id: Optional[str] = None
    service_type: Optional[str] = None
    supplier: Optional[str] = None
    status: str = 'requested'
    requested_by: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    document_status: Optional[str] = 'pending'
    laudo_path: Optional[str] = None
    certificate_path: Optional[str] = None
    warranty_until: Optional[date] = None
    operational_status: Optional[str] = None
    notes: Optional[str] = None

class ExternalServiceRequestCreate(ExternalServiceRequestBase):
    pass

class ExternalServiceRequest(ExternalServiceRequestBase):
    id: str
    requested_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NotificationRuleBase(BaseModel):
    event_type: str
    roles_json: Optional[str] = None
    sector_id: Optional[str] = None
    is_active: bool = True
    channel: Optional[str] = 'email'

class NotificationRuleCreate(NotificationRuleBase):
    pass

class NotificationRule(NotificationRuleBase):
    id: str
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class NotificationQueueBase(BaseModel):
    rule_id: Optional[str] = None
    order_id: Optional[str] = None
    event_type: Optional[str] = None
    recipient: str
    channel: str = 'email'
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str = 'pending'
    attempt_count: Optional[int] = 0
    error_msg: Optional[str] = None
    idempotency_key: Optional[str] = None

class NotificationQueueCreate(NotificationQueueBase):
    pass

class NotificationQueue(NotificationQueueBase):
    id: str
    last_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DowntimeRecordBase(BaseModel):
    asset_id: str
    order_id: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_mins: Optional[int] = None
    reason: Optional[str] = None
    released_by: Optional[str] = None
    condition_after: Optional[str] = None
    notes: Optional[str] = None

class DowntimeRecordCreate(DowntimeRecordBase):
    pass

class DowntimeRecord(DowntimeRecordBase):
    id: str
    model_config = ConfigDict(from_attributes=True)


class ChecklistImportLogBase(BaseModel):
    file_name: str
    file_path: Optional[str] = None
    file_hash: str
    rq_cmp_number: Optional[str] = None
    year: Optional[int] = None
    version: Optional[str] = None
    title: Optional[str] = None
    asset_references: Optional[str] = None
    status: str
    classification: Optional[str] = None
    conflicts_json: Optional[str] = None
    checklist_template_id: Optional[str] = None
    checklist_version_id: Optional[str] = None
    items_count: Optional[int] = None
    epi_count: Optional[int] = None
    materials_count: Optional[int] = None
    notes: Optional[str] = None

class ChecklistImportLog(ChecklistImportLogBase):
    id: str
    imported_at: datetime
    model_config = ConfigDict(from_attributes=True)
