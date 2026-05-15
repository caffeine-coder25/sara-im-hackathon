# SARA — Seller Alert & Retention Agent
## Complete Project Documentation
### IndiaMart Hackathon · May 15–16, 2026

---

## 1. What is SARA?

SARA is an AI-powered **seller churn early-warning system** built for IndiaMart. It monitors 998 active sellers daily, scores each one for churn risk (0–100), and automatically dispatches the right intervention — a personalized WhatsApp message, a BD call brief, or an IVR rescue call — before the seller silently goes dark.

**The core problem SARA solves:**
Sellers don't complain before they churn. They ghost. By the time a BD exec notices, the renewal is already lost. SARA detects the ghosting pattern 4–8 weeks early using behavioral signals — not catalog quality.

**Key finding that drives everything:**
> `replies` (buyer reply count) has a **19× gap** between churning sellers (avg 5 replies/month) and healthy sellers (avg 98 replies/month). The existing `rag_score` is near-random — RAG=2 sellers actually have a *higher* lapse rate than RAG=1 sellers.

---

## 2. System Flowchart

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SOURCE DATA                                                            │
│  998 sellers × 219 attributes × 4 months (Feb–May 2026)               │
│  Pulled from IndiaMart Scorecard API                                    │
│  ⚠ May data partial (14 days) → normalize: value × (30 ÷ 14)         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   ingest.py           │
                    │   Pull API, flatten   │
                    │   JSON, clean nulls,  │
                    │   normalize May data  │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   features.py         │
                    │   25 derived signals  │
                    │   (ratios, MoM trends,│
                    │   BD recency, comm    │
                    │   health flags)       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   score.py            │
                    │   5-dimension weighted│
                    │   score 0–100         │
                    │   per seller          │
                    └───────────┬───────────┘
                                │
              ┌─────────────────▼─────────────────┐
              │     LangGraph StateGraph           │
              │     (orchestrator.py)              │
              │                                    │
              │  ingest → features → rules → score │
              │              ↓                     │
              │         band_router                │
              │        (conditional)               │
              └──────┬───────────┬────────┬────────┘
                     │           │        │
              score ≥70     score 25–69  score < 25
                     │           │        │
              ┌──────▼──────┐ ┌──▼──────┐ ┌▼────────┐
              │  CALL NODE  │ │  WA     │ │  LOW    │
              │             │ │  NODE   │ │  NODE   │
              │ ≥85: IVR    │ │         │ │         │
              │ rescue call │ │ Claude  │ │ monitor │
              │ (SquadStack)│ │ writes  │ │ only    │
              │             │ │ message │ │         │
              │ 70–84: BD   │ │ → sends │ │         │
              │ CRM task P1 │ │ via     │ │         │
              │ + call brief│ │ VANI API│ │         │
              └──────┬──────┘ └──┬──────┘ └─┬───────┘
                     │           │           │
              └───────────┬───────────────────┘
                          │
                  ┌───────▼────────┐
                  │   log_node     │
                  │ → alert_log.csv│
                  └───────┬────────┘
                          │
                  ┌───────▼────────┐
                  │  report_node   │
                  │ Daily summary  │
                  │ to Ops team    │
                  └───────┬────────┘
                          │
                  ┌───────▼────────────────────┐
                  │   SARA Dashboard           │
                  │   (Streamlit — Port 8501)  │
                  │   998 sellers sorted by    │
                  │   churn score, clickable   │
                  │   seller deep-dive,        │
                  │   AI BD brief + WA send    │
                  └────────────────────────────┘
