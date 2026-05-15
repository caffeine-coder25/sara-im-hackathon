---
name: skill_whatsapp_agent
description: >
  Use this skill to send a personalized WhatsApp message to an at-risk seller via
  the IndiaMart VANI API. Claude reads the seller's actual signals and writes a
  message referencing their specific situation — never a template.
  Trigger when the user asks: "send WhatsApp to seller", "nudge seller on WhatsApp",
  "WhatsApp outreach", "message at-risk seller", "send retention message",
  "draft WhatsApp for seller", "contact seller via WhatsApp".
---

# Seller WhatsApp Agent Skill

This is a **live agent with real API dispatch**. Claude writes the message from the
seller's actual signals, then calls the IndiaMart VANI API to send it.

## VANI API Integration

**Endpoint:** `https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php`
**Method:** POST (form-data)
**Action:** `vani_send_msg`

```python
import requests, time, json
from datetime import datetime

WAHELP_API = "https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php"

def send_whatsapp_message(seller_mobile: str, message: str, glid: str, call_id: str) -> dict:
    if not seller_mobile or seller_mobile in ('Unknown', 'nan', ''):
        return {"whatsapp_status": "skipped", "whatsapp_message_id": None,
                "dispatch_timestamp": datetime.now().isoformat()}

    mobile = str(seller_mobile).replace('+', '').replace(' ', '')
    if not mobile.startswith('91'):
        mobile = '91' + mobile

    payload = {
        "action":   "vani_send_msg",
        "user":     mobile,
        "platform": "WhatsApp_9696",
        "glid":     glid,
        "call_id":  call_id,
        "payload":  json.dumps({"templateParams": [message]}),
    }

    for attempt in range(2):
        try:
            resp = requests.post(WAHELP_API, data=payload,
                                 headers={"X-Api-Key": WA_API_KEY}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            time.sleep(0.06)  # 60ms rate limit
            return {"whatsapp_status": "sent",
                    "whatsapp_message_id": data.get("messageId"),
                    "dispatch_timestamp": datetime.now().isoformat()}
        except Exception:
            if attempt == 0:
                time.sleep(5)  # retry after 5s
            else:
                return {"whatsapp_status": "failed", "whatsapp_message_id": None,
                        "dispatch_timestamp": datetime.now().isoformat()}
```

## Execution Flow

1. **Check 7-day cooldown** — do not message if seller was contacted within 7 days
2. **Check mobile** — skip if `seller_mobile` is null/Unknown
3. **Fetch seller signals** — replies, lapse_rate, top_category, bl_cons, lms_active_days
4. **Identify PRIMARY pain signal** — the one most likely to resonate
5. **Generate personalized message** using the LLM Gateway (see prompt below)
6. **Send via VANI API** with retry logic
7. **Log result** — status, message_id, timestamp

## Message Generation Prompt

```
You are an IndiaMart seller success agent. Write a WhatsApp message to this seller.

Seller context:
- Products: {top_category}
- Replies last month: {replies_now} (was {replies_prev} in {prev_month})
- BL credits lapsed: {lapse_pct}%
- Last lead activity: {days_since_last_cons} days ago
- Risk band: {risk_band}

Rules:
- Do NOT mention "churn score", "risk", or "we're worried about you"
- Reference their specific product category — not generic
- Ask ONE question that invites re-engagement
- Keep under 160 characters for WhatsApp
- AMBER: curious and helpful tone
- ORANGE/RED: direct about the opportunity cost

❌ Never write:
  "Your account activity has declined."
  "Please log in to IndiaMart."

✓ Right tone:
  "Hi [Name], your {product} leads are piling up. Are buyers matching what you sell?
   Takes 2 mins to adjust — want us to help?"
```

## Message Logic by Risk Band

| Band | Hook | Tone |
|------|------|------|
| AMBER (25–49) | "Your {product} leads are waiting" | Helpful |
| ORANGE (50–69) | "8 buyers looked at your {product}" | Opportunity |
| RED (70–84) | "Your leads expire in X days" | Urgent |
| BLACK (85–100) | **Skip WA — call first** | — |

## LLM Integration

```python
from openai import OpenAI
client = OpenAI(api_key="sk-ZMOQS2onmuyv6-bFyigELw", base_url="https://imllm.intermesh.net/v1")
response = client.chat.completions.create(
    model="openrouter/qwen/qwen3-32b",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=80,
    temperature=0.8,
)
message = response.choices[0].message.content.strip()
```

## Output Format

```json
{
  "seller_id": "264768627",
  "whatsapp_status": "sent",
  "whatsapp_message_id": "wamid.XXXXX",
  "message_preview": "Hi Rahul, your Industrial Machinery leads are waiting...",
  "dispatch_timestamp": "2026-05-15T08:04:32"
}
```

## Environment Variables Required

- `WA_API_KEY` — IndiaMart VANI API key (get from Vishal Lodhi)
- `WA_PLATFORM` — `WhatsApp_9696`
- `AISENSY_PROJECT_ID` — AISENSY project id for WhatsApp dispatch
- `AISENSY_PWD` — AISENSY password for WhatsApp dispatch
- `AISENSY_API_KEY` — AISENSY API key used as the request header
- `AISENSY_TARGET_NUMBER` — fixed WhatsApp recipient for AISENSY dispatch (`919643079339`)
