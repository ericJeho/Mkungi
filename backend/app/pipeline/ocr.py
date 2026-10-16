"""OCR engines behind one interface so they can be swapped or tested."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.models import BBox, TextLine


class OCREngine(Protocol):
    name: str

    def read(self, img: np.ndarray) -> list[TextLine]:
        """Return the text lines found in a BGR page image."""
        ...


class PaddleOCREngine:
    """PaddleOCR adapter. Imported lazily: the dependency is large."""

    name = "paddleocr"

    def __init__(self, lang: str = "en") -> None:
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)

    def read(self, img: np.ndarray) -> list[TextLine]:
        result = self._ocr.ocr(img, cls=True) or []
        lines: list[TextLine] = []
        for page in result:
            for quad, (text, conf) in page or []:
                xs = [int(p[0]) for p in quad]
                ys = [int(p[1]) for p in quad]
                lines.append(
                    TextLine(text=text, bbox=BBox(min(xs), min(ys), max(xs), max(ys)), confidence=float(conf))
                )
        return lines


class TesseractEngine:
    """Fallback engine via pytesseract, grouped to line level."""

    name = "tesseract"

    def __init__(self, lang: str = "eng") -> None:
        import pytesseract

        self._tess = pytesseract
        self._lang = lang

    def read(self, img: np.ndarray) -> list[TextLine]:
        d = self._tess.image_to_data(img, lang=self._lang, output_type=self._tess.Output.DICT)
        groups: dict[tuple[int, int, int], list[int]] = {}
        for i, word in enumerate(d["text"]):
            if word.strip() and float(d["conf"][i]) >= 0:
                groups.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
        lines = []
        for idx in groups.values():
            x0 = min(d["left"][i] for i in idx)
            y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx)
            y1 = max(d["top"][i] + d["height"][i] for i in idx)
            conf = sum(float(d["conf"][i]) for i in idx) / len(idx) / 100
            lines.append(TextLine(" ".join(d["text"][i] for i in idx), BBox(x0, y0, x1, y1), conf))
        return lines


def get_engine(name: str, lang: str = "en") -> OCREngine:
    if name == "paddleocr":
        return PaddleOCREngine(lang)
    if name == "tesseract":
        return TesseractEngine("eng" if lang == "en" else lang)
    raise ValueError(f"Unknown OCR engine: {name}")
