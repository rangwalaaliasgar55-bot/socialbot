"""Thread / carousel support — smart splitting of long content.

``split_thread`` breaks text into numbered parts that fit a platform's length
limit, preferring sentence boundaries and keeping human-readable numbering
("1/3"). ``split_carousel`` is the same machinery for Instagram-style carousel
captions where each slide carries its own (optional) caption.
"""
from __future__ import annotations

import re
from typing import List, Optional

MIN_PART = 60          # never produce absurdly short parts
MAX_PARTS = 25         # safety ceiling
PART_LABEL = "{i}/{n} · "


def _sentences(text: str) -> List[str]:
    """Split text into sentence-ish chunks, preserving newlines as breaks."""
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [c.strip() for c in chunks if c.strip()]


def split_thread(text: str, max_length: Optional[int] = None,
                 label: str = PART_LABEL, min_part: int = MIN_PART) -> List[str]:
    """Split *text* into numbered thread parts that each fit *max_length*.

    Returns ``[text]`` when the text already fits (or there's no limit).
    """
    max_length = max_length or 280
    if len(text) <= max_length:
        return [text]

    sentences = _sentences(text)
    parts: List[str] = []
    current: List[str] = []

    def flush():
        nonlocal current
        if current:
            parts.append(" ".join(current))
            current = []

    for sentence in sentences:
        probe = " ".join(current + [sentence]) if current else sentence
        if len(probe) <= max_length:
            current.append(sentence)
            continue
        flush()
        # a single sentence may still be too long — hard-split it
        if len(sentence) > max_length:
            parts.extend(_hard_split(sentence, max_length))
        else:
            current.append(sentence)

    flush()

    # re-number: parts must fit label overhead
    n = len(parts)
    if n == 1:
        return [parts[0]]
    if n > MAX_PARTS:
        merged: List[str] = []
        buffer = ""
        for part in parts:
            if len(buffer) + len(part) + 1 <= max_length:
                buffer = f"{buffer} {part}".strip()
            else:
                merged.append(buffer)
                buffer = part
        if buffer:
            merged.append(buffer)
        parts = merged
        n = len(parts)

    numbered: List[str] = []
    for i, part in enumerate(parts, 1):
        prefix = label.format(i=i, n=n)
        room = max_length - len(prefix)
        if len(part) > room:
            part = _hard_split(part, room)[0]
        numbered.append(prefix + part)
    return numbered


def split_carousel(text: str, slides: Optional[int] = None,
                   max_length: Optional[int] = None) -> List[str]:
    """Split text into carousel captions (one per slide).

    When *slides* is given the text is distributed across exactly that many
    parts; otherwise the same sentence-aware split as :func:`split_thread`
    applies (without numbering, since each slide is its own caption).
    """
    max_length = max_length or 280
    if slides and slides > 1:
        sentences = _sentences(text)
        per_slide = max(1, len(sentences) // slides)
        parts: List[str] = []
        for i in range(0, len(sentences), per_slide):
            part = " ".join(sentences[i:i + per_slide])
            if len(part) > max_length:
                part = _hard_split(part, max_length)[0]
            parts.append(part)
            if len(parts) >= slides:
                break
        return parts
    if len(text) > max_length:
        return split_thread(text, max_length, label="")
    return [text]


def _hard_split(text: str, max_length: int) -> List[str]:
    words = text.split()
    parts: List[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_length:
            current = f"{current} {word}".strip()
        else:
            if current:
                parts.append(current)
            current = word
            while len(current) > max_length:  # pathological single word
                parts.append(current[:max_length])
                current = current[max_length:]
    if current:
        parts.append(current)
    return parts