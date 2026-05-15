---
name: skill_feature_engineer
description: >
  Use this skill to compute 25 derived features from a seller's raw monthly
  scorecard data. Produces ratios, MoM trend vectors, BD recency, and
  communication health flags needed by the churn scorer.
  Trigger when the user asks: "compute features for seller", "derive features",
  "feature engineering", "calculate ratios", "compute monthly trends",
  "prepare seller data for scoring", "build feature vector".
---

# Feature Engineering Skill

Transforms raw scorecard attributes (219 fields × 4 months) into 25 derived
signals used by `skill_churn_scorer`.

## Critical: May Normalization

May data (year_month=202605) is partial — only 14 days elapsed. Normalize FIRST:

```python
DAYS_ELAPSED = {"202602": 28, "202603": 31, "202604": 30, "202605": 14}

def normalize(value: float, year_month: str) -> float:
    return value * (30 / DAYS_ELAPSED.get(year_month, 30))
```

Apply `normalize()` to any time-series field before computing MoM deltas.

## Feature Computation

```python
def engineer_features(seller_months: list[dict]) -> dict:
    latest = seller_months[-1]
    prev   = seller_months[-2] if len(seller_months) > 1 else latest

    def n(val, ym): return normalize(val, ym)

    return {
        # ── BL Value ────────────────────────────────────────────────────────
        "bl_lapse_rate":          latest['bl_credit_lapsed'] / max(latest['bl_credits_alctd'], 1),
        "bl_util_rate":           latest['bl_cons'] / max(latest['bl_credits_alctd'], 1),
        "blni_rate":              latest['blni'] / max(latest['bl_cons'], 1),
        "slow_response_rate":     latest['cons_grter_1day'] / max(latest['bl_cons'], 1),
        "bl_cons_mom":            (n(latest['bl_cons'], latest['year_month']) -
                                   n(prev['bl_cons'], prev['year_month'])) / max(n(prev['bl_cons'], prev['year_month']), 1),

        # ── Engagement ──────────────────────────────────────────────────────
        "reply_rate":             latest['replies'] / max(latest['total_enq'], 1),
        "replies_mom":            n(latest['replies'], latest['year_month']) -
                                  n(prev['replies'],   prev['year_month']),
        "email_open_rate":        latest['emails_opened'] / max(latest['emails_sent'], 1),
        "notif_loss_rate":        latest['undelivered_notifications'] / max(latest['total_notifications'], 1),
        "hide_rate":              latest['total_hide'] / max(latest['total_enq'], 1),

        # ── BD Reach ────────────────────────────────────────────────────────
        "bd_unreached":           1 if latest['succ_connect_bd'] == 0 else 0,
        "days_since_bd_call":     compute_days_since(latest.get('last_succ_bd_call_dt')),
        "days_since_bl_cons":     compute_days_since(latest.get('last_cons_date')),

        # ── Communication Health ─────────────────────────────────────────────
        "email_dead":             1 if (latest['emails_sent'] > 5 and latest['emails_opened'] == 0) else 0,
        "notif_unreachable":      1 if (latest['undelivered_notifications'] /
                                        max(latest['total_notifications'], 1)) > 0.8 else 0,

        # ── Business Outcomes ───────────────────────────────────────────────
        "connect_rate":           latest['success_connect'] / max(latest['total_enq'], 1),
        "pns_answer_rate":        latest['pns_success_prcnt'] / 100,

        # ── Catalog ─────────────────────────────────────────────────────────
        "catalog_score_delta":    latest['catalog_score'] - prev['catalog_score'],
        "product_net_change":     latest['prd_added'] - latest['deactivated_prd'],
        "neg_cat_pct":            latest['prd_neg_cat'] / max(latest['live_prd_cnt'], 1),

        # ── Trend Momentum ──────────────────────────────────────────────────
        "consecutive_lapse_increase": compute_lapse_trend(seller_months),
        "replies_3m_slope":           compute_slope([n(m['replies'], m['year_month']) for m in seller_months]),
        "lms_3m_slope":               compute_slope([m['lms_active_days'] for m in seller_months]),

        # ── Composite (populated later by rule_check_node) ──────────────────
        "red_flag_count": 0,
    }
```

## Helper Functions

```python
from datetime import datetime, date

def compute_days_since(date_str: str | None) -> int:
    if not date_str or str(date_str) in ('nan', 'None', ''):
        return 999
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        return (date.today() - dt).days
    except Exception:
        return 999

def compute_lapse_trend(seller_months: list[dict]) -> int:
    """Count consecutive months where lapse rate increased."""
    rates = [m['bl_credit_lapsed'] / max(m['bl_credits_alctd'], 1) for m in seller_months]
    count = 0
    for i in range(1, len(rates)):
        if rates[i] > rates[i-1]:
            count += 1
        else:
            break
    return count

def compute_slope(values: list[float]) -> float:
    """Linear regression slope over the series."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(values) / n
    num   = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
    denom = sum((xi - x_mean) ** 2 for xi in x)
    return num / denom if denom != 0 else 0.0
```

## Output

Returns a flat dict of 25 float/int features ready to pass into `skill_churn_scorer`.
All values are normalized; `red_flag_count` will be filled by `skill_rule_checker`.
