#!/usr/bin/env python3
"""
Skill frequency of London data-scientist jobs posted directly by companies,
collected from the free public job-board APIs of Greenhouse, Lever and Ashby.
No API key needed.

Pipeline
  1. For each company in COMPANIES, try its likely board names on all three
     platforms and remember which one works (saved to output_ats/boards.json,
     so later runs skip the guessing).
  2. Download every open job from each found board.
  3. Keep jobs that are in London, have a data-scientist title, are not senior,
     and were first published in the last N days (default 30).
  4. Count skills once per job (same dictionary as reed_ds_skills.py) and
     draw the frequency chart.

Usage (put this file next to reed_ds_skills.py):
  python3 ats_ds_skills.py                # London, last 30 days
  python3 ats_ds_skills.py --days 60      # wider window
  python3 ats_ds_skills.py --uk-remote    # also count "Remote (UK)" jobs
  python3 ats_ds_skills.py --region UK --out output_ats_uk   # whole UK
  python3 ats_ds_skills.py --add greenhouse:examplecorp lever:another
                                          # add boards you found by hand
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reed_ds_skills import (TITLE_EXCLUDE, TITLE_INCLUDE, analyse,  # noqa: E402
                            clean_text, in_region)

# --------------------------------------------------------------------------
# Companies with London data teams. Each entry: display name -> board-name
# guesses (tried in order on Greenhouse, Lever and Ashby). Edit freely.
# --------------------------------------------------------------------------

COMPANIES: dict[str, list[str]] = {
    # Fintech / banking
    "Monzo": ["monzo"], "Wise": ["wise", "transferwise"], "Revolut": ["revolut"],
    "Starling Bank": ["starlingbank", "starling"], "OakNorth": ["oaknorth"],
    "GoCardless": ["gocardless"], "Checkout.com": ["checkoutcom", "checkout"],
    "Zopa": ["zopa", "zopabank"], "Cleo": ["cleo", "cleoai"], "Marshmallow": ["marshmallow"],
    "Lendable": ["lendable"], "Tide": ["tide"], "Curve": ["curve", "imaginecurve"],
    "Moneybox": ["moneybox"], "Freetrade": ["freetrade"], "Plum": ["plum", "withplum"],
    "Chip": ["chip", "getchip"], "Yapily": ["yapily"], "TrueLayer": ["truelayer"],
    "Primer": ["primer"], "Paddle": ["paddle"], "Pleo": ["pleo"],
    "Funding Circle": ["fundingcircle"], "ClearScore": ["clearscore"], "Zilch": ["zilch"],
    "Bud": ["bud", "thisisbud"], "Thought Machine": ["thoughtmachine"],
    "10x Banking": ["10xbanking", "10x"], "Kroo": ["kroo"], "Allica Bank": ["allicabank", "allica"],
    "iwoca": ["iwoca"], "Capital on Tap": ["capitalontap"], "Ebury": ["ebury"],
    "Dojo": ["dojo", "paymentsense"], "Teya": ["teya"], "SumUp": ["sumup"],
    "Wagestream": ["wagestream", "stream"], "Ophelos": ["ophelos"], "Yonder": ["yonder"],
    "ComplyAdvantage": ["complyadvantage"], "Elliptic": ["elliptic"],
    "Chainalysis": ["chainalysis"], "Blockchain.com": ["blockchain"], "Copper": ["copper", "coppertechnologies"],
    "Ravelin": ["ravelin"], "Onfido": ["onfido"], "Nutmeg": ["nutmeg"], "Monese": ["monese"],
    "Uncapped": ["uncapped"], "Pockit": ["pockit"], "Paysend": ["paysend"],
    # Insurance / insurtech
    "Zego": ["zego"], "ManyPets": ["manypets", "boughtbymany"], "Cuvva": ["cuvva"],
    "Hyperexponential": ["hyperexponential", "hx"], "Artificial Labs": ["artificiallabs", "artificial"],
    "Ki Insurance": ["kiinsurance", "ki"], "Cytora": ["cytora"], "Flock": ["flock"],
    # Consumer / marketplaces / travel
    "Deliveroo": ["deliveroo"], "Gousto": ["gousto"], "Depop": ["depop"], "Lyst": ["lyst"],
    "Trainline": ["trainline"], "Skyscanner": ["skyscanner"], "Bumble": ["bumble"],
    "Zoopla": ["zoopla"], "Moonpig": ["moonpig"], "Motorway": ["motorway"],
    "Bloom & Wild": ["bloomandwild"], "Huel": ["huel"], "Butternut Box": ["butternutbox"],
    "Papier": ["papier"], "Citymapper": ["citymapper"], "FREENOW": ["freenow"],
    "Duffel": ["duffel"], "Mubi": ["mubi"], "DAZN": ["dazn"], "Busuu": ["busuu"],
    "Memrise": ["memrise"], "Goodlord": ["goodlord"], "Zapp": ["zapp"], "Hinge": ["hinge"],
    "Spotify": ["spotify"], "Farfetch": ["farfetch"], "Vinted": ["vinted"], "Sorare": ["sorare"],
    "OVO": ["ovo", "ovoenergy"], "Octopus Energy": ["octopusenergy", "octopus"],
    "Kraken Tech": ["kraken", "krakentech"], "Fuse Energy": ["fuseenergy", "fuse"],
    "Permutive": ["permutive"], "Ometria": ["ometria"], "Multiverse": ["multiverse"],
    "Beamery": ["beamery"], "Unmind": ["unmind"], "Snyk": ["snyk"], "Improbable": ["improbable"],
    "Bolt": ["bolt"], "Cazoo": ["cazoo"], "Juro": ["juro"], "Hopin": ["hopin"],
    # Health / bio
    "Cera": ["cera", "ceracare"], "Healx": ["healx"], "BenevolentAI": ["benevolentai", "benevolent"],
    "Flo Health": ["flohealth", "flo"], "Thriva": ["thriva"], "Accurx": ["accurx"],
    "Huma": ["huma"], "Kheiron Medical": ["kheironmed", "kheiron"], "Elvie": ["elvie"],
    "Lindus Health": ["lindushealth", "lindus"], "LabGenius": ["labgenius"],
    "Relation Therapeutics": ["relationtx", "relation"], "Isomorphic Labs": ["isomorphiclabs"],
    "Basecamp Research": ["basecampresearch"], "Latent Labs": ["latentlabs"], "Peppy": ["peppy"],
    # AI / data companies
    "Google DeepMind": ["deepmind"], "Anthropic": ["anthropic"], "OpenAI": ["openai"],
    "Cohere": ["cohere"], "Synthesia": ["synthesia"], "ElevenLabs": ["elevenlabs"],
    "Stability AI": ["stabilityai", "stability"], "PolyAI": ["polyai"], "Wayve": ["wayve"],
    "Faculty": ["faculty", "facultyai"], "Tractable": ["tractable"], "Quantexa": ["quantexa"],
    "Signal AI": ["signalai"], "causaLens": ["causalens"], "Prolific": ["prolific"],
    "PhysicsX": ["physicsx"], "Helsing": ["helsing"], "V7": ["v7", "v7labs"],
    "Robin AI": ["robinai"], "Luminance": ["luminance"], "Vortexa": ["vortexa"],
    "Kpler": ["kpler"], "Climate X": ["climatex", "climate-x"], "CuspAI": ["cuspai"],
    "Granola": ["granola"], "Palantir": ["palantir"], "Conjecture": ["conjecture"],
    "Speechmatics": ["speechmatics"], "Peak": ["peak", "peakai"], "Mesh-AI": ["meshai"],
    "Datatonic": ["datatonic"], "Dunnhumby": ["dunnhumby"], "Hex": ["hex"],
    # Trading / quant (some post data-science roles)
    "G-Research": ["gresearch", "g-research"], "XTX Markets": ["xtxmarkets"],
    "Marshall Wace": ["marshallwace"], "Squarepoint": ["squarepoint", "squarepointcapital"],
}

PLATFORMS = ("greenhouse", "lever", "ashby")
LONDON = re.compile(r"\blondon\b", re.I)
UK_REMOTE = re.compile(r"remote.{0,15}\b(uk|united kingdom|england|gb)\b|\b(uk|united kingdom)\b.{0,15}remote", re.I)

# --------------------------------------------------------------------------
# Platform adapters: each returns a list of normalised job dicts
# --------------------------------------------------------------------------

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (job-skills research script)"


def _get_json(url: str, params: dict | None = None):
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):  # Lever: epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fetch_greenhouse(name: str) -> list[dict] | None:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{name}/jobs", {"content": "true"})
    if not data or "jobs" not in data:
        return None
    jobs = []
    for j in data["jobs"]:
        offices = " | ".join(o.get("name", "") for o in j.get("offices", []) or [])
        loc = " | ".join(x for x in [(j.get("location") or {}).get("name", ""), offices] if x)
        jobs.append({
            "job_id": f"gh-{name}-{j['id']}",
            "title": j.get("title", ""),
            "employer": j.get("company_name") or name,
            "location": loc,
            "date": _parse_iso(j.get("first_published") or j.get("updated_at")),
            "url": j.get("absolute_url", ""),
            # Greenhouse returns HTML that is itself entity-escaped
            "text": clean_text(html.unescape(j.get("content") or "")),
        })
    return jobs


def fetch_lever(name: str) -> list[dict] | None:
    data = _get_json(f"https://api.lever.co/v0/postings/{name}", {"mode": "json"})
    if not isinstance(data, list):
        return None
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locs = [cats.get("location") or ""] + list(cats.get("allLocations") or [])
        parts = [j.get("descriptionPlain") or clean_text(j.get("description"))]
        for block in j.get("lists") or []:
            parts.append(block.get("text", ""))
            parts.append(clean_text(block.get("content", "")))
        parts.append(j.get("additionalPlain") or clean_text(j.get("additional")))
        jobs.append({
            "job_id": f"lv-{name}-{j.get('id')}",
            "title": j.get("text", ""),
            "employer": name,
            "location": " | ".join(dict.fromkeys(x for x in locs if x)),
            "date": _parse_iso(j.get("createdAt")),
            "url": j.get("hostedUrl", ""),
            "text": "\n".join(p for p in parts if p),
        })
    return jobs


def fetch_ashby(name: str) -> list[dict] | None:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{name}")
    if not data or "jobs" not in data:
        return None
    jobs = []
    for j in data["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        addr = ((j.get("address") or {}).get("postalAddress") or {}).get("addressLocality", "")
        jobs.append({
            "job_id": f"ab-{name}-{j.get('id')}",
            "title": j.get("title", ""),
            "employer": name,
            "location": " | ".join(dict.fromkeys(x for x in locs + [addr] if x)),
            "date": _parse_iso(j.get("publishedAt")),
            "url": j.get("jobUrl", ""),
            "text": j.get("descriptionPlain") or clean_text(j.get("descriptionHtml")),
        })
    return jobs


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def discover(boards: dict, out_dir: Path) -> dict:
    """Find which platform/name works for each company; cache the answer."""
    todo = [c for c in COMPANIES if c not in boards and COMPANIES[c]]
    print(f"1) Looking up job boards for {len(todo)} companies (cached: {len(boards)}) ...")
    for i, company in enumerate(todo, 1):
        found = None
        for slug in COMPANIES[company]:
            for platform in PLATFORMS:
                jobs = FETCHERS[platform](slug)
                if jobs is not None:
                    found = {"platform": platform, "name": slug}
                    break
            if found:
                break
        boards[company] = found  # None = not found (skipped next time)
        mark = f"{found['platform']}:{found['name']}" if found else "not found"
        print(f"   [{i:3d}/{len(todo)}] {company:24s} {mark}")
        (out_dir / "boards.json").write_text(json.dumps(boards, indent=1))
    return boards


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--uk-remote", action="store_true", help="also keep 'Remote (UK)' jobs")
    ap.add_argument("--region", default="London", choices=["London", "UK"])
    ap.add_argument("--add", nargs="*", default=[], help="extra boards, e.g. greenhouse:acme lever:foo")
    ap.add_argument("--rediscover", action="store_true", help="ignore the cached board lookups")
    ap.add_argument("--top", type=int, default=35)
    ap.add_argument("--out", default="output_ats")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "boards.json"
    boards = {} if args.rediscover or not cache.exists() else json.loads(cache.read_text())

    for item in args.add:
        platform, _, name = item.partition(":")
        if platform not in FETCHERS or not name:
            sys.exit(f"--add expects platform:name, got {item!r}")
        boards[f"{name} (manual)"] = {"platform": platform, "name": name}

    boards = discover(boards, out_dir)
    live = {c: b for c, b in boards.items() if b}
    missing = [c for c, b in boards.items() if not b]

    print(f"2) Downloading jobs from {len(live)} boards ...")
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = today - timedelta(days=args.days)
    log = Counter(boards_found=len(live), boards_not_found=len(missing))
    all_jobs, keep = [], []
    for company, b in live.items():
        jobs = FETCHERS[b["platform"]](b["name"]) or []
        for j in jobs:
            j["employer"] = company.replace(" (manual)", "")
            j["source"] = b["platform"]
        all_jobs.extend(jobs)
        log["jobs_downloaded"] += len(jobs)

    windows = Counter()
    for j in all_jobs:
        in_place = in_region(j["location"], args.region) or (args.uk_remote and UK_REMOTE.search(j["location"]))
        if not in_place:
            log[f"dropped_not_{args.region.lower()}"] += 1
        elif not TITLE_INCLUDE.search(j["title"]):
            log["dropped_not_data_scientist_title"] += 1
        elif TITLE_EXCLUDE.search(j["title"]):
            log["dropped_senior_title"] += 1
        elif not j["date"]:
            log["dropped_no_date"] += 1
        else:
            age = (today - j["date"]).days
            for w in (30, 60, 90, 180):
                windows[f"would_pass_with_{w}_days"] += age <= w
            if j["date"] < cutoff:
                log["dropped_older_than_window"] += 1
            else:
                keep.append(j)

    (out_dir / "all_jobs_raw.json").write_text(json.dumps(
        [{**j, "date": j["date"].isoformat() if j["date"] else None} for j in all_jobs], indent=1))

    if not keep:
        print("No jobs passed the filters. See run_summary.txt; try --days 60 or --uk-remote.")
    else:
        print(f"3) {len(keep)} jobs pass. Extracting skills and drawing the chart ...")
        log.update(analyse(keep, out_dir, args.top, args.days, today,
                           source="company job boards: Greenhouse, Lever, Ashby", region=args.region))
    log.update(windows)

    per_company = Counter(j["employer"] for j in keep)
    lines = [f"  {k:34s} {v}" for k, v in log.items()]
    lines += ["", "Jobs kept per company:"] + [f"  {v:3d}  {k}" for k, v in per_company.most_common()]
    lines += ["", "Companies whose board was not found (add by hand with --add):",
              "  " + ", ".join(missing)]
    summary = "\n".join(lines)
    (out_dir / "run_summary.txt").write_text(summary + "\n")
    print("\nSummary\n" + summary)
    print(f"\nDone. Results in {out_dir}/")


if __name__ == "__main__":
    main()
