import os
from dataclasses import dataclass


def _detect_device() -> str:
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


@dataclass
class STTConfig:
    """Settings, overridable through STT_* environment variables."""
    model: str = "small"            # tiny/base/small/medium/large-v3 or a local path
    device: str = "auto"            # auto/cpu/cuda
    compute_type: str = "auto"      # auto -> int8 on CPU, float16 on CUDA
    language: str = "ar"
    beam_size: int = 5
    vad_filter: bool = True
    sample_rate: int = 16000

    @classmethod
    def from_env(cls) -> "STTConfig":
        e = os.environ.get
        return cls(
            model=e("STT_MODEL", cls.model),
            device=e("STT_DEVICE", cls.device),
            compute_type=e("STT_COMPUTE_TYPE", cls.compute_type),
            language=e("STT_LANGUAGE", cls.language),
            beam_size=int(e("STT_BEAM_SIZE", cls.beam_size)),
            vad_filter=e("STT_VAD_FILTER", "1").lower() not in ("0", "false", "no"),
        )

    def resolved(self) -> tuple:
        """Return (device, compute_type) with 'auto' values resolved."""
        device = _detect_device() if self.device == "auto" else self.device
        compute = self.compute_type
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return device, compute
