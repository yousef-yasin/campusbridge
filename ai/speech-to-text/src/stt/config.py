import os
from dataclasses import dataclass, replace
from typing import Optional


def _detect_device() -> str:
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


@dataclass
class STTConfig:
    """Settings, overridable through STT_* environment variables."""
    model: str = "medium"           # saved/uploaded audio: tiny/base/small/medium/large-v3 or a path
    live_model: str = "small"       # live microphone sessions
    device: str = "auto"            # auto/cpu/cuda
    compute_type: str = "auto"      # auto -> int8 on CPU, float16 on CUDA
    language: str = "ar"
    beam_size: int = 5
    vad_filter: bool = True
    code_switching: bool = False    # opt-in English re-pass + gap recovery (see codeswitch.py)
    glossary_path: Optional[str] = None  # approved course glossary; None disables term correction
    sample_rate: int = 16000

    @classmethod
    def from_env(cls) -> "STTConfig":
        e = os.environ.get
        return cls(
            model=e("STT_MODEL", cls.model),
            live_model=e("STT_LIVE_MODEL", cls.live_model),
            device=e("STT_DEVICE", cls.device),
            compute_type=e("STT_COMPUTE_TYPE", cls.compute_type),
            language=e("STT_LANGUAGE", cls.language),
            beam_size=int(e("STT_BEAM_SIZE", cls.beam_size)),
            vad_filter=e("STT_VAD_FILTER", "1").lower() not in ("0", "false", "no"),
            code_switching=e("STT_CODE_SWITCHING", "0").lower() in ("1", "true", "yes"),
            glossary_path=e("STT_GLOSSARY") or None,
        )

    def for_live(self) -> "STTConfig":
        """Copy of this config that uses live_model, for live microphone sessions."""
        return replace(self, model=self.live_model)

    def resolved(self) -> tuple:
        """Return (device, compute_type) with 'auto' values resolved."""
        device = _detect_device() if self.device == "auto" else self.device
        compute = self.compute_type
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return device, compute
