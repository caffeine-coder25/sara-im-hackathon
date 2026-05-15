# Seller Churn Early-Warning System
## Full Implementation Plan — Hackathon May 15–16, 2026
## v2.0 — Merged with SARA v3.0 Architecture

---

## 1. Executive Summary

**Problem:** 47% of active sellers (467 of 998) show churn signals right now. The existing
`rag_score` field cannot detect them — sellers going dark look identical to healthy sellers
on the current system. Sellers don't complain before they churn. They ghost.

**Solution:** A Claude Skills-based hybrid system that:
1. Scores all sellers daily using behavioral signals (not catalog quality)
2. Routes each seller to the right intervention automatically via a typed LangGraph StateGraph
3. Deploys two live agents — one sends personalized WhatsApp messages, one triggers calls
4. Logs every action to `alert_log.csv` with full dispatch audit trail
5. Persists graph state to `sara.db` for replay and debugging

**Why it wins on axis 5 (Skills quality):** Three canonical SKILL.md files, two live agents
with tool use, a runnable pipeline, a full audit log, and the same skill works verbatim
for Catalog QA monitoring.

---

## 2. What the Data Actually Shows (Findings from 998 Sellers × 4 Months)

### Finding 1: RAG Score Is Broken — This Is Our Value Proposition

| RAG Band | Avg Lapse Rate | Avg LMS Days |
|----------|---------------|-------------|
| -2 (worst) | 0.57 | 7.9 |
| -1 | 0.52 | 7.9 |
| 0 | 0.44 | 8.8 |
| 1 | 0.41 | 8.8 |
| **2 (best)** | **0.43** | **8.0** |

RAG=2 sellers have a HIGHER lapse rate than RAG=1 sellers. LMS days are essentially
identical across all bands. The current system is blind to churn. This is slide one of the demo.

### Finding 2: Sellers Ghost — They Don't Complain

Compare going-dark sellers (our score ≥ 80) vs healthy sellers (score ≤ 20):

| Signal | Going Dark | Healthy | Ratio |
|--------|-----------|---------|-------|
| `replies` | 5.08 | 97.80 | **19× gap** |
| `emails_opened` | 4.56 | 25.68 | 5× gap |
| `total_enq` | 4.66 | 8.13 | 1.7× gap |
| `cmplnts_cnt` | 0.01 | 0.18 | **Inverted** |
| `qrf_bl` | 0.07 | 1.67 | **Inverted** |
| `total_hide` | 0.25 | 3.30 | **Inverted** |
| `cqs` | 64.3 | 67.1 | No difference |
| `catalog_score` | 65.7 | 68.5 | No difference |

**Key insight:** Sellers who complain, hide leads, and give QRF feedback are still ENGAGED.
Churning sellers simply stop replying and disappear. Catalog quality is not the driver.
`replies` is the single strongest predictor — a 19× difference between churning and healthy.

### Finding 3: Current At-Risk Population (Live Numbers)

| Risk Band | Count | % of Base |
|-----------|-------|-----------|
| Score 100 — all signals firing | **180** | 18% → rescue calls today |
| Score 80–99 — critical | **212** | 21% → BD L2 this week |
| Score 60–79 — warning | **75** | 7.5% → automated nudge |
| Score < 60 — healthy | **531** | 53% → monitor only |

### Finding 4: BD Coverage Crisis

**82% of sellers (819/998) had zero BD connects in May.** The agent's primary value is
triaging who to call today — not just scoring but producing call-ready briefs.

### Finding 5: May Data Is Partial — Must Normalize

Data pulled May 13–14. Only 13 days elapsed. Raw May numbers are 2.3× understated.
All trend comparisons involving May must normalize: `value × (30 / days_elapsed)`.

```python
DAYS_ELAPSED = {'202602': 28, '202603': 31, '202604': 30, '202605': 14}

def normalize_monthly(value, year_month):
    return value * (30 / DAYS_ELAPSED.get(year_month, 30))
```

---

## 3. System Architecture

### 3.1 High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                     │
│  Scorecard API → 219 fields × 998 sellers × 4 months           │
│  Partial month normalization on ingest (May ÷14 ×30)           │
│  Store: MongoDB / PostgreSQL                                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  FEATURE ENGINEERING (features.py)                              │
│  25 derived ratios: lapse_rate, util_rate, reply_rate, etc.     │
│  MoM trend vectors for 6 core signals                           │
│  BD recency: days_since_last_bd_touch                           │
│  Comm health: email_dead_flag, notification_loss_rate           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  CHURN SCORING ENGINE (score.py)                                │
│  Phase 1: Rule-based weighted score 0–100                       │
│  Phase 2: LightGBM trained on going-dark labels (stretch)      │
│  Output per seller: score, band, top_3_reasons, action_code     │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
┌──────────────▼──────────────┐  ┌────────────▼────────────────┐
│  SKILL 1                    │  │  COMM ROUTER                │
│  seller-churn-scorer        │  │  Per seller:                │
│  Claude explains risk in    │  │  email_dead? → WhatsApp     │
│  natural language, ranks    │  │  notif_lost > 80%? → call   │
│  BD call list, generates    │  │  score 100? → call first    │
│  per-seller talking points  │  └────────────┬────────────────┘
└──────────────┬──────────────┘               │
               │              ┌───────────────┘
               │              │
┌──────────────▼──────────────▼─────────────────────────────────┐
│  LANGGRAPH STATEGRAPH — 9 Nodes (orchestrator)                 │
│  Typed AgentState · SqliteSaver checkpointer (sara.db)         │
│  Runs daily at 08:00 via cron                                  │
│  Scores all 998 sellers → sorts by churn_score                 │
│  Routes each seller to correct downstream agent                │
│  Top 50: generates BD brief + talking points                   │
└──────────┬──────────────────────────────┬──────────────────────┘
           │                              │
