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
import urllib.parse
import urllib.request
from pathlib import Path

ADS = "https://api.adsabs.harvard.edu/v1"


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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def api_post(path: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(
        f"{ADS}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _print_results(docs: list[dict]) -> None:
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
        sys.exit(f"No record found for bibcode: {bibcode}")
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
    token = get_token()
    data = api_post("/export/bibtex", {"bibcode": bibcodes}, token)
    print(data.get("export", ""), end="")


def cmd_arxiv(arxiv_id: str) -> None:
    token = get_token()
    # strip any leading "arXiv:" prefix; keep bare ID
    arxiv_id = arxiv_id.removeprefix("arXiv:").removeprefix("arxiv:").strip()
    params = [
        ("q", f"identifier:arXiv:{arxiv_id}"),
        ("fl", "bibcode,title,author,year,citation_count,pub,doctype"),
        # sort article before eprint so refereed version comes first
        ("sort", "doctype asc,date desc"),
        ("rows", "5"),
    ]
    data = api_get("/search/query", params, token)
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        sys.exit(f"No ADS record found for arXiv:{arxiv_id}")
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
        sys.exit(f"No ADS record found for DOI: {doi}")
    _print_results(docs)


def cmd_citations(bibcode: str) -> None:
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
