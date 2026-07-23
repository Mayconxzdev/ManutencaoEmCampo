"""Geração de relatórios PDF do Manutenção em Campo.

Os relatórios respeitam competências mensais: quando a planilha não informa um
dia, o PDF mostra apenas mês/ano e nunca inventa o dia 1º.
"""
from __future__ import annotations

import io
import json
import hashlib
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clock import format_local_datetime, local_now, local_today
from app.config import APP_VERSION, UPLOADS_DIR
from app.models import (
    Asset,
    ChecklistItem,
    MaintenanceIssue,
    MaintenanceOrder,
    WorkOrderCorrection,
)

MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def competence_text(order: MaintenanceOrder) -> str:
    if order.scheduled_day_is_explicit and order.planned_date:
        return order.planned_date.strftime("%d/%m/%Y")
    if order.planned_year and order.planned_month:
        return f"{MONTHS_PT[order.planned_month - 1]} de {order.planned_year}"
    if order.original_competence:
        try:
            year, month = map(int, order.original_competence.split("-"))
            return f"{MONTHS_PT[month - 1]} de {year}"
        except Exception:
            return order.original_competence
    return "Não informado"


def status_text(value: Optional[str]) -> str:
    return {
        "scheduled": "Programada",
        "today": "Pendente neste mês",
        "in_progress": "Em andamento",
        "overdue": "Atrasada",
        "completed": "Concluída",
        "completed_with_issues": "Concluída com pendência",
        "demo_completed": "Teste/demonstração concluído",
        "cancelled": "Cancelada",
    }.get(value or "", value or "Não informado")


def record_kind_text(value: Optional[str]) -> str:
    return "TESTE / DEMONSTRAÇÃO — NÃO CONTA COMO MANUTENÇÃO OFICIAL" if value == "demo_test" else "MANUTENÇÃO OFICIAL"


def final_condition_text(value: Optional[str]) -> str:
    return {
        "released": "Liberada",
        "released_with_attention": "Liberada com atenção",
        "stopped": "Máquina parada",
    }.get(value or "", value or "Não informado")


def checklist_result_text(value: Optional[str]) -> str:
    return {
        "unanswered": "",
        "ok": "OK",
        "attention": "DEF",
        "not_applicable": "N/A",
    }.get(value or "", value or "")


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ManutencaoEmCampoTitle", parent=styles["Heading1"], fontSize=17,
            leading=21, textColor=colors.HexColor("#1A365D"), spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "ManutencaoEmCampoSection", parent=styles["Heading2"], fontSize=11,
            leading=14, textColor=colors.HexColor("#2B6CB0"),
            spaceBefore=8, spaceAfter=5,
        ),
        "normal": ParagraphStyle(
            "ManutencaoEmCampoNormal", parent=styles["Normal"], fontSize=8.5, leading=10.5,
        ),
        "bold": ParagraphStyle(
            "ManutencaoEmCampoBold", parent=styles["Normal"], fontSize=8.5,
            leading=10.5, fontName="Helvetica-Bold",
        ),
        "header": ParagraphStyle(
            "ManutencaoEmCampoHeader", parent=styles["Normal"], fontSize=8,
            leading=9.5, textColor=colors.white, fontName="Helvetica-Bold",
        ),
    }