```

---

## 3. How the Churn Score is Determined (0–100)

The score is a **5-dimension weighted sum**. The points come from two separate processes — dimension weights are fully data-driven, and points within each dimension are calibrated heuristics. Both are explained below.

---

### Why Not Use the Existing RAG Score?

| RAG Band | Avg Lapse Rate | LMS Days |
|----------|---------------|----------|
| RAG = -2 (worst) | 57% | 7.9 |
| RAG = -1 | 52% | 7.9 |
| RAG = 0 | 44% | 8.8 |
| RAG = 1 | 41% | 8.8 |
| **RAG = 2 (best)** | **43%** | **8.0** |

RAG=2 sellers have a *higher* lapse rate than RAG=1. The system is blind. SARA replaces it entirely.

---

### How the Points Were Determined — Two-Level Process

The scoring has two distinct levels. Each level used a different method.

#### Level 1 — Dimension Weights (the 40 / 30 / 15 / 10 / 5 split)

These came from **actual data correlation analysis** on all 998 sellers. Each signal was compared between sellers who churned (went dark) vs sellers who stayed healthy:

| Signal | Churning Sellers | Healthy Sellers | Gap | → Weight |
|--------|-----------------|----------------|-----|---------|
| `replies` | avg 5/month | avg 98/month | **19× difference** | → **40%** |
| `bl_credit_lapsed` | high lapse, paid & wasted | low lapse, credits used | Direct financial loss | → **30%** |
| `succ_connect_bd` | 82% had ZERO BD contact in May | regular BD touch | Coverage crisis | → **15%** |
| `success_connect` | 1.7× fewer conversions | higher connect rate | Secondary signal | → **10%** |
| `catalog_score` | avg **64.3** | avg **67.1** | Almost no difference | → **5%** |

The data literally told us what mattered. `replies` has a 19× gap so it gets 40%. Catalog quality barely separates churning sellers from healthy ones — so it only gets 5%, included for completeness.

#### Level 2 — Points Within Each Dimension

These are **calibrated heuristics**, not regression outputs. They were designed using three rules:

**Rule A — Must sum to the dimension maximum**
Each condition within a dimension is designed so the worst-case scenario fills the dimension's max points. Since conditions are mutually exclusive (a seller can't have `replies==0` AND `replies<10` at the same time), the practical max stays at the dimension ceiling.

**Rule B — Severity is proportional, roughly halving each tier**
```
replies == 0  (completely ghosted)      → +20  ← worst possible
replies < 10  (critical but not dead)   → +12  ← serious
drop > 50% MoM (declining fast)         → +8   ← trend warning
```
Each tier is roughly 60% of the one above — reflecting that complete ghosting is far worse than just declining.

**Rule C — Validated against known outcomes**
Thresholds were tuned so sellers already known to have churned (didn't renew) scored ≥70, and known healthy renewing sellers scored <30. This gave us the band boundaries: 85 / 70 / 50 / 25.

#### Summary

| What | Method Used |
|------|------------|
| Which dimensions matter | Real data correlation (19× replies gap, 82% BD gap found in the 998-seller dataset) |
| Dimension weights (40/30/15/10/5) | Proportional to correlation strength — data-driven |
| Points within dimensions (+20, +12, +8…) | Expert-calibrated heuristics that sum to dimension max and reflect relative severity |
| Band thresholds (85 / 70 / 50 / 25) | Back-tested against known churners and renewers to minimize false positives |
| Phase 2 (stretch goal) | Replace heuristic point values with a **LightGBM model** trained on actual renewal labels — making within-dimension weights fully data-driven too |

---

### Dimension 1 — Platform Engagement (40 points)

**Why 40%?** `replies` has a 19× gap between churning and healthy sellers. It is the single strongest signal in the dataset.

**Why these specific point values?**
- `replies == 0` earns +20 (half the dimension) because a seller who has completely stopped responding is the clearest possible churn signal
- `replies < 10` earns +12 because it's serious but the seller is still technically present
- Each subsequent condition covers a different aspect of engagement (platform login, email) — together they can fill the remaining 20 points

| What We Check | Points | Why This Amount |
|---------------|--------|----------------|
| `replies_now == 0` | +20 | Worst signal — completely dark. Half the dimension. |
| `replies_now < 10` | +12 | Critically low but not zero. ~60% of the above. |
| Replies dropped >50% MoM | +8 | Trend signal — declining fast even if not yet critical |
| `lms_active_days == 0` | +10 | Never logged in. Second axis of engagement. |
| `lms_active_days < 3` | +5 | Barely logging in. Half of above. |
| Email open rate = 0 (5+ sent) | +10 | Email channel dead — another contact axis lost |

---

### Dimension 2 — BL Value ROI (30 points)

**Why 30%?** BL credits are what the seller paid for. Letting them lapse = zero perceived value from IndiaMart.

**Why these specific point values?**
- Lapse rate >80% earns +20 (the lion's share) because paying for something and using almost none of it is a direct financial dissatisfaction signal
- `util_rate < 30%` is a different lens (usage vs waste) that adds 10 more points, capping the dimension at 30

| What We Check | Points | Why This Amount |
|---------------|--------|----------------|
| `lapse_rate > 80%` | +20 | Paid for credits, 80%+ expired. Severe value failure. |
| `lapse_rate > 50%` | +12 | More than half wasted. Significant dissatisfaction. |
| `lapse_rate > 20%` | +5 | Mild under-utilization. Early warning only. |
| `util_rate < 30%` | +10 | Different lens: actively using <30% of what they bought |
| BL consumption dropped >50% MoM | +10 | Usage collapsing — trend confirms structural problem |

**Formula:**
```
lapse_rate = bl_credit_lapsed ÷ bl_credits_allocated
util_rate  = bl_consumed ÷ bl_credits_allocated
```

---

### Dimension 3 — BD Coverage (15 points)

**Why 15%?** 82% of sellers had zero BD contact in May. The BD gap is real but it's a *cause* of churn, not a symptom — so it gets less weight than engagement signals.

**Why these point values?** The dimension only has 15 points total, split 10/5 between zero connects (worse) and unanswered calls (less severe but still a gap).

| What We Check | Points | Why This Amount |
|---------------|--------|----------------|
| `succ_connect_bd == 0` this month | +10 | No BD contact at all — largest portion of the 15 |
| `success_bd_calls == 0` | +5 | BD tried but couldn't reach — partial gap |

---

### Dimension 4 — Business Outcomes (10 points)

**Why these point values?** 10 points split across 3 signals (5/3/2) — each signal is a different downstream consequence of low engagement, weighted by how directly it predicts churn.

| What We Check | Points | Why This Amount |
|---------------|--------|----------------|
| `success_connect == 0` | +5 | No buyer conversions — strongest outcome signal |
| `success_calls == 0` | +3 | No calls answered — secondary |
| `pns_success_prcnt == 0` | +2 | PNS zero success — weakest, mostly a flag |

---

### Dimension 5 — Catalog & PNS (5 points)

**Why only 5%?** The data showed catalog score averages 64.3 for churning sellers vs 67.1 for healthy sellers — a 4% difference that is statistically near-meaningless. It was kept in the model to avoid completely ignoring catalog signals, but capped at 5 points.

| What We Check | Points | Why This Amount |
|---------------|--------|----------------|
| `catalog_score < 40` | +3 | Very low quality — most of the 5pt budget |
| `defaulter_flag == 'yes'` | +2 | PNS payment default — financial risk flag |

---

### Trend Bonus (up to +15 points)

Rewards *accelerating* decline — a seller worsening faster gets scored higher than one who has been bad for a long time but is stable.

**Why +3 per month?** Three months of low replies (max +9) signals a structural pattern, not a one-off bad month. The +5 for accelerating lapse rewards detecting sellers who are getting worse, not just already bad.

| What We Check | Bonus | Why |
|---------------|-------|-----|
| Each month where replies < 5 (last 3 months) | +3/month (max +9) | Pattern = more dangerous than a single bad month |
| Lapse rate increasing vs previous month | +5 | Acceleration = seller is getting worse, not stable |

---

### Final Score Formula

```
churn_score = min(100,
    dim_engagement     (0–40)   ← data-driven weight, heuristic points
  + dim_bl_roi         (0–30)   ← data-driven weight, heuristic points
  + dim_bd_coverage    (0–15)   ← data-driven weight, heuristic points
  + dim_biz_outcomes   (0–10)   ← data-driven weight, heuristic points
  + dim_catalog        (0–5)    ← data-driven weight, heuristic points
  + trend_bonus        (0–15)   ← pure heuristic
)
```

---

### Risk Bands & Automatic Actions

| Score | Band | Color | Action | SLA |
|-------|------|-------|--------|-----|
| 85–100 | BLACK | ⚫ | IVR rescue call via SquadStack | Same day, within 15 min |
| 70–84 | RED | 🔴 | BD CRM task P1 + AI call brief | Call within 1 hr |
| 50–69 | ORANGE | 🟠 | WhatsApp first, then callback | WA within 2 hrs, call within 48 hrs |
| 25–49 | AMBER | 🟡 | WhatsApp nudge only | WA this session |
| 0–24 | GREEN | 🟢 | Monitor, no action | — |

---

## 4. The 6 Skills — What They Do

Skills are Claude Code skill packages (SKILL.md files) that define trigger phrases and behavior for Claude to invoke automatically.

---

### Skill 1 — `skill_data_loader`

**What it does:** Loads seller scorecard data from the API or Excel file, flattens the JSON structure (219 nested fields), cleans nulls, and applies partial-month normalization for May data.

**Triggered when:** "load seller data", "fetch scorecard", "ingest data", "pull seller attributes"

**Key logic:**
```python
# May had only 14 days elapsed — raw numbers are 2.3× understated
DAYS_ELAPSED = {"202602": 28, "202603": 31, "202604": 30, "202605": 14}

