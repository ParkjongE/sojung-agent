# agents.py
"""
agents.py
Rule / Submission / Review Agent 실행 모듈

스타터의 resume_agent.py · jd_agent.py · matching_agent.py와 같은 역할.
세 파일이 ID만 다르고 구조가 같아 한 파일로 모았다.
"""

from agent_client import AgentClient
from config import (
    REVIEW_AGENT_ID, REVIEW_CONFIG_ID,
    RULE_AGENT_ID, RULE_CONFIG_ID,
    SUBMISSION_AGENT_ID, SUBMISSION_CONFIG_ID,
)

rule_agent = AgentClient("Rule Agent", RULE_AGENT_ID, RULE_CONFIG_ID)
submission_agent = AgentClient("Submission Agent", SUBMISSION_AGENT_ID, SUBMISSION_CONFIG_ID)
review_agent = AgentClient("Review Agent", REVIEW_AGENT_ID, REVIEW_CONFIG_ID)


def analyze_rules(file_id: str) -> dict:
    return rule_agent.run(file_id)


def analyze_submission(file_id: str) -> dict:
    return submission_agent.run(file_id)


def analyze_review(file_id: str) -> dict:
    return review_agent.run(file_id)