def _table(data, widths, header_color="#1A365D"):
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def generate_correction_addendum_pdf(order: MaintenanceOrder, correction: WorkOrderCorrection) -> io.BytesIO:
    """Gera o adendo separado de uma correção, sem substituir o PDF original."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm)
    st = _styles()
    asset = order.asset
    story = [
        Paragraph("ADENDO DE CORREÇÃO — RASTREABILIDADE", st["title"]),
        Paragraph("Este documento complementa o PDF final original. Ele não apaga nem substitui a versão anterior.", st["normal"]),
        Spacer(1, 0.35 * cm),
        _table([
            [Paragraph("Ordem", st["header"]), Paragraph("Ativo", st["header"]), Paragraph("Revisão", st["header"]), Paragraph("Data", st["header"])],
            [
                Paragraph(f"OM {order.friendly_number or order.id}", st["normal"]),
                Paragraph(f"{getattr(asset, 'description', '')}<br/>{getattr(asset, 'controlled_code', None) or getattr(asset, 'patrimonio', '')}", st["normal"]),
                Paragraph(f"v{correction.document_revision or order.final_revision or 1}", st["normal"]),
                Paragraph(format_local_datetime(correction.created_at), st["normal"]),
            ],
        ], [3.2 * cm, 7.0 * cm, 2.0 * cm, 3.5 * cm]),
        Spacer(1, 0.45 * cm),
        Paragraph("CORREÇÃO REGISTRADA", st["section"]),
        _table([
            [Paragraph("Campo", st["header"]), Paragraph("Valor anterior", st["header"]), Paragraph("Novo valor", st["header"])],
            [
                Paragraph(correction.field_name or "Não informado", st["normal"]),
                Paragraph(correction.old_value or "Não informado", st["normal"]),
                Paragraph(correction.new_value or "Não informado", st["normal"]),
            ],
        ], [4.0 * cm, 6.0 * cm, 6.0 * cm]),
        Spacer(1, 0.35 * cm),
        Paragraph("JUSTIFICATIVA", st["section"]),
        Paragraph(correction.reason or "Não informada", st["normal"]),
        Spacer(1, 0.35 * cm),
        Paragraph("RESPONSÁVEL PELA CORREÇÃO", st["section"]),
        Paragraph(correction.operator_name or "Não informado", st["normal"]),
        Spacer(1, 0.55 * cm),
        Paragraph("Integridade: o PDF final original continua preservado; este adendo registra apenas a alteração posterior e sua justificativa.", st["normal"]),
    ]
    doc.build(story)
    buffer.seek(0)
    return buffer


async def generate_monthly_schedule_pdf(
    db: AsyncSession,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> io.BytesIO:
    today = local_today()
    year = year or today.year
    month = month or today.month
    if month < 1 or month > 12:
        raise ValueError("Mês inválido")

    query = (
        select(MaintenanceOrder)
        .where(MaintenanceOrder.planned_year == year, MaintenanceOrder.planned_month == month)
        .options(selectinload(MaintenanceOrder.asset).selectinload(Asset.sector))
        .order_by(MaintenanceOrder.status, MaintenanceOrder.friendly_number)
    )
    result = await db.execute(query)
    orders = result.scalars().all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=1.2 * cm, leftMargin=1.2 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
    )
    st = _styles()
    story = [
        Paragraph(f"Programação de Manutenção — {MONTHS_PT[month - 1].title()} de {year}", st["title"]),
        Paragraph(f"Gerado em {local_now().strftime('%d/%m/%Y %H:%M')}", st["normal"]),
        Spacer(1, 8),
    ]
    rows = [[
        Paragraph("OM", st["header"]), Paragraph("Patrimônio", st["header"]),
        Paragraph("Ativo", st["header"]), Paragraph("Setor", st["header"]),
        Paragraph("Competência", st["header"]), Paragraph("Situação", st["header"]),
        Paragraph("Responsável", st["header"]),
    ]]
    for order in orders:
        rows.append([
            Paragraph(f"#{order.friendly_number}", st["normal"]),
            Paragraph(order.asset.patrimonio, st["normal"]),
            Paragraph(order.asset.description, st["normal"]),
            Paragraph(order.asset.sector.name if order.asset.sector else "Não informado", st["normal"]),
            Paragraph(competence_text(order), st["normal"]),
            Paragraph(status_text(order.status), st["normal"]),
            Paragraph(order.operator_name or "", st["normal"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Nenhuma manutenção encontrada para o período.", st["normal"]), "", "", "", "", "", ""])
    story.append(_table(rows, [1.3*cm, 2.3*cm, 7.2*cm, 3.4*cm, 3.5*cm, 3.5*cm, 3.7*cm]))
    doc.build(story)
    buffer.seek(0)
    return buffer


async def generate_yearly_schedule_pdf(db: AsyncSession, year: Optional[int] = None) -> io.BytesIO:
    year = year or local_today().year
    query = (
        select(MaintenanceOrder)
        .where(MaintenanceOrder.planned_year == year)
        .options(selectinload(MaintenanceOrder.asset).selectinload(Asset.sector))
        .order_by(MaintenanceOrder.planned_month, MaintenanceOrder.friendly_number)
    )
    result = await db.execute(query)
    orders = result.scalars().all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=1.0*cm, leftMargin=1.0*cm,
        topMargin=1.0*cm, bottomMargin=1.0*cm,
    )
    st = _styles()
    story = [
        Paragraph(f"Programação Anual de Manutenção — {year}", st["title"]),
        Paragraph(f"Gerado em {local_now().strftime('%d/%m/%Y %H:%M')}", st["normal"]),
        Spacer(1, 8),
    ]
    rows = [[
        Paragraph("Mês", st["header"]), Paragraph("OM", st["header"]),
        Paragraph("Patrimônio", st["header"]), Paragraph("Ativo", st["header"]),
        Paragraph("Setor", st["header"]), Paragraph("Situação", st["header"]),
        Paragraph("Origem", st["header"]),
    ]]
    for order in orders:
        month_label = MONTHS_PT[order.planned_month - 1].title() if order.planned_month else "Não informado"
        rows.append([
            Paragraph(month_label, st["normal"]),
            Paragraph(f"#{order.friendly_number}", st["normal"]),
            Paragraph(order.asset.patrimonio, st["normal"]),
            Paragraph(order.asset.description, st["normal"]),
            Paragraph(order.asset.sector.name if order.asset.sector else "Não informado", st["normal"]),
            Paragraph(status_text(order.status), st["normal"]),
            Paragraph(order.source_status or "Aplicativo", st["normal"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Nenhuma manutenção encontrada para o ano.", st["normal"]), "", "", "", "", "", ""])
    story.append(_table(rows, [2.2*cm, 1.3*cm, 2.4*cm, 8.5*cm, 3.4*cm, 3.6*cm, 2.2*cm], "#2B6CB0"))
    doc.build(story)
    buffer.seek(0)
    return buffer


async def generate_asset_history_pdf(db: AsyncSession, asset_id: Optional[str]) -> io.BytesIO:
    query = (
        select(MaintenanceOrder)
        .where(MaintenanceOrder.status.in_(["completed", "completed_with_issues", "cancelled"]))
        .options(selectinload(MaintenanceOrder.asset))
        .order_by(MaintenanceOrder.completed_at.desc(), MaintenanceOrder.planned_year.desc(), MaintenanceOrder.planned_month.desc())
    )
    asset_name = "Todos os ativos"
    if asset_id:
        query = query.where(MaintenanceOrder.asset_id == asset_id)
        asset_result = await db.execute(select(Asset).where(Asset.id == asset_id))
        asset = asset_result.scalars().first()
        if not asset:
            raise ValueError("Ativo não encontrado")
        asset_name = f"{asset.patrimonio} — {asset.description}"
    result = await db.execute(query)
    orders = result.scalars().all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    st = _styles()
    story = [
        Paragraph("Histórico de Manutenções", st["title"]),
        Paragraph(f"Ativo: <b>{asset_name}</b>", st["normal"]),
        Paragraph(f"Gerado em {local_now().strftime('%d/%m/%Y %H:%M')}", st["normal"]),
        Spacer(1, 8),
    ]
    rows = [[
        Paragraph("OM", st["header"]), Paragraph("Patrimônio", st["header"]),
        Paragraph("Competência", st["header"]), Paragraph("Conclusão", st["header"]),
        Paragraph("Situação", st["header"]), Paragraph("Responsável", st["header"]),
        Paragraph("Observações", st["header"]),
    ]]
    for order in orders:
        rows.append([
            Paragraph(f"#{order.friendly_number}", st["normal"]),
            Paragraph(order.asset.patrimonio, st["normal"]),
            Paragraph(competence_text(order), st["normal"]),
            Paragraph(format_local_datetime(order.completed_at) if order.completed_at else "Sem data exata", st["normal"]),
            Paragraph(status_text(order.status), st["normal"]),
            Paragraph(order.operator_name or "", st["normal"]),
            Paragraph(order.notes or order.source_note or "", st["normal"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Nenhum registro encontrado.", st["normal"]), "", "", "", "", "", ""])
    story.append(_table(rows, [1.3*cm, 2.4*cm, 3.3*cm, 3.6*cm, 3.6*cm, 3.5*cm, 7.5*cm], "#2C5282"))
    doc.build(story)
    buffer.seek(0)
    return buffer


async def generate_complete_order_pdf(db: AsyncSession, order_id: str) -> io.BytesIO:
    query = (
        select(MaintenanceOrder)
        .where(MaintenanceOrder.id == order_id)
        .options(
            selectinload(MaintenanceOrder.asset).selectinload(Asset.sector),
            selectinload(MaintenanceOrder.items),
            selectinload(MaintenanceOrder.evidences),
            selectinload(MaintenanceOrder.materials),
        )
    )
    result = await db.execute(query)
    order = result.scalars().first()
    if not order:
        raise ValueError("Ordem de manutenção não encontrada")

    item_ids = [item.item_id for item in order.items]
    checklist_map = {}
    if item_ids:
        item_result = await db.execute(select(ChecklistItem).where(ChecklistItem.id.in_(item_ids)))
        checklist_map = {item.id: item for item in item_result.scalars().all()}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)
    st = _styles()
    story = [
        Paragraph(f"Registro de Manutenção - OM #{order.friendly_number}", st["title"]),
        Paragraph(record_kind_text(getattr(order, "record_kind", "official")), st["bold"]),
        Spacer(1, 5),
    ]
    info = [
        [Paragraph("Ativo", st["bold"]), Paragraph(order.asset.description, st["normal"]), Paragraph("Patrimônio", st["bold"]), Paragraph(order.asset.patrimonio, st["normal"])],
        [Paragraph("Setor", st["bold"]), Paragraph(order.asset.sector.name if order.asset.sector else "Não informado", st["normal"]), Paragraph("Competência", st["bold"]), Paragraph(competence_text(order), st["normal"])],
        [Paragraph("Conferido e finalizado por", st["bold"]), Paragraph(order.operator_name or "Não informado", st["normal"]), Paragraph("Condição final", st["bold"]), Paragraph(final_condition_text(order.final_condition), st["normal"])],
        [Paragraph("Manutenção executada por", st["bold"]), Paragraph(getattr(order, "performed_by_snapshot", None) or getattr(order, "performed_by_name", None) or "Não informado", st["normal"]), Paragraph("Versão do documento", st["bold"]), Paragraph(f"v{order.final_revision or 1}", st["normal"])],
        [Paragraph("Participantes", st["bold"]), Paragraph(", ".join(person.get("name", "") for person in json.loads(getattr(order, "performed_by_participants_json", None) or "[]")) or "Nenhum", st["normal"]), Paragraph("", st["bold"]), Paragraph("", st["normal"])],
        [Paragraph("Conclusão", st["bold"]), Paragraph(format_local_datetime(order.completed_at) if order.completed_at else "Pendente", st["normal"]), Paragraph("Status", st["bold"]), Paragraph(status_text(order.status), st["normal"])],
    ]
    table = Table(info, colWidths=[3.6*cm, 5.4*cm, 3.0*cm, 6.0*cm])
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#CBD5E0")),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#F7FAFC")),
        ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#F7FAFC")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story += [table, Spacer(1, 8), Paragraph("Checklist", st["section"])]

    rows = [[Paragraph("Item", st["header"]), Paragraph("Verificação", st["header"]), Paragraph("Res.", st["header"]), Paragraph("Observação / transcrição", st["header"])]]
    for response in order.items:
        checklist = checklist_map.get(response.item_id)
        notes = response.notes or response.audio_transcript or ""
        rows.append([
            Paragraph(checklist.item_number if checklist else "—", st["normal"]),
            Paragraph(checklist.description if checklist else "Item não encontrado", st["normal"]),
            Paragraph(checklist_result_text(response.status), st["bold"]),
            Paragraph(notes, st["normal"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Esta ordem não possui checklist confirmado.", st["normal"]), "", "", ""])
    story.append(_table(rows, [1.35*cm, 8.1*cm, 1.35*cm, 7.0*cm], "#2B6CB0"))

    materials = ", ".join(f"{m.name}{f' ({m.quantity_text})' if m.quantity_text else ''}" for m in order.materials) or "Nenhum material registrado."
    general_notes = order.notes or order.source_note or ""
    if order.materials or general_notes:
        story += [Spacer(1, 8), Paragraph("Materiais e observações gerais", st["section"])]
        if order.materials:
            story.append(Paragraph(materials, st["normal"]))
        if general_notes:
            story.append(Paragraph(general_notes, st["normal"]))

    photo_cells = []
    audio_evidence_rows = []
    labels = {
        "form_photo": "Folha preenchida", "defect_photo": "Defeito",
        "before_photo": "Antes", "after_photo": "Depois",
        "replaced_part_photo": "Peça substituída", "general_photo": "Foto geral",
        "item_audio": "Áudio do item",
    }
    for evidence in order.evidences:
        path = Path(UPLOADS_DIR) / Path(evidence.file_path).name
        if not path.exists():
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            audio_evidence_rows.append([
                Paragraph(labels.get(evidence.evidence_type, evidence.evidence_type), st["normal"]),
                Paragraph(path.name, st["normal"]),
                Paragraph(evidence.uploaded_at.strftime("%d/%m/%Y %H:%M") if evidence.uploaded_at else "", st["normal"]),
            ])
            continue
        try:
            img = Image(str(path), width=5.2*cm, height=5.2*cm)
            photo_cells.append([img, Paragraph(labels.get(evidence.evidence_type, evidence.evidence_type), st["bold"])])
        except Exception:
            continue
    if audio_evidence_rows:
        story += [Spacer(1, 8), Paragraph("Evidências de áudio/documento", st["section"])]
        rows = [[Paragraph("Tipo", st["header"]), Paragraph("Arquivo", st["header"]), Paragraph("Enviado em", st["header"])]]
        rows.extend(audio_evidence_rows)
        story.append(_table(rows, [4.0 * cm, 9.8 * cm, 4.0 * cm], "#2B6CB0"))
    if photo_cells:
        story += [Spacer(1, 8), Paragraph("Evidências", st["section"])]
        grid = []
        row = []
        for img, label in photo_cells:
            row.append([img, Spacer(1, 2), label])
            if len(row) == 2:
                grid.append(row); row = []
        if row:
            row.append(""); grid.append(row)
        photo_table = Table(grid, colWidths=[9*cm, 9*cm])
        photo_table.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "TOP")]))
        story.append(photo_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


async def generate_cmp_form_pdf(
    db: AsyncSession,
    order_id: str,
    *,
    responsible: Optional[str] = None,
    execution_date: Optional[str] = None,
    base_url: Optional[str] = None,
) -> io.BytesIO:
    """Gera a folha física CMP em PDF A4 controlado.

    O PDF é gerado no backend para evitar imprimir a SPA inteira, cabeçalhos do
    navegador e páginas em branco em tablets/celulares.
    """
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    query = (
        select(MaintenanceOrder)
        .where(MaintenanceOrder.id == order_id)
        .options(
            selectinload(MaintenanceOrder.asset).selectinload(Asset.sector),
            selectinload(MaintenanceOrder.items),
            selectinload(MaintenanceOrder.plan),
        )
    )
    result = await db.execute(query)
    order = result.scalars().first()
    if not order:
        raise ValueError("Ordem de manutenção não encontrada")

    item_ids = [item.item_id for item in order.items]
    checklist_items: list[ChecklistItem] = []
    if item_ids:
        item_result = await db.execute(select(ChecklistItem).where(ChecklistItem.id.in_(item_ids)))
        checklist_map = {item.id: item for item in item_result.scalars().all()}
        checklist_items = [checklist_map[item_id] for item_id in item_ids if item_id in checklist_map]

    responsible = (responsible or order.operator_name or "").strip() or ""
    execution_date = (execution_date or local_today().strftime("%d/%m/%Y")).strip()
    qr_payload = {
        "kind": "mec_cmp_form",
        "order_id": order.id,
        "friendly_number": order.friendly_number,
        "asset_id": order.asset_id,
        "checklist_template_version_id": order.checklist_version_id,
        "app_version": APP_VERSION,
    }
    qr_payload["hash"] = hashlib.sha256(
        json.dumps(qr_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    qr_text = json.dumps(qr_payload, ensure_ascii=False, sort_keys=True)
    if base_url:
        qr_text = f"{base_url.rstrip('/')}/cmp/{order.id}/digitalizar"

    buffer = io.BytesIO()
    page_size = A4
    width, height = page_size
    c = canvas.Canvas(buffer, pagesize=page_size)
    c.setTitle(f"CMP OM {order.friendly_number}")

    margin = 0.75 * cm
    content_w = width - 2 * margin
    items_per_page = 6
    pages = [checklist_items[i:i + items_per_page] for i in range(0, len(checklist_items), items_per_page)] or [[]]

    def draw_wrapped(text: str, xx: float, yy: float, max_chars: int, max_lines: int, leading: float = 8.4) -> None:
        clean_text = re.sub(r"\s+", " ", text or "").strip()
        lines = textwrap.wrap(clean_text, width=max_chars)[:max_lines]
        for line_index, line in enumerate(lines):
            c.drawString(xx, yy - line_index * leading, line)

    def draw_box_label(label: str, value: str, xx: float, yy: float, ww: float, hh: float = 0.74 * cm) -> None:
        c.rect(xx, yy, ww, hh, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 6.2)
        c.drawString(xx + 0.10 * cm, yy + hh - 0.20 * cm, label)
        c.setFont("Helvetica", 7.8)
        value_text = str(value or "")
        max_chars = max(12, int(ww / (0.14 * cm)))
        if len(value_text) > max_chars:
            value_text = value_text[:max(9, max_chars - 1)].rstrip() + "."
        c.drawString(xx + 0.10 * cm, yy + 0.17 * cm, value_text)

    for page_index, page_items in enumerate(pages, start=1):
        y = height - margin
        c.setStrokeColor(colors.black)
        # Corner marks for camera alignment.
        mark = 0.38 * cm
        for mx, my, sx, sy in [
            (margin, height - margin, 1, -1),
            (width - margin, height - margin, -1, -1),
            (margin, margin, 1, 1),
            (width - margin, margin, -1, 1),
        ]:
            c.setLineWidth(1.4)
            c.line(mx, my, mx + sx * mark, my)
            c.line(mx, my, mx, my + sy * mark)
        c.setLineWidth(0.7)

        qr_size = 2.55 * cm
        import qrcode

        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
        qr.add_data(qr_text)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        header_h = 2.78 * cm
        c.rect(margin, y - header_h, content_w, header_h, stroke=1, fill=0)
        c.line(margin + 2.55 * cm, y - header_h, margin + 2.55 * cm, y)
        c.line(width - margin - qr_size - 0.25 * cm, y - header_h, width - margin - qr_size - 0.25 * cm, y)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(margin + 1.27 * cm, y - 1.44 * cm, "MANUTENÇÃO")
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(width / 2, y - 1.48 * cm, "CMP - CONTROLE DE MANUTENÇÃO PREVENTIVA")
        c.drawImage(ImageReader(qr_buffer), width - margin - qr_size - 0.06 * cm, y - qr_size - 0.10 * cm, qr_size, qr_size, mask="auto")

        y -= header_h + 0.28 * cm
        left_w = 10.5 * cm
        right_x = margin + left_w + 0.35 * cm
        right_w = width - margin - right_x
        field_h = 0.74 * cm
        draw_box_label("Equipamento/Máquina", order.asset.description, margin, y - field_h, left_w, field_h)
        draw_box_label("Patrimônio", order.asset.patrimonio, right_x, y - field_h, 3.1 * cm, field_h)
        draw_box_label("Nº da ordem", str(order.friendly_number), right_x + 3.35 * cm, y - field_h, 2.35 * cm, field_h)
        draw_box_label("Setor", order.asset.sector.name if order.asset.sector else "Não informado", right_x + 5.95 * cm, y - field_h, max(2.8 * cm, right_w - 5.95 * cm), field_h)
        y -= 0.92 * cm
        draw_box_label("Responsável", responsible, margin, y - field_h, left_w, field_h)
        draw_box_label("Data de execução", execution_date, right_x, y - field_h, 3.1 * cm, field_h)
        draw_box_label("Competência", competence_text(order), right_x + 3.35 * cm, y - field_h, max(5.4 * cm, right_w - 3.35 * cm), field_h)

        y -= 0.86 * cm
        col_item = 2.0 * cm
        col_check = 8.0 * cm
        col_status = 0.82 * cm
        col_obs = content_w - col_item - col_check - 3 * col_status
        x_item = margin
        x_check = x_item + col_item
        x_ok = x_check + col_check
        x_def = x_ok + col_status
        x_na = x_def + col_status
        x_obs = x_na + col_status
        table_w = content_w
        header_row_h = 0.64 * cm

        c.setFillColor(colors.HexColor("#1A365D"))
        c.rect(margin, y - header_row_h, table_w, header_row_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7.2)
        c.drawCentredString(x_item + col_item / 2, y - 0.40 * cm, "Item")
        c.drawString(x_check + 0.12 * cm, y - 0.40 * cm, "Serviços / Verificações")
        c.drawCentredString(x_ok + col_status / 2, y - 0.40 * cm, "OK")
        c.drawCentredString(x_def + col_status / 2, y - 0.40 * cm, "DEF")
        c.drawCentredString(x_na + col_status / 2, y - 0.40 * cm, "N/A")
        c.drawString(x_obs + 0.10 * cm, y - 0.40 * cm, "Observações / Materiais")
        c.setFillColor(colors.black)
        y -= header_row_h

        available_for_rows = y - (margin + 3.05 * cm)
        rows_on_page = max(1, len(page_items))
        row_h = max(1.72 * cm, min(2.18 * cm, available_for_rows / rows_on_page))
        for local_index, item in enumerate(page_items, start=1):
            y -= row_h
            c.setStrokeColor(colors.black)
            c.rect(margin, y, table_w, row_h, stroke=1, fill=0)
            for xx in [x_check, x_ok, x_def, x_na, x_obs]:
                c.line(xx, y, xx, y + row_h)
            c.setFont("Helvetica-Bold", 6.8)
            draw_wrapped(item.item_number or str((page_index - 1) * items_per_page + local_index), x_item + 0.10 * cm, y + row_h - 0.34 * cm, 15, 3, 7.2)
            c.setFont("Helvetica", 6.9)
            description_max_lines = max(4, int((row_h - 0.45 * cm) / 7.25))
            draw_wrapped(item.description or "", x_check + 0.13 * cm, y + row_h - 0.34 * cm, 58, description_max_lines, 7.25)
            box = 0.38 * cm
            box_y = y + row_h / 2 - box / 2
            for xx in [x_ok, x_def, x_na]:
                c.rect(xx + (col_status - box) / 2, box_y, box, box, stroke=1, fill=0)
            # Linha livre de observação no campo direito.
            for line_y in [y + row_h * 0.34, y + row_h * 0.62]:
                c.line(x_obs + 0.16 * cm, line_y, width - margin - 0.16 * cm, line_y)

        y -= 0.28 * cm
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(margin, y, "Observações gerais / materiais utilizados")
        c.rect(margin, y - 1.32 * cm, content_w, 1.06 * cm, stroke=1, fill=0)
        y -= 1.62 * cm
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(margin, y, "Condição operacional final")
        conditions = ["Apta / liberada", "Apta com atenção", "Parada / bloqueio físico"]
        condition_x = margin + 0.15 * cm
        for idx, condition in enumerate(conditions):
            cx = condition_x + idx * 6.2 * cm
            cy = y - 0.42 * cm
            c.rect(cx, cy, 0.26 * cm, 0.26 * cm, stroke=1, fill=0)
            c.setFont("Helvetica", 6.8)
            c.drawString(cx + 0.34 * cm, cy + 0.04 * cm, condition)

        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


async def generate_issues_pdf(db: AsyncSession, stopped_only: bool = False) -> io.BytesIO:
    query = select(MaintenanceIssue).options(selectinload(MaintenanceIssue.asset)).order_by(MaintenanceIssue.created_at.desc())
    if stopped_only:
        query = query.where(MaintenanceIssue.is_operable_affected.is_(True), MaintenanceIssue.status == "open")
    result = await db.execute(query)
    issues = result.scalars().all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    st = _styles()
    title = "Máquinas Paradas" if stopped_only else "Pendências e Ocorrências"
    story = [Paragraph(title, st["title"]), Paragraph(f"Gerado em {local_now().strftime('%d/%m/%Y %H:%M')}", st["normal"]), Spacer(1, 8)]
    rows = [[Paragraph("Patrimônio", st["header"]), Paragraph("Ativo", st["header"]), Paragraph("Problema", st["header"]), Paragraph("Prioridade", st["header"]), Paragraph("Situação", st["header"]), Paragraph("Criado em", st["header"])]]
    for issue in issues:
        rows.append([
            Paragraph(issue.asset.patrimonio if issue.asset else "", st["normal"]),
            Paragraph(issue.asset.description if issue.asset else "", st["normal"]),
            Paragraph(issue.description, st["normal"]),
            Paragraph(issue.priority, st["normal"]),
            Paragraph("Aberta" if issue.status == "open" else "Resolvida", st["normal"]),
            Paragraph(format_local_datetime(issue.created_at) if issue.created_at else "", st["normal"]),
        ])
    if len(rows) == 1:
        rows.append([Paragraph("Nenhum registro encontrado.", st["normal"]), "", "", "", "", ""])
    story.append(_table(rows, [2.5*cm, 6.5*cm, 9.5*cm, 2.7*cm, 2.7*cm, 3.5*cm]))
    doc.build(story); buffer.seek(0); return buffer
