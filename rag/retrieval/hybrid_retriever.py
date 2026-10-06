"""
하이브리드 검색기 모듈 (Hybrid Retriever Module)

도메인 사전 치환 + BM25(정규화 키워드) / Dense(원 질문 또는 HyDE 가상 답변) 병렬 검색 +
RRF 순위 융합 + 상위 top_k 선택 + Window 확장을 하나의 검색 흐름으로 묶습니다.
"""

from typing import List, Dict, Tuple, Optional
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langchain_community.retrievers import BM25Retriever
from langchain_chroma import Chroma

from rag.retrieval.domain_dictionary import DomainDictionary
from rag.retrieval.context_window_expander import ChunkWindowExpander


# HyDE 가상 답변 생성용 기본 프롬프트. {query} 자리에 정규화된 질문이 들어갑니다.
# 도메인에 맞는 문체가 필요하면 생성자의 hyde_prompt 인자로 교체합니다.
DEFAULT_HYDE_PROMPT = (
    "다음 질문에 답하는 문서에 실려 있을 법한 서술 1문장만 작성하세요.\n"
    "질문: {query}\n"
    "서술:"
)


class HybridRetriever:
    """사전 치환 → BM25·Dense 검색 → RRF 융합 → top_k 선택 → Window 확장의 5단계 하이브리드 검색기"""

    def __init__(
        self,
        vectorstore: Chroma,
        bm25_retriever: BM25Retriever,
        chunk_lookup_map: Dict[Tuple[int, int], Document],
        llm: Optional[BaseChatModel] = None,
        domain_dict: Optional[DomainDictionary] = None,
        use_hyde: bool = True,
        hyde_prompt: str = DEFAULT_HYDE_PROMPT,
        use_window_expansion: bool = True,
        window_size: int = 1,
    ):
        if "{query}" not in hyde_prompt:
            raise ValueError("hyde_prompt에는 질문이 들어갈 '{query}' 자리가 있어야 합니다.")
        self.vectorstore = vectorstore
        self.bm25_retriever = bm25_retriever
        self.expander = ChunkWindowExpander(chunk_lookup_map)
        self.llm = llm
        self.domain_dict = domain_dict or DomainDictionary()
        self.use_hyde = use_hyde and (llm is not None)
        self.hyde_prompt = hyde_prompt
        self.use_window_expansion = use_window_expansion
        self.window_size = window_size

    def search(self, query: str, top_k: int = 3) -> List[Document]:
        """
        자연어 쿼리를 5단계로 처리해 상위 top_k 청크(Window 확장 시 전후 청크 포함)를 반환합니다.
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
        
        # 4. RRF 순위 상위 top_k 선택 (별도 리랭커 없음)
        final_candidates = fused_docs[:top_k]
        
        # 5. Window Expansion (전후 인접 청크 문맥 확장)
        if self.use_window_expansion:
            final_docs = self.expander.expand_documents(final_candidates, window_size=self.window_size)
        else:
            final_docs = final_candidates
            
        return final_docs

    def _generate_hyde_answer(self, query: str) -> str:
        """hyde_prompt로 질문에 대한 가상 답변 1문장 생성 (실패 시 원 질문 반환)"""
        # str.format 대신 replace: 프롬프트 안의 다른 중괄호가 오류를 내지 않도록
        prompt = self.hyde_prompt.replace("{query}", query)
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

