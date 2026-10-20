#!/usr/bin/env python3
"""
Merge the two data sources into one skill-frequency chart.

  Source 1: company job boards (Greenhouse / Lever / Ashby) -> output_ats/
  Source 2: Reed.co.uk, mostly recruitment agencies          -> output/

Run the two collectors first, then this:
  python3 reed_ds_skills.py
  python3 ats_ds_skills.py
  python3 combine_ds_skills.py            # last 30 days (default)

Whole UK:
  python3 reed_ds_skills.py --location UK --out output_uk
  python3 ats_ds_skills.py --region UK --out output_ats_uk
  python3 combine_ds_skills.py --region UK --reed-dir output_uk \\
      --ats-dir output_ats_uk --out output_combined_uk

Filters (the same for both sources):
  - located in London (or anywhere in the UK with --region UK)
  - title contains "Data Scientist" (so not "Data Science Manager",
    "Machine Learning Scientist", "Data Science Trainee" ...)
  - not senior: no Senior / Lead / Principal / Staff / Head / Manager ...
    in the title. "Junior", "Graduate", "Associate" and plain
    "Data Scientist" are kept.
  - first posted within the last N days
Each skill is counted once per job ad.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reed_ds_skills import (TITLE_EXCLUDE, TITLE_INCLUDE, analyse,  # noqa: E402
                            clean_text, in_region, parse_date)



def load_ats(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  (no {path}; run ats_ds_skills.py first)")
        return []
    out = []
    for j in json.loads(path.read_text()):
        j["date"] = datetime.fromisoformat(j["date"]) if j.get("date") else None
        j["source"] = f"company board ({j.get('source', '')})"
        out.append(j)
    return out


def load_reed(search_path: Path, cache_dir: Path, log: Counter) -> list[dict]:
    if not search_path.exists():
        print(f"  (no {search_path}; run reed_ds_skills.py first)")
        return []
    out = []
    for j in json.loads(search_path.read_text()):
        rec = {
            "job_id": f"reed-{j['jobId']}",
            "title": j.get("jobTitle", ""),
            "employer": j.get("employerName", ""),
            "location": j.get("locationName", ""),
            "_reed": True,
            "date": parse_date(j.get("date")),
            "min_salary": j.get("minimumSalary"),
            "max_salary": j.get("maximumSalary"),
            "url": j.get("jobUrl", ""),
            "source": "Reed (agency/employer)",
            "_cache": cache_dir / f"{j['jobId']}.json",
            "text": None,
        }
        out.append(rec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--reed-dir", default="output")
    ap.add_argument("--ats-dir", default="output_ats")
    ap.add_argument("--out", default="output_combined")
    ap.add_argument("--top", type=int, default=35)
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--region", default="London", choices=["London", "UK"])
    args = ap.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d") if args.today else datetime.now()
    cutoff = today - timedelta(days=args.days)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log: Counter = Counter()

    reed_dir, ats_dir = Path(args.reed_dir), Path(args.ats_dir)
    jobs = load_ats(ats_dir / "all_jobs_raw.json") + \
        load_reed(reed_dir / "search_results.json", reed_dir / "cache", log)

    keep = []
    for j in jobs:
        src = "reed" if j["source"].startswith("Reed") else "company"
        # Reed results already come from a London-radius or UK-wide search.
        if not j.pop("_reed", False) and not in_region(j["location"], args.region):
            continue  # most company-board jobs are outside the region; not logged
        if not TITLE_INCLUDE.search(j["title"]):
            continue
        log[f"{src}: {args.region} 'Data Scientist' titles"] += 1
        if TITLE_EXCLUDE.search(j["title"]):
            log[f"{src}: dropped senior"] += 1
            continue
        if not j["date"] or j["date"] < cutoff:
            log[f"{src}: dropped older than {args.days} days"] += 1
            continue
        if j["text"] is None:  # Reed: full description comes from the cache
            cache = j.pop("_cache")
            if not cache.exists():
                log["reed: missing full description (re-run reed_ds_skills.py)"] += 1
                continue
            d = json.loads(cache.read_text())
            j["text"] = clean_text(d.get("jobDescription"))
            j["date"] = parse_date(d.get("datePosted")) or j["date"]
        j.pop("_cache", None)
        log[f"{src}: kept"] += 1
        keep.append(j)

    if not keep:
        sys.exit("No jobs passed the filters.")
    stats = analyse(keep, out_dir, args.top, args.days, today,
                    source="company job boards + Reed", region=args.region)
    log.update(stats)

    per_employer = Counter(j["employer"] for j in keep)
    lines = [f"  {k:52s} {v}" for k, v in log.items()]
    lines += ["", "Jobs kept per employer:"] + [f"  {v:3d}  {k}" for k, v in per_employer.most_common()]
    summary = "\n".join(lines)
    (out_dir / "run_summary.txt").write_text(summary + "\n")
    print("Summary\n" + summary + f"\n\nDone. Results in {out_dir}/")


if __name__ == "__main__":
    main()