┌──────────▼──────────────┐  ┌───────────▼──────────────────────┐
│  SKILL 2                │  │  SKILL 3                         │
│  seller-whatsapp-agent  │  │  seller-call-agent               │
│                         │  │                                  │
│  Claude generates       │  │  Claude generates call script    │
│  personalized message   │  │  + talking points                │
│  based on seller's      │  │                                  │
│  specific signals       │  │  Routes to:                      │
│                         │  │  • score 100 → SquadStack IVR   │
│  Calls wahelp API:      │  │    immediate rescue call         │
│  wrapper_api_prod.php   │  │  • score 80–99 → BD CRM task    │
│  action=vani_send_msg   │  │    with script + priority        │
│                         │  │  • score 60–79 → scheduled       │
│  Rate limiting: 60ms    │  │    callback slot booking         │
│  delay between calls    │  │                                  │
│  Retry: once after 5s   │  └──────────────────────────────────┘
│  on failure → log+skip  │
└─────────────────────────┘
```

### 3.2 LangGraph — 9 Node Graph

Replacing the simple `orchestrator.py` loop with a typed LangGraph StateGraph gives us
audit replay via SqliteSaver, clean node-level separation, and conditional routing as a
first-class primitive — all visible in LangSmith traces during the demo.

| Node | Skill Invoked | What It Does |
|------|--------------|-------------|
| `ingest_node` | skill_data_loader | Load seller from scorecard API; normalize partial months; build `raw_attributes` + `data_flags` |
| `feature_node` | skill_feature_engineer | Compute 25 derived features (ratios, MoM trends, BD recency, comm health) |
| `rule_check_node` | skill_rule_checker | Evaluate 8 hard red-flag rules; set `is_critical_override` if any fire |
| `score_node` | skill_churn_scorer | Weighted 5-dimension score 0–100; assign band; generate `top_3_risk_factors` via Claude |
| `band_router` | — (conditional edge) | Route: BLACK/RED → `call_node` \| ORANGE/AMBER → `whatsapp_node` \| GREEN → `low_node` |
| `whatsapp_node` | skill_whatsapp_agent | Claude writes personalized message; calls wahelp API; records `whatsapp_message_id` |
| `call_node` | skill_call_agent | Score ≥ 85 → SquadStack IVR immediately; score 70–84 → BD CRM task + brief |
| `low_node` | — (pass-through) | GREEN: no action; set `action_taken='monitor'`; pass to `log_node` |
| `log_node` | skill_alert_logger | Append row to `alert_log.csv`; write `log_entry_id` to state |
| `report_node` | skill_alert_logger | After all sellers: generate daily summary (counts by band, messages sent, calls triggered) |

### 3.3 Conditional Router

```python
# agent/router.py
def band_router(state: AgentState) -> str:
    if state['is_critical_override']:       return 'call'   # Any red flag → immediate call
    elif state['churn_score'] >= 85:        return 'call'   # BLACK
    elif state['churn_score'] >= 70:        return 'call'   # RED — call + WA follow-up
    elif state['churn_score'] >= 50:        return 'whatsapp'  # ORANGE
    elif state['churn_score'] >= 25:        return 'whatsapp'  # AMBER
    else:                                   return 'skip'   # GREEN — monitor only
```

### 3.4 Graph Wiring

```python
# agent/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import AgentState
from agent.nodes import (
    ingest_node, feature_node, rule_check_node, score_node,
    whatsapp_node, call_node, low_node, log_node, report_node
)
from agent.router import band_router

graph = StateGraph(AgentState)
graph.add_node('ingest',    ingest_node)
graph.add_node('features',  feature_node)
graph.add_node('rules',     rule_check_node)
graph.add_node('score',     score_node)
graph.add_node('whatsapp',  whatsapp_node)
graph.add_node('call',      call_node)
graph.add_node('low',       low_node)
graph.add_node('log',       log_node)
graph.add_node('report',    report_node)

graph.set_entry_point('ingest')
graph.add_edge('ingest',   'features')
graph.add_edge('features', 'rules')
graph.add_edge('rules',    'score')

graph.add_conditional_edges('score', band_router, {
    'call':     'call',
    'whatsapp': 'whatsapp',
    'skip':     'low',
})

graph.add_edge('call',     'log')
graph.add_edge('whatsapp', 'log')
graph.add_edge('low',      'log')
graph.add_edge('log',      'report')
graph.add_conditional_edges('report', lambda s: 'done', {'done': END})

checkpointer = SqliteSaver.from_conn_string('sara.db')
churn_agent  = graph.compile(checkpointer=checkpointer)
```

---

## 4. Typed AgentState

Formal typed state — every node reads from and writes to this dict. The SqliteSaver
checkpointer snapshots it at each node boundary, enabling full audit replay in LangSmith.

```python
# agent/state.py
from typing import TypedDict, Optional
from datetime import datetime

class AgentState(TypedDict):
    # Identity
    seller_id:            str
    seller_name:          str
    seller_mobile:        str
    run_date:             str          # e.g. '2026-05-15'
    run_timestamp:        datetime

    # skill_data_loader → ingest_node
    raw_attributes:       dict         # {year_month: {219 attrs}}
    data_flags:           dict         # {year_month: {3 cleaning flags}}

    # skill_feature_engineer → feature_node
    derived_features:     dict         # 25-feature vector

    # skill_rule_checker → rule_check_node
    red_flags:            list         # Triggered rule IDs
    is_critical_override: bool

    # skill_churn_scorer → score_node
    churn_score:          float        # 0–100
    risk_band:            str          # BLACK / RED / ORANGE / AMBER / GREEN
    top_risk_factors:     list         # 3 plain-English sentences

    # skill_whatsapp_agent → whatsapp_node
    whatsapp_status:      str          # sent / failed / skipped
    whatsapp_message_id:  Optional[str]
    dispatch_timestamp:   str          # ISO timestamp

    # skill_call_agent → call_node
    call_action:          str          # IVR_TRIGGERED / BD_TASK_CREATED_P1 / BD_TASK_CREATED_P2 / skipped
    bd_task_id:           Optional[str]
    call_brief_preview:   Optional[str]

    # General
    action_taken:         str          # summary: whatsapp / call_ivr / call_bd / monitor
    log_entry_id:         str          # e.g. 'ALT-264203724-2026-05-15'
```

---

## 5. Skills Registry (6 Skills)

Install all skills before running Claude Code:

```bash
claude skill install skill_data_loader.skill
claude skill install skill_feature_engineer.skill
claude skill install skill_rule_checker.skill
claude skill install skill_churn_scorer.skill
claude skill install skill_whatsapp_agent.skill
claude skill install skill_alert_logger.skill
```

### 5.1 Skill 1 — `seller-churn-scorer`

```yaml
---
name: seller-churn-scorer
description: >
  Use this skill when asked to: check seller health, identify at-risk sellers,
  calculate churn risk score, explain why a seller might not renew, rank the BD
  call list, generate per-seller retention talking points, or run the daily
  seller health batch.
  Trigger phrases: "churn risk", "seller health", "at risk sellers",
  "seller not renewing", "BD call list", "who should we call today",
  "retention priority", "seller going dark".
