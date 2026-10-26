"""Byte-range chunk reading for parallel dump processing."""

import multiprocessing as mp
import os
from collections.abc import Iterator

# Minimum bytes per chunk when the chunk count is chosen automatically.
MIN_CHUNK_SIZE = 1024 * 1024

# Block size used when scanning for the next newline past a chunk boundary.
_NEWLINE_SEARCH_BLOCK = 4096


def _next_line_start(f, from_pos: int, file_size: int) -> int:
    """Return the first position at or after from_pos that starts a line.

    Scans forward in blocks until a newline is found; returns ``file_size``
    if none exists before the end of the file.
    """
    f.seek(from_pos)
    pos = from_pos
    while pos < file_size:
        block = f.read(min(_NEWLINE_SEARCH_BLOCK, file_size - pos))
        newline_pos = block.find(b"\n")
        if newline_pos != -1:
            return pos + newline_pos + 1
        pos += len(block)
    return file_size


def calculate_file_chunks(
    dump_file_path: str, num_chunks: int | None = None
) -> list[tuple[int, int]]:
    """Split a file into roughly equal byte ranges on line boundaries.

    Each chunk starts at 0 or immediately after a newline, so workers can
    seek to their start and read whole lines independently; the last chunk
    extends to the end of the file. ``num_chunks`` selects the chunk count
    explicitly; by default it is the CPU count, reduced for small files.
    """
    file_size = os.path.getsize(dump_file_path)

    if num_chunks is None:
        num_chunks = mp.cpu_count()
        if file_size < num_chunks * MIN_CHUNK_SIZE:
            num_chunks = max(1, file_size // MIN_CHUNK_SIZE)

    chunk_size = file_size // num_chunks
    chunks = []

    current_pos = 0
    with open(dump_file_path, "rb") as f:
        for i in range(num_chunks):
            start_pos = current_pos

            if i == num_chunks - 1:
                end_pos = file_size
            else:
                end_pos = _next_line_start(f, start_pos + chunk_size, file_size)

            if start_pos < end_pos:
                chunks.append((start_pos, end_pos))

            current_pos = end_pos
            if current_pos >= file_size:
                break

    return chunks


def read_chunk_lines(
    dump_file_path: str, start_byte: int, end_byte: int
) -> Iterator[bytes]:
    """Yield raw lines whose start position falls within the byte range.

    Assumes ``start_byte`` is aligned to a line boundary, as guaranteed by
    :func:`calculate_file_chunks`.
    """
    with open(dump_file_path, "rb") as f:
        f.seek(start_byte)
        current_pos = start_byte
        while current_pos < end_byte:
            line = f.readline()
            current_pos = f.tell()
            yield line
