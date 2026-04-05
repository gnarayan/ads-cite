# ads-cite

A [Claude Code](https://docs.claude.com/claude-code) skill for searching NASA ADS, fetching records, and exporting verbatim bibtex straight into a `.bib` file.

## Why

Writing astronomy/astrophysics papers and proposals means citing a lot of ADS-indexed work. This skill wraps the [ADS API](https://github.com/adsabs/adsabs-dev-api) so you can, from Claude Code:

- Search by author / year / title / text / journal / ORCID / grant / collection
- Pick from a numbered result list
- Pull the **verbatim** bibtex entry from ADS (no hand-written or hallucinated entries)
- Append it to an existing `.bib` file, or print for paste-in
- Look up records by arXiv ID or DOI (prefers refereed version when one exists)
- List papers citing a given bibcode

The helper script `ads.py` is also a self-contained CLI — you can use it without Claude Code if you just want a fast ADS CLI.

## Install

Requires [Claude Code](https://docs.claude.com/claude-code) and Python 3.9+ (standard library only, no extra dependencies).

Clone into your Claude Code skills directory:
```bash
git clone https://github.com/gnarayan/ads-cite.git ~/.claude/skills/ads-cite
```

Claude Code picks up the skill automatically on next session. Verify with `/skills` or invoke `/ads-cite help`.

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

Add this line to your `~/.claude/settings.local.json` under `permissions.allow` so Claude Code doesn't prompt on every script run:

```json
"Bash(python3 ~/.claude/skills/ads-cite/ads.py:*)"
```

## Usage — from Claude Code

```text
/ads-cite Narayan 2024 white dwarf calibration
/ads-cite ^Coelho 2020               # first-author Coelho, year 2020
/ads-cite kilonova r-process 2017
/ads-cite help                        # print full usage
```

Claude parses author/year/text arguments automatically, runs the search, shows a numbered list, asks which one you want, and fetches the bibtex. If a `.bib` file is in your CWD, it offers to append; otherwise it prints for paste-in.

You can also pass raw ADS field syntax:
```text
/ads-cite author:"Scolnic" bibstem:ApJ year:2022-2024
/ads-cite bibgroup:DESC first_author:"Malz" keyword:"photo-z"
```

## Usage — raw CLI

```bash
python3 ~/.claude/skills/ads-cite/ads.py search "author:^Narayan year:2024"
python3 ~/.claude/skills/ads-cite/ads.py show 2016ApJS..224....3N
python3 ~/.claude/skills/ads-cite/ads.py bibtex 2016ApJS..224....3N
python3 ~/.claude/skills/ads-cite/ads.py citations 2016ApJS..224....3N
python3 ~/.claude/skills/ads-cite/ads.py arxiv 2510.07637
python3 ~/.claude/skills/ads-cite/ads.py doi 10.3847/0067-0049/224/1/3
python3 ~/.claude/skills/ads-cite/ads.py --help
```

## Query fields the skill exposes

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

Default filters applied by the skill: `database:astronomy` + `doctype:(article OR eprint)` — so AAS abstracts, PhD theses, and conference proceedings are excluded but refereed journals and arXiv preprints both show.

## Rate limits

ADS allows 5000 API queries/day per token. A single search + bibtex export is ~2 requests.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [NASA ADS](https://ui.adsabs.harvard.edu/) for the API and the verbatim bibtex export
- [adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api) for the API docs