---
```

**What It Does:** Takes a `seller_id` (or "run batch") and returns:
- Churn score 0–100
- Risk band (GREEN / AMBER / ORANGE / RED / BLACK)
- Top 3 risk factors in plain English
- Recommended action with urgency
- BD talking points (for score ≥ 60)

**Claude Integration Points:**

```
Input to Claude:
  seller_id, 4 months of computed features, peer_segment_averages

Claude tasks:
  1. Explain the risk in one paragraph (why this seller specifically)
  2. Rank the top 3 signals by importance for THIS seller's context
  3. Generate BD talking points that don't sound algorithmic
  4. Suggest the opening question for the BD call
  5. Identify which product category/location issue is most fixable

Tools available to Claude:
  • get_seller_features(seller_id) → structured dict
  • get_peer_comparison(service_tier, score_range) → segment benchmarks
  • get_bd_history(seller_id) → last touch, exec name, notes
  • get_complaint_status(seller_id) → open complaints
```

**Churn Scoring Logic — Updated Weights Based on Actual Data:**

| Dimension | Weight | Top Signal | Data Basis |
|-----------|--------|-----------|------------|
| Platform Engagement | **40%** | `replies` (19× predictor) | Going-dark correlation |
| BL Value ROI | **30%** | `bl_credit_lapsed` | Direct financial signal |
| BD Coverage | **15%** | `succ_connect_bd` | 82% uncovered |
| Business Outcomes | **10%** | `success_connect` | Secondary correlation |
| Catalog / PNS | **5%** | `catalog_score` | Weak predictor (64 vs 67) |

```python
def compute_churn_score(seller_months: list[dict]) -> dict:
    latest = seller_months[-1]
    prev   = seller_months[-2] if len(seller_months) > 1 else latest

    def n(val, ym): return normalize_monthly(val, ym)

    # --- Dimension 1: Platform Engagement (40 pts max) ---
    replies_now  = n(latest['replies'], latest['year_month'])
    replies_prev = n(prev['replies'],   prev['year_month'])
    eng = 0
    if replies_now == 0:                                       eng += 20
    elif replies_now < 10:                                     eng += 12
    elif replies_prev > 0 and replies_now < replies_prev*0.5: eng += 8
    if latest['lms_active_days'] == 0:                         eng += 10
    elif latest['lms_active_days'] < 3:                        eng += 5
    email_open_rate = latest['emails_opened'] / max(latest['emails_sent'], 1)
    if email_open_rate == 0 and latest['emails_sent'] > 5:     eng += 10

    # --- Dimension 2: BL Value ROI (30 pts max) ---
    lapse_rate = latest['bl_credit_lapsed'] / max(latest['bl_credits_alctd'], 1)
    util_rate  = latest['bl_cons'] / max(latest['bl_credits_alctd'], 1)
    roi = 0
    if lapse_rate > 0.8:   roi += 20
    elif lapse_rate > 0.5: roi += 12
    elif lapse_rate > 0.2: roi += 5
    if util_rate < 0.3:    roi += 10
    bl_now  = n(latest['bl_cons'], latest['year_month'])
    bl_prev = n(prev['bl_cons'],   prev['year_month'])
    if bl_prev > 0 and bl_now < bl_prev * 0.5: roi += 10

    # --- Dimension 3: BD Coverage (15 pts max) ---
    bd = 0
    if latest['succ_connect_bd']  == 0: bd += 10
    if latest['success_bd_calls'] == 0: bd += 5

    # --- Dimension 4: Business Outcomes (10 pts max) ---
    biz = 0
    if latest['success_connect']   == 0: biz += 5
    if latest['success_calls']     == 0: biz += 3
    if latest['pns_success_prcnt'] == 0: biz += 2

    # --- Dimension 5: Catalog + PNS (5 pts max) ---
    cat = 0
    if latest['catalog_score'] < 40:      cat += 3
    if latest['defaulter_flag'] == 'yes': cat += 2

    base = eng + roi + bd + biz + cat

    # --- Trend Bonus (up to +15 pts) ---
    trend_bonus = 0
    for m in seller_months[-3:]:
        if n(m['replies'], m['year_month']) < 5: trend_bonus += 3
    prev_lapse = n(prev['bl_credit_lapsed'], prev['year_month']) / max(prev['bl_credits_alctd'], 1)
    if lapse_rate > prev_lapse: trend_bonus += 5  # lapse rate accelerating

    return {
        'churn_score':  min(100, base + trend_bonus),
        'dimensions':   {'engagement': eng, 'roi': roi, 'bd': bd, 'biz': biz, 'catalog': cat},
        'lapse_rate':   lapse_rate,
        'replies_trend': f"{replies_prev:.0f}→{replies_now:.0f}"
    }
```

**Risk Bands and Dispatch SLA:**

| Score | Band | Color | WhatsApp? | Call? | SLA |
|-------|------|-------|-----------|-------|-----|
| 85–100 | BLACK | ⚫ | Skip → go straight to call | IVR immediately | Same day, within 15 min of batch |
| 70–84 | RED | 🔴 | Follow-up after call | BD CRM task P1 | Call within 1 hr; WA within 2 hrs |
| 50–69 | ORANGE | 🟠 | First touchpoint | Schedule callback | WA within 2 hrs; call within 48 hrs |
| 25–49 | AMBER | 🟡 | Nudge only | No call | WA this session |
| 0–24 | GREEN | 🟢 | None | None | Monitor only |

**Output Format:**

```json
{
  "seller_id": "264768627",
  "service": "Catalog",
  "churn_score": 97,
  "risk_band": "black",
  "top_risk_factors": [
    "Replies collapsed from 45 to 0 over last 2 months — seller has completely stopped engaging with leads",
    "97% of BL credits lapsed this month (33 credits allocated, 32 expired unused)",
    "No BD contact in 60+ days despite critical signals"
  ],
  "recommended_action": {
    "type": "RESCUE_CALL",
    "urgency": "same_day",
    "agent": "seller-call-agent"
  },
  "bd_talking_points": [
    "Don't open with metrics — ask: 'Are the leads you're getting matching your products?'",
    "97% lapse means they're not even opening leads. Find out why — wrong category? wrong geography?",
    "Last BD call was 60+ days ago. Acknowledge the gap.",
    "You have discretion on up to 15% renewal discount if they're genuinely considering leaving."
  ],
  "comm_channel": "call_first_then_whatsapp",
  "email_dead": true
}
```

---

## 6. Skill 2 — `seller-whatsapp-agent`

```yaml
---
name: seller-whatsapp-agent
description: >
  Use this skill when you need to send a personalized WhatsApp message to a
  seller based on their churn risk signals. Claude reads the seller's specific
  signals, generates a message tailored to their situation, and sends it via
  the Indiamart WhatsApp API (wahelp.indiamart.com).
  Trigger phrases: "send WhatsApp to seller", "nudge seller on WhatsApp",
  "WhatsApp outreach", "message at-risk seller", "send retention message".
