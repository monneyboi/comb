"""Command-line interface for comb."""

import multiprocessing as mp
import shutil
import time
from pathlib import Path

import click
import orjson

from .dump_reader import calculate_file_chunks, read_chunk_lines
from .filter import ATTRIBUTES, FilterConfig, filter_entity

PROGRESS_EVERY = 1_000_000


def parse_tokens(
    value: str | None, valid: frozenset[str] | None = None
) -> frozenset[str] | None:
    """Split a comma-separated argument into a token set.

    Returns ``None`` for an unset argument. Tokens may be validated against
    ``valid``; property IDs are validated by pattern in ``parse_properties``.
    """
    if value is None:
        return None
    tokens = {token.strip() for token in value.split(",")}
    if any(not token for token in tokens):
        raise click.UsageError(f"empty element in list: {value!r}")
    if valid is not None and (invalid := tokens - valid):
        raise click.UsageError(
            f"unknown attribute(s): {', '.join(sorted(invalid))}; "
            f"valid attributes: {', '.join(ATTRIBUTES)}"
        )
    return frozenset(tokens)


def parse_properties(value: str | None) -> frozenset[str] | None:
    """Parse a comma-separated property ID list; None means no filter."""
    if value is None:
        return None
    tokens = parse_tokens(value)
    invalid = sorted(
        token
        for token in tokens
        if not token.startswith("P") or not token[1:].isdigit()
    )
    if invalid:
        raise click.UsageError(
            f"invalid property ID(s): {', '.join(invalid)}; expected e.g. P31, P279"
        )
    return tokens


def format_bytes(count: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if count < 1024 or unit == "TiB":
            return f"{count} B" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024


def format_duration(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{sec:02d}s" if hours else f"{minutes}m{sec:02d}s"


def _process_chunk(
    input_path: str,
    start_byte: int,
    end_byte: int,
    part_path: str,
    worker_id: int,
    config: FilterConfig,
) -> tuple[int, int, int, int]:
    """Filter one byte range of the dump into a part file.

    Returns ``(read, kept, malformed, written)`` counts for this chunk.
    """
    read = 0
    kept = 0
    malformed = 0
    written = 0

    with open(part_path, "wb") as output_stream:
        for line in read_chunk_lines(input_path, start_byte, end_byte):
            line = line.strip()
            if not line or line in (b"[", b"]"):
                continue
            if line.endswith(b","):
                line = line[:-1]

            try:
                entity = orjson.loads(line)
            except orjson.JSONDecodeError:
                malformed += 1
                continue
            if (
                not isinstance(entity, dict)
                or not isinstance(entity.get("id"), str)
                or not isinstance(entity.get("type"), str)
            ):
                malformed += 1
                continue

            read += 1
            filtered = filter_entity(entity, config)
            if filtered is None:
                continue

            encoded = orjson.dumps(filtered)
            output_stream.write(encoded)
            output_stream.write(b"\n")
            written += len(encoded) + 1
            kept += 1

            if read % PROGRESS_EVERY == 0:
                click.echo(
                    f"worker {worker_id}: {read:,} read ({kept:,} kept)", err=True
                )

    return read, kept, malformed, written


@click.command()
@click.argument(
    "input_path", type=click.Path(exists=True, dir_okay=False), metavar="INPUT"
)
@click.argument("output_path", type=click.Path(dir_okay=False), metavar="OUTPUT")
@click.option(
    "--types",
    type=click.Choice(["item", "property", "both"]),
    default="item",
    show_default=True,
    help="Entity types to keep.",
)
@click.option(
    "--attributes",
    metavar="LIST",
    help=(
        "Comma-separated entity attributes to keep, out of: "
        f"{', '.join(ATTRIBUTES)}. Default: all. id and type are always kept."
    ),
)
@click.option(
    "--properties",
    metavar="LIST",
    help=(
        "Comma-separated property IDs; keep claims for these properties only. "
        "Default: all."
    ),
)
def main(input_path, output_path, types, attributes, properties):
    """Filter a Wikidata JSON dump into a lean NDJSON subset.

    INPUT is split into one byte-range chunk per worker and filtered in
    parallel, one process per CPU core; OUTPUT preserves dump order. Input
    must be a file of uncompressed JSON; decompress before running comb.

    Every option selects what to keep; anything not selected is filtered out.
    With no options, comb converts the dump to items-only NDJSON, untouched.
    """
    type_map = {
        "item": frozenset({"item"}),
        "property": frozenset({"property"}),
        "both": frozenset({"item", "property"}),
    }
    attribute_set = parse_tokens(attributes, valid=frozenset(ATTRIBUTES)) or frozenset(
        ATTRIBUTES
    )
    property_set = parse_properties(properties)

    if property_set is not None and "claims" not in attribute_set:
        raise click.UsageError("--properties requires keeping the claims attribute")
    if input_path == output_path:
        raise click.UsageError("INPUT and OUTPUT are the same file")

    config = FilterConfig(
        types=type_map[types],
        attributes=attribute_set,
        properties=property_set,
    )

    started = time.monotonic()
    chunks = calculate_file_chunks(input_path)
    part_paths = [f"{output_path}.{i}.part" for i in range(len(chunks))]

    pool = None
    try:
        pool = mp.Pool(processes=mp.cpu_count())
        results = pool.starmap_async(
            _process_chunk,
            [
                (input_path, start, end, part_path, i, config)
                for i, ((start, end), part_path) in enumerate(zip(chunks, part_paths))
            ],
        ).get()
    except KeyboardInterrupt:
        click.echo(
            f"Interrupted after {format_duration(time.monotonic() - started)}; "
            "no output written",
            err=True,
        )
        if pool:
            pool.terminate()
            pool.join()
        for part_path in part_paths:
            Path(part_path).unlink(missing_ok=True)
        raise SystemExit(130)
    finally:
        if pool:
            pool.close()
            pool.join()

    with open(output_path, "wb") as output_stream:
        for part_path in part_paths:
            with open(part_path, "rb") as part_stream:
                shutil.copyfileobj(part_stream, output_stream)
            Path(part_path).unlink()

    totals = [sum(counts) for counts in zip(*results)] if results else [0, 0, 0, 0]
    read, kept, malformed, written = totals
    click.echo(
        f"Done: {read:,} read, {kept:,} kept, {malformed} malformed, "
        f"{format_bytes(written)} written in "
        f"{format_duration(time.monotonic() - started)}",
        err=True,
    )
