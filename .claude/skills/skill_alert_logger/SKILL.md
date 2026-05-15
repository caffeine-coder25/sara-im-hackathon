---
name: skill_alert_logger
description: >
  Use this skill to log every seller dispatch action to alert_log.csv and
  generate the daily batch summary report. Every seller processed — regardless
  of band — gets one row written.
  Trigger when the user asks: "log this action", "write to alert log",
  "record dispatch", "generate daily summary", "batch report", "show today's log",
  "how many WhatsApps were sent", "how many IVR calls triggered today".
---

# Alert Logger Skill

The single source of truth for all dispatched actions. Every seller, every run,
every channel — one row in `alert_log.csv`.

## Log Entry Schema

| Column | Type | Example |
|--------|------|---------|
| `log_entry_id` | str | `ALT-264203724-2026-05-15` |
| `run_date` | str | `2026-05-15` |
| `seller_id` | str | `264203724` |
| `seller_name` | str | `Rahul Sharma` |
| `churn_score` | float | `82.4` |
| `risk_band` | str | `BLACK` |
| `top_risk_factors_json` | str (JSON array) | `["Replies: 45→0", ...]` |
| `action_taken` | str | `call_ivr` |
| `whatsapp_status` | str | `sent / failed / skipped` |
| `whatsapp_message_id` | str | `wamid.XXXXX` |
| `call_action` | str | `IVR_TRIGGERED / BD_TASK_CREATED_P1 / BD_TASK_CREATED_P2 / skipped` |
| `bd_task_id` | str | `TASK-001234` |
| `dispatch_timestamp` | str (ISO) | `2026-05-15T08:04:32` |

## log_run() Implementation

```python
import csv, os, json
from datetime import datetime

ALERT_LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'alert_log.csv')

def log_run(state: dict, log_path: str = ALERT_LOG_PATH) -> dict:
    entry_id = f"ALT-{state['seller_id']}-{state['run_date']}"
    row = {
        'log_entry_id':          entry_id,
        'run_date':              state['run_date'],
        'seller_id':             state['seller_id'],
        'seller_name':           state['seller_name'],
        'churn_score':           state['churn_score'],
        'risk_band':             state['risk_band'],
        'top_risk_factors_json': json.dumps(state.get('top_risk_factors', [])),
        'action_taken':          state.get('action_taken', ''),
        'whatsapp_status':       state.get('whatsapp_status', 'skipped'),
        'whatsapp_message_id':   state.get('whatsapp_message_id') or '',
        'call_action':           state.get('call_action', 'skipped'),
        'bd_task_id':            state.get('bd_task_id') or '',
        'dispatch_timestamp':    state.get('dispatch_timestamp', datetime.now().isoformat()),
    }
    file_exists = os.path.isfile(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            w.writeheader()
        w.writerow(row)
    return {'log_entry_id': entry_id}
```

## daily_report() Implementation

```python
import pandas as pd

def daily_report(log_path: str = ALERT_LOG_PATH, run_date: str = None) -> dict:
    df = pd.read_csv(log_path)
    if run_date:
        df = df[df['run_date'] == run_date]
    return {
        'run_date':        run_date or 'all',
        'total_sellers':   len(df),
        'by_band':         df['risk_band'].value_counts().to_dict(),
        'by_action':       df['action_taken'].value_counts().to_dict(),
        'wa_sent':         len(df[df['whatsapp_status'] == 'sent']),
        'wa_failed':       len(df[df['whatsapp_status'] == 'failed']),
        'wa_skipped':      len(df[df['whatsapp_status'] == 'skipped']),
        'ivr_triggered':   len(df[df['call_action'] == 'IVR_TRIGGERED']),
        'bd_tasks_p1':     len(df[df['call_action'] == 'BD_TASK_CREATED_P1']),
        'bd_tasks_p2':     len(df[df['call_action'] == 'BD_TASK_CREATED_P2']),
    }
```

## Daily Summary Sent to Ops

After every batch, the daily report is sent to the OPS WhatsApp number:
```
Daily Churn Batch — 2026-05-15
================================
Sellers processed: 998
⚫ BLACK:  180  |  🔴 RED: 212
🟠 ORANGE: 75  |  🟡 AMBER: 200  |  🟢 GREEN: 331

Actions dispatched:
  📱 WhatsApp sent:     267
  📞 IVR triggered:     180
  📋 BD tasks (P1):     212
  📋 BD tasks (P2):      75

  WA failed: 3  |  WA skipped: 18
```

## Usage in LangGraph

In `agent/nodes.py`:
```python
from skill_alert_logger import log_run

def log_node(state: AgentState) -> AgentState:
    result = log_run(state)
    return {**state, "log_entry_id": result["log_entry_id"]}
```
