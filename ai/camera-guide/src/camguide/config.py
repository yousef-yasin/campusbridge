"""Settings (CAMERA_* environment variables). All analysis is local: OpenCV, no AI, no internet."""
import os
from dataclasses import dataclass, fields


@dataclass
class GuideConfig:
    work_width: int = 480              # frames are scaled to this width before analysis
    min_area: float = 0.50             # writing smaller than this share of the frame -> "move closer"
    center_tolerance: float = 0.12     # page centre further than this (share of width/height) -> move
    edge_margin: float = 0.015         # outer strip of the frame checked for writing that runs off it
    cut_share: float = 0.12            # writing over this share of a side's strip -> the page is cut there
    max_rotation: float = 12.0         # degrees: page turned more than this in the frame -> tilt
    min_side_ratio: float = 0.78       # shorter/longer opposite sides: smaller = phone tilted
    min_sharpness: float = 60.0        # variance of the Laplacian on the page (scaled) -> "hold still"
    min_brightness: float = 70.0       # mean grey level of the frame (0-255) -> "too dark"
    max_glare: float = 0.06            # share of saturated pixels on the page -> "glare"
    hold_seconds: float = 1.0          # every check must pass this long before the photo is taken
    repeat_seconds: float = 3.0        # the same command is not said again before this
    min_gap_seconds: float = 0.8       # minimum time between two spoken commands
    stable_frames: int = 2             # a new command must be seen this many frames in a row
    mirrored: bool = False             # front camera preview (left and right swapped)

    @classmethod
    def from_env(cls) -> "GuideConfig":
        cfg = cls()
        for f in fields(cls):
            value = os.environ.get(f"CAMERA_{f.name.upper()}")
            if value is not None:
                kind = type(getattr(cfg, f.name))
                setattr(cfg, f.name, value.lower() in ("1", "true", "yes") if kind is bool else kind(value))
        return cfg
