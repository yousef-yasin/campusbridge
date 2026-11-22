"""One camera frame -> measurements of the page in it (OpenCV only, a few ms on a CPU).

The frame is scaled to config.work_width first. White paper on a light table has weak edges,
so the page is found from its writing:
1. dark strokes: an adaptive threshold (local contrast), kept only where the background - the
   grey level with the writing closed over - is at least half as bright as the brightest
   area (paper, including shadowed paper; not a dark table);
2. the strokes are joined into blocks, and the biggest block plus the blocks of similar size
   are the page's content; its rotated bounding box is the content area.
If the paper's own edges are clear (a four-sided contour around the content, not much
bigger), its corners are used instead: they also show the phone's tilt (perspective).
Coordinates in the result are in the ORIGINAL frame, so the capture can be cut from it.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .config import GuideConfig


@dataclass
class FrameReport:
    found: bool
    quad: Optional[np.ndarray] = None          # 4x2 corners (tl, tr, br, bl), original pixels
    source: str = ""                           # "paper" (paper edges) or "content" (the writing)
    area: float = 0.0                          # page area / frame area
    offset: Tuple[float, float] = (0.0, 0.0)   # page centre - frame centre, share of width/height
    cut: List[str] = field(default_factory=list)   # frame sides the page goes past
    rotation: float = 0.0                      # degrees the page is turned in the frame
    side_ratio: float = 1.0                    # shorter/longer opposite sides (1 = phone level)
    sharpness: float = 0.0                     # variance of the Laplacian on the page
    brightness: float = 0.0                    # mean grey level of the frame
    glare: float = 0.0                         # share of saturated pixels on the page
    ms: float = 0.0
    size: Tuple[int, int] = (0, 0)             # original width, height

    def to_dict(self) -> Dict:
        return {"found": self.found, "source": self.source,
                "quad": None if self.quad is None else [[round(float(v), 1) for v in p] for p in self.quad],
                "area": round(self.area, 3), "offset": [round(float(v), 3) for v in self.offset],
                "cut": self.cut, "rotation": round(self.rotation, 1), "side_ratio": round(self.side_ratio, 3),
                "sharpness": round(self.sharpness, 1), "brightness": round(self.brightness, 1),
                "glare": round(self.glare, 3), "ms": round(self.ms, 1)}


def order_corners(pts) -> np.ndarray:
    """(tl, tr, br, bl) from any four points."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _content(gray: np.ndarray):
    """(corners of the writing, mask of its strokes) or (None, None)."""
    h, w = gray.shape
    strokes = cv2.adaptiveThreshold(cv2.GaussianBlur(gray, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                    cv2.THRESH_BINARY_INV, max(15, (w // 16) | 1), 12)
    strokes = cv2.morphologyEx(strokes, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 12),) * 2))
    background = cv2.GaussianBlur(background, (0, 0), max(1.0, w / 60))
    level = max(60.0, 0.5 * float(np.percentile(background, 98)))
    strokes[background < level] = 0
    joined = cv2.dilate(strokes, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 18), max(3, h // 40))),
                        iterations=2)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blocks = sorted((c for c in contours if cv2.contourArea(c) > 0.01 * w * h), key=cv2.contourArea, reverse=True)
    if not blocks:
        return None, None
    group = [blocks[0]] + [c for c in blocks[1:] if cv2.contourArea(c) > 0.15 * cv2.contourArea(blocks[0])]
    region = np.zeros_like(joined)
    cv2.drawContours(region, group, -1, 255, -1)
    ys, xs = np.nonzero(cv2.bitwise_and(strokes, region))
    if len(xs) < 50:
        return order_corners(cv2.boxPoints(cv2.minAreaRect(np.vstack(group)))), strokes
    # a few marks at the edge (writing of the pages underneath, a pen) must not stretch the page:
    # drop the outermost 0.2% of the writing on each side
    x_lo, x_hi = np.percentile(xs, [0.2, 99.8])
    y_lo, y_hi = np.percentile(ys, [0.2, 99.8])
    keep = (xs >= x_lo) & (xs <= x_hi) & (ys >= y_lo) & (ys <= y_hi)
    points = np.column_stack([xs[keep], ys[keep]]).astype(np.float32)
    on_page = cv2.bitwise_and(strokes, region)
    return order_corners(cv2.boxPoints(cv2.minAreaRect(points))), on_page


def _cut_sides(strokes: np.ndarray, margin: float, share: float) -> List[str]:
    """Frame sides that writing runs into: in the outer strip of that side, the writing covers
    more than `share` of the side's length (scattered marks cover much less)."""
    h, w = strokes.shape
    mx, my = max(2, int(margin * w)), max(2, int(margin * h))
    strips = {"left": strokes[:, :mx].any(axis=1), "right": strokes[:, w - mx:].any(axis=1),
              "top": strokes[:my, :].any(axis=0), "bottom": strokes[h - my:, :].any(axis=0)}
    out = []
    for side, hits in strips.items():
        # spread the hits a little: a text line touching the edge counts for its height
        covered = np.convolve(hits.astype(np.float32), np.ones(9, np.float32), "same") > 0
        if covered.mean() > share:
            out.append(side)
    return out


def _paper(gray: np.ndarray, content: np.ndarray) -> Optional[np.ndarray]:
    """The paper's own corners, when a clear four-sided edge contour surrounds the content."""
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blur))
    edges = cv2.Canny(blur, int(max(10, 0.4 * median)), int(min(255, median)))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    content_area = cv2.contourArea(content)
    center = tuple(map(float, content.mean(axis=0)))
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:4]:
        hull = cv2.convexHull(contour)
        approx = cv2.approxPolyDP(hull, 0.03 * cv2.arcLength(hull, True), True)
        if len(approx) != 4:
            continue
        quad = order_corners(approx)
        area = cv2.contourArea(quad)
        # with perspective the paper is a trapezoid, narrower than the box around the writing:
        # it must hold the writing's centre and be of a similar size
        if 0.75 * content_area <= area <= 2.2 * content_area and cv2.pointPolygonTest(quad, center, False) > 0:
            return quad
    return None


