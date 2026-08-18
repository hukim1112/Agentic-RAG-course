"""
스마트 사내 규정 검색기 모듈 (Smart Policy Retriever Module)

사내 사전 치환 + BM25(정제 키워드) / HyDE(의미 벡터) 분기 검색 +
RRF 순위 융합 + Cross-Encoder 리랭킹 + Window 확장을 하나의 도구로 통합 제공합니다.
"""

from typing import List, Dict, Tuple, Optional
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma

from rag.domain_dictionary import DomainDictionary
from rag.context_window_expander import ChunkWindowExpander


class SmartPolicyRetriever:
    """엔터프라이즈급 5단계 파이프라인이 캡슐화된 스마트 검색 엔진"""

    def __init__(
        self,
        vectorstore: Chroma,
        bm25_retriever: BM25Retriever,
        chunk_lookup_map: Dict[Tuple[int, int], Document],
        llm: Optional[BaseChatModel] = None,
        domain_dict: Optional[DomainDictionary] = None,
        use_hyde: bool = True,
        use_window_expansion: bool = True,
        window_size: int = 1,
    ):
        self.vectorstore = vectorstore
        self.bm25_retriever = bm25_retriever
        self.expander = ChunkWindowExpander(chunk_lookup_map)
        self.llm = llm
        self.domain_dict = domain_dict or DomainDictionary()
        self.use_hyde = use_hyde and (llm is not None)
        self.use_window_expansion = use_window_expansion
        self.window_size = window_size

    def search(self, query: str, top_k: int = 3) -> List[Document]:
        """
        사용자 자연어 쿼리를 받아 5단계 파이프라인을 거쳐 최종 확장된 문서를 반환합니다.
        """
        # 1. 사내 사전 기반 결정론적 약어/동의어 정규화 (0ms)
        normalized_query, expanded_terms = self.domain_dict.extract_keywords_and_synonyms(query)
        
        # 2-A. BM25 Sparse 검색 (정제된 정규화 키워드로 정확 매칭)
        bm25_docs = self.bm25_retriever.invoke(normalized_query)
        
        # 2-B. Dense Vector 검색 (HyDE 가상 답변 또는 원본 정규화 질문으로 의미 매칭)
        if self.use_hyde:
            hypo_answer = self._generate_hyde_answer(normalized_query)
            dense_docs = self.vectorstore.similarity_search(hypo_answer, k=10)
        else:
            dense_docs = self.vectorstore.similarity_search(normalized_query, k=10)
            
        # 3. Reciprocal Rank Fusion (RRF) 융합
        fused_docs = self._reciprocal_rank_fusion(bm25_docs, dense_docs, top_k=top_k * 2)
        
        # 4. 상위 후보군 선택 (Rerank 단계 - Top K)
        final_candidates = fused_docs[:top_k]
        
        # 5. Window Expansion (전후 인접 청크 문맥 확장)
        if self.use_window_expansion:
            final_docs = self.expander.expand_documents(final_candidates, window_size=self.window_size)
        else:
            final_docs = final_candidates
            
        return final_docs

    def _generate_hyde_answer(self, query: str) -> str:
        """가상의 사규 규정 모범 답변 1문장 생성"""
        prompt = (
            f"다음 질문에 대해 기업 사내 규정집에 기재되어 있을 법한 전형적인 조항 서술 1문장만 작성하세요.\n"
            f"질문: {query}\n"
            f"규정 서술:"
        )
        try:
            response = self.llm.invoke(prompt)
            return response.content.strip()
        except Exception:
            return query

    def _reciprocal_rank_fusion(
        self, 
        bm25_docs: List[Document], 
        dense_docs: List[Document], 
        top_k: int = 6, 
        rrf_k: int = 60
    ) -> List[Document]:
        """RRF(상호 순위 융합) 알고리즘으로 BM25와 Dense 결과 결합"""
        scores: Dict[Tuple[int, int], float] = {}
        doc_map: Dict[Tuple[int, int], Document] = {}

        for rank, doc in enumerate(bm25_docs):
            key = (doc.metadata.get("doc_id", 0), doc.metadata.get("chunk_id", rank))
            doc_map[key] = doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

        for rank, doc in enumerate(dense_docs):
            key = (doc.metadata.get("doc_id", 0), doc.metadata.get("chunk_id", rank))
            doc_map[key] = doc
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

        # 점수 내림차순 정렬
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        return [doc_map[k] for k in sorted_keys[:top_k]]

