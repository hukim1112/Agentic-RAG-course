"""
정규화 결과 검수: 변환 과정에서 원문 텍스트가 사라지지 않았는지 숫자로 확인합니다.
"""

import re


def measure_text_coverage(pdf_path: str, markdown_text: str, min_chars: int = 12) -> dict:
    """정규화 결과 검수: PDF 텍스트 레이어의 각 줄이 Markdown에 남아 있는지 확인합니다.

    공백·Markdown 기호를 지운 뒤 각 줄의 앞 min_chars 글자가 결과에 있는지로 판정합니다.

    Returns:
        {"kept": 보존된 줄 수, "total": 검사한 줄 수, "ratio": 보존율, "lost": [(페이지, 사라진 줄), ...]}
    """
    import pymupdf

    def norm(s: str) -> str:
        return re.sub(r"[\s\*\#\|\[\]\-]+", "", s)

    md_norm = norm(markdown_text)
    total, lost = 0, []
    for page_idx, page in enumerate(pymupdf.open(pdf_path)):
        for line in page.get_text().splitlines():
            key = norm(line)
            if len(key) < min_chars:
                continue
            total += 1
            if key[:min_chars] not in md_norm:
                lost.append((page_idx + 1, line.strip()))
    kept = total - len(lost)
    return {"kept": kept, "total": total, "ratio": kept / total if total else 1.0, "lost": lost}
