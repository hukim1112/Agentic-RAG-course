"""
app/tools/file_rag_tools.py — 엔터프라이즈 File RAG 탐색 도구 3종 (Mission 01 실습 대상)

👉 missions/01_missions.md의 1단계 가이드를 참고하여
   list_docs, search_docs, read_doc 3개 도구를 구현하세요!
"""

import re
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = (PROJECT_ROOT / "data" / "policies").resolve()
ALLOWED_EXTS = {".md", ".txt"}
MAX_READ_LINES = 150


def _resolve_safe_path(rel_path: str) -> tuple[Optional[Path], Optional[str]]:
    """문서 루트(DOCS_ROOT) 외부로의 경로 탈출(Path Traversal)을 차단하고 대상 경로를 해석합니다."""
    raw = (rel_path or "").strip().strip("'\"")
    candidate = (DOCS_ROOT / raw).resolve()
    if not candidate.is_relative_to(DOCS_ROOT):
        return None, f"[보안 차단] 허용된 문서 루트(data/policies) 외부 경로에는 접근할 수 없습니다: '{rel_path}'"
    return candidate, None


def _iter_doc_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(
        p for p in base_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS and p.resolve().is_relative_to(DOCS_ROOT)
    )


# ==============================================================================
# TODO 1: list_docs 도구 구현 (@tool(parse_docstring=True))
# - DOCS_ROOT(또는 하위 폴더) 내 문서 파일 경로, 줄 수, 크기, 첫 줄 제목을 반환합니다.
# ==============================================================================
@tool(parse_docstring=True)
def list_docs(subdir: str = "") -> str:
    """허용된 사내 문서 저장소(data/policies) 내 문서 파일 목록, 줄 수, 크기, 첫 줄 제목을 조회합니다.

    Args:
        subdir: 조회할 하위 폴더 상대 경로. 생략하면 저장소 전체 문서 목록을 반환합니다.
    """
    raise NotImplementedError("Mission 01: list_docs() 도구를 구현하세요. (missions/01_missions.md 참고)")


# ==============================================================================
# TODO 2: search_docs 도구 구현 (@tool(parse_docstring=True))
# - 전체 문서를 가로질러 query 키워드/정규식이 등장하는 파일명, 줄 번호, 섹션, 스니펫을 반환합니다.
# ==============================================================================
@tool(parse_docstring=True)
def search_docs(query: str, path_filter: Optional[str] = None) -> str:
    """문서 저장소 전체(또는 특정 파일)를 가로질러 키워드나 정규식이 등장하는 파일명·줄번호·섹션·스니펫을 검색합니다.

    어느 파일의 몇 번째 줄에 관련 내용이 있는지 모를 때 read_doc 호출 전에 먼저 사용하세요.

    Args:
        query: 검색할 핵심 키워드(공백으로 여러 단어 입력 가능) 또는 정규표현식 (예: '숙박비 부산', '제14조', 'GPU.*회수')
        path_filter: 특정 파일명이나 하위 경로 일부로 범위를 좁힐 때 지정 (예: '여비', '보안'). 생략 시 전체 문서 검색
    """
    raise NotImplementedError("Mission 01: search_docs() 도구를 구현하세요. (missions/01_missions.md 참고)")


# ==============================================================================
# TODO 3: read_doc 도구 구현 (@tool(parse_docstring=True))
# - _resolve_safe_path로 샌드박스 경로를 검증하고 지정한 줄 구간(start_line ~ end_line)을 반환합니다.
# ==============================================================================
@tool(parse_docstring=True)
def read_doc(filename: str, start_line: int = 1, end_line: int = 100) -> str:
    """지정한 문서 파일의 특정 줄 구간(start_line ~ end_line) 원문을 줄 번호와 함께 정밀 열람합니다.

    Args:
        filename: 열람할 문서 상대 경로 또는 파일명 (예: '2026_국내여비교통비지급규정.md')
        start_line: 읽기 시작할 줄 번호 (1부터 시작, 기본값 1)
        end_line: 읽기 종료할 줄 번호 (1회 최대 150줄까지 열람 가능, 기본값 100)
    """
    raise NotImplementedError("Mission 01: read_doc() 도구를 구현하세요. (missions/01_missions.md 참고)")


file_rag_tools = [list_docs, search_docs, read_doc]

__all__ = ["list_docs", "search_docs", "read_doc", "file_rag_tools"]
