"""후처리 단위 테스트 — PRD 8장: 정상 / 에이전트 오판 덮어쓰기 / 리스트 길이 불일치 / 실패 fallback / 적합도"""

import copy
import json
from pathlib import Path

import pytest

from agent_client import parse_json_text
from postprocess import (
    build_result, compute_fitness, decide_overall, normalize_review, normalize_submission,
)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def rules():
    return json.loads((SAMPLES / "sample_rules.json").read_text(encoding="utf-8"))


@pytest.fixture
def submission():
    return json.loads((SAMPLES / "sample_submission.json").read_text(encoding="utf-8"))


def review_with(**changes):
    review = json.loads((SAMPLES / "sample_review.json").read_text(encoding="utf-8"))
    review = copy.deepcopy(review)
    for cid, result in changes.items():
        i = review["check_id"].index(cid)
        review["check_result"][i] = result
    return review


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


# 1. 정상
def test_normal_case(rules, submission):
    r = build_result(rules, submission, review_with(C7="충족"))
    c = by_id(r)
    assert r["overall"] == "적합"
    assert c["C8"]["result"] == "충족" and c["C8"]["source"] == "AI"
    assert c["C9"]["result"] == "충족"
    assert r["counts"] == {"충족": 9, "미충족": 0, "확인필요": 1, "참고": 0}
    assert r["warnings"] == [] and r["review_used"]


# 2. 에이전트 오판을 코드가 덮어씀
def test_code_overrides_agent(rules, submission):
    review = review_with(C5="미충족", C7="미충족", C10="미충족")
    review["overall"] = ["부적합"]
    r = build_result(rules, submission, review)
    c = by_id(r)
    assert (c["C5"]["result"], c["C7"]["result"], c["C10"]["result"]) == ("충족", "충족", "충족")
    assert r["overall"] == "적합"
    assert any(o.startswith("1인당 한도") for o in r["overrides"])
    assert any("종합 판정" in o for o in r["overrides"])


def test_code_violation_beats_agent_pass(rules, submission):
    submission["receipt"][0]["receipt_total"] = 150000      # 6명 × 2만원 = 12만원 초과
    r = build_result(rules, submission, review_with(C7="충족"))
    assert by_id(r)["C7"]["result"] == "미충족"
    assert r["overall"] == "부적합"


def test_ai_place_violation_makes_unfit(rules, submission):
    r = build_result(rules, submission, review_with(C7="충족", C8="미충족"))
    assert by_id(r)["C8"]["result"] == "미충족"
    assert r["overall"] == "부적합"


def test_ai_can_only_downgrade_photo(rules, submission):
    r = build_result(rules, submission, review_with(C11="충족"))
    assert by_id(r)["C11"]["result"] == "확인필요"              # AI가 올려줄 수는 없음
    r = build_result(rules, submission, review_with(C11="미충족 (카페로 보임)"))
    assert by_id(r)["C11"]["result"] == "미충족"
    assert r["overall"] == "보완필요"


# 3. 리스트 길이 불일치
def test_list_length_mismatch(rules, submission):
    review = review_with(C8="미충족")
    review["check_result"] = review["check_result"][:-2]
    r = build_result(rules, submission, review)
    c = by_id(r)
    assert any("길이가 달라" in w for w in r["warnings"])
    assert c["C8"]["result"] == "확인필요"                      # AI 결과를 쓰지 않음
    assert c["C5"]["result"] == "충족"                          # 코드 판정은 그대로


def test_evidence_shorter_is_padded(rules, submission):
    review = review_with()
    review["check_evidence"] = review["check_evidence"][:3]
    rv, warnings = normalize_review(review)
    assert rv["checks"]["C8"]["result"] == "충족" and rv["checks"]["C8"]["evidence"] == ""
    assert warnings


def test_table_form_review(rules, submission):
    review = review_with()
    rows = [{"check_id": i, "check_result": res, "check_evidence": ev} for i, res, ev in
            zip(review.pop("check_id"), review.pop("check_result"), review.pop("check_evidence"))]
    review["checks"] = rows
    r = build_result(rules, submission, review)
    assert by_id(r)["C8"]["source"] == "AI"


# 4. 에이전트 실패 fallback
def test_agent_failure_fallback(rules, submission):
    r = build_result(rules, submission, None, review_error="TimeoutError")
    c = by_id(r)
    assert not r["review_used"]
    assert c["C8"]["result"] == "확인필요" and c["C9"]["result"] == "확인필요"
    assert r["overall"] == "적합"
    assert any("Review Agent 실패" in w for w in r["warnings"])


def test_garbage_review_does_not_crash(rules, submission):
    r = build_result(rules, submission, {"overall": "적합"})
    assert by_id(r)["C8"]["result"] == "확인필요"


# 5. 적합도 계산
def test_fitness_formula():
    checks = [{"result": x} for x in ["충족"] * 6 + ["확인필요"] * 2 + ["미충족"] * 2 + ["참고"]]
    assert compute_fitness(checks) == 70.0                       # (6 + 1) / 10
    assert compute_fitness([{"result": "참고"}]) == 0.0


