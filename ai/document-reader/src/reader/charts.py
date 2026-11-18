"""Native charts in .pptx and .xlsx files: their data is read from the file, without AI."""
import re
import zipfile
from typing import Callable, Dict, List, Optional
from xml.etree import ElementTree as ET

from .lang import detect_language, is_rtl
from .model import Block
from .tables import cell_text

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_MAX_POINTS = 25
_TYPES = (("pie", "pie"), ("doughnut", "pie"), ("line", "line"), ("bar", "bar"), ("column", "bar"),
          ("area", "area"), ("scatter", "scatter"), ("bubble", "scatter"), ("radar", "radar"))
_NAMES = {"ar": {"bar": "أعمدة", "line": "خطي", "pie": "دائري", "area": "مساحي", "scatter": "نقطي",
                 "radar": "راداري"},
          "en": {"bar": "bar", "line": "line", "pie": "pie", "area": "area", "scatter": "scatter",
                 "radar": "radar"}}


def chart_kind(name: str) -> str:
    name = (name or "").lower()
    return next((kind for key, kind in _TYPES if key in name), name or "chart")


def chart_text(chart: Dict) -> str:
    """Readable summary: type, title, axes, then one line per series with its values."""
    words = " ".join([chart.get("title") or ""] + [s.get("name") or "" for s in chart["series"]]
                     + [str(c) for c in chart.get("categories", [])[:5]])
    ar = is_rtl(words)
    lang = "ar" if ar else "en"
    kind = _NAMES[lang].get(chart["type"], chart["type"])
    sep = "، " if ar else ", "
    head = f"مخطط {kind}" if ar else f"{kind.capitalize()} chart"
    if chart.get("title"):
        head += f" بعنوان «{chart['title']}»" if ar else f" titled \"{chart['title']}\""
    lines = [head]
    if chart.get("x_axis"):
        lines.append(f"المحور الأفقي: {chart['x_axis']}" if ar else f"Horizontal axis: {chart['x_axis']}")
    if chart.get("y_axis"):
        lines.append(f"المحور الرأسي: {chart['y_axis']}" if ar else f"Vertical axis: {chart['y_axis']}")
    categories = chart.get("categories") or []
    for series in chart["series"]:
        values = series.get("values") or []
        points = []
        for i, value in enumerate(values[:_MAX_POINTS]):
            label = categories[i] if i < len(categories) else str(i + 1)
            points.append(f"{label} {value if value != '' else ('بدون قيمة' if ar else 'no value')}")
        more = len(values) - _MAX_POINTS
        tail = (f"{sep}و{more} قيمة أخرى" if ar else f"{sep}and {more} more") if more > 0 else ""
        name = series.get("name") or ("السلسلة" if ar else "Series")
        lines.append(f"{name}: {sep.join(points)}{tail}")
    return "\n".join(lines)


def chart_block(chart: Dict, unit: int, unit_type: str, sheet: Optional[str] = None) -> Block:
    text = chart_text(chart)
    return Block("chart", text, detect_language(text), unit, unit_type, sheet, chart=chart)


# --- PowerPoint ---------------------------------------------------------------------------

def _axis_title(axis) -> str:
    try:
        return axis.axis_title.text_frame.text.strip() if axis.has_title else ""
    except Exception:
        return ""


def pptx_chart(shape) -> Optional[Dict]:
    """Chart data from a python-pptx chart shape (cached values saved by PowerPoint)."""
    try:
        chart = shape.chart
        title = ""
        if chart.has_title and chart.chart_title.has_text_frame:
            title = chart.chart_title.text_frame.text.strip()
        plots = list(chart.plots)
        categories = [cell_text(c) for c in plots[0].categories] if plots else []
        series = [{"name": s.name or "", "values": [cell_text(v) for v in s.values]}
                  for plot in plots for s in plot.series]
        x_axis = y_axis = ""
        try:
            x_axis, y_axis = _axis_title(chart.category_axis), _axis_title(chart.value_axis)
        except Exception:
            pass                                   # pie charts have no axes
        kind = getattr(chart.chart_type, "name", str(chart.chart_type))
        return {"type": chart_kind(kind), "source_type": kind, "title": title, "x_axis": x_axis,
                "y_axis": y_axis, "categories": categories, "series": series}
    except Exception:
        return None


# --- Excel --------------------------------------------------------------------------------

