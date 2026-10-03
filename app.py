# app.py
"""
app.py
워크플로우 Orchestrator (실행 순서만 담당)

Step 1. 규칙 로드      data/rules_cache.json → 없으면 Rule Agent
Step 2. 제출 서류 분석  업로드 PDF → Submission Agent → submission.json
Step 3. 검토 입력 PDF  review_builder.create_review_input() → Review_Input.pdf
Step 4. 검토           Review_Input.pdf → Review Agent (실패해도 계속)
Step 5. 후처리         코드 판정 우선 병합 → result.json · report.md

사용법: python app.py data/sample_meeting.pdf
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from config import RULE_REFERENCE_PDF, RULES_CACHE, validate_config
from file_manager import load_json, new_run_dir, save_json


class StepError(Exception):
    """어느 단계에서 멈췄는지 함께 전달한다."""

    def __init__(self, step: str, message: str):
        super().__init__(f"[{step}] {message}")
        self.step = step
        self.message = message


STEPS = ["규칙 로드", "제출 서류 분석", "검토 입력 PDF 생성", "AI 검토", "결과 정리"]


def _noop(step: str, state: str, detail: str = ""):
    print(f"  {state:>4} · {step} {detail}")


##################################################
# Step 1. 규칙
##################################################

def load_rules(force: bool = False, progress=_noop) -> dict:
    if RULES_CACHE.exists() and not force:
        progress(STEPS[0], "done", "(캐시)")
        return load_json(RULES_CACHE)

    from agents import analyze_rules
    from upload import upload_file
    progress(STEPS[0], "run", "(Rule Agent 실행)")
    try:
        rules = analyze_rules(upload_file(RULE_REFERENCE_PDF))
    except Exception as e:
        raise StepError(STEPS[0], f"Rule Agent 실패: {e}") from e
    save_json(rules, RULES_CACHE)
    progress(STEPS[0], "done", "(rules_cache.json 저장)")
    return rules


##################################################
# Step 2~4
##################################################

def process_submission(pdf_path: Path, run_dir: Path, progress=_noop) -> dict:
    from agents import analyze_submission
    from upload import upload_file
    progress(STEPS[1], "run")
    try:
        submission = analyze_submission(upload_file(pdf_path))
    except Exception as e:
        raise StepError(STEPS[1], f"Submission Agent 실패: {e}") from e
    from postprocess import normalize_submission
    submission = normalize_submission(submission)
    save_json(submission, run_dir / "submission.json")
    progress(STEPS[1], "done")
    return submission


def build_review_pdf(run_dir: Path, progress=_noop) -> Path:
    from review_builder import create_review_input
    progress(STEPS[2], "run")
    try:
        pdf = create_review_input(run_dir / "rules.json", run_dir / "submission.json",
                                  run_dir / "Review_Input.pdf")
    except Exception as e:
        raise StepError(STEPS[2], f"Review_Input.pdf 생성 실패 (추출값 형식 확인): {e}") from e
    progress(STEPS[2], "done")
    return pdf


def process_review(review_pdf: Path, run_dir: Path, progress=_noop):
    """(review_raw, error) — 실패해도 예외를 올리지 않는다 (코드 판정 fallback)."""
    from agents import analyze_review
    from upload import upload_file
    progress(STEPS[3], "run")
    try:
        review = analyze_review(upload_file(review_pdf))
    except Exception as e:
        progress(STEPS[3], "fail", f"→ 코드 판정만 사용 ({e})")
        return None, str(e)
    save_json(review, run_dir / "review.json")
    progress(STEPS[3], "done")
    return review, None


##################################################
# 전체 실행
##################################################

def finalize(rules, submission, review, review_error, run_dir: Path,
             file_name: str, started: float, demo: bool = False, progress=_noop) -> dict:
    from postprocess import build_result
    from report import build_report
    progress(STEPS[4], "run")
    result = build_result(rules, submission, review, review_error)
    result.update(
        run_id=run_dir.name, file_name=file_name, demo_mode=demo,
        created_at=f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        elapsed_sec=round(time.monotonic() - started, 1),
        paths={"run_dir": str(run_dir),
               "review_pdf": str(run_dir / "Review_Input.pdf"),
               "result_json": str(run_dir / "result.json"),
               "report_md": str(run_dir / "report.md")},
    )
    save_json(result, run_dir / "result.json")
    (run_dir / "report.md").write_text(build_report(result), encoding="utf-8")
    progress(STEPS[4], "done")
    return result


def run_pipeline(pdf_path: str | Path, file_name: str | None = None, progress=_noop) -> dict:
    validate_config()
    started = time.monotonic()
    pdf_path = Path(pdf_path)
    run_dir = new_run_dir()

    rules = load_rules(progress=progress)
    save_json(rules, run_dir / "rules.json")
    submission = process_submission(pdf_path, run_dir, progress)
    review_pdf = build_review_pdf(run_dir, progress)
    review, review_error = process_review(review_pdf, run_dir, progress)
    return finalize(rules, submission, review, review_error, run_dir,
                    file_name or pdf_path.name, started, progress=progress)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("사용법: python app.py <회의비 증빙 PDF>")
        return 2
    pdf = Path(argv[1])
    if not pdf.exists() or pdf.suffix.lower() != ".pdf":
        print(f"PDF 파일을 찾을 수 없습니다: {pdf}")
        return 2

    print("=" * 60)
    print("SW 동아리 회의비 증빙 검토")
    print("=" * 60)
    try:
        result = run_pipeline(pdf)
    except (StepError, EnvironmentError) as e:
        print(f"\n중단: {e}")
        return 1

    c = result["counts"]
    print("\n" + "=" * 60)
    print(f"판정   : {result['overall']}")
    print(f"적합도 : {result['fitness']}%  ({result['fitness_formula']})")
    print(f"충족 {c['충족']} · 미충족 {c['미충족']} · 확인필요 {c['확인필요']} · 참고 {c['참고']}")
    print(f"요약   : {result['summary']}")
    for k in result["checks"]:
        print(f"  {k['id']:>3} {k['result']:<5} {k['name']} — {k['evidence']}")
    for w in result["warnings"] + result["overrides"]:
        print(f"  ! {w}")
    print(f"소요   : {result['elapsed_sec']}초")
    print(f"산출물 : {result['paths']['run_dir']}")
    print(f"규칙   : {RULES_CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
