import os
import cv2
import numpy as np
import base64
import json
import time
import re
from datetime import date
from urllib.parse import unquote, urlparse
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models import MaintenanceOrder, Asset, ChecklistItem, Operator

# Carregar template JSON
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "cmp_template.json")
if os.path.exists(TEMPLATE_PATH):
    with open(TEMPLATE_PATH, "r") as f:
        TEMPLATE_CONFIG = json.load(f)
else:
    TEMPLATE_CONFIG = {
        "target_width": 800,
        "target_height": 1100,
        "row_start_y": 380,
        "row_height": 45,
        "columns": {
            "ok": {"x_start": 540, "x_end": 565},
            "def": {"x_start": 620, "x_end": 645},
            "na": {"x_start": 700, "x_end": 725}
        }
    }

class ChecklistItemOutput(BaseModel):
    item_number: str
    status: str  # 'ok', 'attention', 'not_applicable'
    notes: Optional[str] = None
    confidence: float

class SheetInterpretationOutput(BaseModel):
    patrimonio: str
    date: Optional[str] = None
    operator_name: Optional[str] = None
    items: List[ChecklistItemOutput]
    final_condition: str  # 'released', 'released_with_attention', 'stopped'
    signature_present: bool
    materials: Optional[str] = None

def align_image_perspective(img):
    """
    Tenta detectar os 4 marcadores de canto e aplicar transformacao de perspectiva.
    Retorna a imagem alinhada 800x1100 ou a original redimensionada em caso de falha.
    """
    target_w = TEMPLATE_CONFIG["target_width"]
    target_h = TEMPLATE_CONFIG["target_height"]

    def has_content(candidate) -> bool:
        try:
            candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
            return float(np.mean(candidate_gray < 245)) > 0.012
        except Exception:
            return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    markers = []
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)

        if len(approx) == 4:
            (x, y, w, h) = cv2.boundingRect(approx)
            aspect_ratio = w / float(h)

            if 0.8 <= aspect_ratio <= 1.2 and 15 <= w <= 60:
                markers.append((x, y, w, h, approx))

    if len(markers) >= 4:
        markers = sorted(markers, key=lambda x: x[2] * x[3], reverse=True)[:4]
        points = []
        for m in markers:
            M = cv2.moments(m[4])
            if M["m00"] != 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                points.append((cX, cY))
            else:
                points.append((m[0] + m[2]//2, m[1] + m[3]//2))

        points = np.array(points, dtype="float32")
        s = points.sum(axis=1)
        diff = np.diff(points, axis=1)

        ordered_pts = np.zeros((4, 2), dtype="float32")
        ordered_pts[0] = points[np.argmin(s)]       # top-left
        ordered_pts[2] = points[np.argmax(s)]       # bottom-right
        ordered_pts[1] = points[np.argmin(diff)]    # top-right
        ordered_pts[3] = points[np.argmax(diff)]    # bottom-left

        dst_pts = np.array([
            [0, 0],
            [target_w - 1, 0],
            [target_w - 1, target_h - 1],
            [0, target_h - 1]
        ], dtype="float32")

        M = cv2.getPerspectiveTransform(ordered_pts, dst_pts)
        warped = cv2.warpPerspective(img, M, (target_w, target_h))
        if has_content(warped):
            return warped, True

    # Fallback: detectar o contorno da folha inteira. As fotos reais do tablet
    # normalmente mostram a pagina toda, mas nem sempre os marcadores de canto
    # aparecem como quatro quadrados limpos.
    page_contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
    img_area = img.shape[0] * img.shape[1]
    for contour in page_contours:
        area = cv2.contourArea(contour)
        if area < img_area * 0.18:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        points = approx.reshape(4, 2).astype("float32")
        s = points.sum(axis=1)
        diff = np.diff(points, axis=1)
        ordered_pts = np.zeros((4, 2), dtype="float32")
        ordered_pts[0] = points[np.argmin(s)]
        ordered_pts[2] = points[np.argmax(s)]
        ordered_pts[1] = points[np.argmin(diff)]
        ordered_pts[3] = points[np.argmax(diff)]
        dst_pts = np.array([
            [0, 0],
            [target_w - 1, 0],
            [target_w - 1, target_h - 1],
            [0, target_h - 1],
        ], dtype="float32")
        M = cv2.getPerspectiveTransform(ordered_pts, dst_pts)
        warped = cv2.warpPerspective(img, M, (target_w, target_h))
        if has_content(warped):
            return warped, True

    return cv2.resize(img, (target_w, target_h)), False

def read_checkboxes_omr(img_aligned, num_items):
    """
    Mede a densidade de preenchimento dos checkboxes para cada item.
    """
    gray = cv2.cvtColor(img_aligned, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)

    results = []

    start_y = TEMPLATE_CONFIG["row_start_y"]
    row_h = TEMPLATE_CONFIG["row_height"]
    cols = TEMPLATE_CONFIG["columns"]

    for i in range(num_items):
        y_center = start_y + (i * row_h)
        y1, y2 = y_center - 12, y_center + 12

        densities = {}
        for col_name, coords in cols.items():
            x1, x2 = coords["x_start"], coords["x_end"]

            crop = thresh[y1:y2, x1:x2]
            if crop.size > 0:
                filled = np.sum(crop == 255)
                total = crop.size
                densities[col_name] = float(filled) / float(total)
            else:
                densities[col_name] = 0.0

        threshold_fill = 0.18
        marked_cols = [name for name, d in densities.items() if d >= threshold_fill]

        sorted_dens = sorted(densities.items(), key=lambda x: x[1], reverse=True)
        best_col, best_val = sorted_dens[0]
        second_col, second_val = sorted_dens[1]

        confidence = float(best_val - second_val)
        if best_val < threshold_fill:
            selected_status = ""
            confidence = 1.0 - best_val
        elif len(marked_cols) > 1:
            selected_status = "ambiguous"
            confidence = 0.0
        else:
            if best_col == "ok":
                selected_status = "ok"
            elif best_col == "def":
                selected_status = "attention"
            else:
                selected_status = "not_applicable"

        results.append({
            "status": selected_status,
            "confidence": confidence,
            "densities": densities
        })

    return results


def _decode_qr_candidates(img) -> tuple[bool, str]:
    detector = cv2.QRCodeDetector()
    candidates = [img]
    h, w = img.shape[:2]
    candidates.extend([
        img[0:int(h * 0.38), int(w * 0.55):w],
        img[0:int(h * 0.45), int(w * 0.45):w],
    ])
    for candidate in list(candidates):
        if candidate is None or candidate.size == 0:
            continue
        candidates.append(cv2.resize(candidate, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY) if len(candidate.shape) == 3 else candidate
        candidates.append(gray)
        candidates.append(cv2.equalizeHist(gray))
    for candidate in candidates:
        try:
            value, _points, _straight = detector.detectAndDecode(candidate)
            if value:
                return True, value.strip()
        except Exception:
            continue
    return False, ""


def _parse_qr_payload(qr_data: str) -> dict:
    payload: dict = {}
    value = (qr_data or "").strip()
    if not value:
        return payload
    json_text = value.split("#", 1)[1] if "#" in value else value
    try:
        parsed = json.loads(unquote(json_text))
        if isinstance(parsed, dict):
            payload.update(parsed)
    except Exception:
        pass
    try:
        parsed_url = urlparse(value)
        path = parsed_url.path or value
        order_match = re.search(r"/cmp/([^/?#]+)", path)
        if not order_match:
            order_match = re.search(r"/o/([^/?#]+)", path)
        if not order_match:
            order_match = re.search(r"/(?:order|ordens)/([^/?#]+)", path)
        if order_match:
            payload.setdefault("order_token", unquote(order_match.group(1)).strip())
        asset_match = re.search(r"/a/([^/?#]+)", path)
        if not asset_match:
            asset_match = re.search(r"/(?:asset|ativos)/([^/?#]+)", path)
        if asset_match:
            payload.setdefault("asset_token", unquote(asset_match.group(1)).strip())
    except Exception:
        pass
    if value.startswith("mec://order/"):
        payload.setdefault("order_token", value.split("mec://order/", 1)[1].split("#", 1)[0].strip())
    if value.startswith("mec://asset/"):
        payload.setdefault("asset_token", value.split("mec://asset/", 1)[1].split("#", 1)[0].strip())
    return payload


def _ocr_text_best_effort(img) -> tuple[str, str]:
    try:
        from rapidocr_onnxruntime import RapidOCR

        result, _elapsed = RapidOCR()(img)
        parts: list[str] = []
        for item in result or []:
            if len(item) >= 2 and item[1]:
                parts.append(str(item[1]).strip())
        return "\n".join(part for part in parts if part), "rapidocr_onnxruntime"
    except Exception as exc:
        return "", f"ocr_unavailable:{exc}"


def _extract_header_fields_from_text(text: str) -> dict:
    normalized = re.sub(r"[ \t]+", " ", text or "")
    fields: dict = {}
    order_patterns = [
        r"(?:N[ºo°]?\s*(?:DA\s*)?ORDEM|OM)\D{0,12}(\d{1,8})",
        r"\bOM\D{0,5}(\d{1,8})\b",
    ]
    for pattern in order_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            fields["friendly_number"] = int(match.group(1))
            break
    patrimonio_match = re.search(r"(?:PATRIM[ÔO]NIO|C[ÓO]DIGO)\D{0,20}([ME]?\s*-?\s*\d{1,4})", normalized, flags=re.IGNORECASE)
    if patrimonio_match:
        fields["patrimonio"] = re.sub(r"\s+", "", patrimonio_match.group(1)).upper()
    responsible_match = re.search(r"RESPONS[ÁA]VEL\D{0,8}([A-ZÀ-Ú][A-ZÀ-Ú\s]{2,40})", normalized, flags=re.IGNORECASE)
    if responsible_match:
        fields["operator_name"] = responsible_match.group(1).strip(" _:-")
    date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", normalized)
    if date_match:
        fields["date_raw"] = date_match.group(1)
    return fields


def _dark_ratio(gray_crop) -> float:
    if gray_crop.size == 0:
        return 0.0
    h, w = gray_crop.shape[:2]
    pad_y = max(1, int(h * 0.22))
    pad_x = max(1, int(w * 0.22))
    inner = gray_crop[pad_y:max(pad_y + 1, h - pad_y), pad_x:max(pad_x + 1, w - pad_x)]
    if inner.size == 0:
        inner = gray_crop
    return float(np.mean(inner < 120))


def read_checkboxes_by_contours(img, num_items: int) -> list[dict]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 9)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape[:2]
    min_side = max(8, int(min(h, w) * 0.006))
    max_side = max(24, int(min(h, w) * 0.045))
    boxes: list[dict] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if not (min_side <= bw <= max_side and min_side <= bh <= max_side):
            continue
        ratio = bw / float(bh or 1)
        if not 0.65 <= ratio <= 1.45:
            continue
        cx = x + bw / 2
        cy = y + bh / 2
        if cx < w * 0.42 or cy < h * 0.22 or cy > h * 0.92:
            continue
        # Ignora QR no cabecalho: muitos quadrados pequenos juntos no topo direito.
        if cx > w * 0.70 and cy < h * 0.28:
            continue
        crop = gray[y:y + bh, x:x + bw]
        boxes.append({"x": x, "y": y, "w": bw, "h": bh, "cx": cx, "cy": cy, "dark": _dark_ratio(crop)})

    if len(boxes) < 6:
        return []

    # Remove duplicados sobrepostos.
    deduped: list[dict] = []
    for box in sorted(boxes, key=lambda b: (b["cy"], b["cx"])):
        if any(abs(box["cx"] - other["cx"]) < min_side and abs(box["cy"] - other["cy"]) < min_side for other in deduped):
            continue
        deduped.append(box)
    boxes = deduped

    # Agrupa linhas pela coordenada Y.
    rows: list[list[dict]] = []
    y_tol = max(14, int(min(h, w) * 0.018))
    for box in sorted(boxes, key=lambda b: b["cy"]):
        for row in rows:
            if abs(box["cy"] - np.mean([b["cy"] for b in row])) <= y_tol:
                row.append(box)
                break
        else:
            rows.append([box])
    rows = [sorted(row, key=lambda b: b["cx"]) for row in rows if len(row) >= 2]
    if not rows:
        return []

    # Detecta as tres colunas globais OK/DEF/N/A; isso evita confundir quando
    # uma linha tem uma caixa fraca ou parcialmente coberta pela perspectiva.
    all_x = np.array([[box["cx"]] for row in rows for box in row], dtype=np.float32)
    if len(all_x) >= 3:
        _compactness, labels, centers = cv2.kmeans(
            all_x,
            3,
            None,
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.2),
            5,
            cv2.KMEANS_PP_CENTERS,
        )
        column_centers = sorted(float(center[0]) for center in centers)
    else:
        column_centers = []

    # Mantem apenas a sequencia principal de linhas do checklist.
    rows = sorted(rows, key=lambda row: np.mean([b["cy"] for b in row]))[:num_items]
    results: list[dict] = []
    for row in rows:
        if len(column_centers) != 3:
            results.append({"status": "", "confidence": 0.0, "densities": {}})
            continue
        candidates: list[dict | None] = []
        x_tol = max(22, int(min(h, w) * 0.055))
        for center in column_centers:
            nearest = min(row, key=lambda b: abs(b["cx"] - center))
            candidates.append(nearest if abs(nearest["cx"] - center) <= x_tol else None)
        densities = {
            "ok": candidates[0]["dark"] if candidates[0] else 0.0,
            "def": candidates[1]["dark"] if candidates[1] else 0.0,
            "na": candidates[2]["dark"] if candidates[2] else 0.0,
        }
        marked = [name for name, value in densities.items() if value >= 0.085]
        sorted_dens = sorted(densities.items(), key=lambda item: item[1], reverse=True)
        best, best_value = sorted_dens[0]
        second_value = sorted_dens[1][1]
        if not marked:
            status = ""
            confidence = max(0.0, 1.0 - best_value)
        elif len(marked) > 1 and best_value - second_value < 0.05:
            status = "ambiguous"
            confidence = 0.0
        elif best == "ok":
            status = "ok"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        elif best == "def":
            status = "attention"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        else:
            status = "not_applicable"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        results.append({"status": status, "confidence": float(confidence), "densities": densities})
    return results


def _dedupe_positions(values: list[float], tolerance: float = 8.0) -> list[float]:
    deduped: list[float] = []
    for value in sorted(values):
        if not deduped or abs(value - deduped[-1]) > tolerance:
            deduped.append(float(value))
    return deduped


def read_checkboxes_by_grid(img_aligned, num_items: int) -> list[dict]:
    """Lê OK/DEF/N/A pela grade real da tabela fotografada.

    A folha CMP antiga e a nova podem ter linhas com alturas diferentes. Ler por
    coordenada fixa erra nesses casos; esta rotina detecta as linhas horizontais
    e verticais da própria tabela e mede apenas o interior das células OK/DEF/N/A.
    """
    if num_items <= 0:
        return []
    gray = cv2.cvtColor(img_aligned, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    threshold = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        9,
    )

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 6), 1))
    horizontal = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, horizontal_kernel)
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    y_positions: list[float] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw >= w * 0.45:
            y_positions.append(y + bh / 2)
    y_positions = _dedupe_positions(y_positions, tolerance=max(6, h * 0.008))
    if len(y_positions) < 3:
        return []

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, h // 8)))
    vertical = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, vertical_kernel)
    contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    x_positions: list[float] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bh >= h * 0.32:
            x_positions.append(x + bw / 2)
    x_positions = _dedupe_positions(x_positions, tolerance=max(6, w * 0.008))
    if len(x_positions) < 5:
        return []

    intervals = [
        (x_positions[i], x_positions[i + 1], x_positions[i + 1] - x_positions[i])
        for i in range(len(x_positions) - 1)
    ]
    checkbox_intervals: list[tuple[float, float, float]] = []
    for index in range(len(intervals) - 2):
        widths = [intervals[index + offset][2] for offset in range(3)]
        if all(max(16, w * 0.018) <= width <= max(80, w * 0.11) for width in widths):
            checkbox_intervals = intervals[index:index + 3]
            break
    if len(checkbox_intervals) != 3:
        return []

    # A detecção costuma retornar a linha inferior do cabeçalho como primeira
    # posição horizontal relevante. O primeiro item começa logo abaixo dela.
    row_bounds = []
    first_interval = (y_positions[1] - y_positions[0]) if len(y_positions) > 1 else 0
    start_index = 1 if first_interval and first_interval < h * 0.09 else 0
    for row_index in range(start_index, min(start_index + num_items, len(y_positions) - 1)):
        y1 = int(y_positions[row_index] + 3)
        y2 = int(y_positions[row_index + 1] - 3)
        if y2 - y1 >= 12:
            row_bounds.append((y1, y2))
    if not row_bounds:
        return []

    results: list[dict] = []
    for y1, y2 in row_bounds[:num_items]:
        densities: dict[str, float] = {}
        for name, (x1, x2, _width) in zip(("ok", "def", "na"), checkbox_intervals):
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            side = int(max(12, min((x2 - x1) * 0.72, (y2 - y1) * 0.46, min(h, w) * 0.045)))
            xx1 = max(0, cx - side // 2)
            xx2 = min(w, cx + side // 2)
            yy1 = max(0, cy - side // 2)
            yy2 = min(h, cy + side // 2)
            crop = gray[yy1:yy2, xx1:xx2]
            densities[name] = _dark_ratio(crop)

        sorted_dens = sorted(densities.items(), key=lambda item: item[1], reverse=True)
        best, best_value = sorted_dens[0]
        second_value = sorted_dens[1][1]
        threshold_fill = 0.145
        if best_value < threshold_fill:
            status = ""
            confidence = max(0.0, 1.0 - best_value)
        elif best_value - second_value < 0.045:
            status = "ambiguous"
            confidence = 0.0
        elif best == "ok":
            status = "ok"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        elif best == "def":
            status = "attention"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        else:
            status = "not_applicable"
            confidence = min(1.0, max(0.0, best_value - second_value + 0.55))
        results.append({"status": status, "confidence": float(confidence), "densities": densities})
    return results

async def process_sheet_photo(image_bytes: bytes, filename: str, db) -> dict:
    """
    Processa a foto do checklist usando OpenCV e chamada hibrida (OpenAI GPT-4o Vision se habilitado,
    ou processamento local baseado em QR Code e OMR).
    Retorna metadados completos para auditoria transparente.
    """
    start_time = time.time()

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Formato de imagem invalido ou corrompido.")

    # 1. Detectar QR Code do CMP gerado pelo ManutencaoEmCampo.
    qr_detected, qr_data = _decode_qr_candidates(img)
    if qr_detected:
        print(f"QR Code detectado na folha: {qr_data[:120]}")
    qr_payload = _parse_qr_payload(qr_data)

    order_id_from_qr = qr_payload.get("order_id") or qr_payload.get("orderId") or qr_payload.get("order_token")
    patrimonio_from_qr = qr_payload.get("patrimonio") or qr_payload.get("asset_token")
    friendly_number_from_ocr = None
    ocr_text = ""
    ocr_method = "not_run"
    header_fields: dict = {}

    if order_id_from_qr:
        order_id_from_qr = str(order_id_from_qr).split("#", 1)[0].strip()
    if patrimonio_from_qr:
        patrimonio_from_qr = str(patrimonio_from_qr).split("#", 1)[0].strip()

    # 2. OCR leve do cabecalho quando QR nao resolve a OM.
    if not order_id_from_qr:
        ocr_text, ocr_method = _ocr_text_best_effort(img)
        header_fields = _extract_header_fields_from_text(ocr_text)
        friendly_number_from_ocr = header_fields.get("friendly_number")
        patrimonio_from_qr = patrimonio_from_qr or header_fields.get("patrimonio")

    # Tentar resolver token opaco do QR Code se for o caso.
    if order_id_from_qr and len(str(order_id_from_qr)) != 36:
        order_res = await db.execute(select(MaintenanceOrder).where(MaintenanceOrder.opaque_token == str(order_id_from_qr)))
        db_order_token = order_res.scalars().first()
        if db_order_token:
            order_id_from_qr = db_order_token.id

    if patrimonio_from_qr and len(str(patrimonio_from_qr)) != 36:
        asset_res = await db.execute(select(Asset).where(Asset.opaque_token == str(patrimonio_from_qr)))
        db_asset = asset_res.scalars().first()
        if db_asset:
            patrimonio_from_qr = db_asset.patrimonio

    # 3. Carregar a ordem do banco.
    db_order = None
    if order_id_from_qr:
        res = await db.execute(
            select(MaintenanceOrder)
            .where(MaintenanceOrder.id == order_id_from_qr)
            .options(selectinload(MaintenanceOrder.asset), selectinload(MaintenanceOrder.items))
        )
        db_order = res.scalars().first()

    if not db_order and friendly_number_from_ocr:
        res = await db.execute(
            select(MaintenanceOrder)
            .where(MaintenanceOrder.friendly_number == friendly_number_from_ocr)
            .options(selectinload(MaintenanceOrder.asset), selectinload(MaintenanceOrder.items))
        )
        db_order = res.scalars().first()

    if not db_order and patrimonio_from_qr:
        query = select(MaintenanceOrder).join(Asset).where(
            Asset.patrimonio == patrimonio_from_qr,
            MaintenanceOrder.status.in_(["scheduled", "today", "in_progress"])
        ).options(selectinload(MaintenanceOrder.asset), selectinload(MaintenanceOrder.items))
        res = await db.execute(query)
        db_order = res.scalars().first()

    # 3. Alinhamento de Perspectiva OpenCV
    img_aligned, is_warped = align_image_perspective(img)

    # 4. Processamento Local OMR
    omr_results = []
    if db_order:
        omr_results = read_checkboxes_by_grid(img_aligned, len(db_order.items))
        if len(omr_results) < max(1, min(len(db_order.items), 3)):
            omr_results = read_checkboxes_by_contours(img_aligned, len(db_order.items))
        if len(omr_results) < max(1, min(len(db_order.items), 3)):
            omr_results = read_checkboxes_omr(img_aligned, len(db_order.items))

    # 5. Logica IA Visual (OpenAI Vision Hibrido)
    api_key = os.getenv("OPENAI_API_KEY")
    vision_enabled = os.getenv("OPENAI_VISION_ENABLED", "False").lower() in ["true", "1", "yes"]
    vision_model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

    if api_key and vision_enabled:
        print(f"Executando interpretacao via IA Visual ({vision_model}) com Structured Outputs...")

        _, encoded_img = cv2.imencode('.jpg', img_aligned)
        base64_image = base64.b64encode(encoded_img).decode('utf-8')

        prompt = """
        Analise esta imagem alinhada de um checklist de manutencao preventiva (CMP).
        Leia os campos manuscritos (data, nome do operador, materiais) e o preenchimento dos checkboxes.
        Retorne os dados rigorosamente no formato de resposta especificado.

        Se a imagem contiver checkboxes ambiguos, marcaçoes duplas ou rasuras, avalie a intencao real ou marque a baixa confianca.
        """

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            response = client.beta.chat.completions.parse(
                model=vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                response_format=SheetInterpretationOutput,
                timeout=30.0
            )

            duration = time.time() - start_time
            parsed_output = response.choices[0].message.parsed

            # Converter Pydantic para dicionario
            result = parsed_output.dict()

            # Vincular item_id do banco usando item_number
            if db_order and "items" in result:
                for item in result["items"]:
                    for idx, db_item in enumerate(db_order.items):
                        chk_item_res = await db.execute(select(ChecklistItem).where(ChecklistItem.id == db_item.item_id))
                        chk_item = chk_item_res.scalars().first()

                        if (chk_item and chk_item.item_number == item.get("item_number")) or (idx == result["items"].index(item) if len(result["items"]) == len(db_order.items) else False):
                            item["item_id"] = db_item.item_id
                            break

            result.update({
                "order_id": db_order.id if db_order else None,
                "provider": "opencv_openai",
                "simulated": False,
                "ia_used": True,
                "opencv_used": True,
                "qr_detected": qr_detected,
                "qr_data": qr_data[:300],
                "ocr_method": ocr_method,
                "ocr_text": ocr_text[:2000],
                "model": vision_model,
                "duration_sec": duration,
                "warnings": []
            })
            return result

        except Exception as e:
            print(f"Falha na chamada da OpenAI: {str(e)}. Utilizando fallback local OMR.")

    # 6. Retorno de Fallback Local (OpenCV OMR)
    duration = time.time() - start_time
    warnings = []
    if api_key and vision_enabled:
        warnings.append("Falha na chamada de IA (OpenAI). Usando fallback local OpenCV OMR.")
    elif not vision_enabled:
        warnings.append("Analise de IA desativada nas configuraçoes. Usando processamento local OpenCV OMR.")
    if db_order and not qr_detected and friendly_number_from_ocr:
        warnings.append(f"OM identificada por OCR do cabecalho: {friendly_number_from_ocr}. Conferir antes de aplicar.")
    if db_order and not any((item.get("status") or "") for item in omr_results):
        warnings.append("Nao foi possivel detectar marcacoes com confianca. Conferir itens manualmente.")

    if db_order:
        items_res = []
        for idx, item in enumerate(db_order.items):
            chk_item_res = await db.execute(select(ChecklistItem).where(ChecklistItem.id == item.item_id))
            chk_item = chk_item_res.scalars().first()
            item_num = chk_item.item_number if chk_item else str(idx + 1)

            omr_status = ""
            omr_conf = 0.0
            if idx < len(omr_results):
                omr_status = omr_results[idx]["status"]
                omr_conf = omr_results[idx]["confidence"]
                if omr_status == "ambiguous":
                    warnings.append(f"Item {item_num} possui marcacao ambigua ou rasura.")

            items_res.append({
                "item_id": item.item_id,
                "item_number": item_num,
                "status": omr_status,
                "notes": "",
                "confidence": omr_conf
            })

        return {
            "order_id": db_order.id,
            "patrimonio": db_order.asset.patrimonio,
            "asset_description": db_order.asset.description,
            "date": header_fields.get("date_raw") or date.today().isoformat(),
            "operator_name": header_fields.get("operator_name") or "",
            "materials": "",
            "items": items_res,
            "final_condition": "released",
            "is_operable": True,
            "signature_present": False,
            "provider": "opencv_local",
            "simulated": False,
            "ia_used": False,
            "opencv_used": True,
            "qr_detected": qr_detected,
            "qr_data": qr_data[:300],
            "ocr_method": ocr_method,
            "ocr_text": ocr_text[:2000],
            "friendly_number_detected": db_order.friendly_number,
            "model": "none",
            "duration_sec": duration,
            "warnings": warnings
        }
    else:
        return {
            "order_id": None,
            "patrimonio": "",
            "asset_description": "",
            "date": date.today().isoformat(),
            "operator_name": "",
            "materials": "",
            "items": [],
            "final_condition": "released",
            "is_operable": True,
            "signature_present": False,
            "provider": "opencv_local",
            "simulated": False,
            "ia_used": False,
            "opencv_used": True,
            "qr_detected": qr_detected,
            "qr_data": qr_data[:300],
            "ocr_method": ocr_method,
            "ocr_text": ocr_text[:2000],
            "friendly_number_detected": friendly_number_from_ocr,
            "model": "none",
            "duration_sec": duration,
            "warnings": warnings + ["QR Code nao identificado. Associe a OM manualmente no sistema."]
        }
