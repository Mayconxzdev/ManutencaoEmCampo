"""Extração leve de texto para indexação documental.

A camada base não obriga OCR pesado. Quando MEC_OCR_ENABLED=1 e PaddleOCR
estiver instalado, imagens/PDFs escaneados passam a gerar texto para busca.
"""
from __future__ import annotations

import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Optional

MAX_TEXT_CHARS = 200_000
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _trim(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").split())[:MAX_TEXT_CHARS]


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "sim"}


def _paddle_ocr_image(path: Path) -> tuple[Optional[str], str, bool, Optional[str]]:
    if not _truthy_env("MEC_OCR_ENABLED"):
        return None, "ocr_disabled", True, "OCR automático desabilitado. Defina MEC_OCR_ENABLED=1 para ativar."
    try:
        from paddleocr import PaddleOCR

        lang = os.getenv("MEC_OCR_LANGUAGE", "pt")
        # use_angle_cls ajuda em fotos de documentos tortas; show_log pode não existir em versões novas.
        try:
            ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        except TypeError:
            ocr = PaddleOCR(use_angle_cls=True, lang=lang)
        result = ocr.ocr(str(path), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                try:
                    text = item[1][0]
                except Exception:
                    text = ""
                if text:
                    lines.append(str(text))
        value = _trim("\n".join(lines))
        return value or None, "paddleocr", not bool(value), None if value else "OCR não retornou texto."
    except ImportError:
        return None, "paddleocr_missing", True, "Pacote paddleocr não instalado."
    except Exception as exc:
        return None, "paddleocr_error", True, str(exc)


def _rapidocr_image(path: Path) -> tuple[Optional[str], str, bool, Optional[str]]:
    if not _truthy_env("MEC_OCR_ENABLED"):
        return None, "ocr_disabled", True, "OCR automático desabilitado. Defina MEC_OCR_ENABLED=1 para ativar."
    try:
        from rapidocr_onnxruntime import RapidOCR

        result, _elapsed = RapidOCR()(str(path))
        lines: list[str] = []
        for item in result or []:
            text = item[1] if len(item) > 1 else ""
            if text:
                lines.append(str(text))
        value = _trim("\n".join(lines))
        return value or None, "rapidocr_onnxruntime", not bool(value), None if value else "OCR não retornou texto."
    except ImportError:
        return None, "rapidocr_missing", True, "Pacote rapidocr-onnxruntime não instalado."
    except Exception as exc:
        return None, "rapidocr_error", True, str(exc)


def _ocr_image(path: Path) -> tuple[Optional[str], str, bool, Optional[str]]:
    text_value, method, needs_review, error = _paddle_ocr_image(path)
    if text_value:
        return text_value, method, needs_review, error
    fallback_text, fallback_method, fallback_needs_review, fallback_error = _rapidocr_image(path)
    if fallback_text:
        return fallback_text, fallback_method, fallback_needs_review, fallback_error
    if method == "ocr_disabled":
        return text_value, method, needs_review, error
    combined_error = "; ".join(x for x in [error, fallback_error] if x)
    return None, f"{method}+{fallback_method}", True, combined_error or "OCR não retornou texto."


def _ocr_pdf_with_pymupdf(path: Path) -> tuple[Optional[str], str, bool, Optional[str]]:
    if not _truthy_env("MEC_OCR_ENABLED"):
        return None, "ocr_disabled", True, "PDF parece escaneado, mas OCR está desabilitado."
    try:
        import fitz
    except ImportError:
        return None, "pymupdf_missing_for_ocr", True, "Instale pymupdf para renderizar PDF escaneado antes do OCR."

    try:
        doc = fitz.open(str(path))
        max_pages = int(os.getenv("MEC_OCR_PDF_MAX_PAGES", "12"))
        zoom = float(os.getenv("MEC_OCR_PDF_ZOOM", "2.0"))
        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="mec_pdf_ocr_") as tmp:
            matrix = fitz.Matrix(zoom, zoom)
            for idx, page in enumerate(doc[:max_pages]):
                image_path = Path(tmp) / f"page_{idx+1:03d}.png"
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                pix.save(str(image_path))
                text_value, _, _, _ = _ocr_image(image_path)
                if text_value:
                    texts.append(text_value)
                if len("\n".join(texts)) > MAX_TEXT_CHARS:
                    break
        value = _trim("\n".join(texts))
        return value or None, "pymupdf+paddleocr", not bool(value), None if value else "OCR do PDF não retornou texto."
    except Exception as exc:
        return None, "pdf_ocr_error", True, str(exc)


def extract_text(path: str | Path) -> tuple[Optional[str], str, bool, Optional[str]]:
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".log"}:
            return _trim(p.read_text(encoding="utf-8", errors="ignore")), "text", False, None
        if suffix == ".csv":
            raw = p.read_text(encoding="utf-8", errors="ignore")
            rows = []
            for row in csv.reader(io.StringIO(raw)):
                rows.append(" | ".join(row))
                if len("\n".join(rows)) > MAX_TEXT_CHARS:
                    break
            return _trim("\n".join(rows)), "csv", False, None
        if suffix == ".docx":
            from docx import Document

            doc = Document(str(p))
            text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
            return _trim(text), "python-docx", False, None
        if suffix in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook

            wb = load_workbook(str(p), read_only=True, data_only=True)
            lines: list[str] = []
            for ws in wb.worksheets[:10]:
                lines.append(f"# {ws.title}")
                for row in ws.iter_rows(max_row=300, values_only=True):
                    values = [str(cell) for cell in row if cell is not None]
                    if values:
                        lines.append(" | ".join(values))
                    if len("\n".join(lines)) > MAX_TEXT_CHARS:
                        break
            return _trim("\n".join(lines)), "openpyxl", False, None
        if suffix == ".pdf":
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(str(p))
                text = "\n".join(page.get_text("text") for page in doc[:80])
                value = _trim(text)
                if value:
                    return value, "pymupdf", False, None
                return _ocr_pdf_with_pymupdf(p)
            except ImportError:
                try:
                    from pypdf import PdfReader

                    reader = PdfReader(str(p))
                    text = "\n".join(page.extract_text() or "" for page in reader.pages[:80])
                    value = _trim(text)
                    if value:
                        return value, "pypdf", False, None
                    return _ocr_pdf_with_pymupdf(p)
                except ImportError:
                    return None, "not_available", True, "Instale pymupdf ou pypdf para extrair texto de PDF."
        if suffix in IMAGE_SUFFIXES:
            return _ocr_image(p)
        return None, "unsupported", suffix in IMAGE_SUFFIXES.union({".pdf"}), "Formato sem extração textual no pacote base."
    except Exception as exc:
        return None, "error", True, str(exc)
