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

Flags: `--json` (machine-readable output), `--rows N`, `--sort "FIELD DIR"`, `--rekey` + `--subject WORD` (rewrite citekey as `LastName_Subject_Year`).

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
   python3 ~/.claude/skills/ads-cite/ads_cite.py append --rekey --subject <WORD> <BIBFILE> <BIBCODE>
   ```
   **Use `--rekey` by default.** It rewrites the citekey as `LastName_Subject_Year`
   (e.g., `Narayan_ESSENCE_2016`) and prepends `% ADS bibcode: <X>` as a comment
   so the original identifier is preserved and dedup still works.

   **Picking the subject:**
   - If the user's query contained a distinctive capitalized term (project name,
     survey, object ID) that appears in the chosen paper's title, use it as
     `--subject`. Examples: user queries `/ads-cite Narayan 2024 ESSENCE` and
     the result's title contains ESSENCE → `--subject ESSENCE`.
   - Otherwise, omit `--subject` and let the CLI auto-derive from the title
     (prefers UPPERCASE acronyms).
   - If the auto-derived subject would be generic (e.g., "Paper", "Analysis"),
     propose one to the user before committing.

   **When to skip `--rekey`:** if the target `.bib` already has entries keyed
   by raw bibcode (`@ARTICLE{2016ApJS..224....3N,...`), match that convention
   and drop `--rekey` so the file stays consistent. Grep the file first.

3. **Or print bibtex** for paste-in (same `--rekey` / `--subject` flags apply):
   ```bash
   python3 ~/.claude/skills/ads-cite/ads_cite.py bibtex --rekey <BIBCODE>
   ```

When both a preprint and a refereed version appear, prefer the refereed one but mention the preprint alternative.

## Example end-to-end (skill invocation → CLI calls)

User: `/ads-cite Narayan 2024 ESSENCE`

Claude:
1. Parses: author=Narayan, year range including 2024, text=ESSENCE
2. Runs: `ads_cite.py search 'author:"Narayan" year:2024 ESSENCE'`
3. Shows numbered list; user picks #1 → bibcode `2016ApJS..224....3N`
4. Greps `refs.bib` in CWD: no existing entries, or rekeyed entries present
5. Runs: `ads_cite.py append --rekey --subject ESSENCE refs.bib 2016ApJS..224....3N`
6. Reports: "Appended as `Narayan_ESSENCE_2016` to refs.bib"

The `--rekey` and `--subject` flags are chosen by Claude from SKILL.md
guidance; the user never types them as slash-command args.

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
