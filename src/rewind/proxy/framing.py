"""Newline-delimited JSON frames.

Payload size is the UTF-8 byte length after removing one trailing LF, and one
leading-side CR when the delimiter is CRLF. Character counts are never used.
An oversized frame halts the decoder; later bytes in that buffer are discarded
and the decoder does not resynchronize.
"""

from __future__ import annotations

import errno
import json
from collections.abc import Awaitable
from typing import NamedTuple

from rewind.constants import DEFAULT_MAX_FRAME_BYTES


class Frame(NamedTuple):
    payload: bytes


class OversizedFrame(NamedTuple):
    pass


class IncompleteFrame(NamedTuple):
    pass


Decoded = Frame | OversizedFrame


class FrameDecoder:
    def __init__(self, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
        if max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be positive")
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self.halted = False

    def feed(self, data: bytes) -> list[Decoded]:
        if self.halted or data == b"":
            return []
        self._buffer.extend(data)
        output: list[Decoded] = []
        while not self.halted:
            newline = self._buffer.find(b"\n")
            if newline == -1:
                if self._pending_exceeds_limit():
                    self._halt()
                    output.append(OversizedFrame())
                return output
            raw_line = bytes(self._buffer[:newline])
            payload = raw_line[:-1] if raw_line.endswith(b"\r") else raw_line
            if len(payload) > self.max_frame_bytes:
                self._halt()
                output.append(OversizedFrame())
                return output
            del self._buffer[: newline + 1]
            output.append(Frame(payload))
        return output

    def finish(self) -> IncompleteFrame | OversizedFrame | None:
        """Classify bytes left after EOF. Does not invent a following frame."""

        if self.halted or not self._buffer:
            return None
        if self._pending_exceeds_limit():
            self._halt()
            return OversizedFrame()
        self._halt()
        return IncompleteFrame()

    def _pending_exceeds_limit(self) -> bool:
        size = len(self._buffer)
        if size > self.max_frame_bytes + 1:
            return True
        return size == self.max_frame_bytes + 1 and not self._buffer.endswith(b"\r")

    def _halt(self) -> None:
        self.halted = True
        self._buffer.clear()


def encode_frame(message: object, max_frame_bytes: int) -> bytes | None:
    try:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return None
    if len(payload) > max_frame_bytes:
        return None
    return payload + b"\n"


def is_broken_stream(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    return isinstance(exc, OSError) and exc.errno in {errno.EPIPE, errno.ECONNRESET}


async def write_frame(writer: object, message: object, max_frame_bytes: int, lock: object) -> bool:
    frame = encode_frame(message, max_frame_bytes)
    if frame is None:
        return False
    try:
        async with lock:  # type: ignore[attr-defined]
            writer.write(frame)  # type: ignore[attr-defined]
            await writer.drain()  # type: ignore[attr-defined]
        return True
    except (BrokenPipeError, ConnectionResetError, RuntimeError):
        return False
    except OSError as exc:
        if is_broken_stream(exc):
            return False
        raise


async def write_frame_unlocked(writer: object, message: object, max_frame_bytes: int) -> bool:
    frame = encode_frame(message, max_frame_bytes)
    if frame is None:
        return False
    try:
        writer.write(frame)  # type: ignore[attr-defined]
        drain: Awaitable[None] = writer.drain()  # type: ignore[attr-defined]
        await drain
        return True
    except (BrokenPipeError, ConnectionResetError, RuntimeError):
        return False
    except OSError as exc:
        if is_broken_stream(exc):
            return False
        raise
