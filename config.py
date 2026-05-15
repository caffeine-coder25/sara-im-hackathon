import os
from dotenv import load_dotenv

load_dotenv()

# IndiaMart LLM Gateway (OpenAI-compatible)
IM_LLM_API_KEY  = os.getenv("IM_LLM_API_KEY", "sk-ZMOQS2onmuyv6-bFyigELw")
IM_LLM_BASE_URL = os.getenv("IM_LLM_BASE_URL", "https://imllm.intermesh.net/v1")
IM_LLM_MODEL    = os.getenv("IM_LLM_MODEL",    "openrouter/qwen/qwen3-32b")

# WhatsApp / AISENSY
WA_API_KEY  = os.getenv("WA_API_KEY", "")
WA_API_URL  = os.getenv("WA_API_URL", "https://wahelp.indiamart.com/whatsapp/wrapper_api_prod.php")
WA_PLATFORM = os.getenv("WA_PLATFORM", "WhatsApp_9696")
AISENSY_PROJECT_ID = os.getenv("AISENSY_PROJECT_ID", "")
AISENSY_PWD = os.getenv("AISENSY_PWD", "")
AISENSY_API_KEY = os.getenv("AISENSY_API_KEY", "")
AISENSY_TARGET_NUMBER = os.getenv("AISENSY_TARGET_NUMBER", "919643079339")

# SquadStack / IVR
SQUADSTACK_BEARER_TOKEN = os.getenv("SQUADSTACK_BEARER_TOKEN", "")
IVR_DIALER_API_URL      = os.getenv("IVR_DIALER_API_URL", "")
IVR_DIALER_API_KEY      = os.getenv("IVR_DIALER_API_KEY", "")

# BD CRM
BD_CRM_API_URL = os.getenv("BD_CRM_API_URL", "")
BD_CRM_API_KEY = os.getenv("BD_CRM_API_KEY", "")

# Data paths
DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
SELLERS_EXCEL   = os.path.join(DATA_DIR, "sellers_data_cleaned.xlsx")
ALERT_LOG_PATH  = os.path.join(os.path.dirname(__file__), "alert_log.csv")
SARA_DB_PATH    = os.path.join(os.path.dirname(__file__), "sara.db")

# Scoring thresholds
SCORE_BLACK  = 85
SCORE_RED    = 70
SCORE_ORANGE = 50
SCORE_AMBER  = 25

# Partial-month normalization (days elapsed per year_month as of 2026-05-14)
DAYS_ELAPSED = {
    "202602": 28,
    "202603": 31,
    "202604": 30,
    "202605": 14,
}

# LangSmith
LANGCHAIN_API_KEY      = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_TRACING_V2   = os.getenv("LANGCHAIN_TRACING_V2", "true")
LANGCHAIN_PROJECT      = os.getenv("LANGCHAIN_PROJECT", "seller-churn-agent")