def test_fitness_in_result(rules, submission):
    r = build_result(rules, submission, review_with())
    assert r["fitness"] == round((9 + 1 * 0.5) / 10 * 100, 1)   # 95.0


def test_overall_rules():
    mk = lambda **kw: [{"id": k, "result": v} for k, v in kw.items()]
    assert decide_overall(mk(C1="충족", C3="충족", C11="확인필요")) == "적합"
    assert decide_overall(mk(C1="미충족", C5="충족")) == "보완필요"
    assert decide_overall(mk(C1="미충족", C7="미충족")) == "부적합"


# 입력 정규화 · 파싱
def test_comma_string_lists(rules, submission):
    submission["attendee_names"] = "김동욱, 이건영, 이환희, 박종희, 천서원, 윤선진"
    submission["attendee_signature"] = "서명있음, 서명있음, 서명있음, 서명있음, 서명있음, 서명있음"
    r = build_result(rules, submission, review_with(C7="충족"))
    assert r["compare"]["amount"]["count"] == 6
    assert by_id(r)["C10"]["result"] == "충족"
    assert normalize_submission({"x": [{"receipt_items": "a, b"}]})["x"][0]["receipt_items"] == ["a", "b"]


def test_parse_strips_citations_and_fences():
    text = '```json\n{"overall": "적합【†1】", "n": [1]}\n```'
    assert parse_json_text(text) == {"overall": "적합", "n": [1]}
    assert parse_json_text('결과입니다: {"a": 1} 끝') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_text("JSON 아님")


# 판정 범위 밖: 참석자 자격(C12) · 1일 1회·월 한도(C13)
def test_out_of_scope_items_removed(rules, submission):
    review = review_with()
    review["check_id"] += ["C12", "C13"]
    review["check_result"] += ["미충족", "확인필요"]
    review["check_evidence"] += ["명단 없음", "이력 없음"]
    review["admin_notes"] += ["C12: 참여학과 재학 여부를 명단과 대조하세요.", "같은 날 다른 회의비 청구가 있는지 확인하세요."]
    review["fix_requests"] += ["C13: 1일 1회 기준을 확인해 주세요."]
    r = build_result(rules, submission, review)
    ids = [c["id"] for c in r["checks"]]
    assert ids == ["C1"] + [f"C{i}" for i in range(3, 12)]
    assert not any("C12" in x or "C13" in x or "같은 날" in x for x in r["admin_notes"] + r["fix_requests"])
    assert [x["name"] for x in r["out_of_scope"]] == ["참석자 자격", "1일 1회·월 한도"]


def test_blank_results_keep_alignment(rules, submission):
    """실제 Studio 출력: C12·C13 결과를 빈 문자열로 채워 13개를 맞춰 보냄"""
    review = review_with(C8="미충족")
    review["check_id"] += ["C12", "C13"]
    review["check_result"] += ["", ""]
    review["check_evidence"] += ["", ""]
    r = build_result(rules, submission, review)
    assert r["warnings"] == []
    assert by_id(r)["C8"]["result"] == "미충족" and by_id(r)["C8"]["source"] == "AI"


def test_c2_removed(rules, submission):
    review = review_with()
    review["check_id"].insert(1, "C2"); review["check_result"].insert(1, "참고"); review["check_evidence"].insert(1, "")
    r = build_result(rules, submission, review)
    assert "C2" not in [c["id"] for c in r["checks"]] and len(r["checks"]) == 10
    assert r["warnings"] == [] and by_id(r)["C8"]["source"] == "AI"


@pytest.mark.parametrize("people, expected", [("6", "충족"), ("7", "미충족"), ("5", "미충족"), ("확인불가", "확인필요")])
def test_photo_people_must_equal_attendees(rules, submission, people, expected):
    submission["evidence"][0]["photo_people_count"] = people   # 참석자 6명
    r = build_result(rules, submission, review_with(C7="충족", C11="충족"))
    assert by_id(r)["C11"]["result"] == expected


def test_screen_shows_names_not_codes(rules, submission):
    submission["meeting_date"] = ""                      # 날짜 일치 미충족 유도
    review = review_with()
    review["summary"] = ["C5에서 날짜가 비어 있고 C8은 충족입니다."]
    review["fix_requests"] = ["C5: 회의 날짜를 적어 주세요."]
    r = build_result(rules, submission, review)
    assert [c["no"] for c in r["checks"]] == list(range(1, 11))
    assert by_id(r)["C5"]["label"] == "날짜 일치"
    shown = [r["summary"], r["ai_summary"], *r["fix_requests"], *r["admin_notes"], *r["overrides"]]
    shown += [c["evidence"] for c in r["checks"]]
    import re
    assert not any(re.search(r"(?<![A-Za-z0-9])C\d", t) for t in shown), shown
    assert "날짜 일치에서" in r["ai_summary"]
