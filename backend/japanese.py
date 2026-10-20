"""Japanese word segmentation and furigana. Optional: degrades to plain text.

Two dictionaries are supported. unidic-lite gives the better readings and is
what a local install uses. It is 248 MB, which does not fit inside a serverless
function, so ipadic (51 MB) is used instead when unidic is absent.
"""

from __future__ import annotations

import re

_TAGGER = None
DICTIONARY = None


def _setup():
    """Pick whichever dictionary is installed, best first."""
    global _TAGGER, DICTIONARY
    try:
        import fugashi
    except Exception:  # pragma: no cover - optional dependency
        return

    try:
        import unidic_lite  # noqa: F401

        _TAGGER = fugashi.Tagger()
        DICTIONARY = "unidic"
        return
    except Exception:
        pass

    try:
        import ipadic

        _TAGGER = fugashi.GenericTagger(ipadic.MECAB_ARGS)
        DICTIONARY = "ipadic"
    except Exception:
        pass


_setup()
AVAILABLE = _TAGGER is not None

_KANJI = re.compile(r"[一-鿿々]")
_KANA_ONLY = re.compile(r"^[぀-ゟ゠-ヿー]+$")

# Parts of speech not worth offering as vocabulary. Both dictionaries' tags:
# unidic marks punctuation 補助記号, ipadic marks it 記号.
_SKIP_POS = {"助詞", "助動詞", "補助記号", "記号", "空白", "フィラー"}


def katakana_to_hiragana(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(char)
    return "".join(out)


def _read(word) -> tuple[str, str, str]:
    """(part of speech, dictionary form, katakana reading) for either dictionary."""
    feature = word.feature
    if DICTIONARY == "unidic":
        return (
            getattr(feature, "pos1", "") or "",
            getattr(feature, "lemma", None) or word.surface,
            getattr(feature, "kana", None) or getattr(feature, "pron", None) or "",
        )

    # ipadic: pos1, pos2, pos3, pos4, conj type, conj form, base, reading, pron
    fields = list(feature)
    get = lambda index: (fields[index] if len(fields) > index and fields[index] != "*" else "")
    return get(0), get(6) or word.surface, get(7)


def tokenize(text: str) -> list[dict]:
    """Split Japanese text into tokens with readings and furigana ruby parts."""
    if not AVAILABLE or not text.strip():
        return [{"s": text, "r": "", "b": "", "p": "", "v": False, "ruby": [[text, None]]}]

    tokens = []
    for word in _TAGGER(text):
        surface = word.surface
        pos, lemma, kana = _read(word)
        reading = katakana_to_hiragana(kana) if kana else ""
        tokens.append(
            {
                "s": surface,
                "r": reading,
                "b": (lemma or surface).split("-")[0],
                "p": pos,
                "v": pos not in _SKIP_POS and bool(surface.strip()),
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
