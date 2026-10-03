# config.py
"""
config.py
환경 설정 · 경로

비밀값은 로컬에서는 .env, 배포(Streamlit Community Cloud)에서는 Streamlit Secrets에서 읽는다.
값은 화면·로그에 절대 출력하지 않는다.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

##################################################
# 경로
##################################################

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = BASE_DIR / "samples"
OUTPUT_DIR = BASE_DIR / "output"
RUNS_DIR = OUTPUT_DIR / "runs"

RULE_REFERENCE_PDF = DATA_DIR / "rule_reference.pdf"
SAMPLE_MEETING_PDF = DATA_DIR / "sample_meeting.pdf"
RULES_CACHE = DATA_DIR / "rules_cache.json"

SAMPLE_RULES = SAMPLES_DIR / "sample_rules.json"
SAMPLE_SUBMISSION = SAMPLES_DIR / "sample_submission.json"
SAMPLE_REVIEW = SAMPLES_DIR / "sample_review.json"

##################################################
# 환경변수
##################################################

load_dotenv(BASE_DIR / ".env")

ENV_KEYS = [
    "UPSTAGE_API_KEY",
    "RULE_AGENT_ID", "RULE_CONFIG_ID",
    "SUBMISSION_AGENT_ID", "SUBMISSION_CONFIG_ID",
    "REVIEW_AGENT_ID", "REVIEW_CONFIG_ID",
]


def _secret(key: str, default: str = "") -> str:
    """환경변수 → Streamlit Secrets 순으로 읽는다."""
    value = os.getenv(key)
    if value:
        return value.strip()
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default


UPSTAGE_API_KEY = _secret("UPSTAGE_API_KEY")
RULE_AGENT_ID = _secret("RULE_AGENT_ID")
RULE_CONFIG_ID = _secret("RULE_CONFIG_ID", "1")
SUBMISSION_AGENT_ID = _secret("SUBMISSION_AGENT_ID")
SUBMISSION_CONFIG_ID = _secret("SUBMISSION_CONFIG_ID", "1")
REVIEW_AGENT_ID = _secret("REVIEW_AGENT_ID")
REVIEW_CONFIG_ID = _secret("REVIEW_CONFIG_ID", "1")

DEMO_MODE = _secret("DEMO_MODE", "0").lower() in ("1", "true", "yes")

##################################################
# 제한
##################################################

AGENT_TIMEOUT_SEC = 300
MAX_UPLOAD_MB = 20
RECENT_LIMIT = 5


def missing_env() -> list[str]:
    """비어 있는 환경변수 이름 목록 (값은 반환하지 않는다)."""
    return [k for k in ENV_KEYS if not _secret(k)]


def validate_config():
    missing = missing_env()
    if missing:
        raise EnvironmentError(
            "환경변수가 없습니다: " + ", ".join(missing)
            + " — .env(로컬) 또는 Streamlit Secrets(배포)에 넣어 주세요."
        )
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
