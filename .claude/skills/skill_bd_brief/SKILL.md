---
name: skill_bd_brief
description: >
  Use this skill to generate a per-seller BD call brief using the IndiaMart
  LLM Gateway. Produces an opening line, discovery questions, pain hypothesis,
  resolution path, and optional discount recommendation.
  Trigger when the user asks: "generate call brief", "BD brief for seller",
  "talking points for seller", "what should BD say", "prepare for call",
  "call script", "retention brief", "brief for BD exec".
---

# BD Brief Generator Skill

Generates a structured call brief that a BD exec reads 2 minutes before calling
an at-risk seller. Uses `openrouter/qwen/qwen3-32b` via the IM LLM Gateway.

## LLM Call

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-ZMOQS2onmuyv6-bFyigELw",
    base_url="https://imllm.intermesh.net/v1",
)

def generate_bd_brief(seller: dict) -> dict:
    prompt = build_brief_prompt(seller)
    response = client.chat.completions.create(
        model="openrouter/qwen/qwen3-32b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.7,
    )
    raw = response.choices[0].message.content.strip()
    return parse_brief(raw)
```

## Prompt Template

```
You are preparing a BD call brief for a seller retention call at IndiaMart.

Seller: {seller_name} (ID: {seller_id})
Service: {service} | Package: ₹{package_value:,}/year | City: {city}
Products: {top_category}
BD Exec: {exec_name} (last contacted: {bd_days_gap} days ago)
Churn Score: {churn_score}/100 | Band: {risk_band}

Top Risk Signals:
{risk_factors_bulleted}

Key metrics:
- Replies (Feb→Mar→Apr→May): {replies_trend}
- BL lapse rate: {lapse_pct}%
- Email dead: {email_dead}
- Open complaints: {open_complaints}

Generate a call brief with these sections:
**OPENING LINE**: One sentence. Do NOT sound like a retention call. Reference
  their specific product category or a recent event.
**DISCOVERY** (2–3 questions): Genuinely curious, not leading. Uncover the real pain.
**PAIN HYPOTHESIS**: What is most likely wrong based on the signals above?
**RESOLUTION**: What specific fix can the BD exec offer in this call?
**DISCOUNT**: {discount_instruction}

Keep under 150 words total. BD reads this 2 minutes before the call.
Use plain text, no markdown.
```

## Discount Instruction Logic

```python
def discount_instruction(seller: dict) -> str:
    if (seller['lapse_rate'] > 0.70
            and seller.get('open_complaints', 0) == 0
            and seller['churn_score'] >= 80):
        return "You have authority to offer up to 15% renewal discount if seller is genuinely considering leaving."
    return "Do not mention discounts in this call."
```

## Output Parsing

```python
def parse_brief(raw: str) -> dict:
    return {
        "text":         raw,
        "opening_line": extract_section(raw, "OPENING LINE"),
        "discovery":    extract_section(raw, "DISCOVERY"),
        "hypothesis":   extract_section(raw, "PAIN HYPOTHESIS"),
        "resolution":   extract_section(raw, "RESOLUTION"),
        "discount_pct": 15 if "15%" in raw else 0,
    }

def extract_section(text: str, header: str) -> str:
    import re
    pattern = rf"{header}[:\s]*(.*?)(?=\n[A-Z]{{3}}|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""
```

## Example Output

```
OPENING LINE: "Hey Rahul, I was looking at some of the Textile Machinery
  leads in your area — there's been a lot of activity lately."

DISCOVERY:
  1. Are the buyers you're seeing relevant to what you actually manufacture?
  2. Have there been any fulfilment challenges on your end this quarter?
  3. What would make this platform worth your time again?

PAIN HYPOTHESIS: Seller has likely seen poor lead quality in their category
  and stopped engaging rather than complaining. The 97% lapse rate suggests
  they're paying but not getting value.

RESOLUTION: Offer a category-targeting review session — 20 minutes with a
  catalog specialist to re-tune their buyer filters.

DISCOUNT: You have authority to offer up to 15% renewal discount if seller
  is genuinely considering leaving.
```

## When to Use vs skill_call_agent

- **skill_bd_brief**: Use standalone when you only need the brief text (e.g. for the dashboard preview, PDF export, or drafting before a call).
- **skill_call_agent**: Use when you need to both generate the brief AND create a CRM task or trigger IVR.
