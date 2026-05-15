"""
Seller Churn Early-Warning Dashboard
Run: streamlit run scripts/dashboard.py
"""
import os
import sys
import json
import time

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Config ──────────────────────────────────────────────────────────────────

BAND_COLOR = {
    "BLACK":  "#1a1a1a",
    "RED":    "#e53e3e",
    "ORANGE": "#dd6b20",
    "AMBER":  "#d69e2e",
    "GREEN":  "#38a169",
}
BAND_BG = {
    "BLACK":  "#fff5f5",
    "RED":    "#fff5f5",
    "ORANGE": "#fffaf0",
    "AMBER":  "#fffff0",
    "GREEN":  "#f0fff4",
}
BAND_EMOJI = {"BLACK": "⚫", "RED": "🔴", "ORANGE": "🟠", "AMBER": "🟡", "GREEN": "🟢"}

MONTHS       = ["202602", "202603", "202604", "202605"]
MONTH_LABELS = ["Feb 26", "Mar 26", "Apr 26", "May 26"]

DATA_PATH     = os.path.join(os.path.dirname(__file__), "..", "data", "sellers_data_scored.csv")
ALERT_LOG     = os.path.join(os.path.dirname(__file__), "..", "alert_log.csv")

# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        st.error(f"Data file not found: {DATA_PATH}\nRun `python data/generate_sample.py` first.")
        st.stop()
    df = pd.read_csv(DATA_PATH, dtype={"seller_id": str})
    return df.sort_values("churn_score", ascending=False).reset_index(drop=True)

@st.cache_data(ttl=60)
def load_alert_log() -> pd.DataFrame:
    if os.path.exists(ALERT_LOG):
        return pd.read_csv(ALERT_LOG, dtype={"seller_id": str})
    return pd.DataFrame()

# ── LLM helpers ──────────────────────────────────────────────────────────────

def _clean_wa_message(text: str) -> str:
    """Strip model preamble lines that leak into the output."""
    import re
    lines = text.strip().splitlines()
    # Drop any line that looks like thinking/meta commentary
    skip_patterns = re.compile(
        r"^(okay|sure|here|i need|i will|i'll|let me|this is|below is|"
        r"the message|whatsapp message|message:|note:|draft:)",
        re.IGNORECASE,
    )
    cleaned = [l for l in lines if not skip_patterns.match(l.strip())]
    return " ".join(cleaned).strip().strip('"').strip("'")

def _llm_client():
    from openai import OpenAI
    return OpenAI(api_key="sk-ZMOQS2onmuyv6-bFyigELw", base_url="https://imllm.intermesh.net/v1")

