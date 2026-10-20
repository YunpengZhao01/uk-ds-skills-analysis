# What do UK employers want from a Data Scientist?

I am moving into data science from astrophysics research. Before choosing what to learn next, I wanted evidence rather than guesswork, so I collected recent UK job ads for entry- and mid-level **Data Scientist** roles and measured how often each skill is requested.

![Skills requested in UK data-scientist job ads](output_combined_uk/skills_frequency.png)

## Key findings (UK, ads posted 21 Sep – 20 Oct 2026, 37 unique ads)

| Skill | Share of ads |
|---|---|
| Python | 95% |
| Machine learning | 78% |
| SQL | 78% |
| Stakeholder management | 73% |
| Communication / collaboration | 68% |
| Statistics | 57% |
| Time series / forecasting | 41% |
| Predictive modelling | 35% |
| A/B testing & experimentation | 27% |
| Model deployment / production | 27% |
| AWS / Azure | 22% each |

What this means in practice:

- **Python, SQL and machine learning are the baseline.** Almost every ad asks for them.
- **Soft skills appear in about 70% of ads.** Employers want people who can explain results to non-technical stakeholders, not only build models.
- **Statistics, forecasting and experimentation set candidates apart.** More than half the ads ask for statistics, and roughly a third ask for time series or A/B testing.
- **Cloud and MLOps are nice-to-haves at this level.** Each appears in about a quarter of ads or fewer.
- **Senior roles dominate the listings.** About 40% of Data Scientist titles were senior and were excluded (see `run_summary.txt`).

The London-only results are in `output_combined/`. Python (95%), machine learning, SQL and teamwork lead there too, from 20 unique ads.

## How it works

| Script | Source | Output (London / UK) |
|---|---|---|
| `reed_ds_skills.py` | [Reed.co.uk API](https://www.reed.co.uk/developers/jobseeker): mostly recruitment agencies; needs a free API key | `output/`, `output_uk/` |
| `ats_ds_skills.py` | Public Greenhouse, Lever and Ashby job boards of ~170 UK tech companies; no key needed | `output_ats/`, `output_ats_uk/` |
| `combine_ds_skills.py` | Merges both sources and removes duplicate reposts | `output_combined/`, `output_combined_uk/` |

Both sources use the same pipeline:

1. **Location:** keep London (or anywhere in the UK). Same-named places abroad, such as London, Ontario, are excluded.
2. **Title:** must contain "Data Scientist".
3. **Seniority:** drop titles containing Senior, Lead, Principal, Staff, Head, Manager, Director and similar.
4. **Recency:** keep ads first posted in the last 30 days.
5. **De-duplication:** remove reposts with the same job ID or the same description text.
6. **Skill extraction:** match about 70 skills from a regex dictionary (languages, libraries, methods, GenAI, data engineering, cloud, MLOps, BI, professional skills and education). A skill counts **once per ad**.

Each output folder contains:

- `skills_frequency.csv` and `skills_frequency.png`: skill frequencies
- `jobs.csv`: one row per ad kept, with salary and years of experience mentioned
- `job_skill_matrix.csv`: one-hot matrix of ads by skills, ready for further analysis
- `run_summary.txt`: how many ads each filter removed

## Set-up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # then add your Reed API key
export $(grep -v '^#' .env | xargs)   # or: export REED_API_KEY="..."
```

The key is read only from the `REED_API_KEY` environment variable (or the `--api-key` flag). It is never stored in the code.

## Run order

```bash
# London
python3 reed_ds_skills.py
python3 ats_ds_skills.py
python3 combine_ds_skills.py

# Whole UK
python3 reed_ds_skills.py --location UK --out output_uk
python3 ats_ds_skills.py  --region UK --out output_ats_uk
python3 combine_ds_skills.py --region UK --reed-dir output_uk \
    --ats-dir output_ats_uk --out output_combined_uk
```

Re-runs are cheap. Reed descriptions are cached in `output*/cache/`, and board lookups are cached in `boards.json`. The raw company-board dump (`all_jobs_raw.json`, about 36 MB) is not tracked in Git, so run `ats_ds_skills.py` before `combine_ds_skills.py` on a fresh clone.

## Limitations

- **Small sample:** 37 UK ads in a single 30-day window. Treat the percentages as indicative, not precise.
- **Agency-heavy:** one recruitment agency accounts for almost half of the Reed ads.
- **Keyword matching:** regexes miss paraphrases and can over-match. For example, "R" is matched case-sensitively and "R&D" is excluded.
- **Title filter:** "Data Scientist" only, so adjacent roles such as ML Engineer or Data Analyst are out of scope.

## Licence

MIT. Job-ad text belongs to the respective employers and job boards.
