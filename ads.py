#!/usr/bin/env python3
"""Helper for the /ads-cite skill — wraps ADS search, record detail, bibtex
export, and citation lookup so the skill only needs one whitelisted Bash
permission instead of separate curl + python3 invocations.

Usage:
  ads.py search "<QUERY>"              search ADS; print numbered results
  ads.py show <BIBCODE>                print full record for one bibcode
  ads.py bibtex <BIBCODE> [<BIBCODE>]  print bibtex entries (verbatim ADS)
  ads.py citations <BIBCODE>           list papers that cite this bibcode
  ads.py arxiv <ID>                    resolve arXiv ID (prefers refereed version)
  ads.py doi <DOI>                     resolve DOI to bibcode

Query syntax (search/citations):
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
  "GW170817"               quoted phrase (use for object names, compact IDs)
  Combine fields with spaces (implicit AND). Also OR, NOT, - (negation).

ADS API token — searched in this order:
  1. macOS Keychain: service 'nasa-ads-api-token', account $USER
  2. Environment variable: ADS_DEV_KEY or ADS_API_TOKEN
  3. File: ~/.ads/dev_key (first line, stripped)
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Structure: _http_call wraps urllib with ADS-specific error translation;
# api_{get,post} thin wrappers over it; cmd_* functions are the CLI verbs.

ADS = "https://api.adsabs.harvard.edu/v1"
BIBTEX_MAX = 2000  # ADS export endpoint per-request limit


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _http_call(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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
        _die("Request to ADS timed out after 30 seconds.")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        _die(f"ADS returned non-JSON response: {body[:200]!r}")


def get_token() -> str:
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
    sys.exit(
        "ERROR: ADS token not found. Set one of:\n"
        "  - macOS keychain: security add-generic-password -a \"$USER\" "
        "-s \"nasa-ads-api-token\" -w \"<TOKEN>\" -U\n"
        "  - Env var: export ADS_DEV_KEY=<TOKEN>\n"
        "  - File: echo <TOKEN> > ~/.ads/dev_key && chmod 600 ~/.ads/dev_key"
    )


def api_get(path: str, params: list[tuple[str, str]], token: str) -> dict:
    url = f"{ADS}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return _http_call(req)


def api_post(path: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(
        f"{ADS}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    return _http_call(req)


def _print_results(docs: list[dict]) -> None:
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


def cmd_search(query: str) -> None:
    # Filter to astronomy DB and to journal articles + arXiv preprints —
    # excludes AAS meeting abstracts, conference proceedings, PhD theses.
    token = get_token()
    params = [
        ("q", query),
        ("fq", "database:astronomy"),
        ("fq", "doctype:(article OR eprint)"),
        ("fl", "bibcode,title,author,year,citation_count,pub"),
        ("sort", "date desc"),
        ("rows", "10"),
    ]
    data = api_get("/search/query", params, token)
    _print_results(data.get("response", {}).get("docs", []))


def cmd_show(bibcode: str) -> None:
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


def cmd_bibtex(bibcodes: list[str]) -> None:
    if len(bibcodes) > BIBTEX_MAX:
        _die(f"ADS export endpoint accepts at most {BIBTEX_MAX} bibcodes per "
             f"request; got {len(bibcodes)}. Split into multiple calls.")
    token = get_token()
    data = api_post("/export/bibtex", {"bibcode": bibcodes}, token)
    export = data.get("export", "")
    if not export:
        _die(f"ADS returned no bibtex for: {', '.join(bibcodes)}")
    print(export, end="")


def cmd_arxiv(arxiv_id: str) -> None:
    token = get_token()
    # strip any leading "arXiv:" prefix; keep bare ID
    arxiv_id = arxiv_id.removeprefix("arXiv:").removeprefix("arxiv:").strip()
    params = [
        ("q", f"identifier:arXiv:{arxiv_id}"),
        ("fl", "bibcode,title,author,year,citation_count,pub,doctype"),
        # Lexicographic sort on doctype puts "article" before "eprint",
        # so any refereed version surfaces ahead of the preprint.
        ("sort", "doctype asc,date desc"),
        ("rows", "5"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        _die(f"No ADS record found for arXiv:{arxiv_id}")
    # Flag refereed vs preprint
    refereed = [d for d in docs if d.get("doctype") == "article"]
    preprints = [d for d in docs if d.get("doctype") == "eprint"]
    if refereed and preprints:
        print(f"Refereed version available (preferred); preprint also in ADS.\n")
    elif preprints and not refereed:
        print(f"Only preprint found on ADS (no refereed version yet).\n")
    _print_results(docs)


def cmd_doi(doi: str) -> None:
    token = get_token()
    params = [
        ("q", f'doi:"{doi}"'),
        ("fl", "bibcode,title,author,year,citation_count,pub"),
        ("rows", "5"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        _die(f"No ADS record found for DOI: {doi}")
    _print_results(docs)


def cmd_citations(bibcode: str) -> None:
    # ADS's citations() query operator returns the set of papers citing the
    # matches of its inner query — here, the single record with this bibcode.
    token = get_token()
    params = [
        ("q", f"citations(bibcode:{bibcode})"),
        ("fq", "database:astronomy"),
        ("fq", "doctype:(article OR eprint)"),
        ("fl", "bibcode,title,author,year,citation_count,pub"),
        ("sort", "citation_count desc"),
        ("rows", "20"),
    ]
    data = api_get("/search/query", params, token)
    _print_results(data.get("response", {}).get("docs", []))


def usage(exit_code: int = 0) -> None:
    print(__doc__, file=sys.stderr if exit_code else sys.stdout)
    sys.exit(exit_code)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        usage(0)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "search" and len(args) == 1:
        cmd_search(args[0])
    elif cmd == "show" and len(args) == 1:
        cmd_show(args[0])
    elif cmd == "bibtex" and len(args) >= 1:
        cmd_bibtex(args)
    elif cmd == "citations" and len(args) == 1:
        cmd_citations(args[0])
    elif cmd == "arxiv" and len(args) == 1:
        cmd_arxiv(args[0])
    elif cmd == "doi" and len(args) == 1:
        cmd_doi(args[0])
    else:
        usage(1)


if __name__ == "__main__":
    main()
