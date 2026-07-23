"""Codecs: split a stream of lines into events (frames).

Mirrors Logstash codecs (docs/adr/0003). Each codec is a stateful, incremental
framer — ``feed(line)`` returns any events completed by that line, ``flush()``
emits a trailing buffered event at EOF — so the same code serves both fixture
lists (M03) and live async line streams (M04).

Framing only. Parsing the log's own timestamp, extracting route_id, and merging a
JSON frame's fields into the event happen later (track C).
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from vmctl import config


@dataclass
class Frame:
    """One framed event: the raw text (possibly multi-line) plus, for JSON codecs,
    the parsed object (or None if the line was not valid JSON)."""

    raw: str
    parsed: dict[str, Any] | None = None


class Codec(ABC):
    @abstractmethod
    def feed(self, line: str) -> list[Frame]:
        """Return the events completed by consuming this line (usually 0 or 1)."""

    def flush(self) -> list[Frame]:
        """Emit any buffered event at end of input. Default: nothing buffered."""
        return []


class PlainCodec(Codec):
    """One event per line; the raw line is the message."""

    def feed(self, line: str) -> list[Frame]:
        return [Frame(raw=line)]


class JsonCodec(Codec):
    """One event per line, parsed as JSON. A line that is not valid JSON degrades to
    a raw frame (parsed=None) instead of failing."""

    def feed(self, line: str) -> list[Frame]:
        stripped = line.strip()
        if not stripped:
            return []
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return [Frame(raw=line, parsed=None)]
        return [Frame(raw=line, parsed=obj if isinstance(obj, dict) else None)]


class MultilineCodec(Codec):
    """Join several physical lines into one event, Logstash-style.

    A line "triggers" when ``regex.search(line)`` XOR ``negate``. With
    ``what="previous"`` a triggering line appends to the buffered event and a
    non-triggering line starts a new one; ``what="next"`` is the mirror image.
    """

    def __init__(self, pattern: str, *, negate: bool = False, what: str = "previous") -> None:
        self._regex = re.compile(pattern)
        self._negate = negate
        self._what = what
        self._buffer: list[str] = []

    def _triggers(self, line: str) -> bool:
        matched = self._regex.search(line) is not None
        return (not matched) if self._negate else matched

    def feed(self, line: str) -> list[Frame]:
        triggers = self._triggers(line)
        if self._what == "next":
            self._buffer.append(line)
            if triggers:
                return []  # this line joins the next one
            return self._drain()
        # what == "previous"
        if triggers:
            self._buffer.append(line)  # joins the previous event
            return []
        frames = self._drain()  # a non-triggering line starts a new event
        self._buffer.append(line)
        return frames

    def flush(self) -> list[Frame]:
        return self._drain()

    def _drain(self) -> list[Frame]:
        if not self._buffer:
            return []
        frame = Frame(raw="\n".join(self._buffer))
        self._buffer = []
        return [frame]


def make_codec(cfg: config.Codec) -> Codec:
    """Build a codec from its config."""
    if cfg.name == "plain":
        return PlainCodec()
    if cfg.name == "json":
        return JsonCodec()
    if cfg.name == "multiline":
        if cfg.pattern is None:
            raise ValueError("multiline codec requires a pattern")
        return MultilineCodec(cfg.pattern, negate=cfg.negate, what=cfg.what)
    raise ValueError(f"unknown codec: {cfg.name}")


def frame_lines(codec: Codec, lines: Iterable[str]) -> Iterator[Frame]:
    """Frame a finite sequence of lines (feed all, then flush). For fixtures/reads."""
    for line in lines:
        yield from codec.feed(line)
    yield from codec.flush()