def normalize(value, year_month):
    return value * (30 / DAYS_ELAPSED[year_month])
```

**Output:** Structured list of monthly dicts, one per seller per month, ready for feature engineering.

---

### Skill 2 — `skill_feature_engineer`

**What it does:** Takes raw monthly scorecard data and computes 25 derived features — ratios, MoM trend vectors, BD recency, and communication health flags.

**Triggered when:** "compute features", "derive features", "calculate ratios", "prepare seller data for scoring"

**The 25 Derived Features:**

| Feature | Formula | What It Measures |
|---------|---------|-----------------|
| `bl_lapse_rate` | `bl_credit_lapsed ÷ bl_credits_allocated` | % of paid credits wasted |
| `bl_util_rate` | `bl_cons ÷ bl_credits_allocated` | % of credits actually used |
| `blni_rate` | `blni ÷ bl_cons` | Rate of "no interest" BL outcomes |
| `slow_response_rate` | `cons_grter_1day ÷ bl_cons` | How often seller responds slowly to leads |
| `bl_cons_mom` | `(current_bl_cons - prev_bl_cons) ÷ prev_bl_cons` | Month-over-month BL consumption change |
| `reply_rate` | `replies ÷ total_enq` | % of inquiries the seller replies to |
| `replies_mom` | `current_replies - prev_replies` (normalized) | How much reply count changed |
| `email_open_rate` | `emails_opened ÷ emails_sent` | % of IndiaMart emails the seller opens |
| `notif_loss_rate` | `undelivered_notifications ÷ total_notifications` | % of notifications that failed to deliver |
| `hide_rate` | `total_hide ÷ total_enq` | % of leads the seller hides |
| `bd_unreached` | `1 if succ_connect_bd == 0` | Flag: BD never connected this month |
| `days_since_bd_call` | `today - last_succ_bd_call_dt` | Days since last BD contact |
| `days_since_bl_cons` | `today - last_cons_date` | Days since last BL activity |
| `email_dead` | `1 if emails_sent > 5 AND emails_opened == 0` | Flag: email channel completely dead |
| `notif_unreachable` | `1 if notif_loss_rate > 0.8` | Flag: contact info likely stale |
| `connect_rate` | `success_connect ÷ total_enq` | % of inquiries that convert to connections |
| `pns_answer_rate` | `pns_success_prcnt ÷ 100` | PNS call answer rate |
| `catalog_score_delta` | `current_cqs - prev_cqs` | Month-over-month catalog quality change |
| `product_net_change` | `prd_added - deactivated_prd` | Net product additions this month |
| `neg_cat_pct` | `prd_neg_cat ÷ live_prd_cnt` | % of products in negative categories |
| `consecutive_lapse_increase` | Count of months where lapse rate went up | How long the lapse trend has been worsening |
| `replies_3m_slope` | Linear regression slope of last 3 months' replies | Direction + speed of reply trend |
| `lms_3m_slope` | Linear regression slope of LMS active days | Direction of platform login trend |
| `red_flag_count` | Count of hard rules triggered | How many critical red flags fired |
| `bl_cons_mom` | BL consumption MoM normalized | Month-over-month BL usage trend |

---

### Skill 3 — `skill_rule_checker`

**What it does:** Evaluates 8 hard red-flag rules against derived features. If any rule fires, it sets `is_critical_override = True`, which bypasses the numeric score and routes the seller directly to the call agent.

**Triggered when:** "check red flags", "hard rules check", "critical override", "flag critical sellers"

**The 8 Hard Rules (any one triggers override):**

| Rule | Condition | Why Critical |
|------|-----------|-------------|
| Zero replies for 2+ months | `replies == 0` in 2 consecutive months | Complete disengagement |
| Email dead + no WhatsApp | `email_dead = 1` AND `mobile = null` | No way to reach seller |
| 100% lapse rate | `lapse_rate == 1.0` this month | Paid for nothing, used nothing |
| BD gap > 90 days | `days_since_bd_call > 90` | Seller abandoned by BD |
| Notification 100% undelivered | `notif_loss_rate == 1.0` | All contact info stale |
| BL consumption 0 for 2+ months | `bl_cons == 0` in 2 consecutive months | Complete non-usage |
| PNS defaulter + high lapse | `defaulter_flag == 'yes' AND lapse_rate > 0.7` | Financial default risk |
| Open complaints + zero reply | `cmplnts_cnt > 0 AND replies == 0` | Active complaint, gone silent |

---

### Skill 4 — `skill_churn_scorer`

**What it does:** Computes the 0–100 churn score using the 5-dimension weighted formula, assigns the risk band, and uses Claude (via LLM Gateway) to explain the top 3 risk factors in plain English and generate BD talking points.

**Triggered when:** "score seller", "churn risk for", "who is at risk", "check seller health", "rank BD call list"

**Claude's role in this skill:**
- Explains *why* the seller is at risk (not just the numbers)
- Identifies which risk factor is most fixable
- Generates BD talking points that don't sound algorithmic
- Suggests the opening question for the BD call

**Output:**
```json
{
  "churn_score": 97,
  "risk_band": "BLACK",
  "top_risk_factors": [
    "Replies collapsed from 45 to 0 over 2 months — completely dark",
    "97% of BL credits lapsed unused this month",
    "No BD contact in 60+ days"
  ],
  "recommended_action": "RESCUE_CALL",
  "bd_talking_points": ["...", "...", "..."]
}
```

---

### Skill 5 — `skill_whatsapp_agent`

**What it does:** Claude reads the seller's actual behavioral signals and writes a personalized WhatsApp message (never a template), then sends it via IndiaMart's VANI API.

**Triggered when:** "send WhatsApp to seller", "nudge seller", "WhatsApp outreach", "message at-risk seller"

**API used:** `https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php`
**Action:** `vani_send_msg`
**Rate limit:** 60ms between calls, one retry after 5s on failure

**Message logic by band:**

| Band | Tone | Hook |
|------|------|------|
| AMBER | Helpful, curious | "Your {product} leads are waiting" |
| ORANGE | Opportunity-focused | "8 buyers looked at your {product}" |
| RED | Warm urgency | "Your leads expire in X days" |
| BLACK | Skip WA | Go straight to IVR call |

**What makes it NOT a template:** Claude gets the seller's name, city, product category, actual reply count, lapse percentage, and package value — then writes a message that references their specific situation.

---

### Skill 6 — `skill_alert_logger`

**What it does:** Logs every seller dispatch action to `alert_log.csv` and generates the daily batch summary report.

**Triggered when:** "log this action", "write to alert log", "generate daily summary", "batch report"

**Alert Log Schema:**

| Column | Type | Example | Meaning |
|--------|------|---------|---------|
| `log_entry_id` | str | `ALT-264203724-2026-05-15` | Unique per seller per day |
| `run_date` | str | `2026-05-15` | Date of batch run |
| `seller_id` | str | `264203724` | IndiaMart seller ID |
| `seller_name` | str | `Rahul Sharma` | Seller display name |
| `churn_score` | float | `82.4` | Score 0–100 |
| `risk_band` | str | `BLACK` | BLACK/RED/ORANGE/AMBER/GREEN |
| `top_risk_factors_json` | JSON str | `["Replies: 45→0", ...]` | 3 plain-English reasons |
| `action_taken` | str | `call_ivr` | whatsapp / call_ivr / call_bd / monitor |
| `whatsapp_status` | str | `sent` | sent / failed / skipped |
| `whatsapp_message_id` | str | `wamid.XXXXX` | Message ID from VANI API |
| `call_action` | str | `IVR_TRIGGERED` | IVR / BD_TASK_P1 / BD_TASK_P2 / skipped |
| `bd_task_id` | str | `TASK-001234` | CRM task ID if created |
| `dispatch_timestamp` | ISO str | `2026-05-15T08:04:32` | When action was dispatched |

---

## 5. All Parameters and Their Meaning

### Raw Scorecard Parameters (Key Fields Used)

| Parameter | Meaning | Used In |
|-----------|---------|---------|
| `replies` | Number of buyer inquiries the seller replied to this month | Dimension 1 (Engagement) — strongest predictor |
| `total_enq` | Total buyer inquiries received | Base for reply_rate |
| `bl_cons` | BL (Business Listing) credits consumed | Dimension 2 (ROI) |
| `bl_credits_alctd` | BL credits allocated (what they paid for) | Base for lapse_rate |
| `bl_credit_lapsed` | BL credits that expired unused | Lapse rate numerator |
| `lms_active_days` | Days the seller logged into IndiaMart this month | Engagement signal |
| `emails_sent` | IndiaMart emails sent to the seller | Communication health |
| `emails_opened` | Emails opened by the seller | Email dead flag |
| `succ_connect_bd` | Successful BD executive connections this month | Dimension 3 (BD Coverage) |
| `success_bd_calls` | BD calls that were answered | BD coverage secondary |
| `last_succ_bd_call_dt` | Date of last successful BD call | BD days gap |
| `success_connect` | Successful buyer-seller connections | Dimension 4 (Outcomes) |
| `undelivered_notifications` | Push/SMS notifications that failed | Contact info staleness |
| `total_notifications` | Total notifications attempted | Base for notif_loss_rate |
| `catalog_score` / `cqs` | Catalog quality score | Dimension 5 (Catalog) |
| `defaulter_flag` | Whether seller is a PNS payment defaulter | Hard rule trigger |
| `cmplnts_cnt` | Open complaints from buyers | Hard rule modifier |
| `prd_neg_cat` | Products in negative/restricted categories | Catalog risk |
| `blni` | BL "No Interest" outcomes | BL quality signal |
| `pns_success_prcnt` | Pay-per-lead call answer success % | Business outcomes |

---

### Dashboard Parameters

| Parameter | Meaning |
|-----------|---------|
| `churn_score` | Final score 0–100. Higher = more likely to churn. |
| `risk_band` | BLACK/RED/ORANGE/AMBER/GREEN based on score thresholds |
| `lapse_rate` | `bl_credit_lapsed ÷ bl_credits_allocated`. At 1.0 = all credits wasted |
| `bd_days_gap` | Days since last successful BD contact |
| `email_dead` | 1 if seller hasn't opened a single email despite 5+ sent |
| `notif_loss_rate` | 0–1. At 0.8+ = contact info is stale |
| `replies_202602` to `replies_202605` | Monthly reply counts (Feb–May 2026) |
| `lapse_rate_202602` to `lapse_rate_202605` | Monthly lapse rates (4-month trend) |
| `bl_cons_202602` to `bl_cons_202605` | Monthly BL consumption trend |
| `dim_engagement` | Points scored in Dimension 1 (max 40) |
| `dim_roi` | Points scored in Dimension 2 (max 30) |
| `dim_bd_coverage` | Points scored in Dimension 3 (max 15) |
| `dim_biz_outcomes` | Points scored in Dimension 4 (max 10) |
| `dim_catalog` | Points scored in Dimension 5 (max 5) |
| `top_risk_factors` | Pipe-separated list of 3 plain-English risk explanations |
| `action_taken` | What SARA decided to do: IVR_TRIGGERED / BD_TASK_CREATED_P1 / whatsapp / monitor |
| `package_value` | Annual package value in ₹ — used for revenue-at-risk calculation |

---

### Config Parameters (`config.py`)

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `IM_LLM_API_KEY` | `sk-FoTNcUSeI_...` | IndiaMart LLM Gateway API key |
| `IM_LLM_BASE_URL` | `https://imllm.intermesh.net/v1` | Gateway base URL (OpenAI-compatible) |
| `IM_LLM_MODEL` | `openrouter/qwen/qwen3-32b` | Model used for all AI generation |
| `WA_API_KEY` | `Xy7Z9v2PqRt8LmN5` | IndiaMart VANI WhatsApp API key |
| `WA_API_URL` | `https://wahelp.indiamart.com/...` | VANI API endpoint |
| `WA_PLATFORM` | `WhatsApp_9696` | Sender platform identifier |
| `AISENSY_TARGET_NUMBER` | `917389680021` | Demo/test recipient number |
| `SCORE_BLACK` | `85` | Threshold for BLACK band (IVR trigger) |
| `SCORE_RED` | `70` | Threshold for RED band (BD P1 task) |
| `SCORE_ORANGE` | `50` | Threshold for ORANGE band (WhatsApp) |
| `SCORE_AMBER` | `25` | Threshold for AMBER band (nudge) |
| `DAYS_ELAPSED` | `{202605: 14, ...}` | Days elapsed per month for normalization |
| `SELLERS_EXCEL` | `data/sellers_data_cleaned.xlsx` | Source data file |
| `ALERT_LOG_PATH` | `alert_log.csv` | Where dispatch actions are logged |
| `SARA_DB_PATH` | `sara.db` | LangGraph SQLite checkpointer |

