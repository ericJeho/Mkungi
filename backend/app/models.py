"""Layout model shared by every pipeline stage.

The pipeline turns a scan into a ``DocumentLayout`` and the writers turn a
``DocumentLayout`` into .docx / .xlsx. Coordinates are in source-image pixels;
writers scale them to the output page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class BBox:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def overlap_ratio(self, other: "BBox") -> float:
        """Share of *self* covered by *other*."""
        ix = max(0, min(self.x1, other.x1) - max(self.x0, other.x0))
        iy = max(0, min(self.y1, other.y1) - max(self.y0, other.y0))
        area = max(1, self.width * self.height)
        return (ix * iy) / area


@dataclass
class TextLine:
    """One OCR line: text, where it sits, and the style we can infer."""

    text: str
    bbox: BBox
    confidence: float = 1.0
    bold: bool = False
    color: tuple[int, int, int] = (0, 0, 0)


@dataclass
class TableCell:
    row: int
    col: int
    bbox: BBox
    text: str = ""
    row_span: int = 1
    col_span: int = 1


@dataclass
class Table:
    bbox: BBox
    n_rows: int
    n_cols: int
    cells: list[TableCell] = field(default_factory=list)
    col_widths: list[int] = field(default_factory=list)
    row_heights: list[int] = field(default_factory=list)

    def grid(self) -> list[list[str]]:
        out = [["" for _ in range(self.n_cols)] for _ in range(self.n_rows)]
        for c in self.cells:
            out[c.row][c.col] = c.text
        return out


class ImageKind(str, Enum):
    LOGO = "logo"
    SIGNATURE = "signature"
    STAMP = "stamp"
    CODE = "code"  # QR / barcode
    PICTURE = "picture"


@dataclass
class ImageRegion:
    """A non-text region kept as an image so it is preserved exactly."""

    bbox: BBox
    kind: ImageKind
    png: bytes


@dataclass
class Page:
    width: int
    height: int
    lines: list[TextLine] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: list[ImageRegion] = field(default_factory=list)

    def free_lines(self) -> list[TextLine]:
        """Lines that are not inside any table, in reading order."""
        free = [
            ln
            for ln in self.lines
            if not any(t.bbox.contains_point(ln.bbox.cx, ln.bbox.cy) for t in self.tables)
        ]
        return sorted(free, key=lambda ln: (ln.bbox.y0, ln.bbox.x0))


@dataclass
class DocumentLayout:
    pages: list[Page]
    doc_type: str = "general"
    language: str = "en"
