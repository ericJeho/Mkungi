"""Image enhancement: load, deskew and clean a scan before OCR."""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image


def load_pages(data: bytes, filename: str, max_pages: int | None = None) -> list[np.ndarray]:
    """Decode an upload into BGR page images.

    PDFs are rendered at 300 dpi with pdfium; images are decoded with Pillow
    (multi-frame TIFFs give one page per frame).
    """
    if filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise ValueError(f"Unsupported or corrupt PDF: {filename}") from exc
        _check_pages(len(pdf), max_pages)
        pages = []
        for page in pdf:
            pil = page.render(scale=300 / 72).to_pil().convert("RGB")
            pages.append(cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR))
        pdf.close()
        return pages

    try:
        img = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Unsupported or corrupt file: {filename}") from exc
    n = getattr(img, "n_frames", 1)
    _check_pages(n, max_pages)
    pages = []
    for i in range(n):
        img.seek(i)
        pages.append(cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR))
    return pages


def _check_pages(n: int, max_pages: int | None) -> None:
    if max_pages and n > max_pages:
        raise ValueError(f"Document has {n} pages; the limit is {max_pages}")


def estimate_skew(gray: np.ndarray) -> float:
    """Angle in degrees of the dominant text direction (small angles only)."""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 50:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90
    # Ignore implausible angles; they usually mean a figure, not skew.
    return float(angle) if abs(angle) <= 10 else 0.0


def deskew(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = estimate_skew(gray)
    if abs(angle) < 0.1:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def enhance(img: np.ndarray) -> np.ndarray:
    """Deskew and lightly denoise; colour is kept so logos and stamps survive."""
    img = deskew(img)
    return cv2.fastNlMeansDenoisingColored(img, None, 3, 3, 7, 21)
