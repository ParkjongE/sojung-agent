# postprocess.py
"""
postprocess.py
코드 판정 + Review Agent 결과 병합

원칙
- 코드 판정이 우선한다. review_builder.compute_checks()의 결과는 바꾸지 않는다.
- Review Agent는 C8(회의장소), C9(회의내용), C11(사진 장소 → 미충족으로만) 판단과 문장만 반영한다.
- 최종 판정과 적합도는 코드가 다시 계산한다.
- Review Agent가 실패하거나 결과가 깨져 있으면 코드 판정만으로 결과를 만든다.
"""

import re

from review_builder import OUT_OF_SCOPE, clean_list, compute_checks, first, flatten, to_number, won

MET, UNMET, UNSURE, REF, AI_PENDING = "충족", "미충족", "확인필요", "참고", "AI 판단"
CRITICAL = ("C5", "C7", "C8")          # 하나라도 미충족이면 부적합
AI_DECIDES = ("C8", "C9")              # AI 판정을 그대로 반영
AI_DOWNGRADE_ONLY = ("C11",)           # AI가 '미충족'이라 할 때만 반영

REVIEW_SCALARS = ("overall", "summary", "attendee_count", "per_person_amount")
REVIEW_LISTS = ("check_id", "check_result", "check_evidence", "fix_requests", "admin_notes")
PARALLEL_LISTS = ("check_id", "check_result", "check_evidence")

##################################################
# 검사표 표시용 매핑
##################################################

FORM_RULE_TEXT = {
    "C1": "증빙서·영수증 첨부철의 '동아리 구분' 칸에 체크해야 한다.",
    "C10": "참석자 성명 옆 서명란에 전원 서명해야 한다.",
}

SUBMITTED_FIELDS = {
    "C1": ("club_type_checked", "form_club_type_checked"),
    "C3": ("club_name", "form_club_name"),
    "C4": ("receipt_present", "receipt_total", "receipt_merchant"),
    "C5": ("meeting_date", "receipt_date"),
    "C6": ("form_date", "form_amount", "receipt_date", "receipt_total"),
    "C7": ("receipt_total", "attendee_names"),
    "C8": ("meeting_place",),
    "C9": ("meeting_topic", "meeting_content", "guide_text_remaining"),
    "C10": ("attendee_names", "attendee_signature"),
    "C11": ("photo_count", "photo_people_count", "photo_note"),
}

FIX_TEMPLATES = {
    "C1": "회의비 지출 증빙과 영수증 첨부철의 '동아리 구분'에 체크해 주세요.",
    "C3": "증빙서와 영수증 첨부철의 동아리명(팀명)을 같게 적어 주세요.",
    "C4": "영수증 원본을 첨부철 가운데에 부착해 다시 제출해 주세요.",
    "C5": "회의 날짜와 영수증 거래일이 같아야 합니다. 회의일 또는 영수증을 확인해 주세요.",
    "C6": "영수증 첨부철의 카드사용일·금액을 실제 영수증과 같게 고쳐 주세요.",
    "C7": "회의비는 1인당 한도 이내만 지원됩니다. 초과분은 지원되지 않으니 금액 또는 참석 인원을 확인해 주세요.",
    "C8": "회의장소는 음식점·카페가 불가합니다. 강의실·동아리실·회의실 등에서 진행한 회의만 지원됩니다.",
    "C9": "양식 안내문을 지우고 회의 주제·내용·결과를 구체적으로 적어 주세요.",
    "C10": "서명이 빠진 참석자의 서명을 받아 주세요.",
    "C11": "참석 인원이 모두 나온 회의 사진(강의실·동아리실 등에서 촬영)을 첨부해 주세요.",
}

FIELD_LABELS = {
    "club_type_checked": "증빙 동아리 구분", "form_club_type_checked": "첨부철 동아리 구분",
    "club_field_checked": "증빙 동아리 분야", "form_club_field_checked": "첨부철 동아리 분야",
    "club_name": "증빙 동아리명", "form_club_name": "첨부철 동아리명",
    "receipt_present": "영수증 부착", "receipt_total": "영수증 결제금액",
    "receipt_merchant": "가맹점", "receipt_date": "영수증 거래일",
    "meeting_date": "회의 날짜", "meeting_round": "회의 차수",
    "form_date": "첨부철 기재일", "form_amount": "첨부철 기재금액",
    "attendee_names": "참석자", "attendee_signature": "서명",
    "meeting_place": "회의 장소", "meeting_topic": "회의 주제",
    "meeting_content": "회의 내용", "guide_text_remaining": "안내문 잔존",
    "photo_count": "사진 장수", "photo_people_count": "사진 속 인원", "photo_note": "판독 메모",
}


