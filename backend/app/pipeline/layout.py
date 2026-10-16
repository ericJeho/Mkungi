"""Layout analysis: ruled tables, preserved image regions and text style.

This is the classical-CV baseline. A learned layout model (LayoutLMv3 / DiT,
see docs/BUILD_CHECKLIST.md phase 3) slots in by producing the same
``Table`` / ``ImageRegion`` objects.
"""

from __future__ import annotations

import statistics

import cv2
import numpy as np

from app.models import BBox, ImageKind, ImageRegion, Page, Table, TableCell, TextLine


def _binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = binary.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 40)))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk)
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk)
    return horiz, vert


def _cluster(positions: np.ndarray, gap: int = 5) -> list[int]:
    """Collapse runs of adjacent indices (a thick rule) into one coordinate."""
    if len(positions) == 0:
        return []
    out, run = [], [int(positions[0])]
    for p in positions[1:]:
        if p - run[-1] <= gap:
            run.append(int(p))
        else:
            out.append(sum(run) // len(run))
            run = [int(p)]
    out.append(sum(run) // len(run))
    return out


def detect_tables(gray: np.ndarray) -> list[Table]:
    binary = _binarize(gray)
    horiz, vert = _line_masks(binary)
    grid = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    tables: list[Table] = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 80 or h < 30:
            continue
        # Solid shapes (logos, filled banners) open into "lines" too; a table is mostly paper.
        if (binary[y : y + h, x : x + w] > 0).mean() > 0.5:
            continue
        hsub = horiz[y : y + h, x : x + w]
        vsub = vert[y : y + h, x : x + w]
        # A row rule must span most of the table; a column rule most of its height.
        ys = _cluster(np.where((hsub > 0).sum(axis=1) > 0.5 * w)[0])
        xs = _cluster(np.where((vsub > 0).sum(axis=0) > 0.5 * h)[0])
        if len(ys) < 2 or len(xs) < 2 or (len(ys) == 2 and len(xs) == 2):
            continue  # a lone box is a frame, not a table
        n_rows, n_cols = len(ys) - 1, len(xs) - 1
        table = Table(
            bbox=BBox(x, y, x + w, y + h),
            n_rows=n_rows,
            n_cols=n_cols,
            col_widths=[xs[i + 1] - xs[i] for i in range(n_cols)],
            row_heights=[ys[i + 1] - ys[i] for i in range(n_rows)],
        )
        for r in range(n_rows):
            c = 0
            while c < n_cols:
                span = 1
                # Merge right while the separating rule is missing in this row.
                while c + span < n_cols:
                    sep = vsub[ys[r] + 2 : ys[r + 1] - 2, max(0, xs[c + span] - 2) : xs[c + span] + 3]
                    if sep.size and (sep.max(axis=1) > 0).mean() > 0.5:
                        break
                    span += 1
                table.cells.append(
                    TableCell(
                        row=r,
                        col=c,
                        col_span=span,
                        bbox=BBox(x + xs[c], y + ys[r], x + xs[c + span], y + ys[r + 1]),
                    )
                )
                c += span
        tables.append(table)
    return sorted(tables, key=lambda t: t.bbox.y0)


def fill_tables(tables: list[Table], lines: list[TextLine]) -> None:
    for table in tables:
        for cell in table.cells:
            inside = [ln for ln in lines if cell.bbox.contains_point(ln.bbox.cx, ln.bbox.cy)]
            inside.sort(key=lambda ln: (ln.bbox.y0, ln.bbox.x0))
            cell.text = "\n".join(ln.text for ln in inside)


def infer_styles(img: np.ndarray, lines: list[TextLine]) -> None:
    """Estimate bold and colour per line from its ink."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = _binarize(gray)
    densities = []
    for ln in lines:
        b = ln.bbox
        roi = binary[b.y0 : b.y1, b.x0 : b.x1]
        densities.append(float((roi > 0).mean()) if roi.size else 0.0)
    if not densities:
        return
    median = statistics.median(densities) or 1e-6
    for ln, dens in zip(lines, densities):
        ln.bold = dens > 1.35 * median
        b = ln.bbox
        roi_px = img[b.y0 : b.y1, b.x0 : b.x1][binary[b.y0 : b.y1, b.x0 : b.x1] > 0]
        if len(roi_px):
            bgr = np.median(roi_px, axis=0)
            rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
            # Near-grey ink is black text that scanned slightly light.
            ln.color = (0, 0, 0) if max(rgb) - min(rgb) < 40 else rgb


def _classify_region(crop: np.ndarray, bbox: BBox, page_h: int) -> ImageKind:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ink = (gray < 200) | (hsv[..., 1] > 60)
    ink_ratio = float(ink.mean())
    # Saturation measured on the ink only, so a hollow stamp still reads as coloured.
    coloured = float((hsv[..., 1][ink] > 80).mean()) if ink.any() else 0.0
    aspect = bbox.width / max(1, bbox.height)
    if coloured < 0.1 and 0.8 < aspect < 1.25 and 0.3 < ink_ratio < 0.7:
        return ImageKind.CODE  # QR: square, roughly half dark, monochrome
    if coloured < 0.1 and aspect > 3 and 0.3 < ink_ratio < 0.7 and bbox.height > 20:
        return ImageKind.CODE  # barcode strip
    if bbox.cy < 0.25 * page_h:
        return ImageKind.LOGO
    if coloured > 0.5 and 0.7 < aspect < 1.4 and ink_ratio < 0.5:
        return ImageKind.STAMP  # coloured, round-ish, hollow
    if coloured < 0.5 and ink_ratio < 0.15:
        return ImageKind.SIGNATURE  # sparse thin strokes
    return ImageKind.PICTURE


def detect_images(img: np.ndarray, lines: list[TextLine], tables: list[Table]) -> list[ImageRegion]:
    """Find ink that is neither OCR text nor table content and keep it as images."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 1]
    # Global ink mask: dark or coloured pixels, so solid logos keep their interior.
    mask = (((gray < 160) | (sat > 60)) * 255).astype(np.uint8)
    for t in tables:
        b = t.bbox
        mask[b.y0 : b.y1 + 1, b.x0 : b.x1 + 1] = 0
    for ln in lines:
        b = ln.bbox
        mask[b.y0 : b.y1, b.x0 : b.x1] = 0
    horiz, vert = _line_masks(_binarize(gray))
    # Long free-standing rules (dividers, signature lines) are layout, not images.
    mask[((horiz > 0) | (vert > 0)) & (sat < 60)] = 0

    page_h, page_w = gray.shape
    blob = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    min_side = max(24, min(page_h, page_w) // 40)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < min_side or h < min_side:
            continue
        # Trim the dilation margin back to the actual ink.
        ys, xs = np.where(mask[y : y + h, x : x + w] > 0)
        if len(xs) == 0:
            continue
        x, y, w, h = x + xs.min(), y + ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        bbox = BBox(int(x), int(y), int(x + w), int(y + h))
        crop = img[bbox.y0 : bbox.y1, bbox.x0 : bbox.x1]
        ok, png = cv2.imencode(".png", crop)
        if ok:
            regions.append(ImageRegion(bbox=bbox, kind=_classify_region(crop, bbox, page_h), png=png.tobytes()))
    return regions


def analyse_page(img: np.ndarray, lines: list[TextLine]) -> Page:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    tables = detect_tables(gray)
    fill_tables(tables, lines)
    infer_styles(img, lines)
    images = detect_images(img, lines, tables)
    return Page(width=w, height=h, lines=lines, tables=tables, images=images)
