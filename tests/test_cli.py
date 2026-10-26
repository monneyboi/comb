"""Behavioral tests for the comb CLI."""

import orjson
from click.testing import CliRunner

from comb import dump_reader
from comb.cli import main


def claim(property_id: str, qid: str, **extra) -> dict:
    statement = {
        "mainsnak": {
            "snaktype": "value",
            "property": property_id,
            "datatype": "wikibase-item",
            "datavalue": {
                "value": {"id": qid, "numeric-id": int(qid[1:])},
                "type": "wikibase-entityid",
            },
        },
        "type": "statement",
        "id": f"{property_id}$aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "rank": "normal",
    }
    statement.update(extra)
    return statement


def politician() -> dict:
    return {
        "id": "Q42",
        "type": "item",
        "labels": {"en": {"language": "en", "value": "Douglas Adams"}},
        "descriptions": {"en": {"language": "en", "value": "writer"}},
        "aliases": {"en": [{"language": "en", "value": "Douglas Noel Adams"}]},
        "claims": {
            "P31": [claim("P31", "Q5")],
            "P106": [claim("P106", "Q82955")],
            "P39": [
                claim(
                    "P39",
                    "Q83307",
                    qualifiers={"P580": [claim("P580", "Q1234")]},
                    qualifiers_order=["P580"],
                    references=[{"snaks": {}, "snaks-order": []}],
                )
            ],
            "P18": [claim("P18", "Q99999")],
        },
        "sitelinks": {
            "enwiki": {"site": "enwiki", "title": "Douglas Adams", "badges": []}
        },
        "lastrevid": 1234,
    }


def country() -> dict:
    return {
        "id": "Q17",
        "type": "item",
        "labels": {"en": {"language": "en", "value": "Japan"}},
        "claims": {
            "P31": [claim("P31", "Q3624078")],
            "P297": [claim("P297", "Q99998")],
        },
    }


def property_entity() -> dict:
    return {
        "id": "P39",
        "type": "property",
        "labels": {"en": {"language": "en", "value": "position held"}},
        "datatype": "wikibase-item",
    }


def dump_bytes() -> bytes:
    lines = [
        b"[",
        orjson.dumps(politician()) + b",",
        orjson.dumps(country()) + b",",
        orjson.dumps(property_entity()),
        b"]",
        b"",
    ]
    return b"\n".join(lines)


def run(args: list[str]):
    result = CliRunner().invoke(main, args, catch_exceptions=False)
    return result


def read_entities(path) -> list[dict]:
    with open(path, "rb") as f:
        return [orjson.loads(line) for line in f if line.strip()]


def test_default_keeps_items_untouched(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())

    run([str(input_path), str(output_path)])

    entities = read_entities(output_path)
    assert [entity["id"] for entity in entities] == ["Q42", "Q17"]

    person = entities[0]
    # All five optional attributes survive; unknown top-level keys are dropped.
    assert set(person) == {
        "id",
        "type",
        "labels",
        "descriptions",
        "aliases",
        "claims",
        "sitelinks",
    }
    assert set(person["claims"]) == {"P31", "P106", "P39", "P18"}
    assert person["sitelinks"] == politician()["sitelinks"]


def test_types_both_keeps_property_entities(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())

    run([str(input_path), str(output_path), "--types", "both"])

    assert [entity["id"] for entity in read_entities(output_path)] == [
        "Q42",
        "Q17",
        "P39",
    ]


def test_properties_select_claims_verbatim(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())

    run([str(input_path), str(output_path), "--properties", "P31,P39,P297"])

    person, nation = read_entities(output_path)
    # Unlisted properties are filtered out, listed ones survive untouched.
    assert set(person["claims"]) == {"P31", "P39"}
    assert person["claims"]["P39"] == politician()["claims"]["P39"]
    assert "qualifiers" in person["claims"]["P39"][0]
    assert "references" in person["claims"]["P39"][0]
    assert set(nation["claims"]) == {"P31", "P297"}


def test_attributes_select_attributes(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())

    run([str(input_path), str(output_path), "--attributes", "labels,aliases"])

    person = read_entities(output_path)[0]
    assert set(person) == {"id", "type", "labels", "aliases"}


def test_empty_claims_attribute_omitted(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())

    run([str(input_path), str(output_path), "--properties", "P9999"])

    for entity in read_entities(output_path):
        assert "claims" not in entity


def test_multiple_chunks_preserve_dump_order(tmp_path, monkeypatch):
    # Shrink the automatic chunk minimum so this small dump splits in three
    monkeypatch.setattr(dump_reader, "MIN_CHUNK_SIZE", 4096)
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    entities = [{"id": f"Q{i}", "type": "item"} for i in range(400)]
    lines = [b"["] + [orjson.dumps(e) + b"," for e in entities] + [b"]"]
    input_path.write_bytes(b"\n".join(lines))

    result = run([str(input_path), str(output_path)])

    assert [e["id"] for e in read_entities(output_path)] == [
        f"Q{i}" for i in range(400)
    ]
    assert not list(tmp_path.glob("*.part"))
    assert "400 read, 400 kept" in result.output


def test_empty_input_writes_empty_output(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(b"")

    result = run([str(input_path), str(output_path)])

    assert output_path.read_bytes() == b""
    assert "0 read, 0 kept" in result.output


def test_usage_errors(tmp_path):
    input_path = tmp_path / "dump.json"
    output_path = tmp_path / "out.json"
    input_path.write_bytes(dump_bytes())
    runner = CliRunner()

    cases = [
        (["--attributes", "labels,id"], "unknown attribute"),
        (["--attributes", "labels,"], "empty element"),
        (["--properties", "P31,foo"], "invalid property"),
        (["--properties", "Q31"], "invalid property"),
        (["--attributes", "labels", "--properties", "P31"], "requires keeping"),
        ([], None),
    ]
    for extra, expected in cases:
        args = [str(input_path), str(output_path)] + extra
        if expected is None:  # no extra options: same-file guard
            args = [str(input_path), str(input_path)]
            expected = "same file"
        result = runner.invoke(main, args)
        assert result.exit_code == 2
        assert expected in result.output
