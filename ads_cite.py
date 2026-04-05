#!/usr/bin/env python3
"""ads-cite — NASA ADS search, bibtex export, citation/reference lookup.

Usable both as a standalone CLI (``ads-cite ...`` after ``pip install``) and
as the backing script for the /ads-cite Claude Code skill. All API access is
funneled through this one entry point so an agent framework only needs a
single whitelisted permission.

Run ``ads-cite --help`` for command-line usage; ``ads-cite <command> --help``
for per-subcommand flags. See the epilog of --help for query syntax and
token lookup order.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# Structure: _http_call wraps urllib with ADS-specific error translation;
# api_{get,post} thin wrappers over it; cmd_* functions are the CLI verbs;
# _build_parser() defines the argparse schema; main() dispatches.

ADS = "https://api.adsabs.harvard.edu/v1"
TIMEOUT = 30  # seconds, for every ADS API call
BIBTEX_MAX = 2000  # ADS export endpoint per-request limit

# Fields returned for list-style output (search / citations / references / arxiv / doi)
LIST_FL = "bibcode,title,author,year,citation_count,pub"

# ADS bibcode format: 4-digit year + 15 compact characters (journal code,
# volume, page, initial). Total length is always 19, no internal whitespace.
_BIBCODE_RE = re.compile(r"^\d{4}\S{15}$")


def _clean_bibcode(bc: str) -> str:
    """Strip whitespace and common copy-paste wrappers from a bibcode, then
    validate its format. Die with a helpful message if malformed."""
    bc = bc.strip().strip("<>[](){}\"'")
    if not _BIBCODE_RE.match(bc):
        _die(f"Bibcode format looks invalid: {bc!r}\n"
             "Expected: 19 chars, 4-digit year + 15 compact chars, no spaces.\n"
             "Example:  2016ApJS..224....3N")
    return bc


def _clean_arxiv_id(s: str) -> str:
    """Extract a bare arXiv ID from URLs, 'arXiv:' prefixes, version suffixes."""
    s = s.strip()
    # Strip URL wrappers: https://arxiv.org/abs/2510.07637 → 2510.07637
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?\s]+)", s, re.I)
    if m:
        s = m.group(1)
    # Strip 'arXiv:' prefix and version suffix 'v1', 'v2', ...
    s = re.sub(r"^arXiv:", "", s, flags=re.I)
    s = re.sub(r"v\d+$", "", s)
    return s.strip()


def _clean_doi(s: str) -> str:
    """Strip 'doi:', 'https://doi.org/', 'dx.doi.org/' prefixes from a DOI."""
    s = s.strip()
    s = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", s, flags=re.I)
    s = re.sub(r"^doi:\s*", "", s, flags=re.I)
    return s.strip()

QUERY_SYNTAX = """\
Query syntax (search/citations/references):
  author:"Narayan, G."     author (use ^Name for first author only)
  first_author:"Name, G."  first author (alternative to ^)
  title:"dark energy"      phrase in title
  abs:"phrase"             phrase in abstract
  year:2020-2024           year or range
  bibstem:ApJ              journal abbreviation
  aff:"Illinois"           author affiliation
  orcid_pub:0000-0001-...  author by ORCID (more reliable than name)
  keyword:"dark energy"    ADS-assigned subject keyword
  bibgroup:DESC            collection/bibgroup (DESC, LSST, etc.)
  grant:"DE-SC0025232"     funding grant ID (useful for proposal prior work)
  arxiv_class:astro-ph.CO  arXiv primary category
  "GW170817"               quoted phrase (for object names, compact IDs)
  Combine fields with spaces (implicit AND). Also OR, NOT, - (negation)."""

TOKEN_DOC = """\
ADS API token is searched in this order:
  1. macOS Keychain: service 'nasa-ads-api-token', account $USER
  2. Environment variable: ADS_DEV_KEY or ADS_API_TOKEN
  3. File: ~/.ads/dev_key (first line, stripped)"""


def _die(msg: str) -> None:
    """Print an error to stderr and exit with status 1."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _http_call(req: urllib.request.Request) -> dict:
    """Execute an ADS API request; translate all failure modes into clean
    exits. Returns the parsed JSON response on success."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        snippet = ""
        try:
            snippet = e.read().decode()[:200].strip().replace("\n", " ")
        except Exception:
            pass
        if e.code == 401:
            _die("ADS API rejected the token (401). Check it at "
                 "https://ui.adsabs.harvard.edu → Account Settings → API Token.")
        elif e.code == 400:
            _die(f"ADS rejected the query (400 BAD REQUEST): {snippet}")
        elif e.code == 429:
            _die("ADS rate limit hit (429). The 5000/day quota is exhausted; "
                 "try again after UTC midnight or check X-RateLimit headers.")
        elif e.code >= 500:
            _die(f"ADS server error ({e.code}). Try again shortly. {snippet}")
        else:
            _die(f"ADS returned HTTP {e.code}: {snippet}")
    except urllib.error.URLError as e:
        _die(f"Could not reach ADS at {ADS}: {e.reason}")
    except TimeoutError:
        _die(f"Request to ADS timed out after {TIMEOUT} seconds.")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        _die(f"ADS returned non-JSON response: {body[:200]!r}")


def get_token() -> str:
    """Locate the ADS API token. Tries macOS Keychain, then env vars
    (ADS_DEV_KEY / ADS_API_TOKEN), then ~/.ads/dev_key. Exits if none found."""
    # 1. macOS Keychain
    try:
        user = os.environ.get("USER") or subprocess.run(
            ["whoami"], capture_output=True, text=True).stdout.strip()
        r = subprocess.run(
            ["security", "find-generic-password",
             "-a", user, "-s", "nasa-ads-api-token", "-w"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except FileNotFoundError:
        pass  # not on macOS
    # 2. Environment variable
    for var in ("ADS_DEV_KEY", "ADS_API_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    # 3. File
    keyfile = Path.home() / ".ads" / "dev_key"
    if keyfile.exists():
        token = keyfile.read_text().strip().splitlines()[0].strip()
        if token:
            return token
    _die("ADS token not found. Set one of:\n"
         "  - macOS keychain: security add-generic-password -a \"$USER\" "
         "-s \"nasa-ads-api-token\" -w \"<TOKEN>\" -U\n"
         "  - Env var: export ADS_DEV_KEY=<TOKEN>\n"
         "  - File: echo <TOKEN> > ~/.ads/dev_key && chmod 600 ~/.ads/dev_key")


def api_get(path: str, params: list[tuple[str, str]], token: str) -> dict:
    """GET request to an ADS endpoint with a list of (key, value) params.
    Duplicate keys are allowed (e.g., multiple fq filters)."""
    url = f"{ADS}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return _http_call(req)


def api_post(path: str, body: dict, token: str) -> dict:
    """POST request to an ADS endpoint with a JSON body."""
    req = urllib.request.Request(
        f"{ADS}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    return _http_call(req)


def _print_results(docs: list[dict], json_out: bool = False) -> None:
    """Format a list of ADS result docs as a numbered list, or emit JSON."""
    if json_out:
        print(json.dumps(docs, indent=2, ensure_ascii=False))
        return
    if not docs:
        print("No results.")
        return
    print(f"Found {len(docs)} results:\n")
    for i, p in enumerate(docs, 1):
        authors = p.get("author", ["?"])
        fa = authors[0] if authors else "?"
        n = len(authors)
        extra = f" et al. ({n} authors)" if n > 1 else ""
        title = p.get("title", ["?"])[0]
        print(f'{i}. {fa}{extra} ({p.get("year","?")}) — {title}')
        print(f'   {p.get("pub","?")} | {p.get("citation_count",0)} cites '
              f'| {p.get("bibcode","?")}\n')


def _list_search(
    query: str,
    default_sort: str,
    default_rows: int,
    rows: Optional[int],
    sort: Optional[str],
    json_out: bool,
    extra_fl: str = "",
) -> None:
    """Shared implementation for search/citations/references: applies filters,
    rows/sort overrides, emits results as text or JSON."""
    token = get_token()
    fl = LIST_FL + (f",{extra_fl}" if extra_fl else "")
    params = [
        ("q", query),
        ("fq", "database:astronomy"),
        ("fq", "doctype:(article OR eprint)"),
        ("fl", fl),
        ("sort", sort or default_sort),
        ("rows", str(rows or default_rows)),
    ]
    data = api_get("/search/query", params, token)
    _print_results(data.get("response", {}).get("docs", []), json_out)


def cmd_search(query: str, rows: Optional[int], sort: Optional[str],
               json_out: bool) -> None:
    """Search NASA ADS and print up to 10 (or --rows N) results.

    Filter to astronomy DB and to journal articles + arXiv preprints —
    excludes AAS meeting abstracts, conference proceedings, PhD theses.

    Tool spec: { query: string, rows?: int, sort?: string, json?: bool }
    """
    _list_search(query, "date desc", 10, rows, sort, json_out)


def cmd_citations(bibcode: str, rows: Optional[int], sort: Optional[str],
                  json_out: bool) -> None:
    """List the top 20 (or --rows N) papers citing the given bibcode.

    Uses ADS's citations() query operator, which returns the set of papers
    citing the matches of its inner query.

    Tool spec: { bibcode: string, rows?: int, sort?: string, json?: bool }
    """
    bibcode = _clean_bibcode(bibcode)
    _list_search(f"citations(bibcode:{bibcode})",
                 "citation_count desc", 20, rows, sort, json_out)


def cmd_references(bibcode: str, rows: Optional[int], sort: Optional[str],
                   json_out: bool) -> None:
    """List papers referenced by (cited in) the given bibcode.

    Uses ADS's references() query operator — the complement of citations().

    Tool spec: { bibcode: string, rows?: int, sort?: string, json?: bool }
    """
    bibcode = _clean_bibcode(bibcode)
    _list_search(f"references(bibcode:{bibcode})",
                 "date desc", 50, rows, sort, json_out)


def cmd_show(bibcode: str, json_out: bool) -> None:
    """Print the full ADS record for one bibcode: title, author list, pub,
    year, DOI, citations, ADS URL, keywords, abstract.

    Tool spec: { bibcode: string, json?: bool }
    """
    bibcode = _clean_bibcode(bibcode)
    token = get_token()
    params = [
        ("q", f"bibcode:{bibcode}"),
        ("fl", "bibcode,title,author,year,pub,doi,abstract,citation_count,keyword"),
        ("rows", "1"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        _die(f"No ADS record found for bibcode: {bibcode}")
    p = docs[0]
    if json_out:
        print(json.dumps(p, indent=2, ensure_ascii=False))
        return
    authors = p.get("author", ["?"])
    title = p.get("title", ["?"])[0]
    print(f"Title:    {title}")
    print(f"Authors:  {'; '.join(authors)}")
    print(f"Pub:      {p.get('pub','?')} ({p.get('year','?')})")
    if p.get("doi"):
        print(f"DOI:      {p['doi'][0]}")
    print(f"Bibcode:  {p.get('bibcode','?')}")
    print(f"Citations: {p.get('citation_count', 0)}")
    print(f"ADS URL:  https://ui.adsabs.harvard.edu/abs/{p.get('bibcode','')}")
    if p.get("keyword"):
        print(f"Keywords: {', '.join(p['keyword'])}")
    print()
    print("Abstract:")
    print(p.get("abstract", "(no abstract available)"))


_TITLE_STOPWORDS = {
    "The", "And", "With", "From", "Using", "Type", "Survey", "Sample", "Data",
    "New", "Results", "Paper", "First", "Second", "Third", "For", "Into",
    "Over", "Under", "Their", "Its", "This", "That", "Which", "When", "Where",
}


def _derive_subject(title: str) -> str:
    """Pick a memorable subject word from a paper title. Prefers UPPERCASE
    acronyms (3+ chars); falls back to the longest capitalized non-stopword."""
    # Strip LaTeX braces and commands
    clean = re.sub(r"\\[a-zA-Z]+|[{}]", "", title)
    # UPPERCASE acronyms of 3+ chars (ESSENCE, PLCK, LSST, DESC...)
    acronyms = re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", clean)
    if acronyms:
        return acronyms[0]
    # Fall back: longest capitalized word that isn't a stopword
    caps = re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", clean)
    caps = [w for w in caps if w not in _TITLE_STOPWORDS]
    if caps:
        return max(caps, key=len)
    return "Paper"


def _rekey_bibtex(bibtex: str, subject: Optional[str] = None) -> str:
    """Transform an ADS bibtex block to use LastName_Subject_Year as the
    citekey. Prepends a '% ADS bibcode: <bibcode>' comment so the original
    identifier is never lost and dedup remains robust."""
    m = re.search(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", bibtex)
    if not m:
        return bibtex  # unrecognizable, return as-is
    bibcode = m.group(2)
    author_m = re.search(r"author\s*=\s*\{\s*\{([^}]+)\}", bibtex)
    lastname = re.sub(r"[^A-Za-z]", "", author_m.group(1)) if author_m else "Unknown"
    year_m = re.search(r"year\s*=\s*(\d{4})", bibtex)
    year = year_m.group(1) if year_m else "XXXX"
    if not subject:
        title_m = re.search(r'title\s*=\s*"?\s*\{(.*?)\}"?,', bibtex, re.DOTALL)
        subject = _derive_subject(title_m.group(1) if title_m else "")
    subject = re.sub(r"[^A-Za-z0-9]", "", subject)
    new_key = f"{lastname}_{subject}_{year}"
    rewritten = re.sub(
        r"(@\w+\s*\{)\s*[^,\s]+\s*,",
        lambda mm: f"{mm.group(1)}{new_key},",
        bibtex, count=1,
    )
    return f"% ADS bibcode: {bibcode}\n{rewritten}"


def _split_bibtex_entries(export: str) -> list[str]:
    """Split an ADS bibtex export string into individual @ARTICLE{...} blocks."""
    # Entries start with @ at column 0 and end before the next @ or EOF.
    entries = re.findall(r"@\w+\s*\{[^@]+", export)
    return [e.rstrip() for e in entries]


def _sort_bib_chronologically(text: str) -> str:
    """Rewrite .bib text with entries sorted ascending by bibcode year.

    Splits on blank-line boundaries; ADS bibtex export and this module's
    own writer both separate entries that way. For each chunk, extracts
    a bibcode from either a '% ADS bibcode: <X>' comment (rekey'd
    entries) or the @ENTRY{<X>,...} citekey (raw-bibcode-keyed entries).
    Chunks without a recognizable bibcode (file-level preamble comments)
    stay at the top in original order. Sort key is (year, bibcode) so
    same-year entries land in a deterministic order.

    Assumes entries are separated by at least one blank line, contain no
    blank lines inside the entry body, and hold at most one @entry per
    chunk — all true of ADS export and of entries written by this tool.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.strip()
    if not text:
        return ""
    chunks = re.split(r"\n\s*\n+", text)
    preamble: list[str] = []
    entries: list[tuple[int, str, str]] = []
    for chunk in chunks:
        m = re.search(r"%\s*ADS bibcode:\s*(\d{4}\S{15})", chunk)
        if not m:
            m = re.search(r"@\w+\s*\{\s*(\d{4}\S{15})\s*,", chunk)
        if m:
            bibcode = m.group(1)
            entries.append((int(bibcode[:4]), bibcode, chunk))
        else:
            preamble.append(chunk)
    entries.sort(key=lambda t: (t[0], t[1]))
    parts = preamble + [c for (_, _, c) in entries]
    return "\n\n".join(parts) + "\n"


