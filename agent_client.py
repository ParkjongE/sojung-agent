# agent_client.py
"""
agent_client.py
공통 Agent 실행 모듈 (수업 스타터 구조)

Rule Agent / Submission Agent / Review Agent 모두 이 클래스로 실행한다.
Job 생성 → Polling → 결과 정리(출처 표시·코드펜스 제거) → JSON 파싱
"""

import json
import re
import time

from openai import OpenAI

from config import AGENT_TIMEOUT_SEC, UPSTAGE_API_KEY

##################################################
# OpenAI Client (Upstage는 OpenAI SDK와 호환)
##################################################

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not UPSTAGE_API_KEY:
            raise EnvironmentError("UPSTAGE_API_KEY가 설정되지 않았습니다.")
        _client = OpenAI(
            api_key=UPSTAGE_API_KEY,
            base_url="https://api.upstage.ai/v2",
            timeout=AGENT_TIMEOUT_SEC,
        )
    return _client


##################################################
# 결과 텍스트 정리
##################################################

CITATION = re.compile(r"【[^】]*†[^】]*】")
FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def clean_output(text: str) -> str:
    """【†1】 같은 출처 표시와 ```json 코드펜스를 제거한다."""
    text = CITATION.sub("", text or "").strip()
    text = FENCE.sub("", text).strip()
    return text


def parse_json_text(text: str) -> dict:
    text = clean_output(text)
    if not text:
        raise ValueError("에이전트 결과(output_text)가 비어 있습니다.")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # 앞뒤에 설명 문장이 붙은 경우 가장 바깥 { } 만 다시 시도
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("에이전트 결과가 JSON 형식이 아닙니다.")
        try:
            result = json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"에이전트 결과 JSON 파싱 실패: {e.msg}") from e
    if not isinstance(result, dict):
        raise ValueError("에이전트 결과가 JSON 객체가 아닙니다.")
    return result


##################################################
# Agent Client
##################################################

class AgentClient:
    """Studio Agent 실행 클래스"""

    def __init__(self, name: str, agent_id: str, config_id: str = "1",
                 timeout: int = AGENT_TIMEOUT_SEC):
        self.name = name
        self.agent_id = agent_id
        self.config_id = config_id
        self.timeout = timeout

    def create_job(self, file_id: str) -> str:
        if not self.agent_id:
            raise EnvironmentError(f"{self.name}의 Agent ID가 설정되지 않았습니다.")
        response = get_client().responses.create(
            model=self.agent_id,
            include=["last"],
            input=[{
                "role": "user",
                "content": [{"type": "input_file", "file_id": file_id}],
            }],
            extra_body={"config_id": self.config_id},
        )
        return response.id

    def wait_until_complete(self, job_id: str, interval: int = 2):
        started = time.monotonic()
        response = get_client().responses.retrieve(job_id, include=["last"])
        while response.status in ("queued", "in_progress"):
            if time.monotonic() - started > self.timeout:
                raise TimeoutError(f"{self.name} 실행이 {self.timeout}초를 넘었습니다.")
            time.sleep(interval)
            response = get_client().responses.retrieve(job_id, include=["last"])
        print(f"[{self.name}] Status : {response.status} "
              f"({time.monotonic() - started:.0f}s)")

        if response.status == "failed":
            raise RuntimeError(f"{self.name} 실행 실패 (Studio 상태: failed)")
        if response.status != "completed":
            raise RuntimeError(f"{self.name} 알 수 없는 상태: {response.status}")
        return response

    def parse_result(self, response) -> dict:
        return parse_json_text(response.output_text)

    def run(self, file_id: str) -> dict:
        print(f"[{self.name}] Create Job")
        job_id = self.create_job(file_id)
        print(f"[{self.name}] Job ID : {job_id}")
        response = self.wait_until_complete(job_id)
        result = self.parse_result(response)
        print(f"[{self.name}] JSON Parsing Complete")
        return result
