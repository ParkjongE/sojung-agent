# PRD: SW 동아리 회의비 증빙 검토 서비스

## 1. 개요
학생이 **회의비 지출 증빙 PDF**(회의비 지출 증빙 + 영수증 첨부철)를 웹에 올리면, 미리 넣어 둔 **공고문·양식 규칙**과 대조해 판정(적합 / 보완필요 / 부적합), 적합도(%), 확인해야 할 부분, 규칙과 제출값의 대조 근거를 보여주는 Streamlit 웹 서비스.

- 사용자: 제출 전 자기 서류를 점검하는 학생, 제출 서류를 검토하는 사업단 담당자
- 기반: 수업 가이드 스타터(`hr-ai-service-workflow`) 구조와 `agent_client.py` 호출 방식을 따른다

## 2. 범위
- 포함: 회의비 지출 증빙 1종 검토, 웹 업로드, 결과 화면, 결과 다운로드, 무료 배포
- 제외: 구매요청서·구입증빙서·전문가 활용비, 로그인, DB 저장, 같은 팀의 다른 제출 건 누적 비교

## 3. 시스템 구성
Upstage Studio 에이전트 3개는 이미 만들어져 있고 코드는 Agent ID로 호출만 한다. 값은 루트 `.env`에 있다 (커밋·출력 금지).

| 에이전트 | 입력 | 출력 | 환경변수 |
|---|---|---|---|
| Rule Agent | `data/rule_reference.pdf` (공고문 + 빈 양식, 미리 넣어 둠) | 규칙 JSON | RULE_AGENT_ID / RULE_CONFIG_ID |
| Submission Agent | 학생 업로드 PDF | 제출 서류 JSON | SUBMISSION_AGENT_ID / SUBMISSION_CONFIG_ID |
| Review Agent | 코드가 만든 `Review_Input.pdf` | 검토 JSON | REVIEW_AGENT_ID / REVIEW_CONFIG_ID |

공통: `UPSTAGE_API_KEY`

처리 흐름:
1. 규칙 로드: `data/rules_cache.json`이 있으면 사용, 없으면 Rule Agent 실행 후 저장
2. 업로드 PDF → Submission Agent
3. `review_builder.py`(제공)로 규칙 + 제출 JSON을 매핑하고 코드 판정 → `Review_Input.pdf`
4. `Review_Input.pdf` → Review Agent
5. 후처리: **코드 판정이 우선**. Review Agent는 C8 회의장소, C9 회의내용, C11 사진 장소 판단과 문장 작성만 반영. 최종 판정은 코드가 재계산. Review Agent 실패 시 코드 판정만으로 결과 표시

에이전트 출력 필드 이름은 `samples/sample_rules.json`, `samples/sample_submission.json`, 그리고 Review Agent의 `overall, summary, attendee_count, per_person_amount, check_id[], check_result[], check_evidence[], fix_requests[], admin_notes[]`를 따른다. Studio 결과는 단일 값도 리스트로, 테이블은 `[{...}]`로 올 수 있다. **필드 이름과 `review_builder.py`의 `compute_checks()` 판정 로직은 바꾸지 않는다.**

## 4. 판정 규칙
- 검사 항목 C1~C13: `review_builder.py`의 `compute_checks()` 참고
- 최종 판정: C5(날짜 일치)·C7(1인당 한도)·C8(회의장소) 중 미충족 → 부적합 / 그 외 미충족 → 보완필요 / 없음 → 적합. "참고"는 제외
- 적합도(%) = (충족 + 확인필요 × 0.5) ÷ ("참고" 제외 항목 수) × 100, 화면에 공식 함께 표시

## 5. 화면 요구사항
**사이드바**: 서비스 소개, 적용 기준 요약(1인당 한도·월 한도·날짜·장소·사진 규칙), 기준 문서 다운로드, 관리자용 "규칙 다시 추출", 최근 검토 5건

**업로드**: 드래그 앤 드롭 또는 파일 선택(PDF, 최대 20MB) → "검토 시작" → 단계별 진행 표시

**결과** (위에서 아래 순서, 가독성 최우선)
1. 판정 요약: 판정 배지(초록/주황/빨강), 적합도 % 와 진행 막대, 충족·미충족·확인필요 개수, 요약 문장
2. 먼저 확인할 것: 미충족 항목(문제 + 보완 요청), 확인필요 항목(담당자가 볼 것)을 카드로 강조
3. 핵심 대조: 날짜(회의록 / 영수증 / 첨부철), 금액(결제금액 / 기재금액 / 인원 / 1인당 / 한도·초과액), 동아리명·구분
4. 참석자·사진: 이름별 서명 여부, 사진 장수와 사진 속 인원 대 참석 인원, 판독 메모
5. 전체 검사표: 항목별로 **공고·양식 기준 문구 | 제출 서류 값 | 판정 | 근거 | 판정 주체(코드/AI)** 나란히
6. 원본 데이터 탭과 다운로드(결과 JSON, Review_Input.pdf, 검토 보고서 .md)

## 6. 비기능 요구사항
- 화면 코드에서 API 직접 호출 금지 (Streamlit → service → agent 계층)
- 실행마다 별도 폴더에 중간 산출물 저장 (동시 사용 대비)
- 파일 없음 / 용량 초과 / 에이전트 실패 / JSON 파싱 실패 / 환경변수 누락 시 원인 메시지, 화면 멈춤 없음
- 에이전트 결과의 `【†숫자】` 출처 표시와 코드펜스 제거 후 파싱, 호출 타임아웃 300초
- `DEMO_MODE=1`이면 API 없이 samples로 결과 화면 렌더링 (UI 개발·시연용)

## 7. 배포
**Streamlit Community Cloud** (무료). 비밀값은 로컬은 `.env`, 배포는 Streamlit Secrets에서 읽는다. `data/rules_cache.json`은 커밋해 배포 서버에서 재사용한다. README에 배포 절차를 적는다. GitHub push와 Secrets 입력은 사용자가 한다.

## 8. 완료 기준
- `DEMO_MODE=1`로 결과 화면 1~6이 모두 렌더링
- `python app.py data/sample_meeting.pdf`가 실제 API로 판정·적합도 출력, `rules_cache.json` 생성
- Streamlit에서 업로드 → 검토 → 결과 → 다운로드 동작
- 후처리 단위 테스트 통과 (정상 / 에이전트 오판을 코드가 덮어씀 / 리스트 길이 불일치 / 에이전트 실패 fallback / 적합도 계산)
- `git status`에 `.env`, `.streamlit/secrets.toml` 없음