def send_via_wahelp(message: str) -> dict:
    """Send a free-flow WhatsApp message via IndiaMart VANI API."""
    import requests as _req
    from config import WA_API_KEY, AISENSY_TARGET_NUMBER
    mobile = AISENSY_TARGET_NUMBER  # always send to fixed demo number

    url = (
        f"https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php"
        f"?action=sendMessage&user={mobile}&api_key={WA_API_KEY}"
    )
    payload_json = json.dumps({
        "messaging_product": "whatsapp",
        "to":                mobile,
        "type":              "text",
        "text":              {"preview_url": False, "body": message},
        "sent_from_CWI":     True,
        "platform":          "WhatsApp_9910273309",
    })
    debug = {
        "url":            url,
        "method":         "POST",
        "headers":        {"Content-Type": "application/x-www-form-urlencoded"},
        "payload":        json.loads(payload_json),
    }
    resp = _req.post(
        url,
        data={"payload": payload_json},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    debug["response_status"] = resp.status_code
    try:
        debug["response_body"] = resp.json()
    except Exception:
        debug["response_body"] = resp.text
    return debug

def _extract_content(resp) -> str:
    """Qwen3 thinking mode can return content=None with text in reasoning_content."""
    msg = resp.choices[0].message
    text = getattr(msg, "content", None)
    if not text:
        text = getattr(msg, "reasoning_content", None)
    if not text:
        # some gateway wrappers put it under choices[0].text
        text = getattr(resp.choices[0], "text", None)
    return (text or "").strip()

# ── LLM brief generation ─────────────────────────────────────────────────────

def generate_bd_brief(seller: pd.Series) -> str:
    try:
        client = _llm_client()
        risk_factors = seller.get("top_risk_factors", "")
        prompt = f"""You are preparing a BD call brief for a seller retention call at IndiaMart.

Seller: {seller['seller_name']} (ID: {seller['seller_id']})
Service: {seller['service']} | Package: ₹{seller['package_value']:,}/year
City: {seller['city']} | Category: {seller['top_category']}
Churn Score: {seller['churn_score']}/100 | Risk Band: {seller['risk_band']}
BD Gap: {seller['bd_days_gap']} days since last contact

Top Risk Signals:
{chr(10).join(f'• {r}' for r in risk_factors.split(' | '))}

Reply trend (Feb→May): {seller['replies_202602']}→{seller['replies_202603']}→{seller['replies_202604']}→{seller['replies_202605']}
BL Lapse Rate: {int(seller['lapse_rate']*100)}%
Email Dead: {'Yes' if seller['email_dead'] else 'No'}

Generate a concise BD call brief with:
1. OPENING LINE (1 sentence — do not sound like a retention call)
2. DISCOVERY QUESTIONS (2-3, genuinely curious)
3. PAIN HYPOTHESIS (what's most likely wrong)
4. RESOLUTION (what BD can offer today)

Keep under 150 words. BD reads this 2 minutes before the call."""

        resp = client.chat.completions.create(
            model="openrouter/qwen/qwen3-32b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.7,
        )
        return _extract_content(resp) or "(No response from model)"
    except Exception as e:
        return f"(LLM unavailable: {e})"

def generate_whatsapp_message(seller: pd.Series) -> str:
    try:
        client = _llm_client()
        prompt = f"""Write a short WhatsApp message (max 80 chars) to re-engage an IndiaMart seller.

Seller: {seller['seller_name']} | Products: {seller['top_category']}
Replies dropped to {seller['replies_202605']} (was {seller['replies_202602']}). Lapse: {int(seller['lapse_rate']*100)}%.

Rules: mention their product, ask ONE question, no "risk"/"score" words, max 80 chars.
Output the message only — no quotes, no explanation."""

        resp = client.chat.completions.create(
            model="openrouter/qwen/qwen3-32b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0.8,
        )
        return _clean_wa_message(_extract_content(resp)) or "(No response from model)"
    except Exception as e:
        return f"(LLM unavailable: {e})"

# ── Chart helpers ─────────────────────────────────────────────────────────────

def gauge_chart(score: float, band: str) -> go.Figure:
    color = BAND_COLOR[band]
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=score,
        delta={"reference": 50, "valueformat": ".1f"},
        title={"text": f"Churn Score<br><span style='font-size:0.8em;color:{color}'>{BAND_EMOJI[band]} {band}</span>"},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar":  {"color": color, "thickness": 0.3},
            "steps": [
                {"range": [0,  25],  "color": "#c6f6d5"},
                {"range": [25, 50],  "color": "#fefcbf"},
                {"range": [50, 70],  "color": "#feebc8"},
                {"range": [70, 85],  "color": "#fed7d7"},
                {"range": [85, 100], "color": "#2d3748"},
            ],
            "threshold": {"line": {"color": color, "width": 4}, "thickness": 0.75, "value": score},
        },
        number={"font": {"size": 48, "color": color}, "suffix": "/100"},
    ))
    fig.update_layout(height=280, margin=dict(t=60, b=0, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)")
    return fig

def dimension_radar(seller: pd.Series) -> go.Figure:
    dims   = ["Engagement\n(40%)", "BL ROI\n(30%)", "BD Coverage\n(15%)", "Biz Outcomes\n(10%)", "Catalog\n(5%)"]
    cols   = ["dim_engagement", "dim_roi", "dim_bd_coverage", "dim_biz_outcomes", "dim_catalog"]
    maxes  = [40, 30, 15, 10, 5]
    values = [min(seller.get(c, 0), m) for c, m in zip(cols, maxes)]
    pct    = [round(v / m * 100) for v, m in zip(values, maxes)]

    fig = go.Figure(go.Scatterpolar(
        r=pct + [pct[0]],
        theta=dims + [dims[0]],
        fill="toself",
        fillcolor=f"rgba(229,62,62,0.2)",
        line=dict(color=BAND_COLOR[seller["risk_band"]], width=2),
        name="Risk Score",
    ))
    fig.add_trace(go.Scatterpolar(
        r=[100] * (len(dims) + 1),
        theta=dims + [dims[0]],
        fill="toself",
        fillcolor="rgba(0,128,0,0.05)",
        line=dict(color="rgba(56,161,105,0.3)", width=1, dash="dot"),
        name="Max",
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        height=300,
        margin=dict(t=30, b=20, l=40, r=40),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def reply_trend_chart(seller: pd.Series) -> go.Figure:
    replies = [seller.get(f"replies_{m}", 0) for m in MONTHS]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=MONTH_LABELS, y=replies,
        mode="lines+markers+text",
        text=replies,
        textposition="top center",
        line=dict(color=BAND_COLOR[seller["risk_band"]], width=3),
        marker=dict(size=10, color=BAND_COLOR[seller["risk_band"]]),
        fill="tozeroy",
        fillcolor=f"rgba(229,62,62,0.08)",
        name="Replies",
    ))
    fig.update_layout(
        title="Reply Trend (4 months)",
        xaxis_title=None, yaxis_title="Replies",
        height=220,
        margin=dict(t=40, b=20, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        showlegend=False,
    )
    return fig

def lapse_trend_chart(seller: pd.Series) -> go.Figure:
    lapse = [seller.get(f"lapse_rate_{m}", 0) * 100 for m in MONTHS]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=MONTH_LABELS, y=lapse,
        marker_color=[BAND_COLOR[seller["risk_band"]]] * 4,
        text=[f"{v:.0f}%" for v in lapse],
        textposition="outside",
        name="Lapse Rate",
    ))
    fig.update_layout(
        title="BL Credit Lapse Rate (4 months)",
        xaxis_title=None, yaxis_title="%",
        yaxis=dict(range=[0, 115]),
        height=220,
        margin=dict(t=40, b=20, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        showlegend=False,
    )
    return fig

def bl_cons_chart(seller: pd.Series) -> go.Figure:
    bl = [seller.get(f"bl_cons_{m}", 0) for m in MONTHS]
    fig = go.Figure(go.Scatter(
        x=MONTH_LABELS, y=bl,
        mode="lines+markers+text",
        text=bl,
        textposition="top center",
        line=dict(color="#3182ce", width=2.5),
        marker=dict(size=8),
        fill="tozeroy",
        fillcolor="rgba(49,130,206,0.08)",
    ))
    fig.update_layout(
        title="BL Consumption Trend",
        xaxis_title=None, yaxis_title="BL Credits",
        height=220,
        margin=dict(t=40, b=20, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        showlegend=False,
    )
    return fig

def band_donut(df: pd.DataFrame) -> go.Figure:
    counts = df["risk_band"].value_counts().reindex(["BLACK","RED","ORANGE","AMBER","GREEN"], fill_value=0)
    fig = go.Figure(go.Pie(
        labels=[f"{BAND_EMOJI[b]} {b}" for b in counts.index],
        values=counts.values,
        hole=0.55,
        marker_colors=[BAND_COLOR[b] for b in counts.index],
        textinfo="value+percent",
        hoverinfo="label+value",
    ))
    fig.update_layout(
        height=300,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=True,
        legend=dict(orientation="v", x=1.0, y=0.5),
    )
    return fig

def score_histogram(df: pd.DataFrame) -> go.Figure:
    fig = px.histogram(
        df, x="churn_score", nbins=40,
        color="risk_band",
        color_discrete_map=BAND_COLOR,
        category_orders={"risk_band": ["BLACK","RED","ORANGE","AMBER","GREEN"]},
        labels={"churn_score": "Churn Score", "risk_band": "Band"},
    )
    fig.update_layout(
        height=280, bargap=0.05,
        margin=dict(t=20, b=40, l=40, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        showlegend=False,
    )
    return fig

# ── Page: Overview ────────────────────────────────────────────────────────────

def page_overview(df: pd.DataFrame):
    st.title("Seller Churn Early-Warning System")
    st.caption("Hackathon May 15–16, 2026  ·  998 sellers  ·  4-month behavioral scoring")

    # KPI row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    total       = len(df)
    at_risk     = len(df[df["churn_score"] >= 50])
    rescue_now  = len(df[df["risk_band"] == "BLACK"])
    critical    = len(df[df["risk_band"] == "RED"])
    wa_today    = len(df[df["risk_band"].isin(["ORANGE", "AMBER"])])
    revenue_risk = df[df["churn_score"] >= 50]["package_value"].sum()

    c1.metric("Total Sellers",    f"{total:,}")
    c2.metric("At Risk (≥50)",    f"{at_risk:,}",    f"{at_risk/total*100:.0f}%")
    c3.metric("⚫ Rescue Now",    f"{rescue_now:,}", "Call today")
    c4.metric("🔴 Critical",      f"{critical:,}",   "Call this week")
    c5.metric("📱 WhatsApp Today", f"{wa_today:,}")
    c6.metric("₹ Revenue at Risk", f"₹{revenue_risk/1e5:.1f}L")

    st.divider()

    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.subheader("Distribution by Risk Band")
        st.plotly_chart(band_donut(df), use_container_width=True)
    with col_right:
        st.subheader("Score Distribution")
        st.plotly_chart(score_histogram(df), use_container_width=True)

    st.divider()
    st.subheader("Top 50 At-Risk Sellers")

    band_filter = st.multiselect(
        "Filter by band",
        ["BLACK","RED","ORANGE","AMBER","GREEN"],
        default=["BLACK","RED"],
    )
    service_filter = st.multiselect("Filter by service", sorted(df["service"].unique()), default=[])

    view = df[df["risk_band"].isin(band_filter)] if band_filter else df
    if service_filter:
        view = view[view["service"].isin(service_filter)]

    view = view.head(50)[["seller_id","seller_name","service","city","churn_score","risk_band",
                            "replies_202605","lapse_rate","bd_days_gap","action_taken","package_value"]]
    view = view.rename(columns={
        "seller_id": "ID", "seller_name": "Name", "service": "Service",
        "city": "City", "churn_score": "Score", "risk_band": "Band",
        "replies_202605": "Replies (May)", "lapse_rate": "Lapse Rate",
        "bd_days_gap": "BD Gap (days)", "action_taken": "Action",
        "package_value": "Pkg Value (₹)",
    })

    def style_band(val):
        color = BAND_COLOR.get(val, "")
        bg    = BAND_BG.get(val, "")
        return f"background-color:{bg};color:{color};font-weight:bold" if color else ""

    def style_score(val):
        if val >= 85:   return "background-color:#2d3748;color:white;font-weight:bold"
        elif val >= 70: return "background-color:#fed7d7;color:#c53030;font-weight:bold"
        elif val >= 50: return "background-color:#feebc8;color:#c05621"
        elif val >= 25: return "background-color:#fefcbf;color:#975a16"
        return "background-color:#c6f6d5;color:#276749"

    styled = view.style.applymap(style_band, subset=["Band"]).applymap(style_score, subset=["Score"])
    st.dataframe(styled, use_container_width=True, height=500)

# ── Page: Seller Detail ───────────────────────────────────────────────────────

def page_seller_detail(df: pd.DataFrame):
    st.title("Seller Deep-Dive")

    # Search
    col_search, col_band = st.columns([3, 1])
    with col_search:
        query = st.text_input("Search by Seller ID or Name", placeholder="e.g. 264768627 or Rahul")
    with col_band:
        band_jump = st.selectbox("Or jump to band", ["— All —", "BLACK", "RED", "ORANGE", "AMBER", "GREEN"])

    filtered = df.copy()
    if query:
        q = query.strip().lower()
        filtered = filtered[
            filtered["seller_id"].str.contains(q, case=False) |
            filtered["seller_name"].str.lower().str.contains(q)
        ]
    if band_jump != "— All —":
        filtered = filtered[filtered["risk_band"] == band_jump]

    if filtered.empty:
        st.warning("No sellers match your search.")
        return

    options = filtered.apply(
        lambda r: f"{BAND_EMOJI[r['risk_band']]} [{r['churn_score']:.0f}] {r['seller_name']} ({r['seller_id']})", axis=1
    ).tolist()
    selected_label = st.selectbox("Select Seller", options)
    idx = options.index(selected_label)
    seller = filtered.iloc[idx]

    band  = seller["risk_band"]
    score = seller["churn_score"]
    color = BAND_COLOR[band]

    # ── Header strip ──────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background:{BAND_BG[band]};border-left:6px solid {color};
                border-radius:8px;padding:16px 20px;margin-bottom:16px">
        <h2 style="margin:0;color:{color}">{BAND_EMOJI[band]} {seller['seller_name']}</h2>
        <p style="margin:4px 0 0 0;color:#555">
            ID: <strong>{seller['seller_id']}</strong> &nbsp;|&nbsp;
            {seller['service']} &nbsp;|&nbsp; {seller['city']} &nbsp;|&nbsp;
            {seller['top_category']} &nbsp;|&nbsp;
            ₹{seller['package_value']:,}/year
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Score + Dimensions ───────────────────────────────────────────────────
    col_gauge, col_radar = st.columns([1, 1])
    with col_gauge:
        st.plotly_chart(gauge_chart(score, band), use_container_width=True)
    with col_radar:
        st.subheader("Risk Dimension Breakdown")
        st.plotly_chart(dimension_radar(seller), use_container_width=True)

    # ── Risk factors ─────────────────────────────────────────────────────────
    st.subheader("Top Risk Factors")
    risks = seller.get("top_risk_factors", "").split(" | ")
    for i, r in enumerate(risks):
        if r.strip():
            st.markdown(f"""
            <div style="background:#fff5f5;border-left:4px solid {color};
                        border-radius:6px;padding:10px 14px;margin-bottom:8px">
                <strong>#{i+1}</strong> {r}
            </div>""", unsafe_allow_html=True)

    # ── Signal chips ─────────────────────────────────────────────────────────
    st.subheader("Signal Flags")
    flags = []
    if seller["email_dead"]:
        flags.append(("Email Dead", "#e53e3e", "Stop all email — 0% open rate"))
    if seller["notif_loss_rate"] > 0.7:
        flags.append((f"Notif Loss {int(seller['notif_loss_rate']*100)}%", "#dd6b20", "Contact info stale"))
    if seller["bd_days_gap"] > 45:
        flags.append((f"BD Gap {seller['bd_days_gap']}d", "#d69e2e", "No BD contact"))
    if seller["replies_202605"] == 0:
        flags.append(("Zero Replies", "#e53e3e", "Completely dark"))
    if seller["lapse_rate"] > 0.8:
        flags.append((f"Lapse {int(seller['lapse_rate']*100)}%", "#e53e3e", "BL credits burning"))
    if not flags:
        flags.append(("Healthy", "#38a169", "No critical flags"))

    cols_flags = st.columns(len(flags))
    for col, (label, color_f, hint) in zip(cols_flags, flags):
        col.markdown(f"""
        <div style="background:{color_f};color:white;border-radius:8px;
                    padding:10px;text-align:center" title="{hint}">
            <strong>{label}</strong><br><small>{hint}</small>
        </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Trend charts ─────────────────────────────────────────────────────────
    st.subheader("4-Month Behavioral Trends")
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        st.plotly_chart(reply_trend_chart(seller), use_container_width=True)
    with tc2:
        st.plotly_chart(lapse_trend_chart(seller), use_container_width=True)
    with tc3:
        st.plotly_chart(bl_cons_chart(seller), use_container_width=True)

    st.divider()

    # ── Recommended action ───────────────────────────────────────────────────
    st.subheader("Recommended Action")
    action_map = {
        "IVR_TRIGGERED":     ("⚫ Immediate IVR Rescue Call", "#1a1a1a", "Trigger SquadStack outbound call NOW. BD escalates if seller responds."),
        "BD_TASK_CREATED_P1":("🔴 BD Call — Priority 1",     "#e53e3e", "Create P1 CRM task. Call within 1 hour. WhatsApp follow-up within 2 hours."),
        "BD_TASK_CREATED_P2":("🟠 BD Call — Priority 2",     "#dd6b20", "Create P2 CRM task. Call within 48 hours."),
        "whatsapp":           ("📱 WhatsApp Outreach",         "#d69e2e", "Send personalized WhatsApp nudge. Trigger call if no reply within 48h."),
        "monitor":            ("🟢 Monitor Only",              "#38a169", "No action needed. Continue monitoring."),
    }
    act_label, act_color, act_desc = action_map.get(
        seller["action_taken"], ("Unknown", "#718096", "No action mapped")
    )
    st.markdown(f"""
    <div style="background:{act_color};color:white;border-radius:10px;
                padding:14px 20px;display:inline-block;width:100%">
        <h3 style="margin:0">{act_label}</h3>
        <p style="margin:4px 0 0 0;opacity:0.9">{act_desc}</p>
    </div>""", unsafe_allow_html=True)

    st.divider()

    # ── AI-generated BD brief ─────────────────────────────────────────────────
    st.subheader("AI-Generated BD Call Brief")
    col_brief, col_wa = st.columns([1, 1])

    with col_brief:
        if band in ("BLACK", "RED", "ORANGE") or score >= 50:
            if st.button("Generate BD Call Brief", type="primary"):
                with st.spinner("Generating with Qwen 3 32B..."):
                    brief = generate_bd_brief(seller)
                st.session_state[f"brief_{seller['seller_id']}"] = brief

            cached_brief = st.session_state.get(f"brief_{seller['seller_id']}")
            if cached_brief:
                st.markdown(f"""
                <div style="background:#ebf8ff;border:1px solid #bee3f8;
                            border-radius:8px;padding:14px 16px;white-space:pre-wrap;
                            font-size:0.92em;line-height:1.6">
{cached_brief}
                </div>""", unsafe_allow_html=True)
        else:
            st.info("BD brief not needed for GREEN band sellers.")

    with col_wa:
        if band in ("ORANGE", "AMBER") or (25 <= score < 85):
            if st.button("Generate WhatsApp Message", type="secondary"):
                with st.spinner("Crafting personalized message..."):
                    msg = generate_whatsapp_message(seller)
                st.session_state[f"wa_{seller['seller_id']}"] = msg

            cached_wa = st.session_state.get(f"wa_{seller['seller_id']}")
            if cached_wa:
                st.markdown(f"""
                <div style="background:#f0fff4;border:1px solid #9ae6b4;
                            border-radius:8px;padding:14px 16px">
                    <strong>WhatsApp Preview</strong>
                    <p style="margin-top:8px;font-size:0.95em">{cached_wa}</p>
                    <small style="color:#718096">{len(cached_wa)} chars</small>
                </div>""", unsafe_allow_html=True)

                sent_key = f"wa_sent_{seller['seller_id']}"
                if st.session_state.get(sent_key):
                    st.success("✅ WhatsApp sent successfully!")
                else:
                    if st.button("📤 Send WhatsApp", type="primary", key=f"send_wa_{seller['seller_id']}"):
                        with st.spinner("Sending..."):
                            try:
                                result = send_via_wahelp(cached_wa)
                                st.session_state[sent_key] = result
                                st.success("✅ WhatsApp sent successfully!")
                            except Exception as e:
                                result = {"error": str(e)}
                                st.error(f"Send failed: {e}")
                        # Log full request+response to browser console
                        import streamlit.components.v1 as components
                        components.html(
                            f"<script>console.log('[WA API]', {json.dumps(result, indent=2)});</script>",
                            height=0,
                        )
        else:
            st.info("WhatsApp not dispatched for this band — use BD call instead." if score >= 85 else "No WhatsApp needed for GREEN band.")

    # ── Raw metrics table ─────────────────────────────────────────────────────
    with st.expander("Raw Metrics"):
        metrics = {
            "Replies (Feb/Mar/Apr/May)": f"{seller['replies_202602']} / {seller['replies_202603']} / {seller['replies_202604']} / {seller['replies_202605']}",
            "BL Lapse Rate":    f"{int(seller['lapse_rate']*100)}%",
            "Notif Loss Rate":  f"{int(seller['notif_loss_rate']*100)}%",
            "Email Dead":       "Yes" if seller["email_dead"] else "No",
            "BD Gap":           f"{seller['bd_days_gap']} days",
            "Dim: Engagement":  f"{seller.get('dim_engagement',0):.1f} / 40",
            "Dim: BL ROI":      f"{seller.get('dim_roi',0):.1f} / 30",
            "Dim: BD Coverage": f"{seller.get('dim_bd_coverage',0):.1f} / 15",
            "Dim: Biz Outcomes":f"{seller.get('dim_biz_outcomes',0):.1f} / 10",
            "Dim: Catalog":     f"{seller.get('dim_catalog',0):.1f} / 5",
        }
        mdf = pd.DataFrame(list(metrics.items()), columns=["Metric", "Value"])
        st.dataframe(mdf, use_container_width=True, hide_index=True)

# ── Page: Band Analysis ───────────────────────────────────────────────────────

def page_band_analysis(df: pd.DataFrame):
    st.title("Band-Level Analysis")

    tabs = st.tabs([f"{BAND_EMOJI[b]} {b}  ({len(df[df['risk_band']==b])})" for b in ["BLACK","RED","ORANGE","AMBER","GREEN"]])

    for tab, band in zip(tabs, ["BLACK","RED","ORANGE","AMBER","GREEN"]):
        with tab:
            bdf = df[df["risk_band"] == band]
            if bdf.empty:
                st.info("No sellers in this band.")
                continue

            color = BAND_COLOR[band]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sellers", len(bdf))
            c2.metric("Avg Score", f"{bdf['churn_score'].mean():.1f}")
            c3.metric("Revenue at Risk", f"₹{bdf['package_value'].sum()/1e5:.1f}L")
            c4.metric("Avg BD Gap", f"{bdf['bd_days_gap'].mean():.0f}d")

            st.divider()

            col_l, col_r = st.columns(2)
            with col_l:
                fig_pkg = px.histogram(bdf, x="package_value", nbins=15, color_discrete_sequence=[color],
                                       title="Package Value Distribution")
                fig_pkg.update_layout(height=250, margin=dict(t=40,b=20,l=30,r=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(248,250,252,1)")
                st.plotly_chart(fig_pkg, use_container_width=True)

            with col_r:
                svc = bdf["service"].value_counts().reset_index()
                svc.columns = ["Service", "Count"]
                fig_svc = px.bar(svc, x="Service", y="Count", color_discrete_sequence=[color],
                                 title="Sellers by Service Type")
                fig_svc.update_layout(height=250, margin=dict(t=40,b=20,l=30,r=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(248,250,252,1)")
                st.plotly_chart(fig_svc, use_container_width=True)

            # Scatter: score vs replies
            fig_scatter = px.scatter(
                bdf, x="replies_202605", y="churn_score",
                hover_data=["seller_name", "lapse_rate", "bd_days_gap"],
                color="lapse_rate", color_continuous_scale="Reds",
                title="Score vs May Replies (color = lapse rate)",
                labels={"replies_202605": "Replies (May)", "churn_score": "Churn Score"},
            )
            fig_scatter.update_layout(height=300, margin=dict(t=40,b=20,l=40,r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(248,250,252,1)")
            st.plotly_chart(fig_scatter, use_container_width=True)

            st.subheader(f"All {band} Sellers")
            show = bdf[["seller_id","seller_name","service","churn_score","replies_202605",
                         "lapse_rate","bd_days_gap","package_value","action_taken"]].copy()
            show["lapse_rate"] = (show["lapse_rate"] * 100).round(0).astype(int).astype(str) + "%"
            st.dataframe(show, use_container_width=True, height=400, hide_index=True)

# ── Page: Alert Log ───────────────────────────────────────────────────────────

def page_alert_log():
    st.title("Alert Log")
    log = load_alert_log()
    if log.empty:
        st.info("No entries in alert_log.csv yet. Run the daily batch (`python orchestrator.py`) to populate.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Actions", len(log))
    c2.metric("WA Sent",  len(log[log.get("whatsapp_status","") == "sent"]) if "whatsapp_status" in log else 0)
    c3.metric("IVR Triggered", len(log[log.get("call_action","") == "IVR_TRIGGERED"]) if "call_action" in log else 0)
    c4.metric("BD Tasks Created", len(log[log.get("call_action","").str.startswith("BD_TASK")]) if "call_action" in log else 0)

    st.dataframe(log, use_container_width=True, height=600)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Seller Churn Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
    </style>
    """, unsafe_allow_html=True)

    df = load_data()

    with st.sidebar:
        st.markdown("## 📊 Churn Dashboard")
        st.markdown(f"**{len(df):,} sellers** · {pd.Timestamp.now().strftime('%b %d, %Y')}")

        band_counts = df["risk_band"].value_counts()
        for band in ["BLACK","RED","ORANGE","AMBER","GREEN"]:
            n = band_counts.get(band, 0)
            st.markdown(
                f"<div style='padding:4px 8px;background:{BAND_BG.get(band,'#fff')};border-left:4px solid {BAND_COLOR[band]};border-radius:4px;margin-bottom:4px'>"
                f"{BAND_EMOJI[band]} <strong>{band}</strong>: {n} sellers</div>",
                unsafe_allow_html=True,
            )

        st.divider()
        page = st.radio(
            "Navigate",
            ["Overview", "Seller Detail", "Band Analysis", "Alert Log"],
            label_visibility="collapsed",
        )

    if page == "Overview":
        page_overview(df)
    elif page == "Seller Detail":
        page_seller_detail(df)
    elif page == "Band Analysis":
        page_band_analysis(df)
    elif page == "Alert Log":
        page_alert_log()

if __name__ == "__main__":
    main()
