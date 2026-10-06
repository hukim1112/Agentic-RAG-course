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
import json
import threading
from functools import lru_cache
from typing import Optional

import networkx as nx
from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from rag.graph.networkx_graph import multi_hop_search
from rag.graph.graphrag_tool import run_graphrag_query

DB_DIR = "app/database"
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")

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


def _graph() -> nx.Graph:
    with _load_lock:
        return _load_graph()


@lru_cache(maxsize=1)
def _load_graph() -> nx.Graph:
    with open(os.path.join(DB_DIR, "knowledge_graph_nodelink.json"), "r", encoding="utf-8") as f:
        return nx.node_link_graph(json.load(f))


@tool(parse_docstring=True)
def search_company_policy(query: str) -> str:
    """사내 규정(국내여비교통비, 인사복무, 정보보안)을 검색하여 상세 조항과 감액 기준을 반환합니다.
    직급별 숙박비/일비 한도, 당일 출장 감액 기준, 보안 승인 절차 등을 조회할 때 사용합니다.
    서로 다른 규정을 함께 확인해야 하면 주제별로 나누어 여러 번 호출하세요.

    Args:
        query: 검색할 사내 규정 관련 자연어 질의
    """
    docs = _vectorstore("enterprise_policy_store").similarity_search(query, k=2)
    if not docs:
        return f"'{query}' 관련 사내 규정을 찾지 못했습니다."
    return "\n\n".join(f"[{d.metadata.get('breadcrumb', '사내규정')}]:\n{d.page_content}" for d in docs)


@tool(parse_docstring=True)
def search_bok_reports(query: str, quarter: Optional[int] = None) -> str:
    """한국은행(BOK) 2024년 분기별 주력산업 모니터링 보고서(반도체, 자동차 등)의 실적과 전망을 검색합니다.
    한 번의 호출에는 '특정 1개 분기'와 '특정 1개 산업'만 검색하세요.
    분기 비교나 산업 비교가 필요하면 분기별/산업별로 나누어 여러 번 호출하세요.
    특정 분기의 수치가 필요하면 quarter를 지정해야 다른 분기 보고서가 섞이지 않습니다.

    Args:
        query: 검색할 산업과 지표 (예: '반도체 수출 증가율')
        quarter: 2024년 분기 번호(1~4). 지정하면 해당 분기 보고서에서만 검색합니다.
    """
    search_kwargs = {"filter": {"quarter": quarter}} if quarter in (1, 2, 3, 4) else {}
    docs = _vectorstore("bok_industry_reports_store").similarity_search(query, k=3, **search_kwargs)
    if not docs:
        return f"'{query}' 관련 산업보고서를 찾지 못했습니다."
    return "\n\n".join(
        f"[{d.metadata.get('breadcrumb', '산업보고서')}]:\n"
        f"{d.metadata.get('raw_content', d.page_content)}"
        for d in docs
    )


@tool(parse_docstring=True)
def search_graph_relations(seed_entity: str, max_hops: int = 2) -> str:
    """조직도 지식 그래프에서 특정 인물/부서의 상위 보고선(본부장), 동료, 프로젝트 연결 관계를 탐색합니다.
    결재선이나 소속 본부처럼 여러 단계를 거쳐야 하는 관계 질문에 사용합니다.

    Args:
        seed_entity: 관계를 탐색할 출발 인물명 또는 부서명 (예: '김철수 수석', '클라우드운영팀')
        max_hops: 탐색 깊이 (1: 직속 관계, 2: 상위 본부/프로젝트까지 확장, 최대 3)
    """
    max_hops = max(1, min(max_hops, 3))
    sub_edges, _ = multi_hop_search(_graph(), seed_entities=[seed_entity], max_hops=max_hops)
    if not sub_edges:
        return f"엔티티 '{seed_entity}'와 연결된 관계를 찾을 수 없습니다."
    return "\n".join(f"- [{u}] ──({d.get('relation', '연결됨')})──> [{v}]" for u, v, d in sub_edges)


@tool(parse_docstring=True)
def query_enterprise_graphrag(query: str, search_method: str = "global") -> str:
    """Microsoft GraphRAG로 전사 프로젝트 종합 분석(global) 또는 특정 인물/부서의 심층 맥락(local)을 조회합니다.

    Args:
        query: 전사 프로젝트 거시 분석 또는 특정 인물/부서 관련 질의문
        search_method: 전사 종합 요약은 'global', 특정 인물/개체 심층 분석은 'local'
    """
    if search_method not in ("global", "local"):
        search_method = "global"
    return run_graphrag_query(query, method=search_method, root_dir=os.path.join(DB_DIR, "graphrag"))


tools_tool_rag = [
    search_company_policy,
    search_bok_reports,
    search_graph_relations,
    query_enterprise_graphrag,
]
