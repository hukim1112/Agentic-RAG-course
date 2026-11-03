"""
스키마 검색기 (Schema Retriever)

전체 스키마 대신 질문에 필요한 테이블·지표 카드만 골라 SQL 생성 모델에 넘깁니다.
문서 RAG의 HybridRetriever와 같은 기법을 스키마 카드에 적용한 것입니다.

    문서 RAG (rag.vector.retrieval)          스키마 RAG (이 모듈)
    ---------------------------------       ---------------------------------
    규정 문서 청크                          테이블 카드 + 지표 카드
    1. DomainDictionary 약어 정규화         1. (동일)
    2. BM25 + Dense 병렬 검색               2. (동일, 같은 BM25 토크나이저 사용)
    3. RRF 순위 융합                        3. (동일)
    4. ContextualWindow 전후 청크 확장      4. FK 확장: 검색된 테이블이 참조하는 상위 테이블 추가

카드 수가 적어 인덱스는 메모리에 바로 만듭니다 (InMemoryVectorStore).
embeddings를 주지 않으면 BM25만으로 검색합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from rag.sql.semantic_layer import DatabaseProfile
from rag.vector.retrieval import DomainDictionary, reciprocal_rank_fusion
from rag.vector.retrieval.hybrid_retriever import _bm25_preprocess


@dataclass
class SchemaSearchResult:
    normalized_query: str
    retrieved: List[str] = field(default_factory=list)  # 검색으로 직접 찾은 카드 ("table:..", "metric:..")
    tables: List[str] = field(default_factory=list)  # FK 확장까지 마친 최종 테이블
    metrics: List[str] = field(default_factory=list)
    context: str = ""  # SQL 생성 프롬프트에 넣을 카드 텍스트


class SchemaRetriever:
    def __init__(
        self,
        profile: DatabaseProfile,
        embeddings: Optional[Embeddings] = None,
        domain_dict: Optional[DomainDictionary] = None,
        fk_hops: int = 1,
    ):
        self.profile = profile
        self.domain_dict = domain_dict or DomainDictionary(profile.synonyms)
        self.fk_hops = fk_hops

        self.cards: List[Document] = [
            Document(page_content=profile.table_card(name), metadata={"kind": "table", "name": name})
            for name in profile.tables
        ] + [
            Document(page_content=profile.metric_card(key), metadata={"kind": "metric", "name": key})
            for key in profile.metrics
        ]
        self.bm25 = BM25Retriever.from_documents(self.cards, k=len(self.cards), preprocess_func=_bm25_preprocess)
        self.vectorstore = InMemoryVectorStore.from_documents(self.cards, embeddings) if embeddings else None

    def search(self, query: str, top_k: int = 3) -> SchemaSearchResult:
        # 1. 사내 약어·동의어 정규화
        normalized = self.domain_dict.normalize(query)

        # 2. BM25 + Dense 병렬 검색 (BM25는 질문 단어가 하나도 없는 점수 0 카드를 제외)
        scores = self.bm25.vectorizer.get_scores(self.bm25.preprocess_func(normalized))
        ranked = sorted(zip(scores, self.bm25.docs), key=lambda pair: pair[0], reverse=True)
        bm25_docs = [doc for score, doc in ranked if score > 0][: top_k * 2]
        dense_docs = self.vectorstore.similarity_search(normalized, k=top_k * 2) if self.vectorstore else []

        # 3. RRF 순위 융합
        fused = reciprocal_rank_fusion(bm25_docs, dense_docs, top_k=top_k)

        tables: List[str] = []
        metrics: List[str] = []
        for doc in fused:
            name = doc.metadata["name"]
            if doc.metadata["kind"] == "metric":
                metrics.append(name)
                tables += [t for t in self.profile.metrics[name].tables if t not in tables]
            elif name not in tables:
                tables.append(name)

        # 4. FK 확장
        expanded = self.expand(tables)
        return SchemaSearchResult(
            normalized_query=normalized,
            retrieved=[f"{d.metadata['kind']}:{d.metadata['name']}" for d in fused],
            tables=expanded,
            metrics=metrics,
            context=self.render(expanded, metrics),
        )

    def render(self, tables: List[str], metrics: List[str]) -> str:
        """테이블·지표 카드를 SQL 생성 프롬프트용 텍스트로 이어 붙입니다."""
        return "\n\n".join(
            [self.profile.table_card(t) for t in tables] + [self.profile.metric_card(m) for m in metrics]
        )

    def expand(self, tables: List[str]) -> List[str]:
        """검색된 테이블이 FK로 참조하는 상위 테이블을 fk_hops 단계까지 추가합니다.
        (지출 전표 → 프로젝트·임직원: 이름이나 부서명을 조회하려면 상위 테이블 조인이 필요하기 때문)
        참조받는 방향(하위 테이블)은 확장하지 않습니다. 임직원처럼 많은 테이블이 참조하는 테이블에서
        하위로 확장하면 거의 모든 테이블이 딸려 오기 때문입니다.
        """
        result = list(tables)
        frontier = list(tables)
        for _ in range(self.fk_hops):
            next_frontier = []
            for table in frontier:
                for parent in self.profile.parents(table):
                    if parent not in result:
                        result.append(parent)
                        next_frontier.append(parent)
            frontier = next_frontier
        return result
