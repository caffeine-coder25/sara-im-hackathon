# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Seller Churn Early-Warning System** — a hackathon project (May 15–16, 2026) for IndiaMart that scores 998 sellers daily for churn risk and auto-dispatches WhatsApp messages or BD call briefs via a 9-node LangGraph pipeline.

Core insight: `replies` is a 19× predictor of churn. `rag_score` (current system) is near-random — RAG=2 sellers have a *higher* lapse rate than RAG=1. The new system replaces it with a behavioral 5-dimension weighted score.

## Commands

```bash
# Install Claude skills before running
claude skill install .claude/skills/skill_data_loader/SKILL.md
claude skill install .claude/skills/skill_feature_engineer/SKILL.md
claude skill install .claude/skills/skill_rule_checker/SKILL.md
claude skill install .claude/skills/skill_churn_scorer/SKILL.md
claude skill install .claude/skills/skill_whatsapp_agent/SKILL.md
claude skill install .claude/skills/skill_alert_logger/SKILL.md

# Run data pipeline (in order)
python scripts/ingest.py          # Pull scorecard API, normalize partial months
python scripts/features.py        # 25 derived features + MoM trends
python scripts/score.py           # 5-dimension churn score for all 998 sellers

# Run daily batch
python orchestrator.py            # Invokes LangGraph per seller; writes alert_log.csv

# Dashboard
streamlit run scripts/dashboard.py   # Port 8501 — 998 sellers sorted by score

# Tests
python -m pytest tests/
```

## Architecture

### Data Flow
`ingest.py` → `features.py` → `score.py` → `orchestrator.py` → LangGraph → `alert_log.csv`

### LangGraph StateGraph (9 nodes)
All state lives in `agent/state.py` (`AgentState` TypedDict). The `SqliteSaver` checkpointer writes to `sara.db` after each node — enabling full audit replay via LangSmith.

Node sequence: `ingest` → `features` → `rules` → `score` → **`band_router`** (conditional) → `{call | whatsapp | low}` → `log` → `report`

Routing logic in `agent/router.py`:
- `is_critical_override` or score ≥ 70 → `call` node
- score 25–69 → `whatsapp` node
- score < 25 → `low` (monitor only)

### Three Skills with Live Agents
1. **`seller-churn-scorer`** — scores a seller 0–100, returns top 3 risk factors in plain English and BD talking points. Uses 5 weighted dimensions: Platform Engagement 40%, BL Value ROI 30%, BD Coverage 15%, Business Outcomes 10%, Catalog 5%.
2. **`seller-whatsapp-agent`** — Claude writes a personalized message (not a template) based on seller signals, calls `wahelp.indiamart.com` (action=`vani_send_msg`), 60ms rate limit, one retry after 5s.
3. **`seller-call-agent`** — score ≥ 85: trigger SquadStack IVR immediately; score 70–84: Claude generates call brief + opening line + CRM task (P1); score 50–69: P2 CRM task.

### Dispatch SLA by Band
| Score | Band | Action |
|-------|------|--------|
| 85–100 | BLACK | IVR rescue call, same day |
| 70–84 | RED | BD CRM task P1, call within 1hr |
| 50–69 | ORANGE | WhatsApp first, call within 48hr |
| 25–49 | AMBER | WhatsApp nudge only |
| 0–24 | GREEN | Monitor, no action |

### May Data Normalization
May data was pulled after only 14 days. Raw values must be normalized: `value × (30 / 14)`. Applied in `ingest.py` using `DAYS_ELAPSED = {'202602': 28, '202603': 31, '202604': 30, '202605': 14}`.

### Audit Log
`alert_log.csv` — cumulative, one row per seller per day. Columns: `log_entry_id`, `churn_score`, `risk_band`, `action_taken`, `whatsapp_status`, `whatsapp_message_id`, `call_action`, `bd_task_id`, `dispatch_timestamp`.

## Environment Variables

```bash
ANTHROPIC_API_KEY=...
WA_API_KEY=...                        # IndiaMart VANI API (from Vishal Lodhi)
WA_API_URL=https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php
SQUADSTACK_BEARER_TOKEN=...
IVR_DIALER_API_KEY=...
BD_CRM_API_KEY=...
SCORECARD_API_KEY=...
LANGCHAIN_API_KEY=...                 # LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=seller-churn-agent
```

## Claude API Usage

All Claude calls use `claude-sonnet-4-20250514`. The system prompt (~2000 tokens, contains domain rules + signal definitions) is **prompt-cached** on every call — critical for batch runs of 998 sellers (saves ~1.9M tokens/run).

```python
client.messages.create(
    model="claude-sonnet-4-20250514",
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    ...
)
```

## Second Workflow (Portability)

The same three skills can score **catalog abandonment** for the Catalog QA team by swapping `CATALOG_QA_WEIGHTS` (catalog_engagement 40%, catalog_quality 30%, product_health 20%, bd_catalog_support 10%). Zero code change — demonstrates skill portability for the demo.
