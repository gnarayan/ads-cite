# ads-cite

A [Claude Code](https://docs.claude.com/claude-code) skill and standalone CLI for searching NASA ADS, fetching records, and exporting verbatim bibtex into a `.bib` file.

## Why

Writing astronomy/astrophysics papers and proposals means citing a lot of ADS-indexed work. This skill wraps the [ADS API](https://github.com/adsabs/adsabs-dev-api) so you can, from Claude Code or a shell:

- Search by author / year / title / text / journal / ORCID / grant / collection
- Pick from a numbered result list
- Pull the **verbatim** bibtex entry from ADS (no hand-written or hallucinated entries)
- Append to a `.bib` file with duplicate detection — or print for paste-in
- Look up records by arXiv ID or DOI (prefers refereed version when one exists)
- List papers citing or referenced by a given bibcode

`ads_cite.py` is also a self-contained CLI usable without Claude Code (pip-installable as `ads-cite`).

## Install

Requires Python 3.9+. Standard library only; no extra dependencies.

**As a Claude Code skill:**
```bash
git clone https://github.com/gnarayan/ads-cite.git ~/.claude/skills/ads-cite
```
Claude Code picks up the skill automatically on next session. Verify with `/skills` or invoke `/ads-cite help`.

**As a standalone CLI** (installs `ads-cite` on your PATH, no Claude Code required):
```bash
pip install git+https://github.com/gnarayan/ads-cite.git
# or once on PyPI: pip install ads-cite
ads-cite --help
```

Both paths share the same token config (next section). If you install as a skill, also grant the permission described further below.

## Configure your ADS API token

Get a token from https://ui.adsabs.harvard.edu → Account Settings → API Token. ADS allows 5000 API calls/day per token; a search + bibtex export is 2 calls. The script looks for the token in this order (first match wins):

1. **macOS Keychain** (recommended on Mac):
   ```bash
   security add-generic-password -a "$USER" -s "nasa-ads-api-token" -w "<TOKEN>" -U
   ```
2. **Environment variable** (recommended on linux):
   ```bash
   export ADS_DEV_KEY="<TOKEN>"
   # or ADS_API_TOKEN
   ```
3. **File** (portable fallback):
   ```bash
   mkdir -p ~/.ads && echo "<TOKEN>" > ~/.ads/dev_key && chmod 600 ~/.ads/dev_key
   ```

## Grant the skill its permission (one time)

Add this line to `~/.claude/settings.local.json` under `permissions.allow` so Claude Code doesn't prompt on every script run:

```json
"Bash(python3 ~/.claude/skills/ads-cite/ads_cite.py:*)"
```

## Configure Claude's bibliography behavior

Installing the skill is not enough. Claude defaults to writing bibtex from
memory when asked for a citation, and it **will hallucinate** journal names,
volumes, page numbers, and author lists. Add a rule to your global
`~/.claude/CLAUDE.md` that redirects all bibtex requests through ads-cite.

Paste this into your `~/.claude/CLAUDE.md` (create the file if it doesn't exist):

```markdown
## Bibliography rules (STRICT)

- **NEVER hand-write or generate bibtex entries.** Every `.bib` entry must
  come verbatim from NASA ADS's export endpoint.
- Always use `.bib` files with `natbib` or `biblatex` — never hardcode
  citations in `.tex`.
- **Workflow:** use the `/ads-cite` skill (or `ads-cite` CLI directly) to
  search ADS, pick the result, then either:
  - `ads-cite append --rekey <BIBFILE> <BIBCODE>` — appends verbatim bibtex
    with a memorable `LastName_Subject_Year` citekey and preserves the
    original bibcode as a `% ADS bibcode:` comment; skips duplicates
  - `ads-cite bibtex --rekey <BIBCODE>` — prints bibtex for paste-in
- With `--rekey`, cite as `\citep{Narayan_ESSENCE_2016}`. Without it, the
  citekey is the raw bibcode (`\citep{2016ApJS..224....3N}`). Match whatever
  convention the existing `.bib` file already uses. No URL comment needed —
  the ADS URL is in the bibtex `adsurl` field.
```

With this in place, when you ask Claude for a citation or to add references
to a draft, it will run `ads-cite` instead of making up a bibtex entry.

## Usage — from Claude Code

```text
/ads-cite Narayan 2024 white dwarf calibration
/ads-cite ^Coelho 2020               # first-author Coelho, year 2020
/ads-cite kilonova r-process 2017
/ads-cite help                        # print full usage
```

Claude parses author/year/text arguments automatically, runs the search, shows a numbered list, asks which one you want, and either appends to a `.bib` in CWD or prints the bibtex for paste-in.

Raw ADS field syntax works too:
```text
/ads-cite author:"Scolnic" bibstem:ApJ year:2022-2024
/ads-cite bibgroup:DESC first_author:"Malz" keyword:"photo-z"
```

## Usage — raw CLI

```bash
ads-cite search "author:^Narayan year:2024"
ads-cite show 2016ApJS..224....3N
ads-cite bibtex 2016ApJS..224....3N
ads-cite citations 2016ApJS..224....3N
ads-cite references 2016ApJS..224....3N
ads-cite arxiv 2510.07637
ads-cite doi 10.3847/0067-0049/224/1/3
ads-cite append refs.bib 2016ApJS..224....3N 2025PASP..137b4101S
ads-cite --help
```

### Flags

| Flag | Applies to | Effect |
|---|---|---|
| `--json` | all verbs | Emit structured JSON instead of formatted text. Useful for scripts and agent tool calls. |
| `--rows N` | `search`, `citations`, `references` | Override the default row cap (10 / 20 / 50). |
| `--sort "FIELD DIR"` | `search`, `citations`, `references` | Override sort, e.g. `--sort "citation_count desc"`. |
| `--rekey` | `bibtex`, `append` | Rewrite citekey as `LastName_Subject_Year` (e.g., `Narayan_ESSENCE_2016`). Prepends `% ADS bibcode: <X>` as a comment, so the original identifier is preserved and dedup still works across both styles. |
| `--subject WORD` | `bibtex`, `append` (with `--rekey`) | Explicit subject for the citekey. Single-bibcode only. If omitted, auto-derived from the title (prefers uppercase acronyms like ESSENCE, PLCK, LSST). |

### Memorable citekeys with `--rekey`

ADS bibcodes (`2016ApJS..224....3N`) are unambiguous but hard to type or remember when you're citing a paper by name. `--rekey` transforms each entry to a human-friendly citekey while keeping the bibcode safe:

```bash
# Auto-derive subject from title
$ ads-cite bibtex --rekey 2016ApJS..224....3N
% ADS bibcode: 2016ApJS..224....3N
@ARTICLE{Narayan_ESSENCE_2016,
  ...
}

# Explicit subject override
$ ads-cite bibtex --rekey --subject SN2023ixf 2024ApJ...XXX..YYYZ
% ADS bibcode: 2024ApJ...XXX..YYYZ
@ARTICLE{Author_SN2023ixf_2024,
  ...
}

# Append with rekey — your .tex file uses \citep{Narayan_ESSENCE_2016}
$ ads-cite append --rekey refs.bib 2016ApJS..224....3N
```

Dedup is robust across styles: if you've already appended a bibcode with `--rekey`, appending the same bibcode later (with or without `--rekey`) will skip it, because the bibcode lives in the preserved `% ADS bibcode:` comment.

### Examples

```bash
# Lit review: get JSON of top 50 papers citing SELDON, most-cited first
ads-cite citations 2603.04392 --rows 50 --json

# Dedup-append the top result of a search to your proposal's .bib
ads-cite search 'first_author:"Pierel" title:"H0pe"' --json | jq -r '.[0].bibcode' \
  | xargs ads-cite append proposal.bib

# What does this paper build on?
ads-cite references 2024PASP..136f4501G --sort "citation_count desc" --rows 20
```

## Query fields

| Field | Example |
|---|---|
| `author:` | `author:"Narayan, G."` (use `^Name` for first author) |
| `first_author:` | `first_author:"Hawking, S"` |
| `title:` | `title:"dark energy"` |
| `abs:` | `abs:"gravitational waves"` |
| `year:` | `year:2020-2024` or `year:2023` |
| `bibstem:` | `bibstem:ApJ` |
| `aff:` | `aff:"Illinois"` |
| `orcid_pub:` | `orcid_pub:0000-0001-XXXX-XXXX` |
| `keyword:` | `keyword:"dark energy"` |
| `bibgroup:` | `bibgroup:DESC` |
| `grant:` | `grant:"DE-SC0025232"` |
| `arxiv_class:` | `arxiv_class:astro-ph.CO` |
| free text (quoted) | `"GW170817"` |

Default filters applied: `database:astronomy` + `doctype:(article OR eprint)` — so AAS abstracts, PhD theses, and conference proceedings are excluded; refereed journals and arXiv preprints both show.

## Troubleshooting & common pitfalls

**"No ADS record found" for a bibcode / arXiv ID / DOI you know exists.**
Check the input for silent mangling:
- arXiv: `v2` suffixes and URL wrappers (`https://arxiv.org/abs/…`) are stripped automatically; bare versioned IDs (`2510.07637v2`) work.
- DOI: `https://doi.org/…`, `dx.doi.org/…`, and `doi:` prefixes are stripped automatically.
- Bibcode: must be 19 chars, 4-digit year + 15 compact chars, no spaces. `ads-cite` validates format and prints a clear error if it's malformed.

**401 from ADS** — the token is wrong or was copy-pasted with surrounding quotes or newlines. Regenerate at https://ui.adsabs.harvard.edu → Account Settings → API Token and re-store it.

**Keychain keeps prompting** — click "Always Allow" the first time. If you already dismissed the dialog, delete the entry (`security delete-generic-password -a "$USER" -s "nasa-ads-api-token"`) and re-add it.

**Rekey'd citekeys look wrong** (e.g., generic subject like `Paper`, or a non-ASCII author name stripped to something unreadable) — pass `--subject WORD` explicitly. Non-ASCII chars in author surnames are stripped (`Müller` → `Mller`); if you care, set the subject explicitly or live with the collision.

**Duplicate citekeys from `--rekey`** (two papers by the same author, same year, same auto-derived subject) — you'll get two entries with identical citekeys. LaTeX will warn. Override with a distinguishing `--subject` for one of them.

**Appending to a path whose parent directory doesn't exist** — `ads-cite` creates the parent directory automatically. Good for starting a new proposal.

**Mixing `--rekey` and non-rekey styles in one `.bib`** — works; dedup scans both the citekey and the `% ADS bibcode:` comment. But LaTeX users will find it jarring to see both styles; pick one per file.

**`.bib` file with a BOM or DOS line endings** — BOM is stripped on read. DOS endings don't affect the dedup regex.

**Preprint returned when you wanted the refereed version** — `arxiv` subcommand already prefers articles over eprints. For direct `search`, if you see an `arXiv` bibcode, check ADS for a linked published version.

**Matching existing `.bib` convention** — if the file already has entries keyed by raw bibcode, drop `--rekey` to keep the file consistent.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [NASA ADS](https://ui.adsabs.harvard.edu/) for the API and verbatim bibtex export
- [adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api) for the API docs
