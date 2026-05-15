"""Generate sample sellers_data_scored.csv for dashboard development."""
import pandas as pd
import numpy as np
import random
import os

random.seed(42)
np.random.seed(42)

MONTHS = ["202602", "202603", "202604", "202605"]
SERVICES = ["Catalog", "Lead Manager", "MaxBiz", "TrustSEAL"]
CATEGORIES = [
    "Industrial Machinery", "Textile & Apparel", "Chemicals", "Electronics",
    "Auto Parts", "Furniture", "Packaging Materials", "Food Processing",
    "Construction", "Medical Equipment"
]
CITIES = ["Mumbai", "Delhi", "Ahmedabad", "Chennai", "Kolkata", "Pune", "Hyderabad", "Surat"]
NAMES = [
    "Rahul Sharma", "Priya Patel", "Amit Kumar", "Sunita Singh", "Vijay Mehta",
    "Kavita Joshi", "Deepak Gupta", "Anita Rao", "Manoj Tiwari", "Pooja Verma",
    "Suresh Nair", "Rekha Agarwal", "Ramesh Chandra", "Meena Pillai", "Arun Bose",
]

BANDS = {
    "BLACK": (85, 100),
    "RED":   (70, 84),
    "ORANGE":(50, 69),
    "AMBER": (25, 49),
    "GREEN": (0, 24),
}

BAND_COUNTS = {"BLACK": 180, "RED": 212, "ORANGE": 75, "AMBER": 200, "GREEN": 331}

rows = []
seller_id = 264000000

for band, count in BAND_COUNTS.items():
    lo, hi = BANDS[band]
    for _ in range(count):
        sid = str(seller_id)
        seller_id += random.randint(100, 9999)
        name    = random.choice(NAMES) + f" ({random.randint(10,99)})"
        mobile  = f"9{random.randint(600000000, 999999999)}"
        service = random.choice(SERVICES)
        city    = random.choice(CITIES)
        cat     = random.choice(CATEGORIES)
        pkg_val = random.choice([12000, 18000, 25000, 35000, 50000])

        score = round(random.uniform(lo, hi), 1)

        # Signals — correlated with band
        replies_base  = max(0, int(np.random.normal({"BLACK":2,"RED":8,"ORANGE":20,"AMBER":45,"GREEN":90}[band], 5)))
        lapse_rate    = round(random.uniform(*{"BLACK":(0.7,1.0),"RED":(0.5,0.8),"ORANGE":(0.3,0.6),"AMBER":(0.1,0.4),"GREEN":(0.0,0.2)}[band]), 2)
        bd_days       = {"BLACK": random.randint(45,120), "RED": random.randint(30,90), "ORANGE": random.randint(15,60), "AMBER": random.randint(5,30), "GREEN": random.randint(0,15)}[band]
        email_dead    = 1 if band in ("BLACK","RED") and random.random() < 0.5 else 0
        notif_loss    = round(random.uniform(*{"BLACK":(0.6,1.0),"RED":(0.4,0.8),"ORANGE":(0.2,0.5),"AMBER":(0.1,0.3),"GREEN":(0.0,0.15)}[band]), 2)

        # 4-month trend
        replies_trend = []
        lapse_trend   = []
        bl_cons_trend = []
        base_r = replies_base + random.randint(20, 60)
        base_l = max(0.0, lapse_rate - random.uniform(0.1, 0.3))
        base_b = random.randint(20, 80)
        for m in MONTHS:
            decay = 1.0 if band == "GREEN" else random.uniform(0.6, 0.95)
            replies_trend.append(max(0, int(base_r * decay)))
            base_r = replies_trend[-1]
            lapse_trend.append(round(min(1.0, base_l + random.uniform(0, 0.05)), 2))
            base_l = lapse_trend[-1]
            bl_cons_trend.append(max(0, int(base_b * (decay if band != "GREEN" else 1.0))))
            base_b = bl_cons_trend[-1]

        top_risks = []
        if replies_base == 0:
            top_risks.append("Replies collapsed to 0 — seller has stopped responding to leads entirely")
        elif replies_base < 10:
            top_risks.append(f"Reply rate critically low ({replies_base} replies/month, was {replies_trend[1]})")
        if lapse_rate > 0.7:
            top_risks.append(f"{int(lapse_rate*100)}% of BL credits lapsed unused this month")
        if bd_days > 45:
            top_risks.append(f"No BD contact in {bd_days} days — seller has been ignored")
        if email_dead:
            top_risks.append("Email channel dead — 0% open rate on 5+ sent emails")
        if notif_loss > 0.7:
            top_risks.append(f"{int(notif_loss*100)}% notifications undelivered — contact info stale")
        if not top_risks:
            top_risks.append(f"BL consumption trending down ({bl_cons_trend[0]}→{bl_cons_trend[-1]})")
        top_risks = top_risks[:3]

        action = (
            "IVR_TRIGGERED" if score >= 85 else
            "BD_TASK_CREATED_P1" if score >= 70 else
            "whatsapp" if score >= 25 else
            "monitor"
        )

        rows.append({
            "seller_id":         sid,
            "seller_name":       name,
            "seller_mobile":     mobile,
            "service":           service,
            "city":              city,
            "top_category":      cat,
            "package_value":     pkg_val,
            "churn_score":       score,
            "risk_band":         band,
            "top_risk_factors":  " | ".join(top_risks),
            "replies_202602":    replies_trend[0],
            "replies_202603":    replies_trend[1],
            "replies_202604":    replies_trend[2],
            "replies_202605":    replies_trend[3],
            "lapse_rate_202602": lapse_trend[0],
            "lapse_rate_202603": lapse_trend[1],
            "lapse_rate_202604": lapse_trend[2],
            "lapse_rate_202605": lapse_trend[3],
            "bl_cons_202602":    bl_cons_trend[0],
            "bl_cons_202603":    bl_cons_trend[1],
            "bl_cons_202604":    bl_cons_trend[2],
            "bl_cons_202605":    bl_cons_trend[3],
            "lapse_rate":        lapse_rate,
            "email_dead":        email_dead,
            "notif_loss_rate":   notif_loss,
            "bd_days_gap":       bd_days,
            "action_taken":      action,
            "dim_engagement":    round(score * 0.40 * random.uniform(0.7, 1.0), 1),
            "dim_roi":           round(score * 0.30 * random.uniform(0.7, 1.0), 1),
            "dim_bd_coverage":   round(score * 0.15 * random.uniform(0.7, 1.0), 1),
            "dim_biz_outcomes":  round(score * 0.10 * random.uniform(0.7, 1.0), 1),
            "dim_catalog":       round(score * 0.05 * random.uniform(0.7, 1.0), 1),
        })

df = pd.DataFrame(rows).sort_values("churn_score", ascending=False).reset_index(drop=True)
out = os.path.join(os.path.dirname(__file__), "sellers_data_scored.csv")
df.to_csv(out, index=False)
print(f"Wrote {len(df)} sellers to {out}")
print(df["risk_band"].value_counts().to_string())
