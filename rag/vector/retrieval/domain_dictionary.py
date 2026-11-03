"""
사내 도메인 약어 및 동의어 사전 모듈 (Domain Dictionary Module)

사내 약어, 부서 별칭, 일상 용어를 규정집의 정식 명칭으로 0ms에 정규화하여
BM25 키워드 검색과 Dense 의미 검색의 매칭 정확도를 높입니다.
"""

import re
from typing import Dict, List, Optional, Tuple, Union


class DomainDictionary:
    """사내 약어 및 동의어 정규화 사전 클래스"""

    DEFAULT_SYNONYMS: Dict[str, str] = {
        # 부서 약어 → 공식 부서명
        "클운팀": "클라우드운영팀",
        "인프라팀": "인프라엔지니어링팀",
        "에이팀": "AgenticAI팀",
        "데플팀": "데이터플랫폼팀",
        "인사팀": "인사기획팀",
        "재무팀": "재무관리팀",
        "보안팀": "정보보안팀",
        "AI랩": "인공지능연구소",
        "데이터팀": "데이터엔지니어링팀",

        # 일상 용어 / 약어 → 규정 표준 용어
        "출장비": "국내 여비 및 교통비",
        "밥값": "식비",
        "식대": "식비",
        "차비": "교통비",
        "연차": "연차유급휴가",
        "반차": "반일 휴가",
        "재택": "재택근무",
        "전결": "위임전결 권한",
        "유휴 GPU": "유휴 GPU 회수",
        "보안위반": "정보보안 위반 징계",
        "DLP": "DLP 사외 데이터 반출 승인",
        "CISO": "CISO 정보보안책임자",
    }

    def __init__(self, custom_synonyms: Optional[Dict[str, str]] = None):
        self.synonym_map: Dict[str, str] = self.DEFAULT_SYNONYMS.copy()
        if custom_synonyms:
            self.synonym_map.update(custom_synonyms)

        # 이미 정식 명칭이 들어 있는 경우(예: '연차유급휴가', '재택근무') 앞글자('연차', '재택')만
        # 중복 치환되어 '연차유급휴가유급휴가'가 되는 버그를 막기 위해 정식 명칭도 패턴에 함께 등록합니다.
        self._replace_table: Dict[str, str] = {v: v for v in self.synonym_map.values()}
        self._replace_table.update(self.synonym_map)

        sorted_tokens = sorted(self._replace_table.keys(), key=len, reverse=True)
        pattern_str = "|".join(re.escape(t) for t in sorted_tokens if t)
        self.regex_pattern = re.compile(pattern_str) if pattern_str else None

    def normalize(self: Union["DomainDictionary", str], query: Optional[str] = None) -> str:
        """자연어 질문에서 사내 약어·동의어를 정식 명칭으로 정규화합니다 (멱등성 보장).
        인스턴스 메서드(`domain_dict.normalize(q)`)와 클래스 호출(`DomainDictionary.normalize(q)`) 모두 지원합니다.
        """
        if isinstance(self, str) and query is None:
            return _DEFAULT_INSTANCE.normalize(self)
        if not self.regex_pattern or not query:
            return query or ""
        return self.regex_pattern.sub(lambda m: self._replace_table[m.group(0)], query)


_DEFAULT_INSTANCE = DomainDictionary()
