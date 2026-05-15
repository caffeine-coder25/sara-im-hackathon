---
name: skill_churn_scorer
description: >
  Use this skill to score a seller's churn risk from 0–100, explain the top 3
  risk factors in plain English, and generate a recommended action with urgency.
  Trigger when the user asks: "score seller", "churn risk for", "who is at risk",
  "check seller health", "why might seller not renew", "rank BD call list",
  "who should we call today", "seller going dark", "retention priority",
  "seller health check", "at risk sellers", "run churn scoring".
---

# Seller Churn Scorer Skill

You score IndiaMart sellers on a 0–100 churn risk scale using behavioral signals —
NOT catalog quality. The key insight: `replies` has a 19× gap between churning and
healthy sellers. Catalog quality (cqs, catalog_score) shows almost no difference.

## Scoring Logic — 5 Weighted Dimensions

| Dimension | Weight | Primary Signal |
|-----------|--------|---------------|
| Platform Engagement | **40 pts** | `replies`, `lms_active_days`, email open rate |
| BL Value ROI | **30 pts** | `bl_credit_lapsed / bl_credits_alctd` (lapse rate) |
| BD Coverage | **15 pts** | `succ_connect_bd`, `success_bd_calls` |
| Business Outcomes | **10 pts** | `success_connect`, `pns_success_prcnt` |
| Catalog / PNS | **5 pts** | `catalog_score`, `defaulter_flag` |

### May Data Normalization (CRITICAL)
May data is partial — only 14 days elapsed as of the batch date.
Always normalize: `value × (30 / 14)` for May (`year_month = "202605"`).

```python
DAYS_ELAPSED = {"202602": 28, "202603": 31, "202604": 30, "202605": 14}
def normalize(value, year_month):
    return value * (30 / DAYS_ELAPSED.get(year_month, 30))
```

### Dimension 1: Platform Engagement (max 40 pts)
```python
replies_now  = normalize(latest['replies'], latest['year_month'])
replies_prev = normalize(prev['replies'],   prev['year_month'])
eng = 0
if replies_now == 0:                                        eng += 20
elif replies_now < 10:                                      eng += 12
elif replies_prev > 0 and replies_now < replies_prev * 0.5: eng += 8
if latest['lms_active_days'] == 0:                          eng += 10
elif latest['lms_active_days'] < 3:                         eng += 5
email_open_rate = latest['emails_opened'] / max(latest['emails_sent'], 1)
if email_open_rate == 0 and latest['emails_sent'] > 5:      eng += 10
```

### Dimension 2: BL Value ROI (max 30 pts)
```python
lapse_rate = latest['bl_credit_lapsed'] / max(latest['bl_credits_alctd'], 1)
util_rate  = latest['bl_cons'] / max(latest['bl_credits_alctd'], 1)
roi = 0
if lapse_rate > 0.8:   roi += 20
elif lapse_rate > 0.5: roi += 12
elif lapse_rate > 0.2: roi += 5
if util_rate < 0.3:    roi += 10
bl_now  = normalize(latest['bl_cons'], latest['year_month'])
bl_prev = normalize(prev['bl_cons'],   prev['year_month'])
if bl_prev > 0 and bl_now < bl_prev * 0.5: roi += 10
```

### Dimension 3: BD Coverage (max 15 pts)
```python
bd = 0
if latest['succ_connect_bd']  == 0: bd += 10
if latest['success_bd_calls'] == 0: bd += 5
```

### Dimension 4: Business Outcomes (max 10 pts)
```python
biz = 0
if latest['success_connect']   == 0: biz += 5
if latest['success_calls']     == 0: biz += 3
if latest['pns_success_prcnt'] == 0: biz += 2
```

### Dimension 5: Catalog + PNS (max 5 pts)
```python
cat = 0
if latest['catalog_score'] < 40:      cat += 3
if latest['defaulter_flag'] == 'yes': cat += 2
```

### Trend Bonus (up to +15 pts)
```python
trend_bonus = 0
for m in seller_months[-3:]:
    if normalize(m['replies'], m['year_month']) < 5: trend_bonus += 3
prev_lapse = normalize(prev['bl_credit_lapsed'], prev['year_month']) / max(prev['bl_credits_alctd'], 1)
if lapse_rate > prev_lapse: trend_bonus += 5  # accelerating lapse
```

Final: `churn_score = min(100, eng + roi + bd + biz + cat + trend_bonus)`

## Risk Bands and Actions

| Score | Band | Emoji | Action | SLA |
|-------|------|-------|--------|-----|
| 85–100 | BLACK | ⚫ | IVR rescue call | Same day, within 15 min of batch |
| 70–84 | RED | 🔴 | BD CRM task P1 | Call within 1 hr, WA within 2 hrs |
| 50–69 | ORANGE | 🟠 | WhatsApp first | WA within 2 hrs, call within 48 hrs |
| 25–49 | AMBER | 🟡 | WhatsApp nudge | WA this session |
| 0–24 | GREEN | 🟢 | Monitor only | No action |

## Output Format

Always return structured JSON:
```json
{
  "seller_id": "264768627",
  "churn_score": 97,
  "risk_band": "BLACK",
  "top_risk_factors": [
    "Replies collapsed from 45 to 0 over last 2 months — completely stopped engaging with leads",
    "97% of BL credits lapsed this month — 33 credits allocated, 32 expired unused",
    "No BD contact in 60+ days despite critical signals"
  ],
  "recommended_action": {
    "type": "IVR_TRIGGERED",
    "urgency": "same_day"
  },
  "dimensions": {
    "engagement": 38,
    "roi": 28,
    "bd_coverage": 15,
    "biz_outcomes": 8,
    "catalog": 3
  }
}
```

## How to Use This Skill

When invoked, ask for the `seller_id` if not provided. Load their 4-month data,
run `compute_churn_score()` from `scripts/score.py`, then:

1. Explain the score in one paragraph — WHY this seller specifically
2. Rank top 3 signals by importance for THIS seller's context
3. State the recommended action with SLA
4. If score ≥ 60, add 2–3 BD talking points that don't sound algorithmic

**Never mention "churn score" to the seller** — use language like "engagement trends"
or "account activity."

## LLM Integration

Use the IndiaMart LLM Gateway for natural-language explanation:
```python
from openai import OpenAI
client = OpenAI(api_key="sk-ZMOQS2onmuyv6-bFyigELw", base_url="https://imllm.intermesh.net/v1")
response = client.chat.completions.create(
    model="openrouter/qwen/qwen3-32b",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=600,
)
```
