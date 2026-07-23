import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Text, Float, Date, CheckConstraint
from sqlalchemy.orm import relationship
from app.database import Base

def generate_uuid():
    return str(uuid.uuid4())

from app.clock import utcnow_naive

def utcnow():
    return utcnow_naive()

class Sector(Base):
    __tablename__ = "sectors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    assets = relationship("Asset", back_populates="sector")

class Asset(Base):
    __tablename__ = "assets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    patrimonio = Column(String(50), nullable=False, index=True) # Não exclusivo por duplicidades na planilha
    type = Column(String(20), nullable=False) # 'machine' ou 'equipment'
    description = Column(String(255), nullable=False)
    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    serial_number = Column(String(100), nullable=True)
    sector_id = Column(String(36), ForeignKey("sectors.id"), nullable=True)
    status = Column(String(20), default="active") # 'active' ou 'inactive'
    is_operable = Column(Boolean, default=True) # False se for Máquina Parada
    last_maintenance_date = Column(DateTime, nullable=True)
    next_maintenance_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # Campos para homologação e integração
    manual = Column(String(255), nullable=True)
    ficha_tecnica = Column(String(255), nullable=True)
    foto = Column(String(255), nullable=True)
    caminho_documentos = Column(String(500), nullable=True)
    has_patrimonio_conflict = Column(Boolean, default=False)
    conflict_patrimonio_suggested = Column(String(50), nullable=True)
    opaque_token = Column(String(64), unique=True, index=True, nullable=True)

    # Governança operacional. O patrimônio de origem é preservado para auditoria,
    # porém a rotina diária não deve misturar máquinas, instrumentos, ferramentas
    # e componentes substituíveis.
    legacy_patrimonio = Column(String(50), nullable=True, index=True)
    # Não é unique no banco: registros legados podem compartilhar patrimônio.
    # A identificação inequívoca para QR/dossiê continua sendo o UUID/token.
    controlled_code = Column(String(80), nullable=True, index=True)
    asset_class = Column(String(40), nullable=False, default="maintainable_asset", index=True)
    maintenance_strategy = Column(String(40), nullable=False, default="preventive", index=True)
    show_in_daily_list = Column(Boolean, nullable=False, default=True, index=True)

    sector = relationship("Sector", back_populates="assets")
    documents = relationship("AssetDocument", back_populates="asset", cascade="all, delete-orphan")
    plans = relationship("MaintenancePlan", back_populates="asset")
    orders = relationship("MaintenanceOrder", back_populates="asset")
    issues = relationship("MaintenanceIssue", back_populates="asset")
    downtime_records = relationship("DowntimeRecord", back_populates="asset")
    material_requests = relationship("MaterialRequest", back_populates="asset")
    external_services = relationship("ExternalServiceRequest", back_populates="asset")
    epi_suggestions = relationship("EpiSuggestion", back_populates="asset")

