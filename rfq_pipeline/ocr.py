"""Free OCR for scanned PDFs (Tesseract). Silently returns '' if the tools are missing.
Install: Tesseract + Poppler on your OS, then `pip install pytesseract pdf2image`.
For German text also install the 'deu' language pack and use lang='eng+deu'."""


def ocr_pdf(path, lang="eng+deu", dpi=200):
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return ""
    try:
        pages = convert_from_path(str(path), dpi=dpi)
        try:
            return "\n".join(pytesseract.image_to_string(p, lang=lang) for p in pages)
        except pytesseract.TesseractError:  # language pack missing -> English only
            return "\n".join(pytesseract.image_to_string(p, lang="eng") for p in pages)
    except Exception:
        return ""
