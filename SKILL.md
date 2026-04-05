---
name: ads-cite
description: Search NASA ADS by author/year/text, pick from results, export bibtex entry to a .bib file
user-invocable: true
---

# ADS Cite

Search NASA ADS, fetch records, export bibtex, look up citations. Primary use case: the user wants a bibtex entry for a `.bib` file — you search, they pick, you fetch.

All API access goes through the helper script `ads.py` next to this file. Run `python3 ~/.claude/skills/ads-cite/ads.py --help` to see the full CLI.

The script finds the ADS token in this order: macOS Keychain (service `nasa-ads-api-token`) → `ADS_DEV_KEY`/`ADS_API_TOKEN` env var → `~/.ads/dev_key` file. This makes the skill portable to linux (NCSA, NERSC, etc.) without keychain access.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `search "<QUERY>"` | Search ADS, print numbered results (10 max) |
| `show <BIBCODE>` | Full record: title, authors, abstract, DOI, keywords |
| `bibtex <BIBCODE>...` | Verbatim bibtex from ADS export endpoint |
| `citations <BIBCODE>` | Top 20 papers citing this one, sorted by citation count |
| `arxiv <ID>` | Resolve arXiv ID; prefers refereed version if one exists |
| `doi <DOI>` | Resolve DOI to ADS bibcode |

## Parse the user's query

Accept any combination of:
- **author** — surname or "Surname, F." A leading `^` means first author
- **year** — single year `2024`, range `2020-2024`, or open range `2020-`
- **text** — free text matched against title + abstract

Examples:
- `/ads-cite Narayan 2024 white dwarf calibration`
- `/ads-cite ^Coelho 2020`
- `/ads-cite kilonova r-process 2017`
- `/ads-cite Wu SELDON`

Token assignment: capitalized surname-looking word (or one with leading `^`) → author; 4-digit number or `YYYY-YYYY`/`YYYY-` → year; everything else → text. If ambiguous, ask once.

## Build the query

Join with implicit AND spaces:
- author → `author:"SURNAME"` (keep any leading `^` inside the quotes for first-author)
- year → `year:2024` or `year:[2020 TO 2024]` or `year:[2020 TO *]`
- text → free text appended as-is

## Search

```bash
python3 ~/.claude/skills/ads-cite/ads.py search '<QUERY>'
```

The script applies `fq=database:astronomy`, `fq=doctype:(article OR eprint)`, `sort=date desc`, `rows=10`, and prints a numbered list with first author, year, title, journal, citation count, and bibcode. This restricts to journal articles and arXiv preprints — AAS meeting abstracts, conference proceedings, PhD theses, and similar non-journal items are excluded. Both refereed journals and preprints are included.

If 0 results: report the query and suggest broadening (drop a term). If 1 result: auto-select it. If >1: ask the user which number (or `all`).

When both a preprint and a refereed version appear, prefer the refereed one but mention the preprint alternative.

## Show (record detail)

```bash
python3 ~/.claude/skills/ads-cite/ads.py show <BIBCODE>
```

Prints title, full author list, journal, year, DOI, keywords, ADS URL, and abstract. Use when the user knows a bibcode and wants to see what the paper is about without clicking through to ADS.

## Citations

```bash
python3 ~/.claude/skills/ads-cite/ads.py citations <BIBCODE>
```

Top 20 papers citing the given bibcode, sorted by citation count (most-cited citers first). Use for literature reviews ("who cited SELDON?") or impact assessment.

## arXiv / DOI lookup

```bash
python3 ~/.claude/skills/ads-cite/ads.py arxiv <ID>     # e.g. 2510.07637
python3 ~/.claude/skills/ads-cite/ads.py doi <DOI>      # e.g. 10.3847/0067-0049/224/1/3
```

Common workflow: user sees an arXiv ID in an email or a DOI in a webpage, wants the citeable bibtex. `arxiv` prefers the refereed version when one exists (sorts articles before eprints) and flags whether only a preprint is available.

## Fetch the bibtex

```bash
python3 ~/.claude/skills/ads-cite/ads.py bibtex <BIBCODE> [<BIBCODE2> ...]
```

Prints the bibtex verbatim from the ADS export endpoint.

## Output

Ask the user whether to:
- **append to a .bib file** — if one `.bib` exists in CWD, offer it as default; otherwise ask for the path. Append with a leading blank line if the file is non-empty.
- **print to stdout only** — display the bibtex in a fenced code block.

Default: if a single `.bib` file exists in CWD, offer to append; otherwise print.

## Notes

- Do NOT hand-edit or fabricate bibtex — it comes verbatim from the ADS export endpoint.
- Do NOT cache results across invocations; ADS data can change.
- Rate limit: ADS allows ~5000 queries/day per token; a search + export round-trip is cheap.
- If the search returns a preprint bibcode (e.g., `2026arXiv...`) and a refereed version also exists, prefer the refereed one — mention the alternative to the user.
