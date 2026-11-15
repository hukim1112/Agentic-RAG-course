"""
app/tools/file_rag_tools.py — 파일 기반 RAG 탐색 도구 3종 (Mission 01 완성본)

별도의 벡터 인덱싱 없이 문서 폴더(DOCS_ROOT) 내부의 텍스트·마크다운 문서를
1) 목록 조회(list_docs) -> 2) 키워드/정규식 검색(search_docs) -> 3) 줄 구간 열람(read_doc)
순서로 탐색하며, Path.resolve().is_relative_to() 검증으로 허용 폴더 외부 접근(../.env 등)을 차단합니다.
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
    """허용된 문서 루트(DOCS_ROOT) 외부 경로로의 접근(Path Traversal)을 차단합니다."""
    raw = (rel_path or "").strip().strip("'\"")
    candidate = (DOCS_ROOT / raw).resolve()
    if not candidate.is_relative_to(DOCS_ROOT):
        return None, f"[접근 차단] 허용된 문서 폴더(data/policies) 외부 경로입니다: '{rel_path}'"
    return candidate, None


def _iter_doc_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(
        p for p in base_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS and p.resolve().is_relative_to(DOCS_ROOT)
    )


def _clean_snippet(text: str, max_len: int = 100) -> str:
    """마크다운 기호와 표 구분자를 정리해 한 줄 미리보기로 다듬습니다."""
    cleaned = re.sub(r"<br\s*/?>", ", ", text)
    cleaned = cleaned.replace("**", "").replace("`", "")
    if cleaned.strip().startswith("|"):
        cells = [c.strip() for c in cleaned.strip().strip("|").split("|") if c.strip()]
        cleaned = " | ".join(cells)
    else:
        cleaned = re.sub(r"^#+\s*", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len] + ("..." if len(cleaned) > max_len else "")


@tool(parse_docstring=True)
def list_docs(subdir: str = "") -> str:
    """사내 문서 폴더(data/policies) 내 문서 파일 목록, 줄 수, 크기, 첫 줄 제목을 조회합니다.

    Args:
        subdir: 조회할 하위 폴더 상대 경로. 생략하면 전체 문서 목록을 반환합니다.
    """
    target_dir, err = _resolve_safe_path(subdir)
    if err:
        return err
    if not target_dir.exists() or not target_dir.is_dir():
        return f"[오류] 디렉터리를 찾을 수 없습니다: '{subdir}'"

    files = _iter_doc_files(target_dir)
    if not files:
        return "[알림] 조회 가능한 문서 파일(.md, .txt)이 없습니다."

    rows = []
    for fpath in files:
        rel = fpath.relative_to(DOCS_ROOT).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        first_title = next((ln.strip().lstrip("# ").strip() for ln in lines if ln.strip()), "(제목 없음)")
        size_kb = fpath.stat().st_size / 1024
        rows.append(f"- {rel} ({len(lines)}줄, {size_kb:.1f}KB) : {first_title}")

    return f"문서 목록 (총 {len(rows)}개 파일):\n" + "\n".join(rows)


@tool(parse_docstring=True)
def search_docs(query: str, path_filter: Optional[str] = None) -> str:
    """문서 폴더에서 키워드 또는 정규표현식이 포함된 파일명, 줄 번호, 섹션 제목, 미리보기를 검색합니다.

    관련 내용이 어느 파일의 몇 번째 줄에 있는지 모를 때 read_doc 호출 전에 먼저 사용하세요.

    Args:
        query: 검색할 키워드(공백으로 여러 단어 입력 가능) 또는 정규표현식 (예: '숙박비 상한액', '제14조', 'GPU.*회수')
        path_filter: 특정 파일명 일부로 검색 범위를 좁힐 때 지정 (예: '여비', '보안'). 생략 시 전체 문서 검색
    """
    q = (query or "").strip()
    if not q:
        return "[오류] 검색어(query)를 입력해 주세요."

    if path_filter and ".." in path_filter:
        _, err = _resolve_safe_path(path_filter)
        if err:
            return err

    files = _iter_doc_files(DOCS_ROOT)
    if path_filter:
        pf = path_filter.strip().lower()
        files = [f for f in files if pf in f.relative_to(DOCS_ROOT).as_posix().lower()]
    if not files:
        return f"[알림] path_filter='{path_filter}' 조건에 해당하는 문서가 없습니다."

    terms = [t for t in q.split() if t]
    regex = None
    if len(terms) == 1 and any(ch in q for ch in ".*+?[]()|^$"):
        try:
            regex = re.compile(q, re.IGNORECASE)
        except re.error:
            regex = None

    candidates = []
    for fpath in files:
        rel = fpath.relative_to(DOCS_ROOT).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        current_section = "문서 상단"

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or re.fullmatch(r"[\s|:\-]+", stripped):
                continue
            is_heading = stripped.startswith("#")
            if is_heading:
                current_section = stripped.lstrip("#").strip()

            if regex:
                if not regex.search(line):
                    continue
                score = (1, 1, 1)
            else:
                line_lower = line.lower()
                line_hits = sum(1 for t in terms if t.lower() in line_lower)
                if line_hits == 0:
                    continue
                sec_lower = current_section.lower()
                sec_hits = sum(1 for t in terms if t.lower() in sec_lower)
                ctx_hits = sum(1 for t in terms if t.lower() in f"{sec_lower} {line_lower}")
                score = (ctx_hits, line_hits, sec_hits)

            preview_src = stripped
            if is_heading:
                preview_src = ""
                for nxt in lines[idx + 1: idx + 4]:
                    ns = nxt.strip()
                    if ns.startswith("#"):
                        break
                    if ns and not re.fullmatch(r"[\s|:\-]+", ns):
                        preview_src = ns
                        break
                if not preview_src:
                    continue

            candidates.append((score, rel, idx + 1, current_section, _clean_snippet(preview_src)))

    if not candidates:
        return f"[검색 결과 없음] '{query}'와 일치하는 구절이 없습니다. 다른 키워드로 검색하거나 list_docs()로 문서 목록을 확인하세요."

    if len(terms) >= 2:
        best_ctx = max(c[0][0] for c in candidates)
        if best_ctx >= 2:
            narrowed = [c for c in candidates if c[0][0] >= max(2, best_ctx - 1)]
            if narrowed:
                candidates = narrowed

    candidates.sort(key=lambda x: (-x[0][0], -x[0][1], -x[0][2], x[1], x[2]))
    deduped = []
    seen_sections: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item[1], item[3])
        if key in seen_sections:
            continue
        seen_sections.add(key)
        deduped.append(item)

    shown = deduped[:5]
    out = [f"['{query}' 검색 결과: 관련 섹션 {len(deduped)}건 중 상위 {len(shown)}건]"]
    for i, (_, rel, line_no, sec, snippet) in enumerate(shown, 1):
        out.append(f"{i}. {rel} (L{line_no} | {sec})\n   {snippet}")
    return "\n".join(out)


@tool(parse_docstring=True)
def read_doc(filename: str, start_line: int = 1, end_line: int = 100) -> str:
    """지정한 문서의 특정 줄 구간(start_line ~ end_line) 원문을 줄 번호와 함께 읽습니다.

    Args:
        filename: 열람할 문서 파일명 또는 상대 경로 (예: '2026_국내여비교통비지급규정.md')
        start_line: 읽기 시작할 줄 번호 (1부터 시작, 기본값 1)
        end_line: 읽기 종료할 줄 번호 (1회 최대 150줄, 기본값 100)
    """
    fpath, err = _resolve_safe_path(filename)
    if err:
        return err

    if not fpath.is_file():
        stem = Path(filename.strip()).stem.lower()
        candidates = [f for f in _iter_doc_files(DOCS_ROOT) if stem and stem in f.name.lower()]
        if len(candidates) == 1:
            fpath = candidates[0]
        else:
            return f"[오류] '{filename}' 파일을 찾을 수 없습니다. list_docs()로 정확한 파일명을 확인하세요."

    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    s = max(1, int(start_line))
    e = min(total, max(s, int(end_line)), s + MAX_READ_LINES - 1)

    if s > total:
        return f"[알림] '{fpath.name}' 파일은 전체 {total}줄입니다. start_line({s})을 {total} 이하로 지정하세요."

    rel = fpath.relative_to(DOCS_ROOT).as_posix()
    body = "\n".join(f"{ln_no:4d} | {lines[ln_no - 1]}" for ln_no in range(s, e + 1))
    return f"[파일: {rel} | 열람 구간: {s}~{e}줄 / 전체 {total}줄]\n{body}"


file_rag_tools = [list_docs, search_docs, read_doc]

__all__ = ["list_docs", "search_docs", "read_doc", "file_rag_tools"]
