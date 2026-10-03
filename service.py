# service.py
"""
service.py
UI와 app.py 사이의 서비스 계층

Streamlit은 이 모듈의 함수만 호출한다 (화면 코드에서 API 직접 호출 금지).
"""

import time
from pathlib import Path

import app
from config import (
    DEMO_MODE, MAX_UPLOAD_MB, RULES_CACHE, SAMPLE_REVIEW, SAMPLE_RULES,
    SAMPLE_SUBMISSION, missing_env,
)
from file_manager import load_json, new_run_dir, save_json

StepError = app.StepError
STEPS = app.STEPS


class UploadError(Exception):
    pass


def is_demo() -> bool:
    return DEMO_MODE


def config_problems() -> list[str]:
    return [] if DEMO_MODE else missing_env()


def validate_upload(name: str, data: bytes):
    if not data:
        raise UploadError("파일이 없습니다. 회의비 지출 증빙 PDF를 올려 주세요.")
    if not name.lower().endswith(".pdf") or not data.startswith(b"%PDF"):
        raise UploadError("PDF 파일만 검토할 수 있습니다. HWP·이미지는 PDF로 변환해 올려 주세요.")
    size_mb = len(data) / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        raise UploadError(f"파일이 {size_mb:.1f}MB입니다. {MAX_UPLOAD_MB}MB 이하로 줄여 주세요.")


def current_rules() -> dict:
    """사이드바 기준 요약용. 캐시가 없으면 샘플 규칙."""
    path = RULES_CACHE if RULES_CACHE.exists() and not DEMO_MODE else SAMPLE_RULES
    return load_json(path)


def refresh_rules(progress=app._noop) -> dict:
    """관리자용: Rule Agent로 규칙을 다시 추출해 캐시를 덮어쓴다."""
    if DEMO_MODE:
        raise StepError(STEPS[0], "DEMO_MODE에서는 규칙을 다시 추출할 수 없습니다.")
    app.validate_config()
    return app.load_rules(force=True, progress=progress)


def run_review_service(file_name: str, data: bytes, progress=app._noop) -> dict:
    validate_upload(file_name, data)
    if DEMO_MODE:
        return _run_demo(file_name, progress)

    run_dir = new_run_dir()
    pdf_path = run_dir / "upload.pdf"
    pdf_path.write_bytes(data)   # 실행 폴더에만 두고, 결과 화면 이후 보관하지 않는다
    try:
        started = time.monotonic()
        app.validate_config()
        rules = app.load_rules(progress=progress)
        save_json(rules, run_dir / "rules.json")
        submission = app.process_submission(pdf_path, run_dir, progress)
        review_pdf = app.build_review_pdf(run_dir, progress)
        review, review_error = app.process_review(review_pdf, run_dir, progress)
        return app.finalize(rules, submission, review, review_error, run_dir,
                            file_name, started, progress=progress)
    finally:
        pdf_path.unlink(missing_ok=True)


def _run_demo(file_name: str, progress) -> dict:
    """API 없이 samples/*.json으로 같은 흐름을 재현한다."""
    started = time.monotonic()
    run_dir = new_run_dir()
    rules = load_json(SAMPLE_RULES)
    submission = load_json(SAMPLE_SUBMISSION)
    review = load_json(SAMPLE_REVIEW)
    for step, note in zip(STEPS[:2], ("(샘플 규칙)", "(샘플 제출값)")):
        progress(step, "done", note)
    save_json(rules, run_dir / "rules.json")
    save_json(submission, run_dir / "submission.json")
    app.build_review_pdf(run_dir, progress)
    progress(STEPS[3], "done", "(샘플 검토 결과)")
    return app.finalize(rules, submission, review, None, run_dir,
                        file_name, started, demo=True, progress=progress)


def read_bytes(path: str) -> bytes:
    p = Path(path)
    return p.read_bytes() if p.exists() else b""
