# SW 동아리 회의비 증빙 검토 서비스

회의비 지출 증빙 PDF(회의비 지출 증빙 + 영수증 첨부철)를 올리면 공고문·양식 규칙과 대조해
**판정(적합 / 보완필요 / 부적합)**, **적합도(%)**, 먼저 확인할 항목, 규칙과 제출값의 대조 근거를 보여주는 Streamlit 서비스입니다.
서류 심사 보조 결과이며 지급 승인이 아닙니다.

## 구조 (수업 스타터 `hr-ai-service-workflow` 계층을 따름)

```
streamlit_app.py  화면만            ─┐
service.py        UI ↔ 워크플로우     │  Streamlit → service → app → agents
app.py            실행 순서 (CLI 겸용) │  화면 코드는 API를 직접 부르지 않는다
agents.py         Rule / Submission / Review Agent
agent_client.py   Studio Job 생성 → Polling(300초 제한) → 출처·코드펜스 제거 → JSON
upload.py         Upstage Files API
review_builder.py 코드 판정 C1~C13 + Review_Input.pdf (제공 파일, 판정 로직 수정 금지)
postprocess.py    코드 판정 우선 병합 · 최종 판정 · 적합도 재계산 · Review Agent 실패 fallback
report.py         검토 보고서 .md
config.py         .env / Streamlit Secrets, 경로
file_manager.py   실행별 폴더 output/runs/<run_id>/
```

처리 흐름

1. 규칙: `data/rules_cache.json`이 있으면 사용하고, 없으면 Rule Agent로 `data/rule_reference.pdf`를 읽어 저장합니다.
2. 업로드 PDF → Submission Agent
3. `review_builder.py`가 코드 판정 → `Review_Input.pdf`
4. `Review_Input.pdf` → Review Agent
5. 후처리 단계에서는 **코드 판정이 우선**합니다. AI 판단은 C8(회의장소)과 C9(회의내용)에만 반영되고, C11(사진)은 AI가 "미충족"이라고 할 때만 반영됩니다. 최종 판정과 적합도는 코드가 다시 계산합니다.

- 적합도 = (충족 + 확인필요 × 0.5) ÷ ("참고" 제외 항목 수) × 100
- 판정: C5·C7·C8 중 하나라도 미충족이면 부적합, 그 외 미충족이 있으면 보완필요, 미충족이 없으면 적합

## 로컬 실행

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # 키·Agent ID 입력 (커밋 금지)

DEMO_MODE=1 streamlit run streamlit_app.py   # API 없이 샘플로 화면 확인
streamlit run streamlit_app.py               # 실제 실행
python app.py data/sample_meeting.pdf        # CLI: 판정·적합도 출력, rules_cache.json 생성
pytest                                       # 후처리 단위 테스트
```

## 배포 (Streamlit Community Cloud, 무료)

1. `data/rules_cache.json`이 저장소에 포함됐는지 확인합니다. 배포 서버는 이 파일을 그대로 써서 Rule Agent 호출을 건너뜁니다.
2. `git status`에 `.env`나 `.streamlit/secrets.toml`이 없는지 확인한 뒤 GitHub에 push합니다.
3. https://share.streamlit.io 에서 **New app**을 누르고 저장소, 브랜치, Main file `streamlit_app.py`를 고릅니다.
4. **Advanced settings**에서 Python 3.11을 고르고, **Secrets**에 `.streamlit/secrets.toml.example` 형식으로 값 7개를 붙여 넣습니다.
5. Deploy를 누릅니다. 규칙이 바뀌면 사이드바의 "관리자: 규칙 다시 추출"을 실행하거나, 로컬에서 캐시를 다시 만들어 커밋합니다.

참고: Streamlit Cloud의 파일 시스템은 임시 공간입니다. 화면에서 "규칙 다시 추출"을 해도 앱을 재시작하면 커밋된 캐시로 되돌아갑니다.

## 데이터

- `data/rule_reference.pdf`: 공고문과 빈 양식(기준 문서)
- `data/sample_meeting.pdf`: 샘플 제출 서류
- `samples/*.json`: DEMO_MODE용 에이전트 출력 예시
- 업로드한 PDF는 실행이 끝나면 삭제합니다. 중간 산출물(`output/runs/`)은 git에서 제외됩니다.
