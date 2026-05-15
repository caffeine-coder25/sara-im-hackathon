---
name: skill_call_agent
description: >
  Use this skill when a seller's churn score requires a phone intervention.
  Score ≥ 85 triggers an immediate SquadStack IVR rescue call. Score 70–84
  creates a prioritized BD CRM task with a Claude-generated call brief.
  Score 50–69 books a scheduled callback with a P2 task.
  Trigger when the user asks: "call at-risk seller", "trigger rescue call",
  "schedule BD callback", "generate call script", "seller needs a call",
  "urgent seller outreach", "create BD task", "call brief for seller",
  "IVR trigger", "SquadStack call".
---

# Seller Call Agent Skill

Two distinct call pathways based on churn score, plus BD call brief generation
using the IndiaMart LLM Gateway.

## Routing Logic

```python
def call_agent_route(churn_score: float, is_critical_override: bool, state: dict) -> dict:
    if is_critical_override or churn_score >= 85:
        return trigger_ivr(state)           # Pathway A — IVR immediately
    elif churn_score >= 70:
        return create_bd_task(state, priority="P1", deadline_hours=1)
    elif churn_score >= 50:
        return create_bd_task(state, priority="P2", deadline_hours=48)
```

## Pathway A — IVR Rescue Call (score ≥ 85)

```python
import requests

def trigger_ivr(state: dict) -> dict:
    resp = requests.post(
        IVR_DIALER_API_URL,
        headers={"Authorization": f"Bearer {SQUADSTACK_BEARER_TOKEN}"},
        json={
            "phone":     state["seller_mobile"],
            "seller_id": state["seller_id"],
            "priority":  "immediate",
            "campaign":  "seller_rescue",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return {"call_action": "IVR_TRIGGERED", "bd_task_id": None, "call_brief_preview": None}
```

## Pathway B/C — BD Call Brief + CRM Task

### Call Brief Generation Prompt

```
You are preparing a BD call brief for a seller retention call at IndiaMart.

Seller: {seller_id}
Service: {service_tier} | Package: ₹{package_value}/year
BD Exec last contacted: {days_since_contact} days ago

Churn signals:
{top_3_risk_factors}

Key data:
- Replies this month: {replies_now} (was {replies_prev} last month)
- BL lapse rate: {lapse_pct}%
- Open complaints: {open_complaints}
- Products: {top_category}

Generate:
1. OPENING LINE — one sentence, does NOT sound like a retention call
2. DISCOVERY QUESTIONS — 2–3, genuinely curious, not leading
3. PAIN HYPOTHESIS — what is most likely wrong
4. RESOLUTION PATH — specific fix BD can offer today
5. DISCOUNT AUTHORITY — only if lapse_rate > 70% AND no complaints AND score ≥ 80

Under 150 words. BD reads this 2 minutes before the call.
```

### Discount Authority
Recommend **15% max** only when ALL three hold:
- `bl_lapse_rate > 0.70`
- `open_complaints == 0`
- `churn_score >= 80`

### CRM Task Creation

```python
def create_bd_task(state: dict, priority: str, deadline_hours: int) -> dict:
    brief = generate_call_brief(state)
    resp  = requests.post(
        BD_CRM_API_URL,
        headers={"X-Api-Key": BD_CRM_API_KEY},
        json={
            "seller_id":      state["seller_id"],
            "priority":       priority,
            "call_brief":     brief["text"],
            "opening_line":   brief["opening_line"],
            "discount_auth":  brief.get("discount_pct", 0),
            "deadline_hours": deadline_hours,
        },
        timeout=10,
    )
    return {
        "call_action":        f"BD_TASK_CREATED_{priority}",
        "bd_task_id":         resp.json().get("task_id"),
        "call_brief_preview": brief["text"][:200],
    }
```

## LLM Integration

```python
from openai import OpenAI
client = OpenAI(api_key="sk-ZMOQS2onmuyv6-bFyigELw", base_url="https://imllm.intermesh.net/v1")
response = client.chat.completions.create(
    model="openrouter/qwen/qwen3-32b",
    messages=[{"role": "user", "content": brief_prompt}],
    max_tokens=400,
    temperature=0.7,
)
```

## Output Format

```json
{
  "seller_id": "264768627",
  "call_action": "BD_TASK_CREATED_P1",
  "bd_task_id": "TASK-001234",
  "call_brief_preview": "Opening: 'Hey Rahul, I was looking at your Textile leads...'",
  "discount_authority": 15
}
```

## Hard Rules

- Never pitch renewal on first call — discover pain first
- Never mention "churn score" or "we're worried" to the seller
- If `open_complaints > 0`: block renewal pitch, escalate to support first
- If BD gap > 30 days with no assigned exec: auto-assign from availability pool

## Environment Variables Required

- `SQUADSTACK_BEARER_TOKEN`, `IVR_DIALER_API_URL`, `IVR_DIALER_API_KEY`
- `BD_CRM_API_URL`, `BD_CRM_API_KEY`