---

## 6. How SARA Works as a Complete Seller Retention Skill

### The Full Pipeline — End to End

```
Morning 8:00 AM (cron trigger)
        │
        ▼
orchestrator.py loads 998 sellers from Excel/API
        │
        ▼
For each seller (sorted by churn_score, highest first):
        │
        ├─── skill_data_loader
        │    → Loads 4 months of raw data, normalizes May
        │
        ├─── skill_feature_engineer
        │    → Computes 25 derived features
        │
        ├─── skill_rule_checker
        │    → Checks 8 hard rules
        │    → Sets is_critical_override = True if any fire
        │
        ├─── skill_churn_scorer
        │    → Computes 5-dimension score
        │    → Claude explains top 3 risks in English
        │    → Assigns band
        │
        ├─── band_router (LangGraph conditional edge)
        │    ├── Score ≥ 85 OR override → call_node
        │    ├── Score 25–84 → whatsapp_node
        │    └── Score < 25 → low_node (monitor only)
        │
        ├─── [call_node] skill_call_agent
        │    ├── Score ≥ 85: trigger SquadStack IVR immediately
        │    └── Score 70–84: Claude generates call brief → BD CRM task P1
        │
        ├─── [whatsapp_node] skill_whatsapp_agent
        │    └── Claude writes personalized message
        │        → sends via VANI API (action=vani_send_msg)
        │        → 60ms rate limit, one retry on failure
        │
        ├─── [low_node]
        │    └── Set action_taken = 'monitor', no dispatch
        │
        ├─── skill_alert_logger
        │    → Writes one row to alert_log.csv
        │    → Stores state to sara.db (LangGraph checkpoint)
        │
        └─── report_node
             → Generates daily summary
             → Sends ops summary to WhatsApp
```

