#!/usr/bin/env python3
"""
Skill frequency of London data-scientist job ads (mid-level and below) on Reed.co.uk.

Pipeline
  1. Search Reed for "data scientist" jobs around London (paged, 100 per page).
  2. Keep ads posted in the last N days (default 30).
  3. Keep titles that are data-scientist roles and drop senior titles
     (senior, lead, principal, staff, head, director, manager, ...).
  4. Fetch the FULL description of each remaining ad (the search endpoint
     only returns a snippet) and cache it on disk.
  5. Remove duplicates (same jobId, or the same ad reposted by agencies).
  6. Match a skill dictionary against each description. A skill counts
     ONCE per ad, however many times it is mentioned.
  7. Write CSVs and a frequency chart to ./output/.

Usage (on your own computer):
  pip install requests pandas matplotlib
  export REED_API_KEY="your-key-here"
  python3 reed_ds_skills.py                 # defaults: London, 10 miles, 30 days
  python3 reed_ds_skills.py --days 30 --distance 15 --top 40
  python3 reed_ds_skills.py --location UK --out output_uk   # whole UK

Re-running is cheap: full descriptions are cached in ./output/cache/.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

API_BASE = "https://www.reed.co.uk/api/1.0"

# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------

# Title must contain "Data Scientist" (not "Data Science ...", not ML Scientist).
TITLE_INCLUDE = re.compile(r"data\s*scientist", re.I)

# Titles above mid-level. Word boundaries keep "Leading" etc. from matching
# only where it matters; "lead" alone is treated as senior.
TITLE_EXCLUDE = re.compile(
    r"\b(senior|snr|sr\.?|lead|principal|staff|head|director|manager|"
    r"chief|vp|vice\s+president|architect|expert|distinguished|"
    r"consultant\s+lead|team\s+lead)\b",
    re.I,
)

# Location filters for the company-board data (Reed results are UK-only already).
LONDON_RE = re.compile(r"\blondon\b", re.I)
UK_COUNTRY_RE = re.compile(
    r"\b(uk|u\.k\.|united kingdom|great britain|england|scotland|wales|northern ireland)\b", re.I)
UK_CITY_RE = re.compile(
    r"\b(london|manchester|edinburgh|glasgow|cambridge|oxford|bristol|leeds|birmingham|"
    r"cardiff|belfast|newcastle|sheffield|nottingham|liverpool|reading|brighton|bath|york|"
    r"southampton|leicester|coventry|milton keynes|guildford|aberdeen|dundee|exeter|swansea|"
    r"cheltenham|norwich|harwell|didcot)\b", re.I)
# Same-named places abroad (London, Ontario; Cambridge, MA; Birmingham, AL ...).
NON_UK_RE = re.compile(
    r"(?i:\b(usa|united states|u\.s\.|canada|ontario|massachusetts|alabama|new hampshire|"
    r"new york|pennsylvania|ohio|australia)\b)|"
    r"\b(MA|AL|NH|KY|CT|NY|PA|CA|WA|TX|IL|NJ|GA|FL|VA|MD|NC|MI|MN|DC|ON)\b")


def in_region(location: str, region: str) -> bool:
    """region is 'London' or 'UK'. A multi-location job counts if any of its
    locations (split on | ; /) is in the region."""
    for seg in re.split(r"[|;/]", location or ""):
        if NON_UK_RE.search(seg):
            continue
        if region.lower() == "london":
            if LONDON_RE.search(seg):
                return True
        elif UK_COUNTRY_RE.search(seg) or UK_CITY_RE.search(seg):
            return True
    return False


# --------------------------------------------------------------------------
# Skill dictionary: name -> (category, regex). Case-insensitive unless the
# pattern is compiled with flags=0 (see CASE_SENSITIVE).
# --------------------------------------------------------------------------

SKILLS: dict[str, tuple[str, str]] = {
    # Programming languages
    "Python": ("Language", r"\bpython\b"),
    "R": ("Language", r"(?<![\w&/.'-])R(?![\w&/'-])"),  # case-sensitive, not R&D
    "SQL": ("Language", r"\bsql\b|\bpostgres(?:ql)?\b|\bmysql\b|\bt-sql\b"),
    "Scala": ("Language", r"\bscala\b"),
    "Java": ("Language", r"\bjava\b(?!\s*script)"),
    "C++": ("Language", r"\bc\+\+"),
    "SAS": ("Language", r"\bSAS\b"),  # case-sensitive
    "MATLAB": ("Language", r"\bmatlab\b"),
    # Python data / ML libraries
    "pandas": ("Library", r"\bpandas\b"),
    "NumPy": ("Library", r"\bnumpy\b"),
    "scikit-learn": ("Library", r"\bscikit[- ]?learn\b|\bsklearn\b"),
    "PyTorch": ("Library", r"\bpytorch\b|\btorch\b"),
    "TensorFlow": ("Library", r"\btensorflow\b"),
    "Keras": ("Library", r"\bkeras\b"),
    "XGBoost / LightGBM": ("Library", r"\bxgboost\b|\blightgbm\b|\bcatboost\b"),
    "SciPy / statsmodels": ("Library", r"\bscipy\b|\bstatsmodels\b"),
    "Hugging Face": ("Library", r"\bhugging\s?face\b"),
    # Methods
    "Machine learning": ("Method", r"\bmachine[- ]learning\b|\bML\b"),
    "Statistics": ("Method", r"\bstatistic(?:s|al)\b"),
    "Deep learning": ("Method", r"\bdeep[- ]learning\b|\bneural\s+net"),
    "NLP": ("Method", r"\bNLP\b|\bnatural\s+language\s+processing\b"),
    "Computer vision": ("Method", r"\bcomputer\s+vision\b"),
    "A/B testing & experimentation": ("Method", r"\ba/b\s*test|\bab\s+test|\bexperiment(?:s|ation|al design)\b"),
    "Causal inference": ("Method", r"\bcausal\b|\buplift\s+model"),
    "Time series / forecasting": ("Method", r"\btime[- ]series\b|\bforecast"),
    "Bayesian methods": ("Method", r"\bbayesian\b"),
    "Regression": ("Method", r"\bregression\b"),
    "Predictive modelling": ("Method", r"\bpredictive\s+(?:model|analytic)"),
    "Recommender systems": ("Method", r"\brecommend(?:er|ation)\s+(?:system|engine)"),
    "Optimisation": ("Method", r"\boptimi[sz]ation\b"),
    "Feature engineering": ("Method", r"\bfeature\s+engineering\b"),
    "Hypothesis testing": ("Method", r"\bhypothesis\s+test|\bstatistical\s+significance\b"),
    # Generative AI
    "LLMs": ("GenAI", r"\bLLMs?\b|\blarge\s+language\s+models?\b"),
    "Generative AI": ("GenAI", r"\bgenerative\s+ai\b|\bgen\s?ai\b"),
    "RAG": ("GenAI", r"\bRAG\b|\bretrieval[- ]augmented\b"),
    "Prompt engineering": ("GenAI", r"\bprompt\s+engineering\b"),
    # Data engineering / big data
    "Spark": ("Data eng", r"\bspark\b|\bpyspark\b"),
    "Databricks": ("Data eng", r"\bdatabricks\b"),
    "Snowflake": ("Data eng", r"\bsnowflake\b"),
    "BigQuery": ("Data eng", r"\bbig\s?query\b"),
    "Airflow": ("Data eng", r"\bairflow\b"),
    "dbt": ("Data eng", r"\bdbt\b"),
    "Kafka": ("Data eng", r"\bkafka\b"),
    "Hadoop": ("Data eng", r"\bhadoop\b|\bhive\b"),
    "ETL / data pipelines": ("Data eng", r"\bETL\b|\bELT\b|\bdata\s+pipelines?\b"),
    # Cloud
    "AWS": ("Cloud", r"\bAWS\b|\bamazon\s+web\s+services\b|\bsagemaker\b"),
    "Azure": ("Cloud", r"\bazure\b"),
    "GCP": ("Cloud", r"\bGCP\b|\bgoogle\s+cloud\b|\bvertex\s+ai\b"),
    # MLOps / engineering practice
    "Git": ("MLOps", r"\bgit\b|\bgithub\b|\bgitlab\b|\bversion\s+control\b"),
    "Docker": ("MLOps", r"\bdocker\b|\bcontaineri[sz]"),
    "Kubernetes": ("MLOps", r"\bkubernetes\b|\bk8s\b"),
    "MLflow": ("MLOps", r"\bmlflow\b"),
    "MLOps": ("MLOps", r"\bmlops\b"),
    "CI/CD": ("MLOps", r"\bci\s*/\s*cd\b"),
    "Model deployment / production": ("MLOps", r"\bdeploy(?:ing|ment)?\b.{0,40}\bmodels?\b|\bmodels?\b.{0,40}\bproduction\b"),
    "APIs": ("MLOps", r"\bAPIs?\b|\bfastapi\b|\bflask\b"),
    "Linux": ("MLOps", r"\blinux\b|\bbash\b"),
    # Visualisation / BI
    "Data visualisation": ("Viz/BI", r"\bdata\s+visuali[sz]ation\b|\bmatplotlib\b|\bseaborn\b|\bplotly\b|\bggplot"),
    "Tableau": ("Viz/BI", r"\btableau\b"),
    "Power BI": ("Viz/BI", r"\bpower\s?bi\b"),
    "Looker": ("Viz/BI", r"\blooker\b"),
    "Excel": ("Viz/BI", r"\bexcel\b"),
    "Dashboards": ("Viz/BI", r"\bdashboards?\b"),
    # Professional skills
    "Communication": ("Professional", r"\bcommunicat(?:e|ion|ing|or)\b"),
    "Stakeholder management": ("Professional", r"\bstakeholders?\b"),
    "Problem solving": ("Professional", r"\bproblem[- ]solv"),
    "Storytelling": ("Professional", r"\bstorytelling\b|\bdata\s+stor"),
    "Collaboration / teamwork": ("Professional", r"\bcollaborat|\bteam\s?work"),
    "Agile": ("Professional", r"\bagile\b|\bscrum\b"),
    # Education
    "PhD": ("Education", r"\bPhD\b|\bdoctorate\b|\bdoctoral\b"),
    "Master's degree": ("Education", r"\bmaster'?s\b|\bMSc\b"),
    "Quantitative degree (STEM)": ("Education", r"\bSTEM\b|\bmathematic|\bphysics\b|\bcomputer\s+science\b|\bquantitative\s+(?:degree|field|discipline|subject)"),
}

CASE_SENSITIVE = {"R", "SAS", "Machine learning", "NLP", "LLMs", "RAG", "AWS", "GCP",
                  "ETL / data pipelines", "APIs", "PhD", "Master's degree",
                  "Quantitative degree (STEM)"}


def _compile(name: str, pattern: str) -> re.Pattern:
    if name in CASE_SENSITIVE:
        # Case-sensitive for acronyms, but let the long-form alternatives
        # (e.g. "machine learning") match in any case via inline (?i:...).
        parts = pattern.split("|")
        fixed = []
        for p in parts:
            letters = re.sub(r"\\[a-z]|[^A-Za-z]", "", p)
            is_acronym = letters.isupper() or name in {"R", "SAS"}
            fixed.append(p if is_acronym else f"(?i:{p})")
        return re.compile("|".join(fixed))
    return re.compile(pattern, re.I)


SKILL_REGEX = {name: _compile(name, pat) for name, (_, pat) in SKILLS.items()}
SKILL_CATEGORY = {name: cat for name, (cat, _) in SKILLS.items()}

YEARS_RE = re.compile(r"(\d{1,2})(?:\s*(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*years?", re.I)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def clean_text(raw: str | None) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not raw:
        return ""
    text = re.sub(r"<(br|/p|/li|/div|/h\d)\s*/?>", "\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def extract_skills(text: str) -> set[str]:
    """Return the set of skills mentioned at least once (each counted once)."""
    return {name for name, rx in SKILL_REGEX.items() if rx.search(text)}


def max_years_required(text: str) -> int | None:
    """Largest 'N years' figure in the text (rough experience signal)."""
    nums = [int(g) for m in YEARS_RE.finditer(text) for g in m.groups() if g and int(g) <= 20]
    return max(nums) if nums else None


def fingerprint(employer: str, title: str, text: str) -> str:
    """Catch the same ad reposted (often by several agencies)."""
    body = re.sub(r"[^a-z0-9]+", " ", text.lower())[:600]
    return hashlib.md5(body.encode()).hexdigest()


# --------------------------------------------------------------------------
# Reed API
# --------------------------------------------------------------------------


class Reed:
    def __init__(self, api_key: str, pause: float = 0.6):
        self.s = requests.Session()
        self.s.auth = (api_key, "")  # key as username, empty password
        self.pause = pause

    def _get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(5):
            r = self.s.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 5 * (attempt + 1)
                print(f"  server said {r.status_code}, waiting {wait}s ...")
                time.sleep(wait)
                continue
            if r.status_code == 401:
                sys.exit("Reed rejected the API key (401). Check REED_API_KEY.")
            r.raise_for_status()
            time.sleep(self.pause)
            return r.json()
        r.raise_for_status()
        return {}

    def search(self, keywords: str, location: str, distance: int, max_results: int) -> list[dict]:
        out, skip = [], 0
        while skip < max_results:
            params = {"keywords": keywords, "resultsToTake": 100, "resultsToSkip": skip}
            if location and location.lower() not in ("uk", "united kingdom"):
                params.update(locationName=location, distanceFromLocation=distance)
            data = self._get(f"{API_BASE}/search", params)
            batch = data.get("results", []) or []
            total = data.get("totalResults", 0)
            out.extend(batch)
            print(f"  '{keywords}': {len(out)} / {total} fetched")
            if not batch or len(out) >= total:
                break
            skip += 100
        return out

    def details(self, job_id: int, cache_dir: Path) -> dict:
        path = cache_dir / f"{job_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        data = self._get(f"{API_BASE}/jobs/{job_id}")
        path.write_text(json.dumps(data))
        return data


# --------------------------------------------------------------------------
# Analysis + chart (works on already-fetched records, so it can be tested)
# --------------------------------------------------------------------------


def analyse(records: list[dict], out_dir: Path, top: int, days: int, today: datetime,
            source: str = "Reed.co.uk", region: str = "London") -> dict:
    import pandas as pd

    # Deduplicate reposts.
    seen, unique = set(), []
    for rec in records:
        fp = fingerprint(rec["employer"], rec["title"], rec["text"])
        if fp in seen:
            continue
        seen.add(fp)
        unique.append(rec)

    rows, matrix = [], []
    counter: Counter = Counter()
    for rec in unique:
        skills = extract_skills(rec["text"])
        counter.update(skills)
        rows.append({
            "job_id": rec["job_id"],
            "title": rec["title"],
            "employer": rec["employer"],
            "location": rec["location"],
            "date_posted": rec["date"].strftime("%Y-%m-%d") if rec["date"] else "",
            "min_salary": rec.get("min_salary"),
            "max_salary": rec.get("max_salary"),
            "max_years_mentioned": max_years_required(rec["text"]),
            "n_skills": len(skills),
            "skills": "; ".join(sorted(skills)),
            "url": rec.get("url", ""),
            "source": rec.get("source", source),
        })
        matrix.append({"job_id": rec["job_id"], **{k: int(k in skills) for k in SKILLS}})

    n = len(unique)
    jobs = pd.DataFrame(rows)
    jobs.to_csv(out_dir / "jobs.csv", index=False)
    pd.DataFrame(matrix).to_csv(out_dir / "job_skill_matrix.csv", index=False)

    freq = pd.DataFrame(
        [{"skill": k, "category": SKILL_CATEGORY[k], "n_jobs": v,
          "pct_jobs": round(100 * v / n, 1) if n else 0.0}
         for k, v in counter.items()]
    ).sort_values(["n_jobs", "skill"], ascending=[False, True])
    freq.to_csv(out_dir / "skills_frequency.csv", index=False)

    dates = [r["date"] for r in unique if r["date"]]
    span = (f"{min(dates):%d %b} – {max(dates):%d %b %Y}" if dates
            else f"last {days} days to {today:%d %b %Y}")
    plot(freq.head(top), n, span, out_dir / "skills_frequency.png", source, region)

    return {"unique_jobs": n, "duplicates_removed": len(records) - n,
            "jobs_with_5plus_years": int((jobs["max_years_mentioned"].fillna(0) >= 5).sum()) if n else 0}


def plot(freq, n_jobs: int, span: str, path: Path, source: str = "Reed.co.uk",
         region: str = "London") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    surface, ink, ink2, grid, bar = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#2a78d6"

    data = freq.iloc[::-1]  # largest at the top
    h = max(4.0, 0.32 * len(data) + 1.6)
    fig, ax = plt.subplots(figsize=(9, h), dpi=200)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)

    y = range(len(data))
    bars = ax.barh(list(y), data["pct_jobs"], height=0.62, color=bar, zorder=2)
    for b, pct, cnt in zip(bars, data["pct_jobs"], data["n_jobs"]):
        ax.text(b.get_width() + 0.8, b.get_y() + b.get_height() / 2,
                f"{pct:.0f}%  ({cnt})", va="center", ha="left", fontsize=8, color=ink2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(data["skill"], fontsize=9, color=ink)
    ax.set_xlim(0, data["pct_jobs"].max() * 1.15 + 6)  # room for the value labels
    ax.set_xticks([t for t in range(0, 101, 20) if t <= data["pct_jobs"].max() + 5])
    ax.set_xlabel("Share of job ads mentioning the skill (%)", fontsize=9, color=ink2)
    ax.xaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
    ax.tick_params(axis="both", length=0, colors=ink2, labelsize=8)
    ax.tick_params(axis="y", labelcolor=ink)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)

    top_in = 0.95 if h < 8 else 0.97
    fig.tight_layout(rect=(0, 0, 1, top_in - 0.02))
    fig.text(0.01, 1 - 0.18 / h, f"Skills requested in {region} data-scientist job ads (mid-level and below)",
             ha="left", va="top", fontsize=12, fontweight="bold", color=ink)
    fig.text(0.01, 1 - 0.48 / h, f"{n_jobs} unique ads ({source}), posted {span}. "
             "Each skill counted once per ad.", ha="left", va="top", fontsize=9, color=ink2)
    fig.subplots_adjust(top=1 - 0.8 / h)
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-key", default=os.environ.get("REED_API_KEY"))
    ap.add_argument("--location", default="London", help='"UK" searches the whole country')
    ap.add_argument("--distance", type=int, default=10, help="miles from location")
    ap.add_argument("--days", type=int, default=30, help="keep ads posted in the last N days")
    ap.add_argument("--keywords", nargs="+",
                    default=["data scientist", "junior data scientist", "graduate data scientist"])
    ap.add_argument("--max-results", type=int, default=3000, help="per keyword")
    ap.add_argument("--top", type=int, default=35, help="skills shown in the chart")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit('No API key. Run:  export REED_API_KEY="your-key"  then try again.')

    out_dir = Path(args.out)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    reed = Reed(args.api_key)
    today = datetime.now()
    cutoff = today - timedelta(days=args.days)

    print("1) Searching Reed ...")
    hits: dict[int, dict] = {}
    for kw in args.keywords:
        for job in reed.search(kw, args.location, args.distance, args.max_results):
            hits.setdefault(job["jobId"], job)
    (out_dir / "search_results.json").write_text(json.dumps(list(hits.values()), indent=1))

    log = Counter(search_hits=len(hits))
    shortlisted = []
    for job in hits.values():
        posted = parse_date(job.get("date"))
        title = job.get("jobTitle", "")
        if posted is None or posted < cutoff:
            log["dropped_too_old_or_undated"] += 1
        elif not TITLE_INCLUDE.search(title):
            log["dropped_not_data_scientist_title"] += 1
        elif TITLE_EXCLUDE.search(title):
            log["dropped_senior_title"] += 1
        else:
            shortlisted.append((job, posted))
    print(f"2) {len(shortlisted)} ads pass date + title filters. Fetching full descriptions ...")

    records = []
    for i, (job, posted) in enumerate(shortlisted, 1):
        d = reed.details(job["jobId"], cache_dir)
        text = clean_text(d.get("jobDescription") or job.get("jobDescription"))
        records.append({
            "job_id": job["jobId"],
            "title": job.get("jobTitle", ""),
            "employer": job.get("employerName", ""),
            "location": job.get("locationName", ""),
            "date": parse_date(d.get("datePosted")) or posted,
            "min_salary": job.get("minimumSalary"),
            "max_salary": job.get("maximumSalary"),
            "url": job.get("jobUrl", ""),
            "text": text,
        })
        if i % 25 == 0:
            print(f"   {i}/{len(shortlisted)}")

    print("3) Extracting skills and drawing the chart ...")
    region = "UK" if args.location.lower() in ("uk", "united kingdom") else args.location
    stats = analyse(records, out_dir, args.top, args.days, today, region=region)
    log.update(stats)

    summary = "\n".join(f"  {k:34s} {v}" for k, v in log.items())
    (out_dir / "run_summary.txt").write_text(summary + "\n")
    print("\nSummary\n" + summary)
    print(f"\nDone. Open {out_dir/'skills_frequency.png'} and {out_dir/'skills_frequency.csv'}")


if __name__ == "__main__":
    main()
