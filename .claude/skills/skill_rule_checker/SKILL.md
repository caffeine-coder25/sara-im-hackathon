---
name: skill_rule_checker
description: >
  Use this skill to evaluate 8 hard red-flag rules against a seller's derived
  features. If any rule fires, sets is_critical_override=True which routes the
  seller directly to the call agent regardless of their numeric score.
  Trigger when the user asks: "check red flags for seller", "hard rules check",
  "critical override", "rule-based check", "flag critical sellers",
  "override scoring with rules".
---

# Rule Checker Skill

Evaluates 8 deterministic rules on top of the numeric score. A single firing
rule sets `is_critical_override=True` and forces routing to `call_node`.

## 8 Hard Red-Flag Rules

```python
def check_rules(features: dict, latest_month: dict) -> dict:
    red_flags = []

    # Rule 1: Complete silence — zero replies for 2+ consecutive months
    if features.get("replies_3m_slope", 0) < 0 and latest_month.get("replies", 1) == 0:
        red_flags.append("RULE_ZERO_REPLIES_2M")

    # Rule 2: All BL credits lapsing (≥95%)
    if features.get("bl_lapse_rate", 0) >= 0.95:
        red_flags.append("RULE_FULL_LAPSE")

    # Rule 3: Defaulter flag active
    if str(latest_month.get("defaulter_flag", "")).lower() == "yes":
        red_flags.append("RULE_DEFAULTER")

    # Rule 4: BD gap > 90 days AND score > 60
    if features.get("days_since_bd_call", 0) > 90:
        red_flags.append("RULE_BD_ABANDONED_90D")

    # Rule 5: Email dead AND notifications unreachable — no channel left
    if features.get("email_dead", 0) and features.get("notif_unreachable", 0):
        red_flags.append("RULE_ALL_CHANNELS_DEAD")

    # Rule 6: BL consumption at zero this month
    if latest_month.get("bl_cons", -1) == 0:
        red_flags.append("RULE_ZERO_BL_CONS")

    # Rule 7: 3 consecutive months of increasing lapse rate
    if features.get("consecutive_lapse_increase", 0) >= 3:
        red_flags.append("RULE_LAPSE_ACCELERATING_3M")

    # Rule 8: More open complaints than closed (actively deteriorating)
    if (latest_month.get("cmplnts_cnt", 0) > latest_month.get("closed_cmplnts", 0)
            and latest_month.get("cmplnts_cnt", 0) > 0):
        red_flags.append("RULE_COMPLAINTS_GROWING")

    return {
        "red_flags":            red_flags,
        "is_critical_override": len(red_flags) > 0,
        "red_flag_count":       len(red_flags),
    }
```

## Override Behavior

If `is_critical_override=True`, the LangGraph `band_router` routes directly to
`call_node` — bypassing the numeric score threshold entirely:

```python
# agent/router.py
def band_router(state: AgentState) -> str:
    if state['is_critical_override']:
        return 'call'    # Any red flag → immediate call
    elif state['churn_score'] >= 85:
        return 'call'
    elif state['churn_score'] >= 25:
        return 'whatsapp'
    else:
        return 'skip'
```

## Output Format

```json
{
  "red_flags": ["RULE_ZERO_REPLIES_2M", "RULE_ALL_CHANNELS_DEAD"],
  "is_critical_override": true,
  "red_flag_count": 2
}
```

Empty `red_flags` list means no override — scoring proceeds normally.
