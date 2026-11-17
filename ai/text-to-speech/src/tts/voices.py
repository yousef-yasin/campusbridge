"""Ready-made voices the user can pick from, per engine.

gemini: one speaker reads Arabic and English in the same request (the model detects the
language itself). Nika and Finn come from Gemini's Extended Voice Library.
edge: Multilingual voices, chosen by listening to comparison samples.
Other voices of either engine can still be set by their full name.
"""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Voice:
    name: str      # name sent to the engine
    alias: str     # short name accepted by --voice / TTS_GEMINI_VOICE / TTS_EDGE_VOICE
    gender: str    # "male" / "female"
    default: bool = False   # default voice for its gender (within its engine)
    engine: str = "edge"


PRESET_VOICES: List[Voice] = [
    Voice("Nika", "nika", "female", default=True, engine="gemini"),
    Voice("Finn", "finn", "male", default=True, engine="gemini"),
    Voice("en-AU-WilliamMultilingualNeural", "william", "male", default=True),
    Voice("en-US-EmmaMultilingualNeural", "emma", "female", default=True),
    Voice("en-US-BrianMultilingualNeural", "brian", "male"),
    Voice("fr-FR-RemyMultilingualNeural", "remy", "male"),
    Voice("fr-FR-VivienneMultilingualNeural", "vivienne", "female"),
]
DEFAULT_GEMINI_VOICE = "Nika"
DEFAULT_VOICE = "en-AU-WilliamMultilingualNeural"   # edge default
FALLBACK_VOICE = "ar-JO-SanaNeural"                 # edge voice used by the fallback chain


def resolve_voice(name: str, engine: str = "edge") -> str:
    """Full voice name for a preset alias, 'male' or 'female'; other names pass through."""
    key = (name or "").strip().lower()
    for voice in PRESET_VOICES:
        if voice.engine != engine:
            continue
        if key in (voice.alias, voice.name.lower()) or (voice.default and key == voice.gender):
            return voice.name
    return (name or "").strip()


def is_multilingual(name: str) -> bool:
    return "multilingual" in (name or "").lower()