---
```

**What It Does:** This is a **live agent with tool use**. Claude does not use templates.
It reads the seller's actual signals and writes a message that references their specific
situation, asks a re-engagement question, and matches tone to risk band.

**Tools Available to This Agent:**

```python
tools = [
    {
        "name": "get_seller_signals",
        "description": "Returns seller's key behavioral signals for the last 3 months",
        "input_schema": {
            "seller_id": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "string"}}
        }
    },
    {
        "name": "send_whatsapp_message",
        "description": "Sends a WhatsApp message via the Indiamart VANI API",
        "input_schema": {
            "phone_number": {"type": "string"},
            "template_params": {"type": "array"},
            "glid": {"type": "string"},
            "call_id": {"type": "string"}
        }
    },
    {
        "name": "log_outreach",
        "description": "Logs the outreach attempt with timestamp and message preview",
        "input_schema": {
            "seller_id": {"type": "string"},
            "channel": {"type": "string"},
            "message_preview": {"type": "string"},
            "churn_score": {"type": "number"}
        }
    },
    {
        "name": "check_last_outreach",
        "description": "Returns last WhatsApp sent to avoid spamming (7-day cooldown)",
        "input_schema": {"seller_id": {"type": "string"}}
    }
]
```

**Agent Execution Flow:**

```
1. Check last outreach — do not message if contacted in last 7 days
2. Fetch seller signals: replies, lapse_rate, blni_reason, last_bl_cons_date,
   top_10_mcat, success_connect, lms_active_days
3. If seller_mobile is null/unknown → set whatsapp_status='skipped', exit
4. Identify PRIMARY pain signal (the one most likely to resonate with seller)
5. Generate message in seller's context (Claude writes it — not a template)
6. Call send_whatsapp_message tool
7. Rate limit: sleep 60ms between API calls (respects IndiaMart VANI limits)
8. On HTTP error: retry once after 5s. On second failure → whatsapp_status='failed', continue
9. Log outreach with message preview and score
```

**WhatsApp API Integration with Retry Logic:**

```python
import requests, time
from datetime import datetime

WAHELP_API = "https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php"

