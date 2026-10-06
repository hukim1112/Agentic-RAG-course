"""
문서 정규화: 원본 문서(.md / .pdf / .txt)를 표준 Markdown(H1~H4 계층)으로 변환합니다.

문서 형식이 늘어나면 이 모듈에 정규화기만 추가하고, 청킹·인덱싱·검색은 그대로 재사용합니다.
"""

import os
import re
from typing import Dict, List, Optional, Tuple


def pdf_to_markdown(
    pdf_path: str,
    bookmark_level: Optional[int] = None,
    noise_patterns: Optional[List[str]] = None,
    heading_map: Optional[Dict[str, str]] = None,
    demote_parser_headings: bool = False,
    md_options: Optional[dict] = None,
) -> Tuple[str, dict]:
    """PDF를 표준 Markdown으로 정규화합니다.

    1. pymupdf4llm으로 페이지별 Markdown 변환 (다단 편집, 표 구조 보존)
    2. 파서 헤더 강등: 파서가 글자 크기로 추정한 H1~H4를 본문으로 내림 (계층은 3·5단계에서만 생성)
    3. 노이즈 제거: 러닝 헤더, 워터마크 등 반복 문구를 정규식으로 삭제
    4. 소제목 치환: 문서 고유의 소제목 표기를 표준 헤더로 교체
    5. 헤더 승격(Header Promotion): PDF 전자 북마크가 가리키는 페이지 상단에 `# 제목` 헤더 삽입

    Args:
        pdf_path: 변환할 PDF 경로
        bookmark_level: H1으로 승격할 북마크 깊이. None이면 항목이 가장 많은 깊이를 자동 선택
        noise_patterns: 삭제할 정규식 목록
        heading_map: {원본 소제목 문자열: 표준 헤더 문자열} 치환 규칙
        demote_parser_headings: True면 파서가 만든 H1~H4를 신뢰하지 않고 본문으로 내림.
            표지 제목, 굵은 각주 등이 헤더로 오인되어 청크 경로가 오염되는 것을 막습니다.
        md_options: pymupdf4llm.to_markdown()에 그대로 전달할 옵션
            (예: {"ignore_graphics": True} → 배경 도형이 깔린 요약 박스의 텍스트도 보존)

    Returns:
        (markdown_text, metadata) 튜플. metadata에는 페이지 수와 승격된 섹션 목록이 담깁니다.
    """
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(pdf_path)
    toc = doc.get_toc()  # [[level, title, page], ...]

    if bookmark_level is None and toc:
        counts: Dict[int, int] = {}
        for level, _, _ in toc:
            counts[level] = counts.get(level, 0) + 1
        bookmark_level = max(counts, key=counts.get)

    # 페이지 번호 → 승격할 헤더 목록 (한 페이지에 여러 섹션이 시작될 수 있음)
    promoted: Dict[int, List[str]] = {}
    for level, title, page in toc:
        if level != bookmark_level or page < 1:
            continue
        clean_title = " ".join(title.replace("[", "(").replace("]", ")").split())
        promoted.setdefault(page, []).append(f"# {clean_title}")

    pages = []
    for page_idx in range(len(doc)):
        page_md = pymupdf4llm.to_markdown(doc, pages=[page_idx], **(md_options or {}))
        if demote_parser_headings:
            page_md = re.sub(r"(?m)^#{1,4} (.+)$", r"\1", page_md)
        for pattern in noise_patterns or []:
            page_md = re.sub(pattern, "", page_md)
        for src, dst in (heading_map or {}).items():
            page_md = page_md.replace(src, dst)
        headers = promoted.get(page_idx + 1)
        if headers:
            page_md = "\n\n".join(headers) + "\n\n" + page_md
        pages.append(page_md)

    metadata = {
        "source_file": os.path.basename(pdf_path),
        "total_pages": len(doc),
        "sections": [h[2:] for hs in promoted.values() for h in hs],
    }
    return "\n\n".join(pages), metadata


def to_markdown(path: str, pdf_options: Optional[dict] = None) -> Tuple[str, dict]:
    """파일 확장자에 맞는 정규화기를 골라 표준 Markdown으로 변환합니다."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return pdf_to_markdown(path, **(pdf_options or {}))
    if ext in (".md", ".markdown", ".txt"):
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), {"source_file": os.path.basename(path)}
    raise ValueError(f"지원하지 않는 문서 형식입니다: {path}")
