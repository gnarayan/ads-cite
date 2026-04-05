---
name: ads-cite
description: Search NASA ADS by author/year/text, pick from results, export bibtex entry to a .bib file
user-invocable: true
---

# ADS Cite

Search NASA ADS, fetch records, export bibtex, look up citations and references. Primary use case: the user wants a bibtex entry for a `.bib` file — you search, they pick, you fetch (or append directly).

All API access goes through the helper script `ads_cite.py` next to this file. Run `python3 ~/.claude/skills/ads-cite/ads_cite.py --help` to see the full CLI.

The script finds the ADS token in this order: macOS Keychain (service `nasa-ads-api-token`) → `ADS_DEV_KEY`/`ADS_API_TOKEN` env var → `~/.ads/dev_key` file. This makes the skill portable to linux (NCSA, NERSC, etc.) without keychain access.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `search "<QUERY>"` | Search ADS, print numbered results |
| `show <BIBCODE>` | Full record: title, authors, abstract, DOI, keywords |
| `bibtex <BIBCODE>...` | Verbatim bibtex from ADS export endpoint |
| `citations <BIBCODE>` | Papers citing this one, sorted by citation count |
| `references <BIBCODE>` | Papers cited by this one (complement of citations) |
| `arxiv <ID>` | Resolve arXiv ID; prefers refereed version if one exists |
| `doi <DOI>` | Resolve DOI to ADS bibcode |
| `append <BIBFILE> <BIBCODE>...` | Append bibtex to a .bib file, skipping duplicates |

Flags: `--json` (machine-readable output), `--rows N`, `--sort "FIELD DIR"`.

## Parse the user's query

Accept any combination of:
- **author** — surname or "Surname, F." A leading `^` means first author
- **year** — single year `2024`, range `2020-2024`, or open range `2020-`
- **text** — free text matched against title + abstract

Examples:
- `/ads-cite Narayan 2024 white dwarf calibration`
- `/ads-cite ^Coelho 2020`
- `/ads-cite kilonova r-process 2017`

Token assignment: capitalized surname-looking word (or one with leading `^`) → author; 4-digit number or `YYYY-YYYY`/`YYYY-` → year; everything else → text. If ambiguous, ask once.

## Build the query

Join with implicit AND spaces:
- author → `author:"SURNAME"` (keep any leading `^` inside the quotes for first-author)
- year → `year:2024` or `year:[2020 TO 2024]` or `year:[2020 TO *]`
- text → free text appended as-is

## Workflow

1. **Search**:
   ```bash
   python3 ~/.claude/skills/ads-cite/ads_cite.py search '<QUERY>'
   ```
   Default filters: `database:astronomy`, `doctype:(article OR eprint)`. AAS meeting abstracts, conference proceedings, and PhD theses are excluded.

   If 0 results: report and suggest broadening (drop a term). If 1 result: auto-select. If >1: ask which number (or `all`).

2. **Append to .bib** (preferred when a `.bib` exists in CWD):
   ```bash
   python3 ~/.claude/skills/ads-cite/ads_cite.py append <BIBFILE> <BIBCODE>...
   ```
   Deduplicates against existing citekeys in the file. Creates the file if missing.

3. **Or print bibtex** for paste-in:
   ```bash
   python3 ~/.claude/skills/ads-cite/ads_cite.py bibtex <BIBCODE> [<BIBCODE2>...]
   ```

When both a preprint and a refereed version appear, prefer the refereed one but mention the preprint alternative.

## Other verbs

- `show <BIBCODE>` — title, full authors, journal, year, DOI, keywords, ADS URL, abstract (no click-through to ADS needed)
- `citations <BIBCODE>` — lit review: who cited this paper, sorted by citations
- `references <BIBCODE>` — lit review: what this paper builds on
- `arxiv <ID>` / `doi <DOI>` — resolve external identifiers to ADS bibcodes

## Output

Default: if a single `.bib` file exists in CWD, use `append` directly. Otherwise `bibtex` + print in a fenced code block.

## Notes

- Do NOT hand-edit or fabricate bibtex — it comes verbatim from the ADS export endpoint.
- Do NOT cache results across invocations; ADS data can change.
- Rate limit: ADS allows ~5000 queries/day per token.
- If the search returns a preprint bibcode (e.g., `2026arXiv...`) and a refereed version also exists, prefer the refereed one — mention the alternative to the user.
