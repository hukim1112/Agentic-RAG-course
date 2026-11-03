"""
문서 계열 설정: AWS Well-Architected Framework 4대 Pillar 백서 시리즈
(Security / Reliability / Performance Efficiency / Cost Optimization)

범용 정규화 함수(pdf_to_markdown)는 그대로 두고, AWS Well-Architected 문서 계열에만 해당하는
규칙(북마크 기반 장 승격, Best Practice ID 및 하위 항목 계층화, 러닝 헤더·목차 점선 제거)을 정의합니다.

표준 Markdown 4단계 계층 규격:
  - H1 (#)    : 문서 최상위 제목 (예: # Security Pillar - AWS Well-Architected Framework)
  - H2 (##)   : 대분류 아키텍처 영역 (L1 북마크 승격, 예: ## Identity and access management, ## Detection)
                → ContextualHeader의 검색용 목차(toc["search"] = 2)에 포함
  - H3 (###)  : 설계 원칙 및 Best Practice 조항 (예: ### Design principles, ### SEC04-BP01 Configure service and application logging)
                → ContextualHeader의 읽기용 목차(toc["read"] = 3)에 포함 (재검색 지도)
  - H4 (####) : Best Practice 내부 표준 항목 (예: #### Desired outcome, #### Common anti-patterns, #### Implementation guidance)
                → 청크 분할 및 Breadcrumb 말단 경로에만 사용 (목차 오염 방지)
"""

import os
import re

AWS_PDF_OPTIONS = {
    "bookmark_level": 1,
    "noise_patterns": [
        # 1. 매 페이지 상단 러닝 헤더 제거
        r"(?m)^(?:Security|Reliability|Performance Efficiency|Cost Optimization)\s+Pillar\s+AWS\s+Well-Architected\s+Framework\s*$",
        # 2. 표지·목차·부록의 비본문 L1 북마크 헤더 제거
        r"(?m)^# (?:Table of Contents|Contributors|Further reading|Document revisions|Notices|AWS Glossary|(?:Security|Reliability|Performance Efficiency|Cost Optimization) Pillar)\s*$",
        # 3. 목차(Table of Contents) 페이지의 점선 리더 줄 제거
        r"(?m)^.*(?:\.\s*){5,}\**\d+\**\s*$",
    ],
    "heading_map": {
        # 1. 문서 최상위 제목(# ... - AWS Well-Architected Framework)을 제외한 나머지 L1 북마크를 H2(## 대분류 장)로 조정
        r"(?m)^# (?!.*AWS Well-Architected Framework$)(.+)$": r"## \1",
        # 2. 핵심 개념 및 Best Practice ID(SEC01-BP01, REL01-BP01, PERF01-BP01, COST01-BP01 등)를 H3(### 조항)로 승격
        #    (demote_parser_headings 후 ###### **...** 또는 **...** 형태 및 2줄 줄바꿈 제목 모두 대응)
        r"(?m)^(?:#+\s*)?\*\*((?:SEC|REL|PERF|COST)\d{2}-BP\d{2}[^*\n]+)\*\*\s*\*\*([^*\n]+)\*\*\s*$": r"### \1 \2",
        r"(?m)^(?:#+\s*)?\*\*((?:SEC|REL|PERF|COST)\d{2}-BP\d{2}[^*\n]+)\*\*\s*\n(?:#+\s*)?\*\*([^*\n]+)\*\*\s*$": r"### \1 \2",
        r"(?m)^(?:#+\s*)?\*\*((?:SEC|REL|PERF|COST)\d{2}-BP\d{2}[^*\n]+)\*\*\s*$": r"### \1",
        r"(?m)^(?:#+\s*)?\*\*(Design principles|Definition|Definitions|Shared [Rr]esponsibility[^*\n]*|Governance|AWS account management and separation|Operating your workloads securely|Identity management|Permissions management|Protecting networks|Protecting compute|Data classification|Protecting data at rest|Protecting data in transit)\*\*\s*$": r"### \1",
        # 3. Best Practice 내부의 반복 소제목을 H4(#### 세부 항목)로 승격
        r"(?m)^(?:#+\s*)?\*\*(Desired outcome|Common anti-patterns|Benefits of establishing this best practice|Implementation guidance|Implementation steps):?\*\*:?\s*": r"#### \1\n\n",
    },
    "demote_parser_headings": True,          # 파서의 불규칙한 H2~H5 추측을 먼저 내리고 북마크·규칙으로만 계층 생성
    "md_options": {"ignore_graphics": True}, # 배경 박스 안의 텍스트 누락 방지
}


_PILLAR_MAP = {
    "Security": ("security", "보안(Security)"),
    "Reliability": ("reliability", "신뢰성(Reliability)"),
    "Performance_Efficiency": ("performance", "성능 효율성(Performance Efficiency)"),
    "Cost_Optimization": ("cost", "비용 최적화(Cost Optimization)"),
}


def aws_metadata(path: str, meta: dict) -> dict:
    """파일명(예: AWS_Well_Architected_Security_Pillar.pdf)에서 아키텍처 기둥(pillar) 메타데이터를 추출합니다."""
    fname = os.path.basename(path)
    for key, (pillar_id, pillar_label) in _PILLAR_MAP.items():
        if key.lower() in fname.lower():
            return {
                "pillar": pillar_id,
                "pillar_name": pillar_label,
                "framework": "AWS Well-Architected",
            }
    m = re.search(r"AWS_Well_Architected_(.+)_Pillar", fname)
    pillar = m.group(1).lower() if m else "general"
    return {"pillar": pillar, "pillar_name": pillar, "framework": "AWS Well-Architected"}
