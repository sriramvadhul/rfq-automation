"""Free OCR for scanned PDFs. Returns '' if the tools are missing.
Needs the Tesseract program (https://github.com/UB-Mannheim/tesseract/wiki) and `pip install pytesseract pymupdf`.
PyMuPDF renders the pages, so Poppler is NOT required (pdf2image + Poppler is used only as a fallback).
For German text install the 'deu' language pack."""
import io
import os
import shutil


def _find_tesseract():
    """Use PATH if possible, otherwise the default Windows install folder."""
    if shutil.which("tesseract"):
        return True
    win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win):
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = win
        return True
    return False


def _render_pages(path, dpi):
    try:                                    # preferred: pure pip, no Poppler
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf           # older PyMuPDF versions
        from PIL import Image
        doc = pymupdf.open(str(path))
        return [Image.open(io.BytesIO(p.get_pixmap(dpi=dpi).tobytes("png"))) for p in doc]
    except ImportError:
        from pdf2image import convert_from_path      # needs Poppler on PATH
        return convert_from_path(str(path), dpi=dpi)


def ocr_pdf(path, lang="eng+deu", dpi=200):
    try:
        import pytesseract
        if not _find_tesseract():
            return ""
        pages = _render_pages(path, dpi)
    except Exception:
        return ""
    try:
        try:
            return "\n".join(pytesseract.image_to_string(p, lang=lang) for p in pages)
        except pytesseract.TesseractError:           # language pack missing -> English only
            return "\n".join(pytesseract.image_to_string(p, lang="eng") for p in pages)
    except Exception:
        return ""
