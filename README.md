# comb

Filter a Wikidata JSON dump into a lean NDJSON subset, streaming in a single
pass: one entity per line, only what you selected.

```bash
comb INPUT OUTPUT [--types item|property|both] [--attributes LIST] [--properties LIST]
```

- `INPUT` / `OUTPUT` are file paths, or `-` for stdin/stdout.
- Input is always uncompressed JSON — decompress with the shell if needed.
- Every option **selects** what to keep; anything not selected is filtered
  out. With no options, comb converts the dump to items-only NDJSON,
  untouched.

| Option | Values | Default |
|---|---|---|
| `--types` | `item`, `property`, `both` | `item` |
| `--attributes` | comma-separated from `labels, descriptions, aliases, claims, sitelinks` | all (`id` and `type` are always kept) |
| `--properties` | comma-separated property IDs, e.g. `P31,P279`; claims kept verbatim | all |

Claims for selected properties are kept verbatim: mainsnak, rank,
qualifiers, and references. Unselected claims and attributes are dropped.

## Examples

Decompress on the fly — the full dump never has to exist uncompressed on
disk:

```bash
lbzip2 -d -c latest-all.json.bz2 | comb - poliloom.json --properties P31,P279,P361,P131,P17,P1001,P37,P407,P106,P297,P218,P219,P220,P856,P569,P570,P19,P39,P27
```

Terms and sitelinks only, no claims — useful for search indexes:

```bash
comb latest-all.json - --attributes labels,descriptions,aliases,sitelinks > terms.json
```

Compress the output instead of writing it uncompressed:

```bash
comb latest-all.json - | zstd > subset.json.zst
```

## Notes

- Source dumps: <https://dumps.wikimedia.org/wikidatawiki/entities/> (`latest-all.json.bz2`).
- The dumps use parallel compression; `lbzip2` decompresses them fastest.
- Expect a full-dump run to take hours (JSON parse-bound, single process).
  Progress and the final summary go to stderr; malformed lines are
  skipped and counted, never fatal. stdout carries only NDJSON.
