# report.py
"""
report.py
검토 결과 → Markdown 보고서
"""

from review_builder import won


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_report(result: dict) -> str:
    c = result["counts"]
    amt = result["compare"]["amount"]
    date = result["compare"]["date"]
    lines = [
        "# 회의비 증빙 검토 보고서",
        "",
        f"- 파일: {result.get('file_name', '')}",
        f"- 검토 시각: {result.get('created_at', '')}",
        f"- 판정: **{result['overall']}**",
        f"- 적합도: **{result['fitness']}%** — {result['fitness_formula']}",
        f"- 충족 {c.get('충족', 0)} · 미충족 {c.get('미충족', 0)} · 확인필요 {c.get('확인필요', 0)}",
        "",
        f"> {result['summary']}",
        "",
    ]
    if result.get("ai_summary"):
        lines += [f"AI 요약: {result['ai_summary']}", ""]

    lines += ["## 보완 요청", ""]
    lines += [f"- {x}" for x in result["fix_requests"]] or ["- 없음"]
    lines += ["", "## 담당자 확인", ""]
    lines += [f"- {x}" for x in result["admin_notes"]] or ["- 없음"]

    per = won(amt["per_person"]) if amt["per_person"] is not None else "계산 불가"
    lines += [
        "", "## 핵심 대조", "",
        f"- 날짜: 회의 {date['회의 날짜']} / 영수증 {date['영수증 거래일']} / 첨부철 {date['첨부철 기재일']}",
        f"- 금액: 결제 {won(amt['total'])} / 기재 {won(amt['form_amount'])} / "
        f"{amt['count']}명 / 1인당 {per} / 한도 {won(amt['limit'])}",
        "", "## 전체 검사표", "",
        "| 번호 | 검사 항목 | 기준 | 공고·양식 원문 | 제출 값 | 판정 | 근거 | 주체 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k in result["checks"]:
        lines.append("| " + " | ".join(_cell(x) for x in (
            k["no"], k["label"], k["criterion"], k["rule_text"], k["submitted"],
            k["result"], k["evidence"], k["by"])) + " |")

    if result.get("out_of_scope"):
        lines += ["", "## 판정 범위 밖", ""]
        lines += [f"- {x['name']}: {x['reason']}" for x in result["out_of_scope"]]
    if result.get("overrides"):
        lines += ["", "## 코드가 덮어쓴 에이전트 판단", ""]
        lines += [f"- {x}" for x in result["overrides"]]
    if result.get("warnings"):
        lines += ["", "## 경고", ""]
        lines += [f"- {x}" for x in result["warnings"]]
    lines += ["", "---", "이 보고서는 서류 심사 보조 결과이며 지급 승인이 아닙니다.", ""]
    return "\n".join(lines)
