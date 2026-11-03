"""
tool_rag_agent 전용 검색 도구 (Direct Tool Binding)
===============================================================================
사전 구축된 4대 엔터프라이즈 DB(app/database/)를 LangChain `@tool`로 직접 감싸
에이전트에 바인딩합니다. 검색 로직은 MCP 서버(app/mcp/enterprise_rag_server.py)와
동일하므로, skill_rag_agent와는 "도구 연결 방식"만 다릅니다.

DB 인스턴스는 첫 호출 시점에 지연 로드합니다. (서버가 에이전트 목록을 조회할 때
모듈을 import하므로, import 시점에 무거운 DB 로드를 피하기 위함)
===============================================================================
"""

import os
import threading
from functools import lru_cache

from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.utils import init_chat_model
from rag.graph.graph_explorer import graph_explorer_tools
from rag.sql import Text2SQL
from rag.vector.retrieval import HybridRetriever

DB_DIR = "app/database"
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
SEMANTIC_LAYER_PATH = "data/enterprise_erp_sql/semantic_layer.yaml"
ERP_DB_PATH = os.path.join(DB_DIR, "enterprise_erp.db")

# 에이전트가 도구를 병렬로 호출하면 여러 스레드가 동시에 DB를 처음 로드할 수 있습니다.
# Chroma 클라이언트 생성은 스레드 안전하지 않으므로 최초 로드를 직렬화합니다.
_load_lock = threading.Lock()


@lru_cache(maxsize=1)
def _embeddings():
    return OpenAIEmbeddings(model="text-embedding-3-large")


def _vectorstore(collection_name: str) -> Chroma:
    with _load_lock:
        return _load_vectorstore(collection_name)


@lru_cache(maxsize=None)
def _load_vectorstore(collection_name: str) -> Chroma:
    return Chroma(
        collection_name=collection_name,
        embedding_function=_embeddings(),
        persist_directory=CHROMA_DIR,
    )


def _policy_retriever() -> HybridRetriever:
    with _load_lock:
        return _load_policy_retriever()


@lru_cache(maxsize=1)
def _load_policy_retriever() -> HybridRetriever:
    return HybridRetriever.from_chroma(_load_vectorstore("enterprise_policy_store"), window_size=2)


def _aws_retriever() -> HybridRetriever:
    with _load_lock:
        return _load_aws_retriever()


@lru_cache(maxsize=1)
def _load_aws_retriever() -> HybridRetriever:
    return HybridRetriever.from_chroma(_load_vectorstore("aws_waf_guides_store"), window_size=2)


def _erp_text2sql() -> Text2SQL:
    with _load_lock:
        return _load_erp_text2sql()


@lru_cache(maxsize=1)
def _load_erp_text2sql() -> Text2SQL:
    db_path = ERP_DB_PATH if os.path.exists(ERP_DB_PATH) else None
    llm = init_chat_model(model="gemini-3.8-flash", temperature=0.0)
    return Text2SQL.from_semantic_layer(
        SEMANTIC_LAYER_PATH,
        llm=llm,
        db_path=db_path,
        embeddings=_embeddings(),
    )


@tool
def search_company_policy(query: str) -> str:
    """
    사내 5대 공식 규정 문서(국내여비교통비지급규정, 인사복무규정, 정보보안관리지침, 전사위임전결및예산집행규정, 클라우드및GPU인프라운영지침)에서 출장비 기준, 인사·징계 양정, 보안 반출 절차, 금액별 전결 기준, GPU 유휴 회수 규정 등 사내 제도·원칙 조항을 검색합니다.

    반환 형태: 검색된 조항의 앞뒤 문맥이 결합된 본문과 함께 상단에 [문서 전체 목차(TOC)] 및 [현재 위치 경로(Breadcrumb)]가 포함된 텍스트를 반환합니다.
    """
    docs = _policy_retriever().search(query, top_k=2)
    if not docs:
        return f"'{query}' 관련 사내 규정을 찾지 못했습니다."
    return "\n\n".join(f"[{d.metadata.get('breadcrumb', '사내규정')}]:\n{d.page_content}" for d in docs)


@tool
def search_aws_guides(query: str) -> str:
    """
    AWS Well-Architected Framework 4대 아키텍처 백서(Security, Reliability, Performance Efficiency, Cost Optimization)에서 클라우드 설계 원칙, 모범 사례(Best Practice), 흔한 안티패턴(Common anti-patterns), 구현 지침을 검색합니다.

    반환 형태: 검색된 모범 사례의 앞뒤 문맥이 결합된 본문과 함께 상단에 [문서 전체 목차(TOC)] 및 [현재 위치 경로(Breadcrumb)]가 포함된 텍스트를 반환합니다.
    """
    docs = _aws_retriever().search(query, top_k=2)
    if not docs:
        return f"'{query}' 관련 AWS 아키텍처 백서를 찾지 못했습니다."
    return "\n\n".join(f"[{d.metadata.get('breadcrumb', 'AWS 백서')}]:\n{d.page_content}" for d in docs)


@tool
def search_enterprise_erp(query: str, context: str = "") -> str:
    """
    사내 ERP 정형 데이터베이스(부서 마스터, 임직원 명부, 전략 프로젝트 및 투입 인력, 프로젝트 지출 결의 전표, GPU 클러스터 할당·가동률 대장, 부서별·비목별 운영 예산 원장)에서 실시간 수치와 현황 레코드를 조회합니다.
    query에는 SQL 문이 아니라 자연어 질문을 넣으세요. SQL은 이 도구가 스키마를 보고 직접 생성합니다.

    반환 형태: 자연어 질의를 변환해 실행한 SELECT SQL 쿼리문, 적용한 해석 가정, 조회된 결과 마크다운 표(컬럼명 및 행 데이터)를 반환합니다.
    """
    return _erp_text2sql().invoke(query, context=context).to_text()


tools_tool_rag = [
    search_company_policy,
    search_aws_guides,
    search_enterprise_erp,
    # GraphRAG 인덱스를 단계적으로 탐색하는 그래프 도구 5종 (rag/graph/graph_explorer.py)
    *graph_explorer_tools,
]
