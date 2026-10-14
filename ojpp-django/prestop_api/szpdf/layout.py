"""What is on a timetable page: the tables as grids of cell texts, and the text lines around them (pdfplumber).

Cells are read from the characters, not from pdfplumber's text extraction: edited cells mix fonts whose glyphs sit
a point lower, so characters are grouped into lines with a tolerance and then read left to right.
"""
from bisect import bisect_right
from dataclasses import dataclass, field

BLUE = (0.0, 0.306, 0.486)  # SŽ's heading colour


def is_red(char: dict) -> bool:
    c = char.get('non_stroking_color')
    return isinstance(c, (tuple, list)) and len(c) == 3 and c[0] > 0.6 and c[1] < 0.4 and c[2] < 0.4


def is_blue(char: dict) -> bool:
    c = char.get('non_stroking_color')
    return isinstance(c, (tuple, list)) and len(c) == 3 and all(abs(a - b) < 0.05 for a, b in zip(c, BLUE))


def text_lines(chars: list[dict]) -> list[list[dict]]:
    """Characters grouped into lines (tops within 0.6 of the font size), each read left to right."""
    lines: list[list[dict]] = []
    for c in sorted(chars, key=lambda o: o['top']):
        if lines and c['top'] - lines[-1][0]['top'] < c['size'] * 0.6:
            lines[-1].append(c)
        else:
            lines.append([c])
    return [sorted(line, key=lambda o: o['x0']) for line in lines]


def join(line: list[dict]) -> str:
    """One line of characters as text, with a space where the gap is wider than a fifth of the font size."""
    out = ''
    prev = None
    for c in line:
        if prev is not None and c['text'] != ' ' and not out.endswith(' ') and c['x0'] - prev['x1'] > c['size'] * 0.2:
            out += ' '
        out += c['text']
        prev = c
    return ' '.join(out.split())


@dataclass
class Cell:
    text: str = ''
    red: bool = False


@dataclass
class Column:
    x0: float
    x1: float
    cells: list[Cell]  # one per grid row
    source: str = 'text'  # text | ocr
    problems: list[str] = field(default_factory=list)


@dataclass
class Grid:
    page: int
    bbox: tuple[float, float, float, float]
    rows: list[tuple[float, float]]  # (top, bottom) of each row
    columns: list[Column]
    stale: list[Column] = field(default_factory=list)  # text columns hidden under a pasted image

    def text(self, row: int, col: int) -> str:
        return self.columns[col].cells[row].text


def grids(page, page_index: int) -> list[Grid]:
    """The page's tables. Curves (the direction arrows' heads) are left out when looking for grid lines: one cut
    the last row off 11125's table."""
    plain = page.filter(lambda o: o.get('object_type') != 'curve')
    out = []
    for t in plain.find_tables():
        rows = [(r.bbox[1], r.bbox[3]) for r in t.rows]
        xs = [(c.bbox[0], c.bbox[2]) for c in t.columns]
        cells = [[[] for _ in xs] for _ in rows]
        tops = [r[0] for r in rows]
        lefts = [x[0] for x in xs]
        x0, top, x1, bottom = t.bbox
        for c in page.chars:
            cx, cy = (c['x0'] + c['x1']) / 2, (c['top'] + c['bottom']) / 2
            if x0 <= cx <= x1 and top <= cy <= bottom:
                r, k = bisect_right(tops, cy) - 1, bisect_right(lefts, cx) - 1
                if r >= 0 and k >= 0:
                    cells[r][k].append(c)
        columns = []
        for k, (cx0, cx1) in enumerate(xs):
            col = []
            for r in range(len(rows)):
                chars = [c for c in cells[r][k] if c['text'].strip()]
                text = '\n'.join(join(line) for line in text_lines(cells[r][k])).strip()
                col.append(Cell(text, any(is_red(c) for c in chars)))
            columns.append(Column(cx0, cx1, col))
        out.append(Grid(page_index, tuple(t.bbox), rows, columns))
    return out


@dataclass
class Line:
    page: int
    top: float
    x0: float
    text: str
    red: bool
    blue: bool


def lines(page, page_index: int, outside: list[tuple]) -> list[Line]:
    """Text lines outside the given boxes (the tables), split where a wide gap separates two blocks side by side."""
    chars = [c for c in page.chars if not any(
        b[0] <= (c['x0'] + c['x1']) / 2 <= b[2] and b[1] <= (c['top'] + c['bottom']) / 2 <= b[3] for b in outside)]
    out = []
    for line in text_lines(chars):
        parts = [[line[0]]]
        for c in line[1:]:
            if c['x0'] - parts[-1][-1]['x1'] > max(c['size'] * 4, 20):
                parts.append([c])
            else:
                parts[-1].append(c)
        for part in parts:
            text = join(part)
            ink = [c for c in part if c['text'].strip()]
            if text and ink:
                out.append(Line(page_index, part[0]['top'], part[0]['x0'], text,
                                sum(map(is_red, ink)) * 2 > len(ink), sum(map(is_blue, ink)) * 2 > len(ink)))
    return out
