# comb

Filter a Wikidata JSON dump into a lean NDJSON subset: one entity per line,
only what you selected.

```bash
comb INPUT OUTPUT [--types item|property|both] [--attributes LIST] [--properties LIST]
```

- `INPUT` / `OUTPUT` are file paths; input must be uncompressed JSON.
- The dump is split into byte-range chunks and filtered in parallel, one
  worker per CPU core. Output preserves dump order.
- Every option **selects** what to keep; with no options, comb converts the
  dump to items-only NDJSON, untouched.

| Option | Values | Default |
|---|---|---|
| `--types` | `item`, `property`, `both` | `item` |
| `--attributes` | comma-separated from `labels, descriptions, aliases, claims, sitelinks` | all (`id` and `type` are always kept) |
| `--properties` | comma-separated property IDs, e.g. `P31,P279`; claims kept verbatim | all |

Claims for selected properties are kept verbatim: mainsnak, rank,
qualifiers, and references. Unselected claims and attributes are dropped.

## Example

```bash
lbzip2 -d -k latest-all.json.bz2
comb latest-all.json poliloom.json --properties P31,P279
```

## Notes

- Source dumps: <https://dumps.wikimedia.org/wikidatawiki/entities/> (`latest-all.json.bz2`).
- The dumps use parallel compression; `lbzip2` decompresses them fastest.