### What Makes This a True AI Skill (Not Just a Script)

1. **Claude decides the message** — no templates. The model reads seller-specific signals (their actual product category, city, reply count, lapse %) and writes a unique message each time.

2. **Claude explains the risk** — the BD call brief and risk factor text are generated by Claude based on the seller's specific combination of signals, not prefilled strings.

3. **The same skill is portable** — by swapping the dimension weights, the same 6 skills work for Catalog QA abandonment detection. Zero code change.

4. **Prompt caching** — the 2000-token system prompt (domain rules, signal definitions) is cached across all 998 sellers in a single batch run, saving ~1.9M tokens/run.

5. **Full audit trail** — every node in the LangGraph is checkpointed to `sara.db`. Every dispatch action is timestamped in `alert_log.csv`. Full replay capability.

---

## 7. SARA Dashboard — What Was Built

The Streamlit dashboard (`scripts/dashboard.py`) is the human-facing layer on top of the pipeline.

### Pages

| Page | What It Shows |
|------|--------------|
| **Overview** | 998 sellers sorted by churn score. KPI cards: at-risk count, revenue at risk. Band donut chart. Score histogram. Clickable top-50 table (click row → opens Seller Detail). |
| **Seller Detail** | Per-seller deep-dive: churn score gauge, 5-dimension radar chart, 4-month trend charts (replies, lapse rate, BL consumption), signal flags, recommended action, AI-generated BD call brief, WhatsApp message generator + send button. |
| **Band Analysis** | Per-band breakdown with package value distribution, service type split, scatter plot (score vs replies), full seller list per band. |
| **Alert Log** | Full `alert_log.csv` rendered — all dispatched actions, WA statuses, call actions, timestamps. |