def _show(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "(없음)"
    if value in (None, ""):
        return "(빈 값)"
    return str(value)


def rule_text(rules: dict, check: dict) -> str:
    if check["id"] in FORM_RULE_TEXT:
        return FORM_RULE_TEXT[check["id"]]
    parts = []
    for key in (k.strip() for k in check["rule"].split(",")):
        value = first(rules.get(key))
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) or str(value).replace(",", "").isdigit():
            label = {"meeting_per_person_limit": "회의비 1인당 한도",
                     "monthly_budget": "월 활동지원금"}.get(key, key)
            value = f"{label} {won(to_number(value))}"
        parts.append(str(value))
    return " / ".join(parts) or check["rule"]


def submitted_text(sub: dict, cid: str) -> str:
    return " · ".join(f"{FIELD_LABELS.get(f, f)}: {_show(sub.get(f))}"
                      for f in SUBMITTED_FIELDS.get(cid, ()))


##################################################
# Submission Agent 결과 정리
##################################################

# Studio에서 '목록'을 끈 채 추출하면 리스트 항목이 "김동욱, 이건영" 한 문자열로 온다.
LIST_FIELDS = ("attendee_names", "attendee_signature", "receipt_items")


def _split_list(value):
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        value = value[0]
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,\n;/·]+", value) if v.strip()]
    return value


