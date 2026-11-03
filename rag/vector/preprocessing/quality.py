"""
정규화 결과 검수: 변환 과정에서 원문 텍스트가 사라지지 않았는지 숫자로 확인합니다.
"""

import re
import unicodedata


def measure_text_coverage(pdf_path: str, markdown_text: str, min_chars: int = 12) -> dict:
    """정규화 결과 검수: PDF 텍스트 레이어의 각 줄이 Markdown에 남아 있는지 확인합니다.

    유니코드 합자(ﬁ→fi 등), 마크다운 링크 URL, 공백·기호를 정규화한 뒤
    각 줄의 앞 min_chars 글자가 결과에 있는지로 판정합니다.

    Returns:
        {"kept": 보존된 줄 수, "total": 검사한 줄 수, "ratio": 보존율, "lost": [(페이지, 사라진 줄), ...]}
    """
    import pymupdf

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s)
        s = re.sub(r"\]\([^)]+\)", "", s)  # Markdown 링크 URL 제거
        return re.sub(r"[\s\*\#\|\[\]\-•·._~()]+", "", s)

    md_norm = norm(markdown_text)
    total, lost = 0, []
    for page_idx, page in enumerate(pymupdf.open(pdf_path)):
        for line in page.get_text().splitlines():
            # 목차 점선 리더 줄(예: Introduction ........ 1)은 노이즈 제거 대상이므로 모수에서 제외
            if re.search(r"(?:\.\s*){5,}\d+\s*$", line):
                continue
            key = norm(line)
            if len(key) < min_chars:
                continue
            total += 1
            if key[:min_chars] not in md_norm:
                lost.append((page_idx + 1, line.strip()))
    kept = total - len(lost)
    return {"kept": kept, "total": total, "ratio": kept / total if total else 1.0, "lost": lost}