class AssetDocument(Base):
    __tablename__ = "asset_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    original_name = Column(String(255), nullable=True)
    extension = Column(String(20), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    category = Column(String(50), nullable=True)
    origin = Column(String(50), nullable=True)
    original_path = Column(String(1000), nullable=True)
    internal_path = Column(String(1000), nullable=True)
    thumbnail_path = Column(String(1000), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    imported_at = Column(DateTime, default=utcnow)
    uploaded_by = Column(String(100), nullable=True)
    uploaded_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    status = Column(String(30), default="active", index=True)
    is_primary_photo = Column(Boolean, default=False)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(String(100), nullable=True)
    archived_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    review_status = Column(String(50), nullable=True)
    suggested_asset_id = Column(String(36), nullable=True)
    source_index_id = Column(String(36), nullable=True)
    resolved_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    review_reason = Column(String(255), nullable=True)
    possible_assets_json = Column(Text, nullable=True)

    asset = relationship("Asset", back_populates="documents")


class FileOrganizationTask(Base):
    __tablename__ = "file_organization_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_type = Column(String(50), default="asset_file_organization", nullable=False)
    status = Column(String(30), default="pending", nullable=False, index=True)
    source_paths_json = Column(Text, nullable=True)
    total_files = Column(Integer, default=0)
    analyzed_files = Column(Integer, default=0)
    imported_files = Column(Integer, default=0)
    duplicate_files = Column(Integer, default=0)
    review_files = Column(Integer, default=0)
    error_files = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    report_path = Column(String(1000), nullable=True)
    last_file = Column(String(1000), nullable=True)
    attempt = Column(Integer, default=1)
    pause_requested_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    checkpoint_json = Column(Text, nullable=True)
    worker_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class FileReviewItem(Base):
    __tablename__ = "file_review_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("file_organization_tasks.id"), nullable=True, index=True)
    source_path = Column(String(1000), nullable=False)
    file_name = Column(String(255), nullable=False)
    extension = Column(String(20), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    status = Column(String(30), default="pending", nullable=False, index=True)
    reason_code = Column(String(80), nullable=True)
    reason_message = Column(Text, nullable=True)
    possible_assets_json = Column(Text, nullable=True)
    suggested_asset_id = Column(String(36), nullable=True)
    selected_asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    document_id = Column(String(36), ForeignKey("asset_documents.id"), nullable=True)
    resolved_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    resolved_by_name = Column(String(100), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    code_reference = Column(String(50), nullable=True)
    asset_type = Column(String(20), nullable=False) # 'machine' ou 'equipment'
    is_active = Column(Boolean, default=True)
    # Metadados do modelo de checklist.
    asset_patrimonio = Column(String(50), nullable=True)
    asset_manufacturer = Column(String(100), nullable=True)
    asset_model_ref = Column(String(100), nullable=True)
    epi_summary = Column(Text, nullable=True)  # JSON
    materials_summary = Column(Text, nullable=True)  # JSON
    maintenance_type = Column(String(30), default='preventive')
    rq_cmp_reference = Column(String(50), nullable=True)

    versions = relationship("ChecklistTemplateVersion", back_populates="template", cascade="all, delete-orphan")
    epi_requirements = relationship("EpiRequirement", back_populates="checklist_template")
    epi_suggestions = relationship("EpiSuggestion", back_populates="checklist_template")

class ChecklistTemplateVersion(Base):
    __tablename__ = "checklist_template_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    template_id = Column(String(36), ForeignKey("checklist_templates.id"), nullable=False)
    version = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    # Metadados de versionamento do documento-fonte.
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    source_document = Column(String(500), nullable=True)
    source_document_hash = Column(String(64), nullable=True)
    created_by = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    template = relationship("ChecklistTemplate", back_populates="versions")
    items = relationship("ChecklistItem", back_populates="version", cascade="all, delete-orphan")

class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    version_id = Column(String(36), ForeignKey("checklist_template_versions.id"), nullable=False)
    item_number = Column(String(20), nullable=False)
    description = Column(Text, nullable=False)
    is_mandatory = Column(Boolean, default=True)
    allow_photo = Column(Boolean, default=True)
    is_critical = Column(Boolean, default=False)
    suggested_materials = Column(Text, nullable=True)
    # Regras de resposta do item.
    item_type = Column(String(30), default='inspection')  # 'inspection', 'service', 'measurement'
    not_applicable_reasons = Column(Text, nullable=True)  # JSON

    version = relationship("ChecklistTemplateVersion", back_populates="items")

class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    periodicity = Column(String(50), nullable=False) # 'monthly', 'bimonthly', 'trimonthly', 'semiannual', 'annual', 'custom'
    frequency_days = Column(Integer, nullable=True)
    frequency_months = Column(Integer, nullable=True)
    planned_month = Column(Integer, nullable=True) # 1 a 12
    next_due_date = Column(Date, nullable=True)
    checklist_template_version_id = Column(String(36), ForeignKey("checklist_template_versions.id"), nullable=True)
    estimated_duration_mins = Column(Integer, default=60)
    calculation_basis = Column(String(30), default="fixed_calendar")
    plan_type = Column(String(30), default="fixed_calendar")
    fixed_months = Column(Text, nullable=True)
    generation_horizon_months = Column(Integer, default=12)
    confidence = Column(String(10), default="medium")
    source_document = Column(String(500), nullable=True)
    source_document_hash = Column(String(64), nullable=True)
    source_document_page = Column(String(50), nullable=True)
    last_auto_generated_at = Column(DateTime, nullable=True)
    confirmed_by = Column(String(100), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    recurrence_status = Column(String(30), default="to_review")
    recurrence_confirmed_by = Column(String(100), nullable=True)
    recurrence_confirmed_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    safety_instructions = Column(Text, nullable=True)
    is_monthly_competency = Column(Boolean, default=False)

    asset = relationship("Asset", back_populates="plans")
    orders = relationship("MaintenanceOrder", back_populates="plan")
    epi_requirements = relationship("EpiRequirement", back_populates="plan")
    epi_suggestions = relationship("EpiSuggestion", back_populates="plan")

class MaintenanceOrder(Base):
    __tablename__ = "maintenance_orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    friendly_number = Column(Integer, unique=True, index=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    plan_id = Column(String(36), ForeignKey("maintenance_plans.id"), nullable=True)
    checklist_version_id = Column(String(36), ForeignKey("checklist_template_versions.id"), nullable=True)
    planned_date = Column(Date, nullable=True)
    planned_year = Column(Integer, nullable=True)
    planned_month = Column(Integer, nullable=True)
    original_competence = Column(String(7), nullable=True)
    scheduled_day_is_explicit = Column(Boolean, default=False)
    source_status = Column(String(30), nullable=True)
    source_note = Column(Text, nullable=True)
    original_date = Column(Date, nullable=True)
    rescheduled_date = Column(Date, nullable=True)
    reschedule_reason = Column(String(255), nullable=True)
    priority = Column(String(20), default="medium")
    status = Column(String(30), default="scheduled")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_mins = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    final_condition = Column(String(30), default="released")
    operator_name = Column(String(100), nullable=True)
    operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    is_monthly_competency = Column(Boolean, default=False)
    opaque_token = Column(String(64), unique=True, index=True, nullable=True)
    idempotency_key = Column(String(80), unique=True, nullable=True, index=True)
    execution_status = Column(String(30), default="not_started")
    needs_review = Column(Boolean, default=False)
    review_decision = Column(String(30), nullable=True)
    review_operator = Column(String(100), nullable=True)
    review_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    source_file_hash = Column(String(64), nullable=True)
    source_sheet = Column(String(50), nullable=True)
    source_row = Column(Integer, nullable=True)
    source_cell = Column(String(20), nullable=True)
    source_value_130 = Column(String(20), nullable=True)
    rules_engine_version = Column(String(10), nullable=True)
    deadline_calculated_at = Column(DateTime, nullable=True)
    # Metadados de execução e relacionamento da OM.
    order_type = Column(String(30), default='preventive')  # 'preventive', 'corrective', 'rework', 'external', 'inspection'
    parent_work_order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    relation_type = Column(String(30), nullable=True)  # 'rework', 'corrective_from_preventive', 'continuation', etc.
    occurrence_number = Column(Integer, nullable=True)
    plan_code = Column(String(50), nullable=True)
    epi_confirmed = Column(Boolean, default=False)
    epi_confirmed_at = Column(DateTime, nullable=True)
    epi_confirmed_by = Column(String(100), nullable=True)
    machine_stopped = Column(Boolean, default=False)
    machine_stopped_at = Column(DateTime, nullable=True)
    machine_released_at = Column(DateTime, nullable=True)
    final_json = Column(Text, nullable=True)
    final_pdf_path = Column(String(500), nullable=True)
    final_sha256 = Column(String(64), nullable=True)
    # A pessoa que registra/conferiu no tablet não é necessariamente quem
    # executou fisicamente a manutenção. Ambos permanecem no histórico.
    performed_by_name = Column(String(100), nullable=True)
    performed_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    performed_by_snapshot = Column(String(100), nullable=True)
    # Participantes adicionais são uma fotografia em JSON. O responsável
    # principal continua sendo o campo acima, o que deixa a leitura simples no
    # histórico e preserva os demais nomes quando houver trabalho em equipe.
    performed_by_participants_json = Column(Text, nullable=True)
    final_pdf_sha256 = Column(String(64), nullable=True)
    final_revision = Column(Integer, default=1)
    # Nome fixado da pasta no NAS. Evita que a mesma OM ganhe duas pastas
    # quando a primeira evidência é sincronizada antes da conclusão.
    dossier_folder_name = Column(String(255), nullable=True)
    # Classifica a finalidade do registro sem apagar a evidência.  Apenas
    # ``official`` alimenta a programação, os indicadores e a conformidade.
    # ``demo_test`` guarda demonstrações/homologações completas, mas separadas
    # da operação real; ``not_performed`` explica um checklist abandonado.
    record_kind = Column(String(30), nullable=False, default="official")
    record_kind_reason = Column(Text, nullable=True)
    record_kind_classified_at = Column(DateTime, nullable=True)
    record_kind_classified_by = Column(String(100), nullable=True)
    round_id = Column(String(36), ForeignKey("maintenance_rounds.id"), nullable=True)
    reservation_operator = Column(String(100), nullable=True)
    reservation_device_id = Column(String(100), nullable=True)
    reservation_started_at = Column(DateTime, nullable=True)
    reservation_expires_at = Column(DateTime, nullable=True)

    asset = relationship("Asset", back_populates="orders")
    plan = relationship("MaintenancePlan", back_populates="orders")
    items = relationship("MaintenanceOrderItem", back_populates="order", cascade="all, delete-orphan")
    evidences = relationship("MaintenanceEvidence", back_populates="order")
    materials = relationship("MaintenanceMaterial", back_populates="order", cascade="all, delete-orphan")
    issues = relationship("MaintenanceIssue", back_populates="order")
    events = relationship("WorkOrderEvent", back_populates="order", cascade="all, delete-orphan")
    snapshot = relationship("WorkOrderSnapshot", back_populates="order", uselist=False, cascade="all, delete-orphan")
    corrections = relationship("WorkOrderCorrection", back_populates="order", cascade="all, delete-orphan")
    epi_confirmations = relationship("EpiConfirmation", back_populates="order", cascade="all, delete-orphan")
    material_requests = relationship("MaterialRequest", back_populates="order")
    external_services = relationship("ExternalServiceRequest", back_populates="order")
    downtime_records = relationship("DowntimeRecord", back_populates="order")
    parent_order = relationship("MaintenanceOrder", remote_side="MaintenanceOrder.id", foreign_keys=[parent_work_order_id])

class MaintenanceOrderItem(Base):
    __tablename__ = "maintenance_order_items"
    __table_args__ = (
        CheckConstraint("status IN ('unanswered','ok','attention','not_applicable')", name="ck_order_item_status"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    item_id = Column(String(36), ForeignKey("checklist_items.id"), nullable=False)
    status = Column(String(20), default="unanswered")
    notes = Column(Text, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    operator_name = Column(String(100), nullable=True)
    operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    # Metadados da resposta operacional.
    defect_found = Column(Text, nullable=True)
    corrected_in_place = Column(Boolean, nullable=True)
    correction_description = Column(Text, nullable=True)
    needs_part = Column(Boolean, nullable=True)
    part_name = Column(String(255), nullable=True)
    can_operate = Column(Boolean, nullable=True)
    not_applicable_reason = Column(String(100), nullable=True)
    audio_transcript = Column(Text, nullable=True)
    photo_category = Column(String(30), nullable=True)

    order = relationship("MaintenanceOrder", back_populates="items")

class MaintenanceEvidence(Base):
    __tablename__ = "maintenance_evidences"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    order_item_id = Column(String(36), ForeignKey("maintenance_order_items.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    evidence_type = Column(String(30), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    # Declaração de autoria (sem login/RBAC): preserva a pessoa selecionada e
    # o contexto do aparelho em cada arquivo, inclusive nos anexos legados.
    uploader_name = Column(String(100), nullable=True)
    uploader_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    device_id = Column(String(100), nullable=True)
    captured_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=utcnow)
    source = Column(String(30), default="web")
    original_filename = Column(String(255), nullable=True)
    mime_type = Column(String(120), nullable=True)
    file_size = Column(Integer, nullable=True)
    dossier_status = Column(String(30), default="pending", index=True)
    dossier_path = Column(String(1000), nullable=True)
    dossier_synced_at = Column(DateTime, nullable=True)

    order = relationship("MaintenanceOrder", back_populates="evidences")

class MaintenanceMaterial(Base):
    __tablename__ = "maintenance_materials"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    name = Column(String(255), nullable=False)
    quantity_text = Column(String(50), nullable=True)

    order = relationship("MaintenanceOrder", back_populates="materials")

class MaintenanceIssue(Base):
    __tablename__ = "maintenance_issues"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(String(20), default="medium")
    is_operable_affected = Column(Boolean, default=False)
    status = Column(String(20), default="open")
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    operator_name = Column(String(100), nullable=True)
    repair_description = Column(Text, nullable=True)
    final_condition = Column(String(30), nullable=True)
    resolution_date = Column(Date, nullable=True)
    evidence_file_path = Column(String(500), nullable=True)

    asset = relationship("Asset", back_populates="issues")
    order = relationship("MaintenanceOrder", back_populates="issues")


class QualityNonconformity(Base):
    """Registro formal de não conformidade e ação corretiva (CAPA).

    Não substitui a ocorrência simples de manutenção: este registro mantém a
    decisão de qualidade, contenção, causa, ação, eficácia e reabertura.
    """
    __tablename__ = "quality_nonconformities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(40), nullable=False, unique=True, index=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True, index=True)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True, index=True)
    issue_id = Column(String(36), ForeignKey("maintenance_issues.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    requirement_reference = Column(String(500), nullable=True)
    severity = Column(String(20), default="medium", nullable=False)
    status = Column(String(30), default="open", nullable=False, index=True)
    detected_at = Column(DateTime, default=utcnow, nullable=False)
    detected_by_name = Column(String(100), nullable=True)
    detected_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    device_id = Column(String(100), nullable=True)
    containment_action = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    corrective_action = Column(Text, nullable=True)
    action_owner_name = Column(String(100), nullable=True)
    due_date = Column(Date, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    effectiveness_review = Column(Text, nullable=True)
    effectiveness_verified_at = Column(DateTime, nullable=True)
    effectiveness_verified_by = Column(String(100), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String(100), nullable=True)
    reopened_at = Column(DateTime, nullable=True)
    reopen_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)


class DossierSyncJob(Base):
    """Fila persistente de espelhamento para o NAS, com tentativa e hash."""
    __tablename__ = "dossier_sync_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False, index=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False, index=True)
    status = Column(String(30), default="pending", nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    requested_at = Column(DateTime, default=utcnow, nullable=False)
    requested_by = Column(String(100), nullable=True)
    requested_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    device_id = Column(String(100), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    target_path = Column(String(1000), nullable=True)
    manifest_hash = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    action = Column(String(100), nullable=False)
    entity_name = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    origin = Column(String(30), default="web")
    operator_name = Column(String(100), nullable=True)
    selected_user_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    actor_name_snapshot = Column(String(100), nullable=True)
    device_id = Column(String(100), nullable=True)
    session_id = Column(String(100), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True)
    route = Column(String(255), nullable=True)
    method = Column(String(12), nullable=True)
    status_code = Column(Integer, nullable=True)
    client_host = Column(String(100), nullable=True)
    app_version = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=utcnow)

class Operator(Base):
    __tablename__ = "operators"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, index=True)
    normalized_name = Column(String(120), nullable=True, index=True)
    nickname = Column(String(100), nullable=True)
    sector_id = Column(String(36), ForeignKey("sectors.id"), nullable=True)
    origin = Column(String(30), default="manual")
    role = Column(String(30), default="operator", index=True)
    pin_hash = Column(String(255), nullable=True)
    photo_path = Column(String(1000), nullable=True)
    photo_thumbnail_path = Column(String(1000), nullable=True)
    photo_hash = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, nullable=True)
    created_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(String(100), nullable=True)
    archived_by_operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    # Classificações de uso para simplificar o tablet. Não são RBAC nem
    # bloqueiam a Gestão; definem apenas em qual seletor a pessoa aparece.
    can_record_checklist = Column(Boolean, default=False, nullable=False, index=True)
    can_execute_maintenance = Column(Boolean, default=True, nullable=False, index=True)

    @property
    def photo_url(self):
        return f"/operators/{self.id}/photo" if self.photo_path else None

    @property
    def photo_thumbnail_url(self):
        return f"/operators/{self.id}/photo/thumbnail" if self.photo_thumbnail_path else None

class LegacyHistory(Base):
    __tablename__ = "legacy_history"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    planned_year = Column(Integer, nullable=True)
    planned_month = Column(Integer, nullable=True)
    planned_date = Column(String(10), nullable=True)
    source_value = Column(String(20), nullable=True)
    source_file = Column(String(255), nullable=True)
    source_file_hash = Column(String(64), nullable=True)
    source_sheet = Column(String(50), nullable=True)
    source_row = Column(Integer, nullable=True)
    source_cell = Column(String(20), nullable=True)
    interpretation = Column(String(30), nullable=True)
    interpretation_confidence = Column(String(20), nullable=True)
    operator_name = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

class AssetMeter(Base):
    __tablename__ = "asset_meters"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    meter_type = Column(String(50), nullable=False)
    unit = Column(String(20), nullable=False)
    current_reading = Column(Float, default=0.0)
    last_reading_at = Column(DateTime, nullable=True)
    maintenance_interval = Column(Float, nullable=False)
    next_maintenance_at = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)

class QualityConfig(Base):
    __tablename__ = "quality_config"
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow)


class WorkOrderSequence(Base):
    __tablename__ = "work_order_sequence"

    name = Column(String(50), primary_key=True)
    next_value = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=utcnow)

class AssetDocumentIndex(Base):
    __tablename__ = "asset_document_index"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_extension = Column(String(10), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=False)
    document_type = Column(String(50), nullable=False)
    confidence = Column(String(20), nullable=True)
    extracted_text = Column(Text, nullable=True)
    extraction_method = Column(String(30), nullable=True)
    needs_review = Column(Boolean, default=False)
    indexed_at = Column(DateTime, default=utcnow)
    notes = Column(Text, nullable=True)

# ============================================================
# MODELOS OPERACIONAIS DE EXECUÇÃO
# ============================================================

class WorkOrderEvent(Base):
    """Linha do tempo imutável de cada OM."""
    __tablename__ = "work_order_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    event_type = Column(String(50), nullable=False)  # 'created', 'opened', 'started', 'paused', 'resumed', 'completed', 'cancelled', 'corrected', 'email_sent', 'part_requested', 'machine_stopped', 'machine_released'
    operator_name = Column(String(100), nullable=True)
    operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    payload = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=utcnow, nullable=False)

    order = relationship("MaintenanceOrder", back_populates="events")

class WorkOrderSnapshot(Base):
    """Fotografia lógica imutável da OM no momento da criação."""
    __tablename__ = "work_order_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False, unique=True)
    snapshot_json = Column(Text, nullable=False)  # JSON completo com ativo, plano, checklist, EPI, etc.
    created_at = Column(DateTime, default=utcnow, nullable=False)

    order = relationship("MaintenanceOrder", back_populates="snapshot")

class WorkOrderCorrection(Base):
    """Registro de correções posteriores auditadas."""
    __tablename__ = "work_order_corrections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    operator_name = Column(String(100), nullable=True)
    operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    document_path = Column(String(500), nullable=True)
    document_sha256 = Column(String(64), nullable=True)
    document_revision = Column(Integer, nullable=True)

    order = relationship("MaintenanceOrder", back_populates="corrections")

class EpiRequirement(Base):
    """EPIs obrigatórios por plano ou modelo de checklist."""
    __tablename__ = "epi_requirements"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_id = Column(String(36), ForeignKey("maintenance_plans.id"), nullable=True)
    checklist_template_id = Column(String(36), ForeignKey("checklist_templates.id"), nullable=True)
    item_name = Column(String(200), nullable=False)
    ca_number = Column(String(50), nullable=True)
    validity = Column(String(50), nullable=True)
    is_mandatory = Column(Boolean, default=True)
    added_by = Column(String(100), nullable=True)
    added_at = Column(DateTime, default=utcnow)

    plan = relationship("MaintenancePlan", back_populates="epi_requirements")
    checklist_template = relationship("ChecklistTemplate", back_populates="epi_requirements")

class EpiConfirmation(Base):
    """Confirmação de EPI por execução de OM."""
    __tablename__ = "epi_confirmations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    operator_name = Column(String(100), nullable=False)
    operator_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    epi_rule_version = Column(String(50), nullable=True)
    confirmed_at = Column(DateTime, default=utcnow, nullable=False)
    items_json = Column(Text, nullable=True)  # JSON com lista de EPIs confirmados
    status = Column(String(20), default='confirmed')  # 'confirmed', 'blocked', 'bypassed'
    blocker_reason = Column(String(255), nullable=True)

    order = relationship("MaintenanceOrder", back_populates="epi_confirmations")

class MaintenanceRound(Base):
    """Rodada de manutenção agrupando múltiplos ativos (RQ-CMP com vários patrimônios)."""
    __tablename__ = "maintenance_rounds"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    plan_reference = Column(String(100), nullable=True)  # ex: RQ-CMP-011
    competence = Column(String(7), nullable=True)  # YYYY-MM
    status = Column(String(30), default='in_progress')  # 'in_progress', 'completed', 'cancelled'
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    round_orders = relationship("RoundOrder", back_populates="round", cascade="all, delete-orphan")

class RoundOrder(Base):
    """Vínculo entre rodada de manutenção e ordens individuais."""
    __tablename__ = "round_orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    round_id = Column(String(36), ForeignKey("maintenance_rounds.id"), nullable=False)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=False)
    sequence = Column(Integer, nullable=True)

    round = relationship("MaintenanceRound", back_populates="round_orders")
    order = relationship("MaintenanceOrder")

class MaterialRequest(Base):
    """Solicitação de material ou peça para Compras."""
    __tablename__ = "material_requests"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Float, nullable=True)
    unit = Column(String(50), nullable=True)
    priority = Column(String(20), default='medium')
    status = Column(String(30), default='requested')  # 'requested', 'available', 'reserved', 'in_quotation', 'purchased', 'received', 'applied', 'cancelled'
    requested_by = Column(String(100), nullable=True)
    requested_at = Column(DateTime, default=utcnow, nullable=False)
    supplier = Column(String(255), nullable=True)
    purchase_order = Column(String(100), nullable=True)
    received_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    defect_description = Column(Text, nullable=True)
    photo_path = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    order = relationship("MaintenanceOrder", back_populates="material_requests")
    asset = relationship("Asset", back_populates="material_requests")

class ExternalServiceRequest(Base):
    """Solicitação de assistência técnica externa."""
    __tablename__ = "external_service_requests"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    service_type = Column(String(100), nullable=True)
    supplier = Column(String(255), nullable=True)
    status = Column(String(30), default='requested')  # 'requested', 'scheduled', 'in_progress', 'completed', 'cancelled'
    requested_at = Column(DateTime, default=utcnow, nullable=False)
    requested_by = Column(String(100), nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    document_status = Column(String(30), default='pending')  # 'pending', 'complete', 'laudo_pending', 'certificate_pending'
    laudo_path = Column(String(500), nullable=True)
    certificate_path = Column(String(500), nullable=True)
    warranty_until = Column(Date, nullable=True)
    operational_status = Column(String(30), nullable=True)  # 'stopped', 'released', 'released_with_attention'
    notes = Column(Text, nullable=True)

    order = relationship("MaintenanceOrder", back_populates="external_services")
    asset = relationship("Asset", back_populates="external_services")

class NotificationRule(Base):
    """Regra de notificação dinâmica por evento/função/setor."""
    __tablename__ = "notification_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    event_type = Column(String(100), nullable=False)  # 'machine_stopped', 'order_completed', 'order_overdue', etc.
    roles_json = Column(Text, nullable=True)  # JSON lista de destinatários/papéis
    sector_id = Column(String(36), nullable=True)
    is_active = Column(Boolean, default=True)
    channel = Column(String(20), default='email')
    created_at = Column(DateTime, default=utcnow)

    queue_items = relationship("NotificationQueue", back_populates="rule")

class NotificationQueue(Base):
    """Fila de saída de notificações com idempotência e retry."""
    __tablename__ = "notification_queue"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    rule_id = Column(String(36), ForeignKey("notification_rules.id"), nullable=True)
    order_id = Column(String(36), nullable=True)
    event_type = Column(String(100), nullable=True)
    recipient = Column(String(255), nullable=False)
    channel = Column(String(20), default='email')
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String(30), default='pending')  # 'pending', 'sent', 'failed', 'skipped'
    attempt_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)
    idempotency_key = Column(String(120), unique=True, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    rule = relationship("NotificationRule", back_populates="queue_items")

class DowntimeRecord(Base):
    """Registro de parada de máquina com histórico preservado após liberação."""
    __tablename__ = "downtime_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=False)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    duration_mins = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    released_by = Column(String(100), nullable=True)
    condition_after = Column(String(30), nullable=True)  # 'released', 'released_with_attention'
    notes = Column(Text, nullable=True)

    asset = relationship("Asset", back_populates="downtime_records")
    order = relationship("MaintenanceOrder", back_populates="downtime_records")

class ChecklistImportLog(Base):
    """Rastreabilidade da importação de checklists DOCX."""
    __tablename__ = "checklist_import_log"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_hash = Column(String(64), nullable=False)
    rq_cmp_number = Column(String(20), nullable=True)
    year = Column(Integer, nullable=True)
    version = Column(String(20), nullable=True)
    title = Column(String(500), nullable=True)
    asset_references = Column(Text, nullable=True)  # JSON
    status = Column(String(30), nullable=False)  # 'imported', 'conflict', 'duplicate', 'error', 'skipped'
    classification = Column(String(50), nullable=True)
    conflicts_json = Column(Text, nullable=True)  # JSON
    checklist_template_id = Column(String(36), nullable=True)
    checklist_version_id = Column(String(36), nullable=True)
    items_count = Column(Integer, nullable=True)
    epi_count = Column(Integer, nullable=True)
    materials_count = Column(Integer, nullable=True)
    imported_at = Column(DateTime, default=utcnow, nullable=False)
    notes = Column(Text, nullable=True)

# ============================================================
# MOTOR DE INTELIGÊNCIA OPERACIONAL E SEGURANÇA
# ============================================================

class EpiCatalog(Base):
    """Catálogo de EPIs normalizado."""
    __tablename__ = "epi_catalog"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False, unique=True, index=True)
    category = Column(String(100), nullable=False) # ex: 'proteção auditiva', 'proteção das mãos'
    description = Column(Text, nullable=True)
    exige_ca = Column(Boolean, default=True)
    observacoes = Column(Text, nullable=True)
    ativo = Column(Boolean, default=True)

    # Campos reais para homologação de CA.
    ca_number = Column(String(50), nullable=True)
    ca_status = Column(String(50), nullable=True) # ex: 'Vigente', 'Expirado', 'Cancelado'
    ca_validity = Column(Date, nullable=True)
    ca_consulted_at = Column(DateTime, nullable=True)
    ca_source = Column(String(255), nullable=True) # ex: 'Consulta CA / MTE'

    rule_items = relationship("EpiRuleItem", back_populates="epi_catalog")

class SafetyHazard(Base):
    """Catálogo de Perigos/Riscos normatizados."""
    __tablename__ = "safety_hazards"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

class SafetyTask(Base):
    """Tarefas operacionais normatizadas."""
    __tablename__ = "safety_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

class EpiRule(Base):
    """Regras de EPI aprovadas ou sugeridas por escopo."""
    __tablename__ = "epi_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    scope = Column(String(50), nullable=False) # 'plant', 'sector', 'asset_family', 'asset_type', 'manufacturer_model', 'checklist_template', 'checklist_version', 'task', 'plan', 'asset'
    scope_id = Column(String(100), nullable=True) # ID do ativo, plano, setor, etc.
    status = Column(String(30), default="suggested") # 'suggested', 'under_review', 'approved', 'rejected', 'deprecated', 'conflict'
    version = Column(Integer, default=1)
    valid_from = Column(Date, nullable=True)
    valid_until = Column(Date, nullable=True)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)
    document_origin = Column(String(255), nullable=True)
    hash_origin = Column(String(64), nullable=True)
    confidence = Column(String(20), default="medium") # 'high', 'medium', 'low'
    created_at = Column(DateTime, default=utcnow, nullable=False)
    supersedes_rule_id = Column(String(36), ForeignKey("epi_rules.id"), nullable=True)

    rule_items = relationship("EpiRuleItem", back_populates="rule", cascade="all, delete-orphan")
    rule_sources = relationship("EpiRuleSource", back_populates="rule", cascade="all, delete-orphan")

class EpiRuleItem(Base):
    """Itens associados a cada regra de EPI."""
    __tablename__ = "epi_rule_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    rule_id = Column(String(36), ForeignKey("epi_rules.id"), nullable=False)
    epi_catalog_id = Column(String(36), ForeignKey("epi_catalog.id"), nullable=False)
    obrigatoriedade = Column(String(30), default="mandatory") # 'mandatory', 'recommended', 'optional'
    condicao = Column(Text, nullable=True)
    observacao = Column(Text, nullable=True)
    sequencia = Column(Integer, default=0)

    rule = relationship("EpiRule", back_populates="rule_items")
    epi_catalog = relationship("EpiCatalog", back_populates="rule_items")

class EpiRuleSource(Base):
    """Rastreabilidade das fontes de evidência que originaram a regra."""
    __tablename__ = "epi_rule_sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    rule_id = Column(String(36), ForeignKey("epi_rules.id"), nullable=False)
    source_type = Column(String(50), nullable=False) # 'document', 'checklist', 'manual', 'pgr', 'similar_assets', 'history'
    source_path = Column(String(500), nullable=True)
    source_hash = Column(String(64), nullable=True)
    reference = Column(String(255), nullable=True) # ex: 'PGR Pág. 10', 'Checklist Item 3'
    extracted_text = Column(Text, nullable=True)
    evidence_strength = Column(String(20), default="medium") # 'strong', 'medium', 'weak'

    rule = relationship("EpiRule", back_populates="rule_sources")

class EpiSuggestion(Base):
    """Sugestões de segurança/EPI para os 106 planos operacionais."""
    __tablename__ = "epi_suggestions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_id = Column(String(36), ForeignKey("maintenance_plans.id"), nullable=True)
    checklist_template_id = Column(String(36), ForeignKey("checklist_templates.id"), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    items_json = Column(Text, nullable=True) # JSON lista de EPIs sugeridos
    hazards_json = Column(Text, nullable=True) # JSON lista de perigos associados
    confidence = Column(String(20), default="medium") # 'high', 'medium', 'low'
    evidence_json = Column(Text, nullable=True) # JSON justificativas e fontes
    similarity_score = Column(Float, default=0.0)
    status = Column(String(30), default="suggested") # 'suggested', 'under_review', 'approved', 'rejected', 'conflict'
    decision = Column(String(30), nullable=True) # 'approved', 'rejected', 'edited'
    decided_by = Column(String(100), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    plan = relationship("MaintenancePlan", back_populates="epi_suggestions")
    checklist_template = relationship("ChecklistTemplate", back_populates="epi_suggestions")
    asset = relationship("Asset", back_populates="epi_suggestions")



class OfflineSyncOperation(Base):
    """Operações capturadas de tablets/celulares offline para sincronização idempotente."""
    __tablename__ = "offline_sync_operations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_op_id = Column(String(120), unique=True, nullable=False, index=True)
    operation_type = Column(String(50), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("maintenance_orders.id"), nullable=True, index=True)
    entity_name = Column(String(80), nullable=True)
    entity_id = Column(String(80), nullable=True)
    payload_json = Column(Text, nullable=True)
    response_json = Column(Text, nullable=True)
    status = Column(String(30), default="pending", nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    operator_name = Column(String(100), nullable=True)
    selected_user_id = Column(String(36), ForeignKey("operators.id"), nullable=True)
    device_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    received_at = Column(DateTime, default=utcnow, nullable=False)
    applied_at = Column(DateTime, nullable=True)


class DocumentOcrJob(Base):
    """Fila auditável de OCR/extração textual com revisão humana posterior."""
    __tablename__ = "document_ocr_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_kind = Column(String(40), nullable=False, index=True)
    source_id = Column(String(36), nullable=True, index=True)
    file_path = Column(String(1000), nullable=False)
    file_hash = Column(String(64), nullable=True, index=True)
    status = Column(String(30), default="pending", nullable=False, index=True)
    method = Column(String(50), nullable=True)
    extracted_text = Column(Text, nullable=True)
    needs_review = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    attempt = Column(Integer, default=0)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class SystemBackupRun(Base):
    """Histórico de backups/restore-test executados por script ou interface."""
    __tablename__ = "system_backup_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    kind = Column(String(40), default="manual", nullable=False)
    status = Column(String(30), nullable=False, index=True)
    database_path = Column(String(1000), nullable=True)
    backup_path = Column(String(1000), nullable=True)
    backup_sha256 = Column(String(64), nullable=True)
    restore_test_ok = Column(Boolean, default=False)
    report_json = Column(Text, nullable=True)
    executed_by = Column(String(100), nullable=True)


class SemanticDocumentChunk(Base):
    """Chunks preparados para futura busca semântica/RAG local.

    A versão atual cria a estrutura e o reindexador, mas não força dependência de modelo
    vetorial. Se embeddings estiverem configurados, vector_json guarda o vetor local.
    """
    __tablename__ = "semantic_document_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_kind = Column(String(40), nullable=False, index=True)
    source_id = Column(String(36), nullable=False, index=True)
    chunk_index = Column(Integer, default=0, nullable=False)
    title = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False, index=True)
    vector_json = Column(Text, nullable=True)
    embedding_model = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

class SystemValidationRun(Base):
    """Execuções salvas do diagnóstico operacional para auditoria/Codex."""
    __tablename__ = "system_validation_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    kind = Column(String(50), default="manual", nullable=False)
    status = Column(String(30), nullable=False, index=True)
    score = Column(Integer, default=0, nullable=False)
    executed_by = Column(String(100), nullable=True)
    report_json = Column(Text, nullable=False)