def normalize_submission(raw: dict) -> dict:
    """compute_checks()가 기대하는 형태로 입력만 맞춘다 (판정 로직은 그대로)."""
    def fix(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                out[k] = [fix(x) for x in v]
            elif k in LIST_FIELDS:
                out[k] = _split_list(v)
            else:
                out[k] = v
        return out
    return fix(raw) if isinstance(raw, dict) else raw


##################################################
# Review Agent 결과 정리
##################################################

def _transpose_tables(raw: dict) -> dict:
    """[{check_id:.., check_result:..}, ...] 형태의 표를 열별 리스트로 펼친다."""
    out = {}
    for key, value in raw.items():
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            for row in value:
                for k, v in row.items():
                    out.setdefault(k, []).append(v)
        else:
            out[key] = value
    return out


def normalize_check_id(value) -> str:
    m = re.search(r"C\s*(\d+)", str(value), re.IGNORECASE)
    return f"C{int(m.group(1))}" if m else str(value).strip()


def normalize_result(value):
    """에이전트의 판정 문자열을 충족/미충족/확인필요 중 하나로. 알 수 없으면 None."""
    v = str(first(value, "")).replace(" ", "")
    if "미충족" in v or "부적합" in v or "위반" in v:
        return UNMET
    if "확인" in v or "판단불가" in v or "불명" in v:
        return UNSURE
    if "충족" in v or v == "적합":
        return MET
    return None


def normalize_review(raw) -> tuple[dict, list]:
    """Review Agent 출력 → {스칼라 4개, 리스트 5개}. 경고 목록도 함께 돌려준다."""
    warnings = []
    if not isinstance(raw, dict):
        return {}, ["Review Agent 결과가 JSON 객체가 아닙니다."]
    data = _transpose_tables(raw)
    review = {k: first(data.get(k), "") for k in REVIEW_SCALARS}
    for k in REVIEW_LISTS:
        if k in PARALLEL_LISTS:
            # 같은 순서로 짝을 맞추는 목록이라 빈 값도 자리를 지킨다 (빼면 순서가 밀림)
            v = data.get(k)
            v = v if isinstance(v, list) else ([v] if v not in (None, "") else [])
            review[k] = ["" if x is None else str(x).strip() for x in v]
        else:
            review[k] = clean_list(data.get(k))
    review["check_id"] = [normalize_check_id(c) for c in review["check_id"]]

    n_id, n_res, n_ev = (len(review[k]) for k in ("check_id", "check_result", "check_evidence"))
    if n_id != n_res:
        warnings.append(f"Review Agent의 check_id({n_id}개)와 check_result({n_res}개) 길이가 달라 "
                        "AI 항목별 판정을 반영하지 않았습니다.")
        review["checks"] = {}
    else:
        if n_ev != n_id:
            warnings.append(f"Review Agent의 check_evidence 길이({n_ev})가 check_id({n_id})와 달라 "
                            "근거는 맞는 순서까지만 사용했습니다.")
        evidence = review["check_evidence"] + [""] * max(0, n_id - n_ev)
        review["checks"] = {cid: {"result": normalize_result(res), "raw": res, "evidence": ev}
                            for cid, res, ev in zip(review["check_id"], review["check_result"], evidence)}
    return review, warnings


##################################################
# 판정 범위 밖 항목 걸러내기
##################################################

# Studio Review Agent가 예전 C12·C13 기준으로 쓴 메모를 걸러낸다.
OUT_OF_SCOPE_PATTERN = re.compile(r"\bC1[23]\b|\bC2\b|동아리 분야|참석자 자격|참여학과|재학|명단 대조|1일 1회|월 한도|같은 날")


def in_scope(text: str) -> bool:
    return not OUT_OF_SCOPE_PATTERN.search(text)


##################################################
# 병합 · 판정
##################################################

def merge_checks(code_checks: list, review: dict | None) -> tuple[list, list]:
    """코드 판정에 AI 판단을 허용된 항목만 반영한다. (검사 목록, 코드가 덮어쓴 내역)"""
    ai = (review or {}).get("checks", {})
    overrides = []
    merged = []
    for c in code_checks:
        c = dict(c, source="코드")
        got = ai.get(c["id"])
        ai_result = got["result"] if got else None
        ai_ev = (got or {}).get("evidence", "")

        if c["id"] in AI_DECIDES:
            if ai_result:
                c.update(result=ai_result, source="AI",
                         evidence=f"{ai_ev} ({c['evidence']})" if ai_ev else c["evidence"])
            else:
                c.update(result=UNSURE, source="AI 없음",
                         evidence=f"AI 판단 결과 없음 → 담당자 확인. {c['evidence']}")
        elif c["id"] in AI_DOWNGRADE_ONLY and ai_result == UNMET and c["result"] != UNMET:
            c.update(result=UNMET, source="코드+AI",
                     evidence=f"{c['evidence']} / AI: {ai_ev or '사진 장소 부적합'}")
        elif ai_result and c["result"] in (MET, UNMET, UNSURE) and ai_result != c["result"]:
            overrides.append(f"{c['id']} {c['name']}: Review Agent '{ai_result}' → 코드 판정 '{c['result']}' 유지")
        merged.append(c)
    return merged, overrides


def count_results(checks: list) -> dict:
    counts = {MET: 0, UNMET: 0, UNSURE: 0, REF: 0}
    for c in checks:
        counts[c["result"]] = counts.get(c["result"], 0) + 1
    return counts


def decide_overall(checks: list) -> str:
    unmet = {c["id"] for c in checks if c["result"] == UNMET}
    if unmet & set(CRITICAL):
        return "부적합"
    if unmet:
        return "보완필요"
    return "적합"


def compute_fitness(checks: list) -> float:
    """(충족 + 확인필요 × 0.5) ÷ ('참고' 제외 항목 수) × 100"""
    scored = [c for c in checks if c["result"] != REF]
    if not scored:
        return 0.0
    met = sum(c["result"] == MET for c in scored)
    unsure = sum(c["result"] == UNSURE for c in scored)
    return round((met + unsure * 0.5) / len(scored) * 100, 1)


FITNESS_FORMULA = "(충족 + 확인필요 × 0.5) ÷ 검사 항목 수 × 100"


##################################################
# 화면용 대조 데이터
##################################################

def comparisons(rules: dict, sub: dict, calc: dict) -> dict:
    from review_builder import DEFAULT_PER_PERSON_LIMIT
    names = clean_list(sub.get("attendee_names"))
    sigs = clean_list(sub.get("attendee_signature"))
    count = len(names)
    total = to_number(sub.get("receipt_total"))
    form_amount = to_number(sub.get("form_amount"))
    limit = to_number(rules.get("meeting_per_person_limit")) or DEFAULT_PER_PERSON_LIMIT
    meeting_date = first(sub.get("meeting_date"), "")
    receipt_date = first(sub.get("receipt_date"), "")
    form_date = first(sub.get("form_date"), "")
    people = str(first(sub.get("photo_people_count"), "사진없음"))

    return {
        "date": {
            "회의 날짜": meeting_date or "(빈 값)",
            "영수증 거래일": receipt_date or "(빈 값)",
            "첨부철 기재일": form_date or "(빈 값)",
            "match": bool(meeting_date) and meeting_date == receipt_date == form_date,
        },
        "amount": {
            "total": total, "form_amount": form_amount, "count": count,
            "per_person": total / count if count else None,
            "limit": limit, "max_allowed": limit * count,
            "over": max(0.0, total - limit * count) if count else None,
        },
        "club": {
            "증빙 동아리명": first(sub.get("club_name"), "(빈 값)"),
            "첨부철 동아리명": first(sub.get("form_club_name"), "(빈 값)"),
            "증빙 동아리 구분": first(sub.get("club_type_checked"), "없음"),
            "첨부철 동아리 구분": first(sub.get("form_club_type_checked"), "없음"),
            "동아리 분야": first(sub.get("club_field_checked"), "없음"),
        },
        "attendees": [{"name": n, "signed": (sigs[i] if i < len(sigs) else "") == "서명있음",
                       "signature": sigs[i] if i < len(sigs) else "(없음)"}
                      for i, n in enumerate(names)],
        "photo": {
            "count": int(to_number(sub.get("photo_count"))),
            "people": people, "attendee_count": count,
            "note": first(sub.get("photo_note"), ""),
            "place": first(sub.get("meeting_place"), ""),
        },
        "receipt": {
            "merchant": first(sub.get("receipt_merchant"), ""),
            "items": clean_list(sub.get("receipt_items")),
        },
        "calc": calc,
    }


##################################################
# 최종 결과
##################################################

def build_result(rules: dict, submission_raw: dict, review_raw=None,
                 review_error: str | None = None) -> dict:
    sub = flatten(normalize_submission(submission_raw))
    calc, code_checks = compute_checks(rules, sub)

    warnings = []
    review = None
    if review_error:
        warnings.append(f"Review Agent 실패 — 코드 판정만으로 결과를 표시합니다. ({review_error})")
    elif review_raw is not None:
        review, w = normalize_review(review_raw)
        warnings += w

    checks, overrides = merge_checks(code_checks, review)
    for c in checks:
        c["rule_text"] = rule_text(rules, c)
        c["submitted"] = submitted_text(sub, c["id"])

    overall = decide_overall(checks)
    counts = count_results(checks)
    fitness = compute_fitness(checks)

    unmet = [c for c in checks if c["result"] == UNMET]
    unsure = [c for c in checks if c["result"] == UNSURE]

    fix_requests = [f"[{c['id']} {c['name']}] {FIX_TEMPLATES.get(c['id'], '해당 항목을 보완해 주세요.')}"
                    for c in unmet]
    admin_notes = [f"[{c['id']} {c['name']}] {c['evidence']}" for c in unsure]
    if review:
        fix_requests += [f for f in review["fix_requests"] if f not in fix_requests and in_scope(f)]
        admin_notes += [n for n in review["admin_notes"] if n not in admin_notes and in_scope(n)]

    scored = len(checks) - counts[REF]
    summary = (f"{overall} — 검사 {scored}개 항목 중 충족 {counts[MET]}, "
               f"미충족 {counts[UNMET]}, 확인필요 {counts[UNSURE]}.")
    if unmet:
        summary += " 미충족: " + ", ".join(f"{c['id']} {c['name']}" for c in unmet) + "."
    ai_overall = (review or {}).get("overall", "")
    if ai_overall and ai_overall != overall:
        overrides.append(f"종합 판정: Review Agent '{ai_overall}' → 코드 재계산 '{overall}'")

    return {
        "overall": overall,
        "fitness": fitness,
        "fitness_formula": FITNESS_FORMULA,
        "counts": counts,
        "summary": summary,
        "ai_summary": (review or {}).get("summary", ""),
        "review_used": review is not None,
        "checks": checks,
        "fix_requests": fix_requests,
        "admin_notes": admin_notes,
        "overrides": overrides,
        "warnings": warnings,
        "out_of_scope": [{"name": n, "rule": rule_text(rules, {"id": "", "rule": key}), "reason": why}
                         for n, key, why in OUT_OF_SCOPE],
        "compare": comparisons(rules, sub, calc),
        "rules": rules,
        "submission": submission_raw,
        "review_raw": review_raw,
    }