def analyze(frame: np.ndarray, config: GuideConfig) -> FrameReport:
    start = time.perf_counter()
    H, W = frame.shape[:2]
    scale = config.work_width / float(W) if W > config.work_width else 1.0
    small = cv2.resize(frame, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    h, w = gray.shape
    report = FrameReport(found=False, size=(W, H), brightness=float(gray.mean()))
    content, strokes = _content(gray)
    if content is not None:
        paper = _paper(gray, content)
        quad = paper if paper is not None else content
        report.found, report.source = True, "paper" if paper is not None else "content"
        report.quad = quad / scale
        report.area = float(cv2.contourArea(quad)) / (w * h)
        dx = (float(quad[:, 0].mean()) - w / 2) / w
        dy = (float(quad[:, 1].mean()) - h / 2) / h
        report.offset = (-dx if config.mirrored else dx, dy)
        mx, my = config.edge_margin * w, config.edge_margin * h
        cut = _cut_sides(strokes, config.edge_margin, config.cut_share)
        if paper is not None:          # paper corners on the border: the paper itself is cut
            cut += [side for side, hit in (("left", quad[:, 0].min() <= mx), ("right", quad[:, 0].max() >= w - 1 - mx),
                                           ("top", quad[:, 1].min() <= my), ("bottom", quad[:, 1].max() >= h - 1 - my))
                    if hit and side not in cut]
        if config.mirrored:
            cut = [{"left": "right", "right": "left"}.get(c, c) for c in cut]
        report.cut = cut
        tl, tr, br, bl = quad
        angle = float(np.degrees(np.arctan2(tr[1] - tl[1], tr[0] - tl[0])))
        report.rotation = ((angle + 45) % 90) - 45             # 0 = upright (or a quarter turn)
        if paper is not None:
            sides = [np.linalg.norm(tr - tl), np.linalg.norm(br - bl), np.linalg.norm(bl - tl), np.linalg.norm(br - tr)]
            report.side_ratio = float(min(min(sides[0], sides[1]) / max(sides[0], sides[1], 1e-6),
                                          min(sides[2], sides[3]) / max(sides[2], sides[3], 1e-6)))
        mask = np.zeros_like(gray)
        cv2.fillConvexPoly(mask, np.clip(quad, 0, [w - 1, h - 1]).astype(np.int32), 255)
        x0, y0, bw, bh = cv2.boundingRect(np.clip(quad, 0, [w - 1, h - 1]).astype(np.int32))
        crop = gray[y0:y0 + bh, x0:x0 + bw]
        if crop.size and crop.shape[1] > 8:
            crop = cv2.resize(crop, (320, max(1, int(320 * crop.shape[0] / crop.shape[1]))))
            report.sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        on_page = gray[mask > 0]
        report.glare = float((on_page >= 250).mean()) if on_page.size else 0.0
    report.ms = (time.perf_counter() - start) * 1000
    return report
