"""End-to-end conversion: upload bytes in, editable file out."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import DocumentLayout
from app.pipeline.classify import classify, recommended_format
from app.pipeline.layout import analyse_page
from app.pipeline.ocr import OCREngine
from app.pipeline.preprocess import enhance, load_pages
from app.pipeline.writers.docx_writer import write_docx
from app.pipeline.writers.xlsx_writer import write_xlsx

FORMATS = {"docx", "xlsx", "auto"}
MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass
class ConversionResult:
    layout: DocumentLayout
    output_format: str
    data: bytes


def build_layout(data: bytes, filename: str, engine: OCREngine) -> DocumentLayout:
    pages = []
    for img in load_pages(data, filename):
        img = enhance(img)
        pages.append(analyse_page(img, engine.read(img)))
    text = "\n".join(ln.text for p in pages for ln in p.lines)
    return DocumentLayout(pages=pages, doc_type=classify(text))


def convert(data: bytes, filename: str, output_format: str, engine: OCREngine) -> ConversionResult:
    if output_format not in FORMATS:
        raise ValueError(f"output_format must be one of {sorted(FORMATS)}")
    layout = build_layout(data, filename, engine)
    fmt = recommended_format(layout.doc_type) if output_format == "auto" else output_format
    out = write_docx(layout) if fmt == "docx" else write_xlsx(layout)
    return ConversionResult(layout=layout, output_format=fmt, data=out)
