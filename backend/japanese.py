"""Japanese word segmentation and furigana. Optional: degrades to plain text."""

from __future__ import annotations

import re

try:
    import fugashi

    _TAGGER = fugashi.Tagger()
except Exception:  # pragma: no cover - optional dependency
    _TAGGER = None

AVAILABLE = _TAGGER is not None

_KANJI = re.compile(r"[一-鿿々]")
_KANA_ONLY = re.compile(r"^[぀-ゟ゠-ヿー]+$")
_PUNCT = "補助記号"

# Parts of speech not worth offering as vocabulary.
_SKIP_POS = {"助詞", "助動詞", "補助記号", "空白"}


def katakana_to_hiragana(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(char)
    return "".join(out)


def tokenize(text: str) -> list[dict]:
    """Split Japanese text into tokens with readings and furigana ruby parts.

    Each token: {s: surface, r: reading (hiragana), b: dictionary form,
                 p: part of speech, v: is it vocabulary-worthy,
                 ruby: [[base, furigana|None], ...]}
    """
    if not AVAILABLE or not text.strip():
        return [{"s": text, "r": "", "b": "", "p": "", "v": False, "ruby": [[text, None]]}]

    tokens = []
    for word in _TAGGER(text):
        surface = word.surface
        feature = word.feature
        kana = getattr(feature, "kana", None) or getattr(feature, "pron", None) or ""
        reading = katakana_to_hiragana(kana) if kana else ""
        lemma = getattr(feature, "lemma", None) or surface
        pos = getattr(feature, "pos1", None) or ""
        tokens.append(
            {
                "s": surface,
                "r": reading,
                "b": (lemma or surface).split("-")[0],
                "p": pos,
                "v": pos not in _SKIP_POS and not _PUNCT in pos and bool(surface.strip()),
                "ruby": furigana(surface, reading),
            }
        )
    return tokens


def furigana(surface: str, reading: str) -> list[list]:
    """Split a surface into [text, ruby-or-None] pairs so kana keep no ruby.

    `勉強し` + `べんきょうし` -> [["勉強", "べんきょう"], ["し", None]]
    """
    if not reading or not _KANJI.search(surface):
        return [[surface, None]]
    if _KANA_ONLY.match(surface):
        return [[surface, None]]

    hira_surface = katakana_to_hiragana(surface)

    # Trim kana that match at both ends; whatever is left is the kanji core.
    head = 0
    while (
        head < len(surface)
        and head < len(reading)
        and not _KANJI.match(surface[head])
        and hira_surface[head] == reading[head]
    ):
        head += 1

    tail = 0
    while (
        tail < len(surface) - head
        and tail < len(reading) - head
        and not _KANJI.match(surface[len(surface) - 1 - tail])
        and hira_surface[len(surface) - 1 - tail] == reading[len(reading) - 1 - tail]
    ):
        tail += 1

    core_surface = surface[head: len(surface) - tail]
    core_reading = reading[head: len(reading) - tail]
    if not core_surface or not core_reading:
        return [[surface, reading if _KANJI.search(surface) else None]]

    parts = []
    if head:
        parts.append([surface[:head], None])
    parts.append([core_surface, core_reading])
    if tail:
        parts.append([surface[len(surface) - tail:], None])
    return parts


def annotate(segments: list[dict]) -> list[dict]:
    """Attach a token list to every transcript segment."""
    for segment in segments:
        segment["tokens"] = tokenize(segment["text"])
    return segments