def send_whatsapp_message(phone_number: str, template_params: list,
                           glid: str, call_id: str,
                           seller_mobile: str = None) -> dict:
    # Guard: skip if mobile unknown
    if not seller_mobile or seller_mobile == 'Unknown':
        return {'whatsapp_status': 'skipped', 'whatsapp_message_id': None,
                'dispatch_timestamp': datetime.now().isoformat()}

    mobile = str(seller_mobile).replace('+', '').replace(' ', '')
    if not mobile.startswith('91'): mobile = '91' + mobile

    payload = {
        "action":    "vani_send_msg",
        "user":      mobile,
        "platform":  "WhatsApp_9696",
        "glid":      glid,
        "call_id":   call_id,
        "payload":   json.dumps({"templateParams": template_params})
    }

    for attempt in range(2):
        try:
            resp = requests.post(WAHELP_API, data=payload,
                                 headers={"X-Api-Key": WA_API_KEY}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            time.sleep(0.06)  # 60ms — rate limit compliance
            return {
                'whatsapp_status':     'sent',
                'whatsapp_message_id': data.get('messageId'),
                'dispatch_timestamp':  datetime.now().isoformat()
            }
        except Exception:
            if attempt == 0:
                time.sleep(5)   # Wait 5s before retry
            else:
                return {
                    'whatsapp_status':     'failed',
                    'whatsapp_message_id': None,
                    'dispatch_timestamp':  datetime.now().isoformat()
                }
```

**Message Generation Prompt (sent to Claude):**

```
You are an Indiamart seller success agent. Write a WhatsApp message to this seller.

Seller context:
- Service: {service}
- Products: {top_10_mcat}
- Replies in last month: {replies} (down from {replies_prev})
- BL credits lapsed: {lapse_pct}%
- Last lead activity: {days_since_last_cons} days ago
- Primary signal: {primary_pain_signal}
- Risk band: {risk_band}

Rules:
- Do NOT mention "churn score" or "risk" or "we're worried about you"
- Do NOT send a generic message — reference their specific product category
- Ask ONE question that invites them to re-engage
- Keep under 160 characters for WhatsApp
- Tone: helpful, not alarming
- For AMBER: curious and helpful. For ORANGE/RED: more direct about the opportunity cost.

Examples of what NOT to write:
  ❌ "Your account activity has declined."
  ❌ "Please log in to IndiaMart."

Examples of the right tone:
  ✓ "Hi [Name], we noticed your {product} leads are piling up. Are the buyers 
     matching what you sell? Takes 2 mins to adjust — want us to help?"
  ✓ "Hi [Name], your {product} category had 8 new buyer inquiries last week 
     but none were opened. Is everything okay on your end?"
```

**Message Logic by Risk Band:**

| Risk Band | Primary Message Hook | Tone | Follow-up if No Reply |
|-----------|---------------------|------|-----------------------|
| AMBER (25–49) | "Your {product} leads are waiting" | Helpful | Another WA in 5 days |
| ORANGE (50–69) | "8 buyers looked at your {product}" | Opportunity | Trigger call agent |
| RED (70–84) | "Your leads expire in X days" | Urgent | Trigger call agent same day |
| BLACK (85–100) | Skip WA → go straight to call | — | Call agent immediately |

---

## 7. Skill 3 — `seller-call-agent`

```yaml
---
name: seller-call-agent
description: >
  Use this skill when a seller's churn score requires a human or automated
  phone intervention. For score >= 85, triggers an immediate SquadStack IVR
  rescue call. For score 70–84, creates a prioritized BD CRM task with a
  Claude-generated call script. For score 50–69, books a scheduled callback slot.
  Trigger phrases: "call at-risk seller", "trigger rescue call", "schedule BD callback",
  "generate call script", "seller needs a call", "urgent seller outreach".
---
```

**Two Distinct Call Pathways:**

**Pathway A — Automated IVR Call (score ≥ 85):**
- Triggers SquadStack/dialer API immediately
- Claude generates the IVR script (seller hears a recorded message, presses 1 to talk to BD)
- Escalates to live BD if seller responds

**Pathway B — BD Call Brief (score 70–84):**
- Creates a task in BD CRM with full call brief
- Claude writes the exact opening line, key questions, discount authority
- Assigns to the seller's existing BD exec or auto-assigns if gap > 30 days

**Tools Available to This Agent:**

```python
tools = [
    {
        "name": "get_seller_profile",
        "description": "Returns seller details: phone, service tier, BD exec, package value",
        "input_schema": {"seller_id": {"type": "string"}}
    },
    {
        "name": "get_bd_availability",
        "description": "Returns BD exec schedule and current workload",
        "input_schema": {"exec_id": {"type": "string"}, "date": {"type": "string"}}
    },
    {
        "name": "trigger_ivr_call",
        "description": "Triggers an automated outbound IVR call via SquadStack API",
        "input_schema": {
            "phone_number": {"type": "string"},
            "seller_id":    {"type": "string"},
            "script_id":    {"type": "string"},
            "priority":     {"type": "string", "enum": ["immediate", "scheduled"]}
        }
    },
    {
        "name": "create_bd_task",
        "description": "Creates a prioritized call task in BD CRM with call brief",
        "input_schema": {
            "seller_id":          {"type": "string"},
            "exec_id":            {"type": "string"},
            "priority":           {"type": "string"},
            "call_brief":         {"type": "string"},
            "opening_line":       {"type": "string"},
            "discount_authority": {"type": "number"},
            "deadline_hours":     {"type": "number"}
        }
    },
    {
        "name": "check_open_complaints",
        "description": "Returns any open unresolved complaints for the seller",
        "input_schema": {"seller_id": {"type": "string"}}
    },
    {
        "name": "get_churn_score_detail",
        "description": "Returns full score breakdown and top risk factors",
        "input_schema": {"seller_id": {"type": "string"}}
    }
]
```

**Call Agent Decision Logic:**

```python
def call_agent_route(state: AgentState) -> dict:
    seller_id    = state['seller_id']
    churn_score  = state['churn_score']
    top_factors  = state['top_risk_factors']
    profile      = get_seller_profile(seller_id)
    complaints   = get_open_complaints(seller_id)

    if churn_score >= 85:
        # Skip BD — trigger immediate IVR rescue
        script_id = select_ivr_script(top_factors[0])
        trigger_ivr_call(
            phone_number=profile['phone'],
            seller_id=seller_id,
            script_id=script_id,
            priority="immediate"
        )
        return {'call_action': 'IVR_TRIGGERED', 'bd_task_id': None}

    elif churn_score >= 70:
        # Generate BD call brief and create high-priority CRM task
        brief    = claude.generate_call_brief(seller_id, top_factors, profile)
        discount = 15 if (state['derived_features']['bl_lapse_rate'] > 0.7
                          and not complaints) else 0
        task_id  = create_bd_task(
            seller_id=seller_id,
            exec_id=profile['bd_exec_id'],
            priority="P1",
            call_brief=brief['brief'],
            opening_line=brief['opening_line'],
            discount_authority=discount,
            deadline_hours=24
        )
        return {'call_action': 'BD_TASK_CREATED_P1', 'bd_task_id': task_id,
                'call_brief_preview': brief['brief'][:200]}

    elif churn_score >= 50:
        brief   = claude.generate_call_brief(seller_id, top_factors, profile)
        task_id = create_bd_task(
            seller_id=seller_id,
            exec_id=profile['bd_exec_id'],
            priority="P2",
            call_brief=brief['brief'],
            deadline_hours=48
        )
        return {'call_action': 'BD_TASK_CREATED_P2', 'bd_task_id': task_id,
                'call_brief_preview': brief['brief'][:200]}
```

**Call Brief Generation Prompt:**

```
You are preparing a BD call brief for a seller retention call.

Seller: {seller_id}
Service: {service_tier} | Package value: ₹{package_value}/year
BD Exec: {exec_name} (last contacted: {days_since_contact} days ago)

Churn signals:
{top_3_risk_factors}

Key data:
- Replies this month: {replies} (was {replies_prev} last month)
- BL lapse rate: {lapse_pct}%
- Open complaints: {open_complaints}
- Products: {top_10_mcat}

Generate:
1. OPENING LINE: One sentence that does NOT sound like a retention call.
2. DISCOVERY QUESTIONS (3 max): Genuinely curious, not leading.
3. PAIN HYPOTHESIS: What is most likely wrong based on signals?
4. RESOLUTION PATH: What specific fix can BD offer today?
5. DISCOUNT AUTHORITY: Recommend only if lapse_rate > 70% AND no complaints AND score > 80.

Keep the brief under 200 words. BD reads this 2 minutes before the call.
```

---

## 8. Alert Log — `alert_log.csv`

Every seller processed in every daily run is written to `alert_log.csv`.
This is the single source of truth for all dispatched actions.

```python
# agent/nodes.py — log_node
import csv, os, json
from datetime import datetime

def log_run(state: AgentState, log_path: str = 'alert_log.csv') -> dict:
    entry_id = f"ALT-{state['seller_id']}-{state['run_date']}"
    row = {
        'log_entry_id':         entry_id,
        'run_date':             state['run_date'],
        'seller_id':            state['seller_id'],
        'seller_name':          state['seller_name'],
        'churn_score':          state['churn_score'],
        'risk_band':            state['risk_band'],
        'top_risk_factors_json': json.dumps(state['top_risk_factors']),
        'action_taken':         state['action_taken'],
        'whatsapp_status':      state['whatsapp_status'],
        'whatsapp_message_id':  state.get('whatsapp_message_id') or '',
        'call_action':          state['call_action'],
        'bd_task_id':           state.get('bd_task_id') or '',
        'dispatch_timestamp':   state['dispatch_timestamp'],
    }
    file_exists = os.path.isfile(log_path)
    with open(log_path, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists: w.writeheader()
        w.writerow(row)
    return {'log_entry_id': entry_id}
```

**Alert Log Schema:**

| Column | Type | Example | Description |
|--------|------|---------|-------------|
| `log_entry_id` | str | ALT-264203724-2026-05-15 | Unique per seller per day |
| `run_date` | str | 2026-05-15 | Date of this batch run |
| `seller_id` | str | 264203724 | IndiaMart seller ID |
| `seller_name` | str | Rahul Sharma | Seller display name |
| `churn_score` | float | 82.4 | Computed churn score 0–100 |
| `risk_band` | str | BLACK | BLACK/RED/ORANGE/AMBER/GREEN |
| `top_risk_factors_json` | str (JSON) | ["Replies: 45→0", …] | 3 plain-English risk reasons |
| `action_taken` | str | call_ivr | whatsapp / call_ivr / call_bd / monitor |
| `whatsapp_status` | str | sent | sent / failed / skipped |
| `whatsapp_message_id` | str | wamid.XXXXX | Message ID from IndiaMart VANI API |
| `call_action` | str | IVR_TRIGGERED | IVR_TRIGGERED / BD_TASK_CREATED_P1 / BD_TASK_CREATED_P2 / skipped |
| `bd_task_id` | str | TASK-001234 | CRM task ID if created; empty otherwise |
| `dispatch_timestamp` | str (ISO) | 2026-05-15T08:04:32 | When action was dispatched |

**Daily Summary Report:**

```python
def daily_report(log_path: str = 'alert_log.csv', run_date: str = None) -> dict:
    import pandas as pd
    df = pd.read_csv(log_path)
    if run_date: df = df[df['run_date'] == run_date]
    return {
        'total_sellers':    len(df),
        'by_band':          df['risk_band'].value_counts().to_dict(),
        'by_action':        df['action_taken'].value_counts().to_dict(),
        'wa_sent':          len(df[df['whatsapp_status'] == 'sent']),
        'wa_failed':        len(df[df['whatsapp_status'] == 'failed']),
        'wa_skipped':       len(df[df['whatsapp_status'] == 'skipped']),
        'ivr_triggered':    len(df[df['call_action'] == 'IVR_TRIGGERED']),
        'bd_tasks_p1':      len(df[df['call_action'] == 'BD_TASK_CREATED_P1']),
        'bd_tasks_p2':      len(df[df['call_action'] == 'BD_TASK_CREATED_P2']),
    }
```

---

## 9. Orchestrator — Daily Batch Runner

```python
# orchestrator.py — runs daily at 08:00 via cron
import anthropic
from score import compute_all_scores
from agent.graph import churn_agent
from agent.state import AgentState
import pandas as pd
from datetime import datetime

def run_daily_batch():
    run_date = datetime.now().strftime('%Y-%m-%d')
    df = pd.read_excel('data/sellers_data_cleaned.xlsx',
                       dtype={'glusr_usr_id': str})
    scores = compute_all_scores(df)
    scores.sort(key=lambda x: -x['churn_score'])

    for seller in scores:
        seller_row = df[df['glusr_usr_id'] == seller['seller_id']].iloc[0]

        initial_state: AgentState = {
            'seller_id':            seller['seller_id'],
            'seller_name':          str(seller_row.get('seller_name', 'Seller')),
            'seller_mobile':        str(seller_row.get('mobile', 'Unknown')),
            'run_date':             run_date,
            'run_timestamp':        datetime.now(),
            'raw_attributes':       {},
            'data_flags':           {},
            'derived_features':     {},
            'red_flags':            [],
            'is_critical_override': False,
            'churn_score':          0.0,
            'risk_band':            '',
            'top_risk_factors':     [],
            'whatsapp_status':      '',
            'whatsapp_message_id':  None,
            'dispatch_timestamp':   '',
            'call_action':          '',
            'bd_task_id':           None,
            'call_brief_preview':   None,
            'action_taken':         '',
            'log_entry_id':         '',
        }

        churn_agent.invoke(initial_state)

    send_ops_summary(daily_report(run_date=run_date))
```

### Claude Anthropic SDK Integration (with Prompt Caching)

```python
import anthropic

client = anthropic.Anthropic()

def generate_risk_explanation(seller_data: dict) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SELLER_CONTEXT_SYSTEM_PROMPT,  # ~2000 tokens, cached
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Analyze this seller's churn risk:\n{json.dumps(seller_data)}"
            }
        ],
        tools=CHURN_SCORER_TOOLS
    )
    return parse_tool_response(response)