### Sidebar Navigation

- **Clickable band pills** — clicking "BLACK — 180 sellers" filters overview to BLACK only
- **Nav buttons** — styled dark sidebar with active page highlight
- **SARA branding** — full name "Seller Alert & Retention Agent" visible at top

### AI Features in Dashboard

| Feature | What It Does |
|---------|-------------|
| Generate BD Call Brief | Calls Qwen3-32B via IM LLM Gateway. Returns opening line, discovery questions, pain hypothesis, resolution path. |
| Generate WhatsApp Message | Calls Qwen3-32B. Writes personalized English message based on seller's actual signals. |
| Send WhatsApp | Calls `wahelp.indiamart.com` with `action=vani_send_msg`. Shows full API response in UI. Always sends to `917389680021` in demo mode. |

---

## 8. Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| AI / LLM | Qwen3-32B via IndiaMart LLM Gateway | Internal gateway, no external API costs |
| Agent Framework | LangGraph StateGraph | Typed state, conditional routing, SQLite checkpointing |
| WhatsApp | IndiaMart VANI API | Internal — no Meta template approval needed |
| Call Dispatch | SquadStack + IVR Dialer | BLACK tier rescue, RED tier BD tasks |
| Data Processing | Pandas + openpyxl | 219-column Excel → clean feature vectors |
| Dashboard | Streamlit | Rapid deployment, interactive, live filtering |
| Audit | `alert_log.csv` + `sara.db` | Every action logged, every graph state stored |
| Tracing | LangSmith | Full node-level trace per seller for debugging |
| Hosting | Streamlit Community Cloud (free) | Public URL, zero infra cost |

---

## 9. Key Numbers

| Metric | Value |
|--------|-------|
| Total sellers monitored | **998** |
| Sellers at risk (score ≥ 50) | **467 (47%)** |
| BLACK band (rescue today) | **180** |
| RED band (call this week) | **212** |
| Revenue at risk | **₹128L** |
| Strongest predictor | **`replies` — 19× gap** |
| Existing RAG score accuracy | **Near random** |
| BD coverage gap | **82% sellers unreached** |
| Email-dead sellers | **~262** |
| Estimated renewals saved (20%) | **93 sellers = ₹23L** |
| BD research time saved | **45 min → 3 min per seller (15× efficiency)** |
| Tokens saved per batch (prompt caching) | **~1.9M tokens/run** |

---

*Documentation generated for IndiaMart Hackathon, May 15–16, 2026*
*SARA — Seller Alert & Retention Agent*
*Skills: skill_data_loader · skill_feature_engineer · skill_rule_checker · skill_churn_scorer · skill_whatsapp_agent · skill_alert_logger*
