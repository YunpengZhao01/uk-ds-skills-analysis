# UK Data Scientist skills analysis

Which skills do UK employers actually ask for in entry- and mid-level Data Scientist job ads? This project collects recent ads, filters out senior roles and counts how often each skill appears. A skill counts once per ad.

## Data sources

| Script | Source | Output (London / UK) |
|---|---|---|
| `reed_ds_skills.py` | Reed.co.uk API (mostly recruitment agencies; needs a free API key) | `output/`, `output_uk/` |
| `ats_ds_skills.py` | Public Greenhouse, Lever and Ashby job boards of ~170 UK tech companies (no key needed) | `output_ats/`, `output_ats_uk/` |
| `combine_ds_skills.py` | Merges both sources and de-duplicates reposted ads | `output_combined/`, `output_combined_uk/` |

Both sources use the same filters. An ad is kept if it is in London (or the UK), has "Data Scientist" in the title, has no senior keyword (Senior, Lead, Principal, Staff, Head, Manager…), and was posted in the last 30 days.

Each output folder contains:

- `skills_frequency.csv`: skill, category, number of ads and share of ads
- `skills_frequency.png`: bar chart of the top skills
- `jobs.csv`: one row per ad kept
- `job_skill_matrix.csv`: one-hot matrix of ads by skills
- `run_summary.txt`: how many ads each filter removed

## Set-up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your Reed key in .env
export $(grep -v '^#' .env | xargs)   # or: export REED_API_KEY="..."
```

The Reed key is read only from the `REED_API_KEY` environment variable (or the `--api-key` flag) and is never stored in the code.

## Run order

```bash
# London
python3 reed_ds_skills.py
python3 ats_ds_skills.py
python3 combine_ds_skills.py

# Whole UK
python3 reed_ds_skills.py --location UK --out output_uk
python3 ats_ds_skills.py --region UK --out output_ats_uk
python3 combine_ds_skills.py --region UK --reed-dir output_uk --ats-dir output_ats_uk --out output_combined_uk
```

Re-runs are cheap. Reed's full job descriptions are cached in `output*/cache/`, and the company-board lookups are cached in `boards.json`. The raw company-board dump (`all_jobs_raw.json`, about 36 MB) is not stored in Git, so run `ats_ds_skills.py` again before running `combine_ds_skills.py` on a fresh clone.

## Caveats

- Skills are matched with keyword regexes, so some matches will be wrong in both directions. For example, "R" is matched case-sensitively and "R&D" is excluded.
- Each run is a 30-day snapshot (October 2026). The sample is small, especially for London company boards.
