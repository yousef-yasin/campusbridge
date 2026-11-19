"""Reading order for positioned boxes (PDF text blocks, slide shapes)."""
from typing import List, Sequence, Tuple, TypeVar

T = TypeVar("T")
Box = Tuple[float, float, float, float]   # x0, y0, x1, y1


def order_boxes(items: Sequence[Tuple[Box, T]], rtl: bool, gap: float = 8.0,
                span: float = 0.6) -> List[T]:
    """Natural reading order.

    Columns (a vertical strip of empty space through the whole region) are read right to left
    when rtl, else left to right; inside a column, top to bottom. Boxes spanning most of the
    region's width (titles, full-width paragraphs) split it into bands read top to bottom.
    """
    return [item for _, item in _order(list(items), rtl, gap, span)]


def split_columns(items: Sequence[Tuple[Box, T]], gap: float) -> List[List[Tuple[Box, T]]]:
    """Groups separated by a vertical strip of empty space at least `gap` wide (left to right)."""
    items = list(items)
    return (_columns(items, gap) or [items]) if items else []


def _width(region):
    return max(b[2] for b, _ in region) - min(b[0] for b, _ in region)


def _columns(region, gap):
    """Split by vertical gaps; None when there is no gap."""
    region = sorted(region, key=lambda it: it[0][0])
    groups, current, right = [], [region[0]], region[0][0][2]
    for box, item in region[1:]:
        if box[0] - right >= gap:
            groups.append(current)
            current = []
        current.append((box, item))
        right = max(right, box[2])
    groups.append(current)
    return groups if len(groups) > 1 else None


def _line_sort(region, rtl):
    """Top to bottom; boxes on the same line right-to-left (rtl) or left-to-right."""
    region = sorted(region, key=lambda it: (it[0][1], it[0][0]))
    lines = []
    for box, item in region:
        if lines:
            top, bottom = lines[-1][0]
            overlap = min(bottom, box[3]) - max(top, box[1])
            if overlap > 0.5 * min(bottom - top, box[3] - box[1]):
                lines[-1][1].append((box, item))
                lines[-1][0] = (min(top, box[1]), max(bottom, box[3]))
                continue
        lines.append([(box[1], box[3]), [(box, item)]])
    out = []
    for _, members in lines:
        out.extend(sorted(members, key=lambda it: -it[0][2] if rtl else it[0][0]))
    return out


def _order(region, rtl, gap, span):
    if len(region) <= 1:
        return region
    columns = _columns(region, gap)
    if columns:
        if rtl:
            columns.reverse()
        return [it for col in columns for it in _order(col, rtl, gap, span)]
    width = _width(region)
    spanning = [it for it in region if (it[0][2] - it[0][0]) >= span * width]
    if not spanning or len(spanning) == len(region):
        return _line_sort(region, rtl)
    out, group = [], []
    for it in sorted(region, key=lambda it: (it[0][1], it[0][0])):
        if (it[0][2] - it[0][0]) >= span * width:
            out.extend(_order(group, rtl, gap, span) if group else [])
            out.append(it)
            group = []
        else:
            group.append(it)
    out.extend(_order(group, rtl, gap, span) if group else [])
    return out