def _texts(node) -> str:
    return "".join(t.text or "" for t in node.iter(f"{A}t")).strip() if node is not None else ""


def _rels(z: zipfile.ZipFile, part: str) -> Dict[str, str]:
    folder, name = part.rsplit("/", 1)
    rels_path = f"{folder}/_rels/{name}.rels"
    if rels_path not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(rels_path)).iter(f"{REL}Relationship"):
        target = rel.get("Target", "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            parts = folder.split("/")
            for piece in target.split("/"):
                if piece == "..":
                    parts.pop()
                elif piece != ".":
                    parts.append(piece)
            path = "/".join(parts)
        out[rel.get("Id")] = (rel.get("Type", "").rsplit("/", 1)[-1], path)
    return out


def _cache_or_ref(node, resolve: Callable[[str], List[str]]):
    """Values from a series reference: the cached points, else the referenced cells."""
    if node is None:
        return []
    cache = next((n for n in node.iter() if n.tag in (f"{C}strCache", f"{C}numCache")), None)
    if cache is not None and cache.find(f"{C}pt") is not None:
        count_node = cache.find(f"{C}ptCount")
        count = int(count_node.get("val")) if count_node is not None else 0
        values = [""] * count
        for pt in cache.findall(f"{C}pt"):
            idx = int(pt.get("idx", "0"))
            if idx >= len(values):
                values.extend([""] * (idx + 1 - len(values)))
            values[idx] = cell_text((pt.findtext(f"{C}v") or "").strip())
        return values
    literal = node.find(f"{C}v")
    if literal is not None:
        return [cell_text(literal.text)]
    formula = next((n.text for n in node.iter(f"{C}f") if n.text), None)
    return resolve(formula) if formula else []


def _parse_chart(xml: bytes, resolve) -> Optional[Dict]:
    root = ET.fromstring(xml)
    plot = root.find(f"{C}chart/{C}plotArea")
    if plot is None:
        return None
    charts = [n for n in plot if n.tag.endswith("Chart")]
    if not charts:
        return None
    kind = charts[0].tag.replace(C, "")
    series, categories = [], []
    for node in charts:
        for ser in node.findall(f"{C}ser"):
            name = _cache_or_ref(ser.find(f"{C}tx"), resolve)
            values = _cache_or_ref(ser.find(f"{C}val") if ser.find(f"{C}val") is not None
                                   else ser.find(f"{C}yVal"), resolve)
            cats = _cache_or_ref(ser.find(f"{C}cat") if ser.find(f"{C}cat") is not None
                                 else ser.find(f"{C}xVal"), resolve)
            categories = categories or cats
            series.append({"name": name[0] if name else "", "values": values})
    title = _texts(root.find(f"{C}chart/{C}title"))
    x_axis = _texts(plot.find(f"{C}catAx/{C}title")) or _texts(plot.find(f"{C}dateAx/{C}title"))
    y_axis = _texts(plot.find(f"{C}valAx/{C}title"))
    return {"type": chart_kind(kind), "source_type": kind, "title": title, "x_axis": x_axis,
            "y_axis": y_axis, "categories": categories, "series": series,
            "missing_values": any(v == "" for s in series for v in s["values"])}


def xlsx_charts(path, sheet_parts: Dict[str, str], resolve) -> Dict[str, List[Dict]]:
    """Charts per sheet name. sheet_parts: sheet name -> 'xl/worksheets/sheetN.xml'."""
    out: Dict[str, List[Dict]] = {}
    with zipfile.ZipFile(path) as z:
        for sheet, part in sheet_parts.items():
            for kind, drawing in _rels(z, part).values():
                if kind != "drawing" or drawing not in z.namelist():
                    continue
                for kind2, chart_part in _rels(z, drawing).values():
                    if kind2 == "chart" and chart_part in z.namelist():
                        chart = _parse_chart(z.read(chart_part), resolve)
                        if chart:
                            out.setdefault(sheet, []).append(chart)
    return out


def parse_ref(formula: str):
    """"'Sheet name'!$B$4:$B$23" -> ('Sheet name', 'B4:B23')."""
    sheet, _, cells = formula.rpartition("!")
    sheet = sheet.strip()
    if sheet.startswith("'") and sheet.endswith("'"):
        sheet = sheet[1:-1].replace("''", "'")
    return sheet, re.sub(r"\$", "", cells)
