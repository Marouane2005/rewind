from __future__ import annotations

from rewind.constants import DEFAULT_MAX_FRAME_BYTES
from rewind.proxy.framing import Frame, FrameDecoder, IncompleteFrame, OversizedFrame


def test_exact_limit_is_accepted_and_one_extra_byte_is_rejected() -> None:
    decoder = FrameDecoder(4)
    assert decoder.feed(b"abcd\n") == [Frame(b"abcd")]
    rejected = FrameDecoder(4)
    assert rejected.feed(b"abcde\n") == [OversizedFrame()]
    assert rejected.halted


def test_crlf_strips_one_delimiter_before_measuring() -> None:
    decoder = FrameDecoder(4)
    assert decoder.feed(b"abcd\r\n") == [Frame(b"abcd")]
    waiting = FrameDecoder(4)
    assert waiting.feed(b"abcd\r") == []
    assert waiting.feed(b"\n") == [Frame(b"abcd")]


def test_utf8_bytes_not_characters() -> None:
    payload = "é".encode()
    assert len(payload) == 2
    assert FrameDecoder(2).feed(payload + b"\n") == [Frame(payload)]
    assert FrameDecoder(1).feed(payload + b"\n") == [OversizedFrame()]


def test_same_chunk_keeps_earlier_frames_and_drops_the_rest() -> None:
    decoder = FrameDecoder(4)
    items = decoder.feed(b"ab\n" + b"xxxxx\n" + b"zz\n")
    assert items == [Frame(b"ab"), OversizedFrame()]
    assert decoder.feed(b"later\n") == []


def test_frame_above_128_kib_within_limit() -> None:
    size = 130 * 1024
    payload = b"a" * size
    decoder = FrameDecoder(size)
    assert decoder.feed(payload + b"\n") == [Frame(payload)]


def test_default_limit_accepts_exact_boundary() -> None:
    payload = b"z" * DEFAULT_MAX_FRAME_BYTES
    decoder = FrameDecoder()
    assert decoder.feed(payload + b"\n") == [Frame(payload)]
    over = FrameDecoder()
    assert over.feed(b"z" * (DEFAULT_MAX_FRAME_BYTES + 1)) == [OversizedFrame()]


def test_incomplete_tail_is_not_a_frame() -> None:
    decoder = FrameDecoder(100)
    assert decoder.feed(b'{"a":1') == []
    assert decoder.finish() == IncompleteFrame()