def cmd_bibtex(bibcodes: list[str], json_out: bool,
               rekey: bool = False, subject: Optional[str] = None) -> None:
    """Export verbatim bibtex entries for one or more bibcodes via the ADS
    export endpoint. With --rekey, rewrites the citekey to LastName_Subject_Year
    and prepends a '% ADS bibcode:' comment preserving the original identifier.

    Tool spec: { bibcodes: array<string>, max length 2000, json?: bool,
                 rekey?: bool, subject?: string }
    """
    if len(bibcodes) > BIBTEX_MAX:
        _die(f"ADS export endpoint accepts at most {BIBTEX_MAX} bibcodes per "
             f"request; got {len(bibcodes)}. Split into multiple calls.")
    if subject and not rekey:
        _die("--subject requires --rekey.")
    if subject and len(bibcodes) > 1:
        _die("--subject applies to a single bibcode; for batches, omit it "
             "and let the auto-derive choose per-entry subjects.")
    bibcodes = [_clean_bibcode(b) for b in bibcodes]
    token = get_token()
    data = api_post("/export/bibtex", {"bibcode": bibcodes}, token)
    export = data.get("export", "")
    if not export:
        _die(f"ADS returned no bibtex for: {', '.join(bibcodes)}")
    if rekey:
        entries = _split_bibtex_entries(export)
        export = "\n\n".join(_rekey_bibtex(e, subject) for e in entries) + "\n"
    if json_out:
        print(json.dumps({"bibtex": export}, indent=2))
    else:
        print(export, end="")


