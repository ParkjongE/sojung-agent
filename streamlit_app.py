# streamlit_app.py
"""
streamlit_app.py
화면만 담당한다. 모든 처리는 service.py를 통해 호출한다.

실행: streamlit run streamlit_app.py      (DEMO_MODE=1 이면 API 없이 샘플로 렌더링)
"""

import json

import pandas as pd
import streamlit as st

import service
from config import MAX_UPLOAD_MB, RECENT_LIMIT, RULE_REFERENCE_PDF, SAMPLE_MEETING_PDF
from review_builder import first, to_number, won

st.set_page_config(page_title="회의비 증빙 검토", page_icon="🧾", layout="wide")

VERDICT_COLOR = {"적합": "#1a7f37", "보완필요": "#c26a00", "부적합": "#c62828"}
RESULT_COLOR = {"충족": "#1a7f37", "미충족": "#c62828", "확인필요": "#c26a00", "참고": "#6b7280"}

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
.badge {display:inline-block; padding:.35rem 1rem; border-radius:999px; color:#fff;
        font-weight:700; font-size:1.6rem; letter-spacing:.02em;}
.pill {display:inline-block; padding:.05rem .55rem; border-radius:999px; color:#fff;
       font-size:.8rem; font-weight:600; margin-right:.35rem;}
.card {border:1px solid rgba(128,128,128,.25); border-left-width:6px; border-radius:10px;
       padding:.8rem 1rem; margin-bottom:.6rem; background:rgba(128,128,128,.04);}
.card h4 {margin:0 0 .3rem 0; font-size:1rem;}
.card p {margin:.15rem 0; font-size:.92rem;}
.muted {color:rgba(128,128,128,1); font-size:.85rem;}
.kv {display:flex; justify-content:space-between; padding:.25rem 0;
     border-bottom:1px dashed rgba(128,128,128,.25); font-size:.93rem;}
