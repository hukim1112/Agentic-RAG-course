"""
문서 계열 설정: 한국은행 주력산업 모니터링 보고서

범용 정규화 함수(pdf_to_markdown)는 그대로 두고, 이 문서 계열에만 해당하는 규칙을 모아 둡니다.
새로운 문서 계열이 들어오면 이 파일과 같은 설정 모듈을 하나 추가합니다.
"""

import os
import re


BOK_PDF_OPTIONS = {
    "bookmark_level": 3,
    "noise_patterns": [
        r"\d{4}년\s+\d/\d분기\s+주력산업\s+모니터링\s+보고서\([^\)]+\)",  # 러닝 헤더
        r"<산업별 모니터링 결과>",                                       # 산업 첫 페이지의 장식 제목
        r"(?m)^[ \t*\-+.,%()~]*\d[ \t\d*\-+.,%()~]*$",                   # 차트 축 눈금·페이지 번호 (숫자만 있는 줄)
    ],
    "heading_map": {
        "###### 최근 동향": "## 최근 동향 및 주요 실적",
        "###### 향후 전망": "## 향후 전망 및 리스크 요인",
    },
    "demote_parser_headings": True,          # 계층은 북마크(H1)와 heading_map(H2)에서만 만든다
    "md_options": {"ignore_graphics": True}, # 배경 도형이 깔린 요약 박스 텍스트 보존
}


def bok_metadata(path: str, meta: dict) -> dict:
    """파일명(예: 2024_3사분기_...)에서 연도/분기 메타데이터를 추출합니다."""
    m = re.search(r"(\d{4})_(\d)사분기", os.path.basename(path))
    if not m:
        return {}
    year, quarter = int(m.group(1)), int(m.group(2))
    return {"year": year, "quarter": quarter, "quarter_name": f"{year}년 {quarter}/4분기"}