def cmd_arxiv(arxiv_id: str, json_out: bool) -> None:
    """Resolve an arXiv ID to an ADS record, preferring the refereed version
    over the preprint when both are indexed.

    Tool spec: { arxiv_id: string, json?: bool }
    """
    token = get_token()
    arxiv_id = _clean_arxiv_id(arxiv_id)
    params = [
        ("q", f"identifier:arXiv:{arxiv_id}"),
        ("fl", f"{LIST_FL},doctype"),
        # Lexicographic sort on doctype puts "article" before "eprint",
        # so any refereed version surfaces ahead of the preprint.
        ("sort", "doctype asc,date desc"),
        ("rows", "5"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        _die(f"No ADS record found for arXiv:{arxiv_id}")
    if not json_out:
        refereed = [d for d in docs if d.get("doctype") == "article"]
        preprints = [d for d in docs if d.get("doctype") == "eprint"]
        if refereed and preprints:
            print("Refereed version available (preferred); preprint also in ADS.\n")
        elif preprints and not refereed:
            print("Only preprint found on ADS (no refereed version yet).\n")
    _print_results(docs, json_out)


def cmd_doi(doi: str, json_out: bool) -> None:
    """Resolve a DOI to an ADS bibcode.

    Tool spec: { doi: string, json?: bool }
    """
    doi = _clean_doi(doi)
    token = get_token()
    params = [
        ("q", f'doi:"{doi}"'),
        ("fl", LIST_FL),
        ("rows", "5"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        _die(f"No ADS record found for DOI: {doi}")
    _print_results(docs, json_out)


def cmd_append(bibfile: str, bibcodes: list[str], json_out: bool,
               rekey: bool = False, subject: Optional[str] = None) -> None:
    """Append verbatim ADS bibtex entries to a .bib file, skipping any
    bibcode whose citekey OR preserved '% ADS bibcode:' comment already
    exists. Creates the file if missing. With --rekey, citekeys become
    LastName_Subject_Year and the bibcode is preserved as a comment.

    After any write, the whole file is rewritten in ascending chronological
    order (by bibcode year), so new papers land at the bottom and older
    backfills slot into place. Running append on an unchanged set of
    bibcodes is still cheap, and self-heals any file whose order has
    drifted from chronological.

    Tool spec: { bibfile: string (path), bibcodes: array<string>, json?: bool,
                 rekey?: bool, subject?: string }
    """
    if subject and not rekey:
        _die("--subject requires --rekey.")
    if subject and len(bibcodes) > 1:
        _die("--subject applies to a single bibcode; for batches, omit it "
             "and let the auto-derive choose per-entry subjects.")
    bibcodes = [_clean_bibcode(b) for b in bibcodes]
    path = Path(bibfile).expanduser()
    if path.is_dir():
        _die(f"Target path is a directory, not a .bib file: {path}")
    existing_text = ""
    existing_bibcodes: set[str] = set()
    if path.exists():
        existing_text = path.read_text()
        # Strip BOM if present so regex matches the first entry correctly
        if existing_text.startswith("\ufeff"):
            existing_text = existing_text[1:]
        # Collect identifiers that could match an incoming bibcode, from:
        # (a) citekeys (old-style entries key'd by bibcode), and
        # (b) '% ADS bibcode: <X>' comments (rekey'd entries).
        existing_bibcodes.update(
            re.findall(r"@\w+\s*\{\s*([^,\s]+)", existing_text))
        # Constrain to the bibcode format so a trailing user note on the
        # same line (e.g., '% ADS bibcode: 2016ApJS..224....3N — cited in §2')
        # doesn't leak into the captured identifier.
        existing_bibcodes.update(
            re.findall(r"%\s*ADS bibcode:\s*(\d{4}\S{15})", existing_text))
    new = [b for b in bibcodes if b not in existing_bibcodes]
    skipped = [b for b in bibcodes if b in existing_bibcodes]
    result: dict = {"bibfile": str(path), "added": new, "skipped": skipped}

    combined = existing_text
    if new:
        token = get_token()
        data = api_post("/export/bibtex", {"bibcode": new}, token)
        export = data.get("export", "").rstrip()
        if not export:
            _die(f"ADS returned no bibtex for: {', '.join(new)}")
        if rekey:
            entries = _split_bibtex_entries(export)
            export = "\n\n".join(_rekey_bibtex(e, subject) for e in entries)
        # Ensure at least one blank line separates old content from new
        # before the chronological sort parses the combined text.
        if not combined:
            sep = ""
        elif combined.endswith("\n\n"):
            sep = ""
        elif combined.endswith("\n"):
            sep = "\n"
        else:
            sep = "\n\n"
        combined = combined + sep + export + "\n"
        result["bibtex_written"] = export

    sorted_text = _sort_bib_chronologically(combined) if combined else ""
    reordered = bool(sorted_text) and sorted_text != existing_text and not new
    if new or reordered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sorted_text)
    result["reordered"] = reordered

    if json_out:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if new:
        print(f"Appended {len(new)} entry(ies) to {path}:")
        for b in new:
            print(f"  + {b}")
    if skipped:
        print(f"Skipped {len(skipped)} already-present entry(ies):")
        for b in skipped:
            print(f"  = {b}")
    if reordered:
        print("Reordered file chronologically.")
    if not new and not skipped:
        print("Nothing to do.")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse schema for the ads-cite CLI."""
    # Parent parsers for shared flags — inherited via parents=[...] on subparsers.
    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument(
        "--json", action="store_true", dest="json_out",
        help="emit JSON instead of formatted text",
    )
    list_flags = argparse.ArgumentParser(add_help=False)
    list_flags.add_argument(
        "--rows", type=int, default=None, metavar="N",
        help="max results to return",
    )
    list_flags.add_argument(
        "--sort", default=None, metavar="'FIELD DIR'",
        help="sort order, e.g. 'citation_count desc' or 'date asc'",
    )

    # Rekey flags — shared by bibtex and append.
    rekey_flags = argparse.ArgumentParser(add_help=False)
    rekey_flags.add_argument(
        "--rekey", action="store_true",
        help="rewrite citekey to LastName_Subject_Year and prepend an "
             "'% ADS bibcode:' comment preserving the original identifier",
    )
    rekey_flags.add_argument(
        "--subject", default=None, metavar="WORD",
        help="subject term for --rekey (single bibcode only); "
             "auto-derived from title if omitted",
    )

    p = argparse.ArgumentParser(
        prog="ads-cite",
        description="NASA ADS CLI: search, export verbatim bibtex, resolve "
                    "arXiv/DOI, list citations/references, append to .bib files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"{QUERY_SYNTAX}\n\n{TOKEN_DOC}",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    s = sub.add_parser("search", parents=[json_flag, list_flags],
                       help="search ADS with field syntax")
    s.add_argument("query", help="ADS query string (see epilog for syntax)")

    s = sub.add_parser("show", parents=[json_flag],
                       help="full record for one bibcode")
    s.add_argument("bibcode")

    s = sub.add_parser("bibtex", parents=[json_flag, rekey_flags],
                       help="verbatim bibtex for one or more bibcodes")
    s.add_argument("bibcodes", nargs="+", metavar="BIBCODE")

    s = sub.add_parser("citations", parents=[json_flag, list_flags],
                       help="papers citing this bibcode")
    s.add_argument("bibcode")

    s = sub.add_parser("references", parents=[json_flag, list_flags],
                       help="papers cited by this bibcode")
    s.add_argument("bibcode")

    s = sub.add_parser("arxiv", parents=[json_flag],
                       help="resolve arXiv ID (prefers refereed version)")
    s.add_argument("arxiv_id", metavar="ID",
                   help="arXiv ID, with or without 'arXiv:' prefix")

    s = sub.add_parser("doi", parents=[json_flag],
                       help="resolve DOI to an ADS bibcode")
    s.add_argument("doi", metavar="DOI")

    s = sub.add_parser("append", parents=[json_flag, rekey_flags],
                       help="append bibtex to a .bib file, skipping duplicates")
    s.add_argument("bibfile", help="path to the .bib file (created if missing)")
    s.add_argument("bibcodes", nargs="+", metavar="BIBCODE")

    return p


def main(argv: Optional[list[str]] = None) -> None:
    """Parse argv and dispatch to the matching cmd_* function.

    Accepts an optional argv list for testability; defaults to sys.argv[1:]."""
    ns = _build_parser().parse_args(argv)
    if ns.cmd == "search":
        cmd_search(ns.query, ns.rows, ns.sort, ns.json_out)
    elif ns.cmd == "show":
        cmd_show(ns.bibcode, ns.json_out)
    elif ns.cmd == "bibtex":
        cmd_bibtex(ns.bibcodes, ns.json_out, ns.rekey, ns.subject)
    elif ns.cmd == "citations":
        cmd_citations(ns.bibcode, ns.rows, ns.sort, ns.json_out)
    elif ns.cmd == "references":
        cmd_references(ns.bibcode, ns.rows, ns.sort, ns.json_out)
    elif ns.cmd == "arxiv":
        cmd_arxiv(ns.arxiv_id, ns.json_out)
    elif ns.cmd == "doi":
        cmd_doi(ns.doi, ns.json_out)
    elif ns.cmd == "append":
        cmd_append(ns.bibfile, ns.bibcodes, ns.json_out, ns.rekey, ns.subject)


if __name__ == "__main__":
    main()