```

**Prompt caching is critical:** The system prompt containing domain rules, signal
definitions, and action logic is ~2000 tokens. With 998 sellers per daily batch, caching
saves ~1.9M tokens per run.

---

## 10. Data Pipeline

### Scripts (Build Order)

| # | File | What it does | Priority |
|---|------|-------------|----------|
| 1 | `ingest.py` | Pull scorecard API, flatten JSON, normalize partial months | Day 1 AM |
| 2 | `features.py` | 25 derived ratios + MoM trend vectors | Day 1 AM |
| 3 | `score.py` | 5-dimension churn score for all 998 sellers | Day 1 PM |
| 4 | `agent/state.py` | AgentState TypedDict | Day 1 PM |
| 5 | `agent/graph.py` | LangGraph StateGraph wiring | Day 1 PM |
| 6 | `whatsapp_agent.py` | Skill 2 — Claude + wahelp API + retry logic | Day 1 PM |
| 7 | `call_agent.py` | Skill 3 — Claude + SquadStack API | Day 1 PM |
| 8 | `orchestrator.py` | Daily batch runner — invokes graph per seller | Day 1 PM |
| 9 | `dashboard.py` | Streamlit: 998 sellers sorted by score, real-time | Day 2 AM |
| 10 | `bd_brief.py` | Per-seller PDF/markdown brief for BD calls | Day 2 AM |
| 11 | `ml_model.py` | LightGBM Phase 2 model (stretch goal) | Day 2 PM |

### Feature Engineering — 25 Derived Signals

```python
def engineer_features(seller_months: list) -> dict:
    latest = seller_months[-1]
    prev   = seller_months[-2] if len(seller_months) > 1 else latest

    return {
        # BL Value
        "bl_lapse_rate":        latest['bl_credit_lapsed'] / max(latest['bl_credits_alctd'], 1),
        "bl_util_rate":         latest['bl_cons'] / max(latest['bl_credits_alctd'], 1),
        "blni_rate":            latest['blni'] / max(latest['bl_cons'], 1),
        "slow_response_rate":   latest['cons_grter_1day'] / max(latest['bl_cons'], 1),
        "bl_cons_mom":          (normalize(latest['bl_cons'], latest['year_month']) -
                                 normalize(prev['bl_cons'], prev['year_month'])) / max(prev['bl_cons'], 1),

        # Engagement
        "reply_rate":           latest['replies'] / max(latest['total_enq'], 1),
        "replies_mom":          normalize(latest['replies'], latest['year_month']) -
                                normalize(prev['replies'], prev['year_month']),
        "email_open_rate":      latest['emails_opened'] / max(latest['emails_sent'], 1),
        "notif_loss_rate":      latest['undelivered_notifications'] / max(latest['total_notifications'], 1),
        "hide_rate":            latest['total_hide'] / max(latest['total_enq'], 1),

        # BD Reach
        "bd_unreached":         1 if latest['succ_connect_bd'] == 0 else 0,
        "days_since_bd_call":   compute_days_since(latest['last_succ_bd_call_dt']),
        "days_since_bl_cons":   compute_days_since(latest['last_cons_date']),

        # Communication channel health
        "email_dead":           1 if (latest['emails_sent'] > 5 and latest['emails_opened'] == 0) else 0,
        "notif_unreachable":    1 if (latest['undelivered_notifications'] /
                                     max(latest['total_notifications'], 1)) > 0.8 else 0,

        # Business outcomes
        "connect_rate":         latest['success_connect'] / max(latest['total_enq'], 1),
        "pns_answer_rate":      latest['pns_success_prcnt'] / 100,

        # Catalog
        "catalog_score_delta":  latest['catalog_score'] - prev['catalog_score'],
        "product_net_change":   latest['prd_added'] - latest['deactivated_prd'],
        "neg_cat_pct":          latest['prd_neg_cat'] / max(latest['live_prd_cnt'], 1),

        # Trend momentum
        "consecutive_lapse_increase": compute_lapse_trend(seller_months),
        "replies_3m_slope":           compute_slope([m['replies'] for m in seller_months]),
        "lms_3m_slope":               compute_slope([m['lms_active_days'] for m in seller_months]),

        # Composite red flag count
        "red_flag_count":       0,  # populated by rule_check_node
    }
