"""Command-line interface for comb."""

import sys
import time
from contextlib import ExitStack

import click
import orjson

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


@click.command()
@click.argument("input_path", metavar="INPUT")
@click.argument("output_path", metavar="OUTPUT")
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

    INPUT and OUTPUT are file paths, or "-" for stdin/stdout. Input is
    always uncompressed JSON; decompress with the shell if needed.

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
    if input_path == output_path and input_path != "-":
        raise click.UsageError("INPUT and OUTPUT are the same file")

    config = FilterConfig(
        types=type_map[types],
        attributes=attribute_set,
        properties=property_set,
    )

    read = 0
    kept = 0
    malformed = 0
    written = 0
    started = time.monotonic()

    with ExitStack() as stack:
        input_stream = (
            sys.stdin.buffer
            if input_path == "-"
            else stack.enter_context(open(input_path, "rb"))
        )
        output_stream = (
            sys.stdout.buffer
            if output_path == "-"
            else stack.enter_context(open(output_path, "wb"))
        )
        try:
            for line in input_stream:
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
                    click.echo(f"{read:,} entities read ({kept:,} kept)", err=True)
        except KeyboardInterrupt:
            click.echo(
                f"Interrupted: {read:,} read, {kept:,} kept, {malformed} malformed, "
                f"{format_bytes(written)} written in "
                f"{format_duration(time.monotonic() - started)}",
                err=True,
            )
            raise SystemExit(130)

    click.echo(
        f"Done: {read:,} read, {kept:,} kept, {malformed} malformed, "
        f"{format_bytes(written)} written in "
        f"{format_duration(time.monotonic() - started)}",
        err=True,
    )
