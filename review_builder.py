# review_builder.py
"""
review_builder.py

rules.json(Rule Agent) + submission.json(Submission Agent)
        ↓
코드로 계산 가능한 검사(인원·금액·날짜·서명 등)를 먼저 판정
        ↓
output/Review_Input.pdf 생성 → Review Agent 입력

가이드의 matching_builder.py와 같은 역할입니다.
"""

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
)

##################################################
# 경로 (프로젝트의 config.py가 있으면 거기서 가져와도 됨)
##################################################

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
RULES_JSON = OUTPUT_DIR / "rules.json"
SUBMISSION_JSON = OUTPUT_DIR / "submission.json"
REVIEW_PDF = OUTPUT_DIR / "Review_Input.pdf"
FONT_NAME = "Nanum"
FONT_PATH = BASE_DIR / "fonts" / "NanumGothic-Regular.ttf"

DEFAULT_PER_PERSON_LIMIT = 20000
DEFAULT_MONTHLY_BUDGET = 400000

##################################################
# 폰트 · 스타일
##################################################

pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))

TITLE = ParagraphStyle("t", fontName=FONT_NAME, fontSize=16, leading=22, spaceAfter=6)
HEADING = ParagraphStyle("h", fontName=FONT_NAME, fontSize=12, leading=18,
                         spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1f3a5f"))
BODY = ParagraphStyle("b", fontName=FONT_NAME, fontSize=9, leading=13)
CELL = ParagraphStyle("c", fontName=FONT_NAME, fontSize=8.5, leading=12)


##################################################
# JSON 읽기 · 정리
##################################################

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def flatten(data: dict) -> dict:
    """
    Studio Extract 결과의 테이블(evidence, receipt 등)은
    [{...}] 형태의 리스트로 나온다. 첫 행을 꺼내 한 단계로 펼친다.
    """
    flat = {}
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            flat.update(value[0])
        else:
            flat[key] = value
    return flat


def first(value, default=None):
    """목록으로 나온 단일 값의 첫 값을 꺼낸다."""
    if isinstance(value, list):
        return value[0] if value else default
    return value if value not in (None, "") else default


def to_number(value):
    value = first(value)
    try:
        return float(str(value).replace(",", "").replace("원", ""))
    except (TypeError, ValueError):
        return 0


def clean_list(value) -> list:
    if not isinstance(value, list):
        value = [value] if value else []
    return [str(v).strip() for v in value if v is not None and str(v).strip()]


def text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "(없음)"
    if value in (None, ""):
        return "(빈 값)"
    return str(value)


def won(n) -> str:
    return f"{int(n):,}원"


##################################################
# 코드 판정 (계산·비교로 확정 가능한 항목)
##################################################

def compute_checks(rules: dict, s: dict) -> tuple[dict, list]:
    limit = to_number(rules.get("meeting_per_person_limit")) or DEFAULT_PER_PERSON_LIMIT

    names = clean_list(s.get("attendee_names"))
    signatures = clean_list(s.get("attendee_signature"))[: len(names)]
    count = len(names)

    total = to_number(s.get("receipt_total"))
    form_amount = to_number(s.get("form_amount"))
    meeting_date = first(s.get("meeting_date"), "미기재")
    receipt_date = first(s.get("receipt_date"), "")
    form_date = first(s.get("form_date"), "미기재")
    per_person = total / count if count else 0

    calc = {
        "참석 인원 (빈 칸 제외)": f"{count}명 ({', '.join(names) or '없음'})",
        "영수증 결제금액": won(total),
        "1인당 금액": won(per_person) if count else "계산 불가 (참석자 없음)",
        "1인당 한도": won(limit),
        "회의 날짜 / 영수증 거래일": f"{meeting_date} / {receipt_date or '(빈 값)'}",
        "첨부철 기재 날짜 / 금액": f"{form_date} / {won(form_amount)}",
    }

    checks = []

    def add(cid, name, result, evidence, rule, by="코드"):
        checks.append({"id": cid, "name": name, "result": result,
                       "evidence": evidence, "rule": rule, "by": by})

    # C1 동아리 구분: 체크 여부만
    t1 = first(s.get("club_type_checked"), "없음")
    t2 = first(s.get("form_club_type_checked"), "없음")
    add("C1", "동아리 구분 체크", "충족" if "없음" not in (t1, t2) else "미충족",
        f"증빙: {t1}, 첨부철: {t2}", "양식 기재사항")

    # C2 동아리 분야: 전공동아리만 쓰는 칸이라 판정에 쓰지 않아 검사 항목에서 제외 (번호는 유지)

    # C3 동아리명 일치
    n1 = first(s.get("club_name"), "")
    n2 = first(s.get("form_club_name"), "")
    add("C3", "동아리명 일치", "충족" if n1 and n1 == n2 else "미충족",
        f"증빙: {n1 or '(빈 값)'}, 첨부철: {n2 or '(빈 값)'}", "receipt_attach_rule")

    # C4 영수증 첨부
    present = first(s.get("receipt_present"), "없음")
    add("C4", "영수증 첨부", "충족" if present == "있음" and total > 0 else "미충족",
        f"영수증 부착: {present}, 결제금액: {won(total)}", "receipt_attach_rule")

    # C5 날짜 일치
    ok5 = meeting_date not in ("", "미기재") and meeting_date == receipt_date
    add("C5", "회의일·영수증 날짜 일치", "충족" if ok5 else "미충족",
        f"회의 날짜 {meeting_date}, 영수증 거래일 {receipt_date or '(빈 값)'}",
        "meeting_date_freq_rule")

    # C6 첨부철 기재 정확성
    ok6 = form_date == receipt_date and form_amount == total and total > 0
    add("C6", "첨부철 날짜·금액 기재", "충족" if ok6 else "미충족",
        f"기재 {form_date} / {won(form_amount)}, 영수증 {receipt_date or '(빈 값)'} / {won(total)}",
        "receipt_attach_rule")

    # C7 1인당 한도
    if count == 0:
        add("C7", "1인당 한도", "미충족", "참석자 이름이 없어 계산 불가", "meeting_per_person_limit")
    else:
        over = total - count * limit
        ev = f"{total:,.0f} ÷ {count}명 = {per_person:,.0f}원 / 한도 {limit:,.0f}원"
        if over > 0:
            ev += f" (초과 {over:,.0f}원)"
        add("C7", "1인당 한도", "충족" if per_person <= limit else "미충족",
            ev, "meeting_per_person_limit")

    # C8 회의장소: AI 판단
    add("C8", "회의장소", "AI 판단",
        f"회의 장소: {first(s.get('meeting_place'), '(빈 값)')}", "meeting_place_rule", by="AI")

    # C9 회의내용: AI 판단
    add("C9", "회의내용·안내문 삭제", "AI 판단",
        f"주제: {first(s.get('meeting_topic'), '(빈 값)')}, "
        f"안내문 잔존: {first(s.get('guide_text_remaining'), '(빈 값)')}",
        "meeting_content_rule", by="AI")

    # C10 서명
    missing = [n for n, sig in zip(names, signatures) if sig != "서명있음"]
    missing += names[len(signatures):]
    add("C10", "참석자 서명", "충족" if names and not missing else "미충족",
        "전원 서명 확인" if names and not missing else f"서명 없음: {', '.join(missing) or '참석자 없음'}",
        "양식 기재사항")

    # C11 회의사진: 코드로 1차 판정, 장소는 AI
    photos = int(to_number(s.get("photo_count")))
    people = str(first(s.get("photo_people_count"), "사진없음"))
    note = first(s.get("photo_note"), "")
    if photos == 0:
        r11, ev11 = "미충족", "회의 사진 미첨부"
    elif people.isdigit():
        r11 = "충족" if int(people) >= count else "미충족"
        ev11 = f"사진 {photos}장, 사진 속 {people}명 / 참석 {count}명"
    else:
        r11 = "확인필요"
        ev11 = f"사진 {photos}장 첨부, 인원 식별 불분명 ({people})"
    add("C11", "회의사진", r11, f"{ev11}. 판독 메모: {note or '없음'}",
        "meeting_photo_rule", by="코드+AI")

    # 참석자 자격(신청서 회원 명단 필요)과 1일 1회·월 한도(같은 팀 누적 이력 필요)는
    # 이 서류 1건으로 판정할 수 없어 검사 항목에서 제외한다. → OUT_OF_SCOPE

    return calc, checks


# 판정에서 제외한 기준 (화면·보고서·Review Agent 입력에 '범위 밖'으로만 표시)
OUT_OF_SCOPE = [
    ("참석자 자격", "meeting_eligibility_rule", "신청서 회원 명단(학과·재학 여부)을 반영한 뒤 판정 예정"),
    ("1일 1회·월 한도", "meeting_date_freq_rule, monthly_budget", "같은 팀의 다른 제출 건 누적 이력이 필요"),
]


##################################################
# PDF 작성
##################################################

def kv_table(rows: list[tuple[str, str]], widths=(45 * mm, 125 * mm)) -> Table:
    data = [[Paragraph(k, CELL), Paragraph(v, CELL)] for k, v in rows]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def check_table(checks: list) -> Table:
    head = ["ID", "검사 항목", "판정", "판정 주체", "근거", "적용 규칙"]
    data = [[Paragraph(h, CELL) for h in head]]
    for c in checks:
        data.append([Paragraph(str(c[k]), CELL)
                     for k in ("id", "name", "result", "by", "evidence", "rule")])
    t = Table(data, colWidths=[10 * mm, 25 * mm, 16 * mm, 16 * mm, 70 * mm, 33 * mm],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def create_review_input(rules_path=RULES_JSON, submission_path=SUBMISSION_JSON,
                        output_path=REVIEW_PDF) -> Path:
    rules = load_json(rules_path)
    sub = flatten(load_json(submission_path))
    calc, checks = compute_checks(rules, sub)

    story = [
        Paragraph("SW 동아리 회의비 지출 증빙 검토 입력서", TITLE),
        Paragraph("이 문서는 Rule Agent(공고 규칙)와 Submission Agent(학생 제출 서류)의 "
                  "추출 결과를 코드로 합치고, 계산으로 확정 가능한 검사를 먼저 판정한 것이다. "
                  "'코드' 판정은 그대로 따르고, 'AI 판단' 항목만 근거를 읽고 판정한다.", BODY),

        Paragraph("A. 공고 규칙 (Rule Agent)", HEADING),
        kv_table([(k, text(v)) for k, v in rules.items()]),

        Paragraph("B. 제출 서류 추출값 (Submission Agent)", HEADING),
        kv_table([(k, text(v)) for k, v in sub.items()]),

        Paragraph("C. 코드 자동 계산 결과", HEADING),
        kv_table(list(calc.items())),

        Paragraph("D. 검사 결과표 (C1, C3~C11 · C2 동아리 분야는 제외)", HEADING),
        check_table(checks),

        Paragraph("E. 종합 판정 기준", HEADING),
        Paragraph("1) C5(날짜 일치), C7(1인당 한도), C8(회의장소) 중 하나라도 미충족이면 '부적합'.<br/>"
                  "2) 그 외 미충족이 하나라도 있으면 '보완필요'.<br/>"
                  "3) 미충족이 없으면 '적합'. 확인필요 항목은 담당자 확인사항으로 남긴다.<br/>"
                  "4) '참고' 항목은 종합 판정에 반영하지 않는다.<br/>"
                  "5) 판정 범위 밖: " + ", ".join(f"{n}({why})" for n, _, why in OUT_OF_SCOPE)
                  + ". 이 항목은 판정하지 않으며 check_id·fix_requests·admin_notes에 넣지 않는다.", BODY),
        Spacer(1, 4),
        Paragraph("AI 판단 기준 — C8: 회의 장소가 음식점·카페이면 미충족, 강의실·동아리실·회의실 등이면 충족. "
                  "C9: 주제와 내용·결과가 구체적으로 작성되고 안내문 잔존이 '삭제됨'이면 충족. "
                  "C11: 판독 메모상 카페·음식점으로 보이면 미충족으로 바꾼다.", BODY),
    ]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(output_path), pagesize=A4,
                      leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    print(f"Review Input PDF : {output_path}")
    return output_path


if __name__ == "__main__":
    create_review_input()