```

---

## 11. Environment Variables

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# WhatsApp — IndiaMart internal VANI API (Skill 2)
WA_API_KEY=<from Vishal Lodhi>
WA_API_URL=https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php
WA_PLATFORM=WhatsApp_9696

# Call / SquadStack (Skill 3)
SQUADSTACK_API_URL=<SquadStack lead-updated endpoint>
SQUADSTACK_BEARER_TOKEN=<token>
IVR_DIALER_API_URL=<outbound dialer endpoint>
IVR_DIALER_API_KEY=<key>

# BD CRM
BD_CRM_API_URL=<internal CRM endpoint>
BD_CRM_API_KEY=<key>

# Data
SCORECARD_API_URL=<seller scorecard API>
SCORECARD_API_KEY=<key>
MONGO_URI=mongodb://localhost:27017/seller_churn

# Ops
OPS_WHATSAPP_NUMBER=<daily summary recipient>
DASHBOARD_PORT=8501

# LangSmith (tracing)
LANGCHAIN_API_KEY=<langsmith key>
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=seller-churn-agent
```

---

## 12. Action Matrix

| Signal Detected | Agent Action |
|----------------|-------------|
| `replies = 0` for 2+ months | WA: "Are the leads matching your products?" + LMS reactivation guide |
| `lapse_rate > 0.8` | WA: "X leads expiring this week" + BL preference reset offer |
| `email_dead = 1` | Stop all email. Switch to WhatsApp-only. Flag in CRM. |
| `notif_unreachable = 1` | Call agent: "update contact info" IVR flow |
| `succ_connect_bd = 0` for 60+ days | Create BD task: "contact gap alert" with P0 priority |
| `blni_wrng_product > 5` | WA: category fix nudge + link to category update |
| `catalog_score_delta < -15` | Catalog SOS → route to catalog support team |
| `defaulter_flag = yes` | Call agent: PNS rescue IVR immediately |
| `cmplnts_cnt > closed_cmplnts` | Block renewal pitch until complaint closed. Escalate to support. |
| `bl_cons = 0` this month | Call agent: direct BD callback — not automated |
| `prd_neg_cat > 0` | WA: list of negative-category products to remove |

---

## 13. Directory Structure

```
seller_churn/
├── IMPLEMENTATION_PLAN.md            ← this file
│
├── .claude/
│   └── skills/                       ← installed .claude skills
│       ├── skill_data_loader/SKILL.md
│       ├── skill_feature_engineer/SKILL.md
│       ├── skill_rule_checker/SKILL.md
│       ├── skill_churn_scorer/SKILL.md
│       ├── skill_whatsapp_agent/SKILL.md
│       └── skill_alert_logger/SKILL.md
│
├── agent/
│   ├── state.py                      ← AgentState TypedDict
│   ├── nodes.py                      ← 9 node functions
│   ├── graph.py                      ← LangGraph StateGraph wiring
│   └── router.py                     ← band_router conditional edge
│
├── skills/
│   ├── whatsapp-agent/
│   │   └── SKILL.md                  ← seller-whatsapp-agent
│   └── call-agent/
│       └── SKILL.md                  ← seller-call-agent
│
├── scripts/
│   ├── ingest.py                     ← API pull + normalize partial months
│   ├── features.py                   ← 25 derived features + trends
│   ├── score.py                      ← 5-dimension churn score (0–100)
│   ├── orchestrator.py               ← daily batch runner (invokes LangGraph)
│   ├── whatsapp_agent.py             ← Skill 2 — Claude + wahelp API + retry
│   ├── call_agent.py                 ← Skill 3 — Claude + SquadStack API
│   ├── dashboard.py                  ← Streamlit: 998 sellers, sorted by score
│   ├── bd_brief.py                   ← per-seller markdown brief for BD calls
│   └── ml_model.py                   ← LightGBM Phase 2 (stretch goal)
│
├── models/
│   └── churn_model.pkl               ← LightGBM model (Phase 2 stretch)
│
├── data/
│   └── sellers_data_cleaned.xlsx     ← source data (998 sellers, 219 attrs)
│
├── alert_log.csv                     ← cumulative dispatch log (every seller, every run)
├── sara.db                           ← SQLite LangGraph checkpointer (audit replay)
├── config.py                         ← API keys, thresholds, paths
│
├── references/
│   ├── signal-taxonomy.md            ← all 219 fields, organized by churn relevance
│   ├── action-matrix.md              ← full signal → action lookup
│   └── second-workflow.md            ← catalog QA walkthrough
│
├── assets/
│   ├── whatsapp-templates.md         ← message examples per risk band
│   ├── call-scripts.md               ← IVR script templates
│   └── bd-brief-template.md          ← BD call brief output scaffold
│
└── tests/
    ├── test_skills.py
    └── test_graph.py
```