.kv b {font-weight:600;}
</style>
""", unsafe_allow_html=True)


def pill(text: str, color: str) -> str:
    return f'<span class="pill" style="background:{color}">{text}</span>'


def kv(label: str, value: str, ok: bool | None = None) -> str:
    mark = "" if ok is None else (" ✅" if ok else " ❌")
    return f'<div class="kv"><span>{label}</span><b>{value}{mark}</b></div>'


##################################################
# 사이드바
##################################################

def sidebar():
    with st.sidebar:
        st.markdown("### 🧾 회의비 증빙 검토")
        st.caption("SW 동아리 회의비 지출 증빙(증빙서 + 영수증 첨부철) PDF를 공고문·양식 규칙과 "
                   "대조해 판정·적합도·보완할 점을 보여줍니다. 서류 심사 보조용이며 지급 승인이 아닙니다.")
        if service.is_demo():
            st.info("DEMO_MODE: API 없이 샘플 데이터로 동작합니다.")

        st.markdown("#### 적용 기준")
        try:
            rules = service.current_rules()
            limit = to_number(rules.get("meeting_per_person_limit"))
            budget = to_number(rules.get("monthly_budget"))
            st.markdown(
                f"- **1인당 한도** {won(limit) if limit else '미추출'}\n"
                f"- **월 한도** {won(budget) if budget else '미추출'}\n"
                f"- **날짜** 회의일 = 영수증 거래일, 1일 1회\n"
                f"- **장소** 음식점·카페 불가 (강의실·동아리실·회의실)\n"
                f"- **사진** 필수, 참석 인원 모두 촬영")
            st.caption("판정 제외: 참석자 자격(신청서 명단 반영 예정), 1일 1회·월 한도(누적 이력 필요)")
            with st.expander("규칙 원문"):
                for key in ("meeting_date_freq_rule", "meeting_place_rule",
                            "meeting_photo_rule", "meeting_content_rule", "receipt_attach_rule",
                            "meeting_eligibility_rule"):
                    if rules.get(key):
                        st.caption(f"**{key}** — {first(rules[key])}")
        except Exception as e:
            st.warning(f"규칙을 불러오지 못했습니다: {e}")

        st.markdown("#### 문서")
        if RULE_REFERENCE_PDF.exists():
            st.download_button("📄 기준 문서 (공고문 + 양식)", RULE_REFERENCE_PDF.read_bytes(),
                               file_name="rule_reference.pdf", mime="application/pdf",
                               width="stretch")
        if SAMPLE_MEETING_PDF.exists():
            st.download_button("📎 샘플 제출 서류", SAMPLE_MEETING_PDF.read_bytes(),
                               file_name="sample_meeting.pdf", mime="application/pdf",
                               width="stretch")

        st.markdown("#### 최근 검토")
        recent = st.session_state.get("recent", [])
        if not recent:
            st.caption("아직 없습니다.")
        for i, r in enumerate(recent):
            label = f"{r['overall']} · {r['fitness']}% · {r['file_name'][:18]}"
            if st.button(label, key=f"recent{i}", width="stretch",
                         help=r["created_at"]):
                st.session_state["result"] = r
                st.rerun()

        with st.expander("🔧 관리자: 규칙 다시 추출"):
            st.caption("Rule Agent로 기준 문서를 다시 읽어 rules_cache.json을 덮어씁니다. 1~2분 걸립니다.")
            sure = st.checkbox("덮어쓰기에 동의합니다", disabled=service.is_demo())
            if st.button("규칙 다시 추출", disabled=not sure or service.is_demo()):
                with st.spinner("Rule Agent 실행 중..."):
                    try:
                        service.refresh_rules()
                        st.success("규칙을 새로 저장했습니다.")
                    except Exception as e:
                        st.error(f"규칙 추출 실패: {e}")


##################################################
# 업로드 · 실행
##################################################

def run(file_name: str, data: bytes):
    states = {s: ("wait", "") for s in service.STEPS}
    icon = {"wait": "⏳", "run": "🔄", "done": "✅", "fail": "⚠️"}
    with st.status("검토 중...", expanded=True) as status:
        box = st.empty()

        def progress(step, state, detail=""):
            states[step] = (state, detail)
            box.markdown("\n".join(f"{icon[s]} **{name}** {d}" for name, (s, d) in states.items()))

        progress(service.STEPS[0], "wait")
        try:
            result = service.run_review_service(file_name, data, progress)
        except service.UploadError as e:
            status.update(label="업로드 확인 필요", state="error")
            st.warning(str(e))
            return
        except service.StepError as e:
            status.update(label=f"'{e.step}' 단계에서 멈췄습니다", state="error")
            st.error(f"**{e.step}** 단계 실패 — {e.message}")
            st.caption("잠시 후 '검토 시작'을 다시 눌러 재시도하세요.")
            return
        except EnvironmentError as e:
            status.update(label="설정 오류", state="error")
            st.error(str(e))
            return
        except Exception as e:  # 화면이 멈추지 않도록
            status.update(label="알 수 없는 오류", state="error")
            st.error(f"예상하지 못한 오류: {type(e).__name__}: {e}")
            return
        status.update(label=f"검토 완료 · {result['elapsed_sec']}초", state="complete", expanded=False)

    st.session_state["result"] = result
    recent = [r for r in st.session_state.get("recent", []) if r["run_id"] != result["run_id"]]
    st.session_state["recent"] = [result] + recent[: RECENT_LIMIT - 1]


def upload_section():
    problems = service.config_problems()
    if problems:
        st.error("환경변수가 비어 있어 검토할 수 없습니다: " + ", ".join(problems)
                 + "  \n로컬은 `.env`, 배포는 Streamlit Secrets에 넣어 주세요. "
                 "API 없이 화면만 보려면 `DEMO_MODE=1`.")

    up = st.file_uploader(f"회의비 지출 증빙 PDF (증빙서 + 영수증 첨부철, 최대 {MAX_UPLOAD_MB}MB)",
                          type=["pdf"])
    c1, c2, _ = st.columns([1, 1, 3])
    start = c1.button("검토 시작", type="primary", disabled=up is None or bool(problems),
                      width="stretch")
    sample = c2.button("샘플로 해보기", disabled=bool(problems) or not SAMPLE_MEETING_PDF.exists(),
                       width="stretch")
    if up is None:
        st.caption("PDF를 끌어다 놓거나 'Browse files'로 선택하세요. HWP는 PDF로 변환해 올려 주세요.")

    if start and up is not None:
        run(up.name, up.getvalue())
    elif sample:
        run(SAMPLE_MEETING_PDF.name, SAMPLE_MEETING_PDF.read_bytes())


##################################################
# 결과
##################################################

def section_summary(r: dict):
    c = r["counts"]
    color = VERDICT_COLOR.get(r["overall"], "#6b7280")
    left, mid, right = st.columns([1.1, 1.6, 2])
    with left:
        st.caption("판정")
        st.markdown(f'<span class="badge" style="background:{color}">{r["overall"]}</span>',
                    unsafe_allow_html=True)
        if r.get("demo_mode"):
            st.caption("DEMO 샘플 결과")
    with mid:
        st.caption("적합도")
        st.markdown(f"<div style='font-size:2rem;font-weight:700'>{r['fitness']}%</div>",
                    unsafe_allow_html=True)
        st.progress(min(1.0, r["fitness"] / 100))
        st.caption(f"= {r['fitness_formula']}")
    with right:
        a, b, d = st.columns(3)
        a.metric("충족", c.get("충족", 0))
        b.metric("미충족", c.get("미충족", 0))
        d.metric("확인필요", c.get("확인필요", 0))
        if c.get("참고", 0):
            st.caption(f"'참고' {c['참고']}개는 판정·적합도에서 제외")

    st.markdown(f"**{r['summary']}**")
    if r.get("ai_summary"):
        st.caption(f"AI 요약: {r['ai_summary']}")
    for w in r["warnings"]:
        st.warning(w)
    if r["overrides"]:
        with st.expander(f"코드가 덮어쓴 AI 판단 {len(r['overrides'])}건"):
            for o in r["overrides"]:
                st.markdown(f"- {o}")


def section_first(r: dict):
    st.subheader("먼저 확인할 것")
    unmet = [c for c in r["checks"] if c["result"] == "미충족"]
    unsure = [c for c in r["checks"] if c["result"] == "확인필요"]
    if not unmet and not unsure:
        st.success("미충족·확인필요 항목이 없습니다.")
        return

    left, right = st.columns(2)
    with left:
        st.markdown(f"##### 🔴 미충족 {len(unmet)}건 — 보완 요청")
        if not unmet:
            st.caption("없음")
        for c in unmet:
            fix = r.get("fix_by_id", {}).get(c["id"], "")
            st.markdown(
                f'<div class="card" style="border-left-color:{RESULT_COLOR["미충족"]}">'
                f'<h4>{c["label"]}</h4><p class="muted">기준: {c["criterion"]}</p><p>문제: {c["evidence"]}</p>'
                f'<p>요청: {fix}</p><p class="muted">공고·양식: {c["rule_text"]}</p></div>',
                unsafe_allow_html=True)
    with right:
        st.markdown(f"##### 🟠 확인필요 {len(unsure)}건 — 담당자가 볼 것")
        if not unsure:
            st.caption("없음")
        for c in unsure:
            st.markdown(
                f'<div class="card" style="border-left-color:{RESULT_COLOR["확인필요"]}">'
                f'<h4>{c["label"]}</h4><p class="muted">기준: {c["criterion"]}</p><p>{c["evidence"]}</p>'
                f'<p class="muted">공고·양식: {c["rule_text"]}</p></div>',
                unsafe_allow_html=True)

    oos = r.get("out_of_scope", [])
    if oos:
        st.caption("판정 범위 밖 (확인필요로 세지 않음): "
                   + " · ".join(f"{x['name']} — {x['reason']}" for x in oos))

    if r["fix_requests"]:
        st.markdown("**제출자에게 보낼 보완 요청** (오른쪽 위 아이콘으로 복사)")
        st.code("\n".join(f"- {x}" for x in r["fix_requests"]), language=None)
    if r["admin_notes"]:
        with st.expander("담당자 확인 메모 전체"):
            for n in r["admin_notes"]:
                st.markdown(f"- {n}")


def section_compare(r: dict):
    st.subheader("핵심 대조")
    d, a, k = r["compare"]["date"], r["compare"]["amount"], r["compare"]["club"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("##### 📅 날짜")
        st.markdown(kv("회의 날짜", d["회의 날짜"])
                    + kv("영수증 거래일", d["영수증 거래일"], d["회의 날짜"] == d["영수증 거래일"])
                    + kv("첨부철 기재일", d["첨부철 기재일"], d["첨부철 기재일"] == d["영수증 거래일"]),
                    unsafe_allow_html=True)
    with c2:
        st.markdown("##### 💰 금액")
        per = won(a["per_person"]) if a["per_person"] is not None else "계산 불가"
        over = a["over"]
        st.markdown(kv("영수증 결제금액", won(a["total"]))
                    + kv("첨부철 기재금액", won(a["form_amount"]), a["form_amount"] == a["total"] and a["total"] > 0)
                    + kv("참석 인원", f"{a['count']}명")
                    + kv("1인당 금액", per, None if a["per_person"] is None else a["per_person"] <= a["limit"])
                    + kv("1인당 한도", won(a["limit"]))
                    + kv("지원 가능 최대", won(a["max_allowed"]))
                    + kv("초과액", "계산 불가" if over is None else won(over), None if over is None else over == 0),
                    unsafe_allow_html=True)
    with c3:
        st.markdown("##### 🏷️ 동아리")
        st.markdown(kv("증빙 동아리명", k["증빙 동아리명"])
                    + kv("첨부철 동아리명", k["첨부철 동아리명"], k["증빙 동아리명"] == k["첨부철 동아리명"])
                    + kv("증빙 동아리 구분", k["증빙 동아리 구분"])
                    + kv("첨부철 동아리 구분", k["첨부철 동아리 구분"])
                    + kv("동아리 분야", k["동아리 분야"]),
                    unsafe_allow_html=True)
        rc = r["compare"]["receipt"]
        if rc["merchant"]:
            st.caption(f"가맹점 {rc['merchant']} · {', '.join(rc['items'])}  (가맹점은 회의 장소가 아님)")


def section_people(r: dict):
    st.subheader("참석자 · 사진")
    left, right = st.columns([1.2, 1])
    with left:
        att = r["compare"]["attendees"]
        if att:
            df = pd.DataFrame([{"#": i + 1, "이름": x["name"],
                                "서명": "✅ 있음" if x["signed"] else f"❌ {x['signature']}"}
                               for i, x in enumerate(att)])
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.warning("추출된 참석자 이름이 없습니다.")
    with right:
        p = r["compare"]["photo"]
        a, b = st.columns(2)
        a.metric("사진 장수", f"{p['count']}장")
        b.metric("사진 속 인원 / 참석", f"{p['people']} / {p['attendee_count']}명")
        st.markdown(kv("회의 장소", p["place"] or "(빈 값)"), unsafe_allow_html=True)
        st.caption(f"판독 메모: {p['note'] or '없음'}")


def section_table(r: dict):
    st.subheader("전체 검사표")
    df = pd.DataFrame([{
        "번호": c["no"], "검사 항목": c["label"], "기준": c["criterion"], "공고·양식 원문": c["rule_text"],
        "제출 서류 값": c["submitted"], "판정": c["result"], "근거": c["evidence"],
        "판정 주체": c["by"] if c.get("source") in ("코드", None) else f"{c['by']} ({c['source']})",
    } for c in r["checks"]])
    styled = df.style.map(lambda v: f"color:{RESULT_COLOR.get(v, 'inherit')};font-weight:700",
                          subset=["판정"])
    st.dataframe(styled, hide_index=True, width="stretch",
                 column_config={"번호": st.column_config.NumberColumn(width="small"),
                                "기준": st.column_config.TextColumn(width="medium"),
                                "공고·양식 원문": st.column_config.TextColumn(width="large"),
                                "제출 서류 값": st.column_config.TextColumn(width="medium"),
                                "근거": st.column_config.TextColumn(width="large")})


def section_raw(r: dict):
    st.subheader("원본 데이터 · 다운로드")
    paths = r["paths"]
    stem = r["file_name"].rsplit(".", 1)[0]
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ 결과 JSON", json.dumps(r, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"{stem}_result.json", mime="application/json",
                       width="stretch")
    pdf = service.read_bytes(paths["review_pdf"])
    c2.download_button("⬇️ Review_Input.pdf", pdf, file_name=f"{stem}_Review_Input.pdf",
                       mime="application/pdf", disabled=not pdf, width="stretch")
    c3.download_button("⬇️ 검토 보고서 (.md)", service.read_bytes(paths["report_md"]),
                       file_name=f"{stem}_report.md", mime="text/markdown",
                       width="stretch")

    t1, t2, t3 = st.tabs(["규칙 (Rule Agent)", "제출 서류 (Submission Agent)", "검토 (Review Agent)"])
    t1.json(r["rules"], expanded=False)
    t2.json(r["submission"], expanded=False)
    if r.get("review_raw") is not None:
        t3.json(r["review_raw"], expanded=False)
    else:
        t3.info("Review Agent 결과 없음 — 코드 판정만 사용했습니다.")


def render_result(r: dict):
    r = service.upgrade_result(r)
    st.divider()
    st.caption(f"{r['file_name']} · {r['created_at']} · run {r['run_id']}")
    section_summary(r)
    st.divider()
    section_first(r)
    st.divider()
    section_compare(r)
    st.divider()
    section_people(r)
    st.divider()
    section_table(r)
    with st.expander("충족 항목만 보기", expanded=False):
        for c in r["checks"]:
            if c["result"] == "충족":
                st.markdown(pill("충족", RESULT_COLOR["충족"]) + f"**{c['label']}** — {c['evidence']}",
                            unsafe_allow_html=True)
    st.divider()
    section_raw(r)


##################################################
# Main
##################################################

st.title("SW 동아리 회의비 증빙 검토")
st.caption("공고문·양식 규칙 대조 · 코드 판정 우선, AI는 장소·내용·사진 판단만 보조")
upload_section()
if st.session_state.get("result"):
    render_result(st.session_state["result"])
sidebar()   # 마지막에 그려야 이번 실행 결과가 '최근 검토'에 바로 보인다
