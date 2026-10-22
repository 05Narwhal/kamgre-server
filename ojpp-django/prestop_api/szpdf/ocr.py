"""Timetable cells that exist only as a picture: a screenshot pasted over the table (11056 Vintgar – Jesenice,
where the text underneath is stale and lacks bus 4292).

The image's area is rendered at 400 dpi (pypdfium2), its own grid lines are found with a pixel scan, and each cell
is read by the tesseract CLI (one thread, digits and the few letters a cell can hold). Rows are matched by height
to the table's rows, whose labels stay in the text layer; the image's columns replace the text columns under it
(their count can differ: 9 in the image over 8 in the text of 11056).
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile

from .layout import Cell, Column
from .tables import row_kind

logger = logging.getLogger(__name__)

DPI = 400
WHITELIST = '0123456789:/IBUS+*'
DARK = 110  # grey level of grid lines
INK = 160  # grey level of text (the lighter rows are grey on blue)


def apply(path, page, grid, images) -> list[str]:
    """Replace the grid's cells under any image that covers part of the table. Returns file-level problems."""
    problems = []
    for im in images:
        box = _overlap(grid.bbox, im)
        if box is None:
            continue
        under = [c for c in grid.columns[1:] if box[0] <= (c.x0 + c.x1) / 2 <= box[2] and _data(grid, c)]
        if not shutil.which('tesseract'):
            problems.append(f'page {grid.page + 1}: an image covers the table and was not read (tesseract is not '
                            f'installed: apt-get install tesseract-ocr)')
            for c in under:
                c.problems.append('under a pasted image that was not read')
            continue
        try:
            columns = read(path, grid, box)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            problems.append(f'page {grid.page + 1}: the image over the table could not be read ({e})')
            for c in under:
                c.problems.append('under a pasted image that was not read')
            continue
        _compare(grid, under, columns)
        grid.stale += under
        grid.columns = [c for c in grid.columns if c not in under] + columns
        grid.columns[1:] = sorted(grid.columns[1:], key=lambda c: c.x0)
    return problems


def _overlap(bbox, im) -> tuple | None:
    """The part of the image inside the table, when most of the image is."""
    x0, top, x1, bottom = max(bbox[0], im['x0']), max(bbox[1], im['top']), min(bbox[2], im['x1']), min(bbox[3], im['bottom'])
    area = (im['x1'] - im['x0']) * (im['bottom'] - im['top'])
    if x1 <= x0 or bottom <= top or area <= 0 or (x1 - x0) * (bottom - top) < area / 2:
        return None
    return im['x0'], im['top'], im['x1'], im['bottom']


def _data(grid, col) -> bool:
    """A column with something other than P/O marks."""
    return any(cell.text.strip() not in ('', 'P', 'O') for cell in col.cells)


def render(path, page_index: int, box) -> 'Image.Image':
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[page_index]
        width, height = page.get_size()
        x0, top, x1, bottom = box
        bitmap = page.render(scale=DPI / 72, crop=(max(x0, 0), max(height - bottom, 0), max(width - x1, 0), max(top, 0)))
        return bitmap.to_pil().convert('RGB')
    finally:
        pdf.close()


def lines(gray, axis: int, share: float) -> list[tuple[int, int]]:
    """Runs of pixel columns (axis 0) or rows (axis 1) that are dark over `share` of the image: grid lines."""
    w, h = gray.size
    data = gray.load()
    span, other = (w, h) if axis == 0 else (h, w)
    runs = []
    for i in range(span):
        dark = sum(1 for j in range(other) if (data[i, j] if axis == 0 else data[j, i]) < DARK)
        if dark > share * other:
            if runs and runs[-1][1] == i - 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
    return [tuple(r) for r in runs]


def _between(runs, size, minimum=12) -> list[tuple[int, int]]:
    edges = [(-1, -1), *runs, (size, size)]
    return [(a[1] + 1, b[0] - 1) for a, b in zip(edges, edges[1:]) if b[0] - a[1] > minimum]


def read(path, grid, box) -> list[Column]:
    img = render(path, grid.page, box)
    gray = img.convert('L')
    w, h = gray.size
    # Grid lines cross the whole image; the bottoms of a row of bold "BUS" are dark over half its width.
    cols = _between(lines(gray, 0, 0.8), w)
    rows = _between(lines(gray, 1, 0.9), h)
    scale = 72 / DPI
    x0, top = box[0], box[1]
    kinds = [row_kind(c.text) for c in grid.columns[0].cells]
    out = []
    for cx0, cx1 in cols:
        cells = [Cell() for _ in grid.rows]
        for ry0, ry1 in rows:
            mid = top + (ry0 + ry1) / 2 * scale
            r = next((i for i, (t, b) in enumerate(grid.rows) if t <= mid <= b), None)
            if r is None:
                continue
            crop = img.crop((cx0 + 2, ry0 + 2, cx1 - 1, ry1 - 1))
            cells[r] = Cell(_ocr(crop, kinds[r]), _red(crop))
        if any(c.text for c in cells):
            out.append(Column(x0 + cx0 * scale, x0 + cx1 * scale, cells, source='ocr'))
    return out


def _red(crop) -> bool:
    return sum(1 for r, g, b in crop.getdata() if r > 150 and g < 90 and b < 90) > 10


def _ocr(crop, kind: str) -> str:
    gray = crop.convert('L')
    if sum(1 for v in gray.getdata() if v < INK) < 15:
        return ''
    from PIL import ImageOps
    ink = gray.point(lambda v: 0 if v < INK else 255)
    ink = ImageOps.expand(ink, border=20, fill=255)
    with tempfile.TemporaryDirectory(prefix='szpdf-') as tmp:
        name = os.path.join(tmp, 'cell.png')
        ink.save(name)
        done = subprocess.run(['tesseract', name, 'stdout', '--psm', '7', '-c', f'tessedit_char_whitelist={WHITELIST}'],
                              capture_output=True, text=True, timeout=30, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
    if done.returncode:
        raise subprocess.SubprocessError(done.stderr.strip()[-200:])
    text = ''.join(done.stdout.split())
    if kind == 'station' and re.fullmatch(r'\d{4}', text):  # a colon too thin to survive
        text = f'{text[:2]}:{text[2:]}'
    return text


def _compare(grid, stale: list[Column], read_columns: list[Column]):
    """Log where the picture and the stale text under it disagree for the same train."""
    train = next((i for i, c in enumerate(grid.columns[0].cells) if row_kind(c.text) == 'train'), None)
    if train is None:
        return
    labels = [c.text for c in grid.columns[0].cells]
    by_label = {c.cells[train].text: c for c in read_columns}
    for old in stale:
        new = by_label.get(old.cells[train].text)
        if new is None:
            logger.info('Pasted image dropped train %s', old.cells[train].text)
            continue
        for r, (a, b) in enumerate(zip(old.cells, new.cells)):
            if a.text != b.text:
                logger.info('Pasted image changes train %s, row %s: %r → %r', old.cells[train].text, labels[r], a.text, b.text)
    for new in read_columns:
        if new.cells[train].text not in {o.cells[train].text for o in stale}:
            logger.info('Pasted image adds train %s', new.cells[train].text)
