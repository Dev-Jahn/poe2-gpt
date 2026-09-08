# English and Korean game names

The MCP keeps upstream English names and identifiers unchanged and adds verified
Korean names where its offline catalog has an unambiguous match. Korean queries
can resolve to the same English item before Scout or trade search. Currency
prices, item tiers and gem levels remain separate from name translation.

The catalog uses public PoE2DB English (`us`) and Korean (`kr`) page anchors
and canonical page titles.
Records are joined by the actual language-independent page key in their links,
not their position on a page, a machine translation, or similarity of names.
English name text must agree with the actual page key; navigation labels such as
"Item" are excluded. The Korean label must contain Korean text. Conflicting
labels are dropped, including ambiguity introduced by an upstream layout change.
When both canonical page titles are available and the English title agrees with
the page key, that verified title pair takes precedence over incidental links
labelled with a weapon or navigation category. Conflicting canonical titles
remain unresolved; the updater does not select whichever label appeared first. A key is a **PoE2DB page identifier**, not a GGG item or modifier ID.
The canonical English name, Korean name, page key and both source URLs remain
available together. Query matching normalizes Unicode, case, spacing and
punctuation; conflicting exact matches remain ambiguous and require selection
from search results. The project does not generate translations for missing
entries or translate modifier prose automatically.

`src/poe2_companion/data/localization-ko.json` records the snapshot date, verified
game patch, original source-page URLs and SHA-256 of each source HTML response. Its diagnostic
counts report conflicting keys, missing pairs and untranslated entries excluded
from the snapshot. The updater also supports an explicit search-index mode,
which joins each index record by its `value` key. `metadata()` reports catalog size and coverage facets. A
catalog update does not establish complete support for a league or a mechanic in
the PoB engine. In particular, a translated gem name is not evidence that the
engine understands that gem's calculations.

The 2026-09-08 snapshot contains 4,542 bilingual entries from 46 public HTML
responses. All 29 core currency names in the acceptance check resolved, along
with the two test characters' classes, ascendancies and tested skill names. This
is a verified subset, not an assertion that every live Scout entry or game term
is translated.

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
  --fetch --game-version 0.5.5 --html-pages
python -m pytest tests/test_localization.py
```

The HTML mode discovers category links from both [English](https://poe2db.tw/us/)
and [Korean](https://poe2db.tw/kr/) homepages, then fetches at most 24 category
pairs plus those homepages. Requests are sequential with a half-second interval;
responses are size-limited. It extracts only linked short names and shared page
keys, discarding prose and images. Most category pages are discovered through links present in both languages.
The independently verified canonical Currency, Monk and Huntress page pairs are
also included when their category is requested, because dynamic homepage
navigation can omit them. This fixed list contains public source pages, not
hardcoded translated names. An optional list after `--html-pages` selects specific English
category labels already present on the homepages; it cannot specify arbitrary
URLs. The snapshot is intentionally bounded and does not include every page.

A separate search-index mode (omit `--html-pages`) discovers the hashed
`poedb_header` script and its `autocompletecb` JSON assets. On 2026-09-08 the Mac
host could retrieve public HTML normally, while the CDN denied normal JSON
requests. The release therefore uses explicitly selected HTML sources. The
updater does not automatically switch routes after access is denied, impersonate
a browser or reuse browser sessions. HTML mode accepts at most two HTTPS
canonical redirects within the same origin and language, recording the requested
URL, final URL and redirect chain. Other redirects, denied requests and rate
limits abort the selected update. The MCP makes **no PoE2DB network calls** during
gameplay, so a site outage cannot break price lookups or build calculations.

To rebuild from an already downloaded public snapshot, omit `--fetch` and keep
the same source mode. HTML mode reads cached public pages and
`html-provenance.json`; index mode reads `us.json`, `kr.json` and
`provenance.json`. Both verify the source hashes before generating an atomic
replacement. Interrupted HTML collection can resume with `--resume-html` only
when its incremental source-provenance checkpoint exists, every cached hash
matches and the requested page selection is unchanged. This is developer maintenance of public name data, unrelated to
character or PoB file import. Commit only the minimal generated catalog, not the
HTML/index cache. Inspect diagnostic and coverage changes before committing the
output; do not replace a broad catalog with an unexpectedly empty or much smaller
snapshot after an upstream layout change.

## Official trade modifier labels

Trade modifier localization uses the official
[Korean trade metadata](https://poe.kakaogames.com/api/trade2/data/stats), separately
from the PoE2DB name catalog. Entries are joined to canonical English trade
metadata by their **exact stat ID**, including explicit, implicit and other stat
types. A translated label never replaces the ID sent in a trade query.

Results expose `text_ko`, `text_source_en` and `text_source_ko` alongside the
English label, plus translation status, error and retrieval information. The
Korean metadata cache lasts six hours. If the Korean provider fails or has no
matching stat, English search remains available and the missing translation is
reported. English fallback text is never presented as a verified Korean label.
These provider responses are fetched and cached at runtime; modifier descriptions
are not bundled in the repository's game-name catalog.


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