---

## 14. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Development | Claude Code (CLI) | Write, test, iterate all skills and graph nodes |
| Skill System | .claude Skills (6 × .skill packages) | SKILL.md + frontmatter triggers; auto-invoked by Claude Code |
| Agent Framework | LangGraph StateGraph | 9-node typed graph, SqliteSaver checkpointer, conditional routing |
| WhatsApp Dispatch | IndiaMart VANI API (`wahelp.indiamart.com`) | Internal API — personalized messages, no Meta template approval needed |
| Call Dispatch | SquadStack + internal IVR dialer | BLACK tier IVR; RED tier BD CRM tasks |
| ML Scoring | Rule-based (Phase 1) + LightGBM (Phase 2 stretch) | Churn probability 0–100 |
| Data Processing | Pandas + openpyxl | Load Excel; normalize partial months; feature engineering |
| Scheduling | cron — daily at 08:00 | Processes all 998 sellers each morning |
| State Persistence | LangGraph SqliteSaver (`sara.db`) | Per-run AgentState stored; enables audit replay |
| Tracing | LangSmith | Full graph traces per seller; node-level I/O inspection for demo |
| Alert Log | `alert_log.csv` | Cumulative record of all dispatched actions — seller, band, WA status, message ID, call action |
| Dashboard | Streamlit | Live: 998 sellers sorted by score; by-band breakdown; daily summary |

---

## 15. Demo Script (Maps to All 5 Rubric Axes)

**0:00 — The Pain [Axis 1: Impact]**
> "47% of our seller base — 467 sellers — are showing pre-churn signals right now.
> With Catalog packages averaging ₹25,000/year, that's ₹1.1Cr of renewals at risk.
> The BD team has 219 columns of data and no idea who to call."

**0:30 — RAG Score Failure [Axis 5: Skill differentiation]**
> Show the table. RAG=-2 vs RAG=2: lapse rates 0.57 vs 0.43, LMS days 7.9 vs 8.0.
> "The current system is essentially random. We replace it."

**1:00 — The Insight [Axis 4: Robustness]**
> "Sellers don't complain before they churn — they ghost. `replies` has a 19×
> difference between churning and healthy sellers. Complaints and QRF are inverted —
> a seller who complains is still engaged. Our model is built on this insight."

**2:00 — Live Skill 1: Score a Seller**
> Run `ChurnScorer().explain(seller_id="264768627")`. Show the 97/100 score,
> 3 risk factors, and BD talking points in under 3 seconds.

**3:00 — Live Skill 2: WhatsApp Agent**
> Run `WhatsAppAgent().run(seller_id, score=52)`. Show Claude reading the seller's
> signals and writing a personalized message (not a template), then calling the
> `wahelp.indiamart.com` API and getting a 200 back. Show the message on a phone.

**5:00 — Live Skill 3: Call Agent**
> Run `CallAgent().run(seller_id, score=97)`. Show Claude generating the call brief,
> the opening line, the discount recommendation, and the CRM task being created.
> "BD exec opens their dashboard at 8 AM and sees this — not 219 columns."

**7:00 — Batch Dashboard [Axis 2: Pinch Metrics]**
> Show Streamlit: 998 sellers sorted by score. 180 black, 212 red, 75 orange.
> Show `alert_log.csv` — every action timestamped, WA message IDs captured, BD tasks linked.
> "8 AM. BD team has a prioritized call list. Yesterday they had nothing."

**8:00 — LangSmith Trace [Axis 4: Architecture]**
> Open a LangSmith trace for one seller. Show 9 nodes firing: ingest → features → rules
> → score → band_router → whatsapp → log → report. State at every checkpoint.
> "Full auditability. We can replay any seller run from `sara.db`."

**8:30 — Second Workflow [Axis 5 ceiling: Portability]**
> "Same three skills, fed only catalog signals: `cqs`, `catalog_score`, `prd_added`,
> `deactivated_prd`. The Catalog QA team gets a catalog abandonment score — which
> sellers have stopped maintaining their catalog for 60+ days. Zero code change.
> One skill, two business problems."

**9:30 — The Numbers [Axis 2 close]**
> "467 sellers flagged. 20% retention success rate = 93 renewals saved.
> At ₹25,000 average = ₹23L recovered. BD time per seller: 45 min research
> → 3 min reading the Claude brief. Same headcount, 15× coverage."

---

## 16. Second Workflow — Portability Proof (Axis 5)

The same `seller-churn-scorer` skill, with different field weighting, becomes a
**Catalog Abandonment Early-Warning** for the Catalog QA team:

```python
CATALOG_QA_WEIGHTS = {
    "catalog_engagement": 0.40,  # prd_added, prd_modified, catalog_active_days
    "catalog_quality":    0.30,  # cqs, catalog_score, a_rank_mcats
    "product_health":     0.20,  # prod_wo_image, prd_neg_cat, prd_no_prices
    "bd_catalog_support": 0.10,  # succ_connect_bd (BD doing catalog reviews?)
}
```

Same SKILL.md, same agents, different configuration. The QA team gets:
- Which sellers haven't touched their catalog in 60+ days
- Which products urgently need images/descriptions
- Which sellers have products in negative categories (can get blocked)
- Auto-WhatsApp: "3 of your products are missing images — here's how to fix them"

---

## 17. Key Numbers for the Pitch

| Metric | Value |
|--------|-------|
| Sellers at score 100 (rescue today) | **180** |
| Sellers at 80+ (critical) | **392** |
| Existing RAG score accuracy | **Near random** (RAG=-2 ≈ RAG=2) |
| Strongest predictor | **`replies` — 19× gap** |
| BD coverage gap in May | **82% of sellers unreached** |
| Email-dead sellers | **262** (need WhatsApp switch) |
| Notifications > 50% undelivered | **1,343 month-rows (33%)** |
| Catalog sellers' avg lapse rate | **45%** |
| May data normalization factor | **×2.3** (14 days elapsed) |
| Estimated renewals saved (20% conversion) | **93 sellers = ₹23L** |
| BD research time saved per seller | **45 min → 3 min (15× efficiency)** |

---

*Generated for Indiamart Hackathon May 15–16, 2026*
*Skills: seller-churn-scorer · seller-whatsapp-agent · seller-call-agent · skill_alert_logger*
*Architecture: LangGraph StateGraph · SqliteSaver · LangSmith tracing · alert_log.csv*
