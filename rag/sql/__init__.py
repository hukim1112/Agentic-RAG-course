"""
정형 ERP DB (Text2SQL) RAG: 스키마 검색, 값 연결, 읽기 전용 SQL 실행을 묶은 Text2SQL 워크플로우

    semantic_layer.py    DatabaseProfile: yaml 시멘틱 레이어 + PRAGMA 자동 추출 → 개요·테이블·지표 카드
    schema_retriever.py  스키마 검색: 약어 정규화 → BM25 + Dense → RRF → FK 확장
    value_linker.py      값 연결: 질문 속 표현 → DB 실제 값
    executor.py          읽기 전용 실행: 정규식 가드레일 + mode=ro 연결 + 시간·행 수 제한
    pipeline.py          Text2SQL: 위 단계를 LangGraph 워크플로우로 조립 (오류 시 재생성, 되묻기 분기)

DB에 의존하는 정보(시멘틱 레이어 yaml, DB 파일)는 data/<db_name>/에 둡니다.
"""

from rag.sql.executor import ExecutionResult, run_readonly_query, validate_sql
from rag.sql.pipeline import SQLDraft, Text2SQL, Text2SQLResult
from rag.sql.schema_retriever import SchemaRetriever, SchemaSearchResult
from rag.sql.semantic_layer import DatabaseProfile
from rag.sql.value_linker import ValueLinker, ValueMatch

__all__ = [
    "DatabaseProfile",
    "ExecutionResult",
    "SQLDraft",
    "SchemaRetriever",
    "SchemaSearchResult",
    "Text2SQL",
    "Text2SQLResult",
    "ValueLinker",
    "ValueMatch",
    "run_readonly_query",
    "validate_sql",
]
