# upload.py
"""
upload.py
Upstage Files API
"""

from pathlib import Path

from agent_client import get_client


def upload_file(file_path: str | Path) -> str:
    """Files API로 문서를 올리고 File ID를 돌려준다."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"{file_path.name} 파일이 존재하지 않습니다.")

    print(f"Uploading... {file_path.name}")
    with open(file_path, "rb") as f:
        uploaded = get_client().files.create(file=f, purpose="user_data")
    print(f"Upload Complete · File ID : {uploaded.id}")
    return uploaded.id
