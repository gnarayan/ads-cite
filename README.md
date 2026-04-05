# ads-cite

A [Claude Code](https://docs.claude.com/claude-code) skill and standalone CLI for searching NASA ADS, fetching records, and exporting verbatim bibtex straight into a `.bib` file.

## Why

Writing astronomy/astrophysics papers and proposals means citing a lot of ADS-indexed work. This skill wraps the [ADS API](https://github.com/adsabs/adsabs-dev-api) so you can, from Claude Code or a shell:

- Search by author / year / title / text / journal / ORCID / grant / collection
- Pick from a numbered result list
- Pull the **verbatim** bibtex entry from ADS (no hand-written or hallucinated entries)
- Append to a `.bib` file with duplicate detection — or print for paste-in
- Look up records by arXiv ID or DOI (prefers refereed version when one exists)
- List papers citing or referenced by a given bibcode

`ads_cite.py` is also a self-contained CLI usable without Claude Code (pip-installable as `ads-cite`).

## Install — as a Claude Code skill

Requires [Claude Code](https://docs.claude.com/claude-code) and Python 3.9+ (standard library only, no extra dependencies).

```bash
git clone https://github.com/gnarayan/ads-cite.git ~/.claude/skills/ads-cite
```

Claude Code picks up the skill automatically on next session. Verify with `/skills` or invoke `/ads-cite help`.

## Install — as a standalone CLI (via pip)

```bash
pip install git+https://github.com/gnarayan/ads-cite.git
# or once on PyPI:
# pip install ads-cite
ads-cite --help
```

This installs the `ads-cite` command on your PATH without touching Claude Code.

## Configure your ADS API token

Get a token from https://ui.adsabs.harvard.edu → Account Settings → API Token. The script looks for it in this order (first match wins):

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

## Rate limits

ADS allows 5000 API queries/day per token. A single search + bibtex export is ~2 requests.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [NASA ADS](https://ui.adsabs.harvard.edu/) for the API and verbatim bibtex export
- [adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api) for the API docs
