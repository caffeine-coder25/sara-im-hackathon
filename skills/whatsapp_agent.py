import json
import time
from datetime import datetime
from typing import Optional

import requests

from config import (
    AISENSY_API_KEY,
    AISENSY_PROJECT_ID,
    AISENSY_PWD,
    AISENSY_TARGET_NUMBER,
    WA_API_URL,
    WA_API_KEY,
    WA_PLATFORM,
)


def _normalize_mobile(mobile: str) -> str:
    value = str(mobile).strip().replace("+", "").replace(" ", "")
    if not value:
        return ""
    if not value.startswith("91"):
        value = "91" + value
    return value


def send_whatsapp_message(
    message: str,
    seller_mobile: Optional[str] = None,
    glid: str = "seller-whatsapp-agent",
    call_id: str = "chat",
) -> dict:
    """Send a WhatsApp message via AISENSY/VANI API.

    If AISENSY_TARGET_NUMBER is configured, the message is always routed to that
    fixed recipient, overriding the seller mobile number.
    """
    mobile = _normalize_mobile(AISENSY_TARGET_NUMBER or seller_mobile or "")
    if not mobile:
        return {
            "whatsapp_status": "skipped",
            "whatsapp_message_id": None,
            "dispatch_timestamp": datetime.now().isoformat(),
            "recipient": None,
        }

    payload = {
        "action": "vani_send_msg",
        "user": mobile,
        "platform": WA_PLATFORM,
        "glid": glid,
        "call_id": call_id,
        "payload": json.dumps({"templateParams": [message]}),
    }
    if AISENSY_PROJECT_ID:
        payload["project_id"] = AISENSY_PROJECT_ID
    if AISENSY_PWD:
        payload["pwd"] = AISENSY_PWD

    headers = {"X-Api-Key": AISENSY_API_KEY or WA_API_KEY}

    for attempt in range(2):
        try:
            resp = requests.post(WA_API_URL, data=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            time.sleep(0.06)
            return {
                "whatsapp_status": "sent",
                "whatsapp_message_id": data.get("messageId"),
                "dispatch_timestamp": datetime.now().isoformat(),
                "recipient": mobile,
                "response": data,
            }
        except Exception as exc:
            if attempt == 0:
                time.sleep(5)
                continue
            return {
                "whatsapp_status": "failed",
                "whatsapp_message_id": None,
                "dispatch_timestamp": datetime.now().isoformat(),
                "recipient": mobile,
                "error": str(exc),
            }
