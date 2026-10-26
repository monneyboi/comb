"""Tests for byte-range chunk calculation."""

from itertools import pairwise

from comb.dump_reader import calculate_file_chunks


def test_chunks_align_to_line_boundaries(tmp_path):
    # Lines of irregular length, including ones longer than the newline
    # search block, so boundaries must scan across blocks.
    lengths = [5, 300, 9000, 7, 12000, 40, 1, 5000]
    data = b"\n".join(b"x" * length for length in lengths) + b"\n"
    path = tmp_path / "dump.json"
    path.write_bytes(data)

    chunks = calculate_file_chunks(str(path), num_chunks=4)

    # Long lines can make boundaries overshoot, so the count may fall short
    assert 2 <= len(chunks) <= 4
    assert chunks[0][0] == 0
    assert chunks[-1][1] == len(data)
    for (_, end), (next_start, _) in pairwise(chunks):
        assert end == next_start  # contiguous
    for start, end in chunks:
        if start != 0:
            assert data[start - 1 : start] == b"\n"
        if end != len(data):
            assert data[end - 1 : end] == b"\n"


def test_small_file_gets_single_chunk(tmp_path):
    path = tmp_path / "dump.json"
    path.write_bytes(b'{"id": "Q42"}\n')

    assert calculate_file_chunks(str(path)) == [(0, path.stat().st_size)]
