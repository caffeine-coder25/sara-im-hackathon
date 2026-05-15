---
name: skill_data_loader
description: >
  Use this skill to load seller scorecard data from the API or Excel file,
  flatten the JSON structure, clean nulls, and apply partial-month normalization
  for May data. Outputs a structured list of monthly dicts ready for feature
  engineering.
  Trigger when the user asks: "load seller data", "fetch scorecard", "ingest data",
  "pull seller attributes", "load monthly data", "read seller from Excel",
  "prepare data for pipeline".
---

# Data Loader Skill

Loads raw scorecard data for one seller (or all 998) and normalizes partial months.

## Data Sources

**Primary:** Scorecard API (`SCORECARD_API_URL`) — 219 fields per seller per month
**Fallback:** `data/sellers_data_cleaned.xlsx` — static dataset for dev/hackathon

## Load from Excel (dev mode)

```python
import pandas as pd
from config import SELLERS_EXCEL, DAYS_ELAPSED

def load_seller_months(seller_id: str, df: pd.DataFrame = None) -> list[dict]:
    if df is None:
        df = pd.read_excel(SELLERS_EXCEL, dtype={'glusr_usr_id': str})

    rows = df[df['glusr_usr_id'] == seller_id].copy()
    if rows.empty:
        raise ValueError(f"Seller {seller_id} not found")

    months = []
    for _, row in rows.iterrows():
        ym = str(row.get('year_month', ''))
        d  = row.to_dict()
        d['year_month'] = ym
        months.append(d)

    # Sort chronologically
    months.sort(key=lambda x: x['year_month'])
    return months
```

## Load from Scorecard API

```python
import requests

def fetch_from_api(seller_id: str) -> list[dict]:
    resp = requests.get(
        f"{SCORECARD_API_URL}/seller/{seller_id}/monthly",
        headers={"X-Api-Key": SCORECARD_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["monthly_data"]
```

## Partial-Month Normalization

Apply after loading. Normalize any count field from May (202605):

```python
DAYS_ELAPSED = {"202602": 28, "202603": 31, "202604": 30, "202605": 14}

NORMALIZABLE_FIELDS = [
    "replies", "bl_cons", "bl_credit_lapsed", "total_enq",
    "success_connect", "emails_sent", "emails_opened",
    "undelivered_notifications", "total_notifications",
    "succ_connect_bd", "success_bd_calls",
]

def apply_normalization(months: list[dict]) -> list[dict]:
    for m in months:
        ym    = m.get("year_month", "")
        days  = DAYS_ELAPSED.get(ym)
        if days and days < 30:
            factor = 30 / days
            for field in NORMALIZABLE_FIELDS:
                if field in m and m[field] is not None:
                    m[field] = m[field] * factor
    return months
```

## Data Cleaning Flags

Set these flags for downstream nodes:

```python
def set_data_flags(months: list[dict]) -> dict:
    latest = months[-1]
    return {
        "email_dead":       latest['emails_sent'] > 5 and latest['emails_opened'] == 0,
        "mobile_missing":   not latest.get('mobile') or str(latest.get('mobile')) in ('nan','Unknown',''),
        "notif_unreachable": (latest.get('undelivered_notifications', 0) /
                              max(latest.get('total_notifications', 1), 1)) > 0.8,
    }
```

## Output

Returns `(months: list[dict], flags: dict)` where:
- `months` — 4-element list ordered Feb→May, all counts normalized
- `flags` — `{email_dead, mobile_missing, notif_unreachable}`

Used as input to `skill_feature_engineer`.
