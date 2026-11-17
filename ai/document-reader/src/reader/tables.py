"""Tables as readable text: one line per row, each value with its column name."""
from typing import Any, Dict, List, Optional, Sequence

from .lang import clean_text, detect_language


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if hasattr(value, "isoformat"):
        value = value.isoformat(sep=" ") if hasattr(value, "hour") and (value.hour or value.minute) \
            else value.isoformat()[:10]
    return clean_text(str(value)).replace("\n", " ")


def normalize_rows(rows: Sequence[Sequence[Any]]) -> List[List[str]]:
    """Strings everywhere, empty rows removed, all rows padded to the same width."""
    rows = [[cell_text(c) for c in row] for row in rows]
    rows = [row for row in rows if any(row)]
    width = max((len(r) for r in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def make_table(rows: Sequence[Sequence[Any]], total_rows: Optional[int] = None) -> Optional[Dict]:
    """First non-empty row is the header. None when the table is empty."""
    rows = normalize_rows(rows)
    if not rows:
        return None
    columns = [c or f"{i + 1}" for i, c in enumerate(rows[0])]
    table = {"columns": columns, "rows": rows[1:]}
    if total_rows is not None:
        table["total_rows"] = total_rows
    return table


def table_text(table: Dict) -> str:
    """'الاسم: أحمد، الدرجة: 90' per row; a one-row table is its header values."""
    columns, rows = table["columns"], table["rows"]
    sep = "، " if detect_language(" ".join(columns)) in ("ar", "mixed") else "; "
    if not rows:
        return sep.join(c for c in columns if c)
    lines = []
    for row in rows:
        parts = [f"{col}: {val}" for col, val in zip(columns, row) if val]
        if parts:
            lines.append(sep.join(parts))
    return "\n".join(lines)
