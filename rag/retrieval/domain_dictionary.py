"""
사내 도메인 약어 및 동의어 사전 모듈 (Domain Dictionary Module)

기업 사내 은어, 부서 약어, 업무 용어를 0ms 속도로 정규화/치환하여
BM25 키워드 검색 및 쿼리 정규화의 매칭 정확도를 극대화합니다.
"""

import re
from typing import Dict, List, Tuple


class DomainDictionary:
    """사내 약어 및 동의어 사전 관리 및 치환 클래스"""

    # 기본 사내 동의어/약어 매핑 테이블
    DEFAULT_SYNONYMS = {
        # 부서 약어
        "클운팀": "클라우드운영팀",
        "인사팀": "인사기획팀",
        "재무팀": "재무회계팀",
        "AI랩": "인공지능연구소",
        "데이터팀": "데이터엔지니어링팀",
        
        # 규정 및 업무 용어
        "여비": "국내 여비 및 교통비",
        "출장비": "국내 여비 및 교통비",
        "식대": "식비",
        "숙박비": "숙박비 지급 한도",
        "일비": "일비 및 식비 정액 지급 기준",
        "연차": "연차유급휴가",
        "반차": "반일 휴가",
        "재택": "재택근무",
        "보안위반": "정보보안 위반 제재 기준",
        "DLP": "사외 데이터 반출 승인 절차 DLP",
        "CISO": "정보보호최고책임자 CISO",
    }

    def __init__(self, custom_synonyms: Dict[str, str] = None):
        self.synonym_map = self.DEFAULT_SYNONYMS.copy()
        if custom_synonyms:
            self.synonym_map.update(custom_synonyms)
        
        # 긴 단어부터 먼저 치환되도록 정렬
        sorted_keys = sorted(self.synonym_map.keys(), key=len, reverse=True)
        # 단어 경계 및 안전 치환을 위한 정규식 컴파일
        pattern_str = "|".join(re.escape(k) for k in sorted_keys)
        self.regex_pattern = re.compile(pattern_str) if pattern_str else None

    def replace_synonyms(self, query: str) -> str:
        """자연어 질문에서 사내 약어를 정식 명칭으로 치환"""
        if not self.regex_pattern or not query:
            return query
        
        return self.regex_pattern.sub(lambda m: self.synonym_map[m.group(0)], query)

    def extract_keywords_and_synonyms(self, query: str) -> Tuple[str, List[str]]:
        """정규화된 쿼리와 확장된 키워드 목록을 함께 반환"""
        normalized = self.replace_synonyms(query)
        expanded_terms = []
        
        for k, v in self.synonym_map.items():
            if k in query:
                expanded_terms.append(v)
                
        return normalized, expanded_terms
