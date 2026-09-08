# English and Korean game names

The MCP keeps upstream English names and identifiers unchanged and adds verified
Korean names where its offline catalog has an unambiguous match. Korean queries
can resolve to the same English item before Scout or trade search. Currency
prices, item tiers and gem levels remain separate from name translation.

The catalog uses public PoE2DB English (`us`) and Korean (`kr`) search-index
records. Records are joined by their language-independent `value` page key,
not their position in the indexes, a machine translation, or similarity of
names. A key is a **PoE2DB page identifier**, not a GGG item or modifier ID.
The canonical English name, Korean name, page key and both source URLs remain
available together. Query matching normalizes Unicode, case, spacing and
punctuation; conflicting exact matches remain ambiguous and require selection
from search results. The project does not generate translations for missing
entries or translate modifier prose automatically.

`src/poe2_companion/data/localization-ko.json` records the snapshot date, verified
game patch, hashed upstream URLs and SHA-256 of each source index. Its diagnostic
counts report conflicting keys, missing pairs and untranslated entries excluded
from the snapshot. `metadata()` reports catalog size and coverage facets. A
catalog update does not establish complete support for a league or a mechanic in
the PoB engine. In particular, a translated gem name is not evidence that the
engine understands that gem's calculations.

Catalog facets such as `runes`, `soul_cores` and `essences` are browsing aids
inferred from the **English name**. They are not authoritative item classes and
must never replace a Scout category, trade filter ID or PoB type. `game_term`
means no narrower facet was inferred. Unknown, untranslated or ambiguous names
retain their English spelling. Do not describe an unmatched name as a verified
Korean name. Compact upstream names such as `MartialArtist` can match the verified
`Martial Artist` name through normalization, without changing the upstream class
identifier.

## Refreshing the snapshot

```bash
python scripts/update_localization.py \
  --source-dir /tmp/poe2db-localization \
  --fetch --game-version 0.5.5
python -m pytest tests/test_localization.py
```

The updater discovers the current hashed `poedb_header` JavaScript asset from
[PoE2DB's English homepage](https://poe2db.tw/us/), then resolves its English and
Korean `autocompletecb` JSON URLs. It makes ordinary, bounded HTTPS requests to
`poe2db.tw` and `cdn.poe2db.tw`; redirects, denied requests and rate limits abort
the update. It does not use browser sessions or retry around access restrictions.
The MCP itself makes **no PoE2DB network calls** during gameplay, so a site outage
cannot break price lookups or build calculations.

To rebuild from an already downloaded public snapshot, omit `--fetch`. The
source directory must contain `us.json`, `kr.json`, and `provenance.json` with the
snapshot date and the original source URLs/SHA-256 values. This is developer
maintenance of public name data; it is unrelated to character or PoB file import.
Inspect diagnostic and coverage changes before committing the output. In
particular, do not replace a broad catalog with an unexpectedly empty or much
smaller index after an upstream layout change.

## Data provenance and rights

The catalog contains only short names and public page keys. It does not bundle
PoE2DB HTML, wiki articles, modifier descriptions, stats, images, or its website
code. Game content belongs to Grinding Gear Games. The project's MIT license
covers its original code and documentation; it does not grant rights to
third-party game names or source data. PoE2DB separately identifies rights in
game content and a CC BY-NC-SA 3.0 license for wiki articles; this project does not
represent that wiki license as a blanket license for all game data. See the
[PoE2DB disclaimer](https://poe2db.tw/us/General_disclaimer) and [NOTICE](../NOTICE).

Names are verified against the Korean names published by PoE2DB, a community
source. They are not a claim that GGG endorses this project or that every name
has been independently checked in the running Korean game client.

## README translations

English is canonical for project documentation. README editions cover Korean
(`ko`), German (`de`), Russian (`ru`), and Brazilian Portuguese (`pt-BR`), plus
English. Technical reference documentation remains in English. This set is not
an authoritative ranking of player nationalities. The initial choices used a
2026-09-07 sample of Steam review-language counts and included Korean at the
owner's request; standalone and regional clients are not represented by that
sample. See [Valve's review endpoint documentation](https://partner.steamgames.com/doc/store/getreviews).

When behavior changes, update all five READMEs in the same PR. Preserve commands,
identifiers, numbers, links, privacy boundaries and limitations. README language
coverage and game-name catalog coverage are separate.
