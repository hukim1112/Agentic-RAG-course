"""
하이브리드 검색기 모듈 (Hybrid Retriever Module)

1단계: DomainDictionary 약어·동의어 정규화
2단계: BM25(키워드) + Dense(의미) 병렬 검색
3단계: Reciprocal Rank Fusion (RRF) 순위 융합
4단계: ContextualWindow 전후 인접 청크 문맥 확장
"""

import re
from typing import Dict, Hashable, List, Optional, Tuple
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel

from rag.vector.retrieval.contextual_window import ContextualWindow
from rag.vector.retrieval.domain_dictionary import DomainDictionary


DEFAULT_HYDE_PROMPT = (
    "다음 질문에 답하는 문서에 실려 있을 법한 서술 1문장만 작성하세요.\n"
    "질문: {query}\n"
    "서술:"
)

_TOC_BLOCK_RE = re.compile(r"\[문서 전체 목차 \(TOC\)\]:.*?(?=\[현재 위치|\Z)", re.DOTALL)
_TOKEN_RE = re.compile(r"[가-힣a-zA-Z0-9]+")
_KO_PARTICLE_RE = re.compile(r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터|이란|란)$")


def _bm25_preprocess(text: str) -> List[str]:
    """BM25 인덱싱 및 질의 토큰화 함수.

    1. 모든 청크에 공통으로 들어 있는 `[문서 전체 목차 (TOC)]` 블록을 제거하여,
       다른 조항의 제목이 BM25 키워드 매칭을 오염시키는 현상을 방지합니다.
    2. 문장부호·괄호를 제거하고 한국어 조사(은/는/이/가/와/과 등)를 분리해 어근 일치율을 높입니다.
    """
    cleaned = _TOC_BLOCK_RE.sub("", text)
    tokens: List[str] = []
    for raw_tok in _TOKEN_RE.findall(cleaned.lower()):
        tokens.append(raw_tok)
        if len(raw_tok) >= 3:
            stem = _KO_PARTICLE_RE.sub("", raw_tok)
            if stem and stem != raw_tok and len(stem) >= 2:
                tokens.append(stem)
    return tokens


def _doc_key(doc: Document) -> Hashable:
    """청크 고유 식별 키를 반환합니다. (doc_id, chunk_id)가 없으면 본문 해시를 사용합니다."""
    doc_id = doc.metadata.get("doc_id")
    chunk_id = doc.metadata.get("chunk_id")
    if doc_id is not None and chunk_id is not None:
        return (int(doc_id), int(chunk_id))
    return ("content", doc.metadata.get("source_file", ""), hash(doc.page_content))


def reciprocal_rank_fusion(
    bm25_docs: List[Document],
    dense_docs: List[Document],
    top_k: int = 3,
    rrf_k: int = 60,
) -> List[Document]:
    """RRF(Reciprocal Rank Fusion) 알고리즘으로 BM25와 Dense 검색 순위를 융합합니다."""
    scores: Dict[Hashable, float] = {}
    doc_map: Dict[Hashable, Document] = {}

    for rank, doc in enumerate(bm25_docs):
        key = _doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

    for rank, doc in enumerate(dense_docs):
        key = _doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)

    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [doc_map[k] for k in sorted_keys[:top_k]]


class HybridRetriever:
    """약어 사전 정규화 → BM25 + Dense 병렬 검색 → RRF 순위 융합 → ContextualWindow 확장을 수행하는 검색기"""

    def __init__(
        self,
        vectorstore: Chroma,
        bm25_retriever: BM25Retriever,
        chunk_lookup_map: Optional[Dict[Tuple[int, int], Document]] = None,
        domain_dict: Optional[DomainDictionary] = None,
        use_window_expansion: bool = True,
        window_size: int = 2,
        llm: Optional[BaseChatModel] = None,
        use_hyde: bool = False,
        hyde_prompt: str = DEFAULT_HYDE_PROMPT,
    ):
        if "{query}" not in hyde_prompt:
            raise ValueError("hyde_prompt에는 질문이 들어갈 '{query}' 자리가 있어야 합니다.")
        self.vectorstore = vectorstore
        self.bm25_retriever = bm25_retriever
        self.window = ContextualWindow(chunk_lookup_map or {})
        self.domain_dict = domain_dict or DomainDictionary()
        self.use_window_expansion = use_window_expansion
        self.window_size = window_size
        self.llm = llm
        self.use_hyde = use_hyde and (llm is not None)
        self.hyde_prompt = hyde_prompt

    @classmethod
    def from_chroma(
        cls,
        vectorstore: Chroma,
        domain_dict: Optional[DomainDictionary] = None,
        use_window_expansion: bool = True,
        window_size: int = 2,
        bm25_k: int = 6,
    ) -> "HybridRetriever":
        """이미 인덱싱된 Chroma 컬렉션에서 전체 청크와 (doc_id, chunk_id) 룩업 맵을 복원하여
        별도 파일 없이 즉시 HybridRetriever(BM25 + Dense + RRF + ContextualWindow)를 생성합니다.
        """
        stored = vectorstore.get(include=["documents", "metadatas"])
        documents = stored.get("documents") or []
        metadatas = stored.get("metadatas") or []

        all_docs: List[Document] = []
        lookup_map: Dict[Tuple[int, int], Document] = {}
        for text, meta in zip(documents, metadatas):
            meta = dict(meta or {})
            doc = Document(page_content=text, metadata=meta)
            all_docs.append(doc)
            doc_id = meta.get("doc_id")
            chunk_id = meta.get("chunk_id")
            if doc_id is not None and chunk_id is not None:
                lookup_map[(int(doc_id), int(chunk_id))] = doc

        # doc_id, chunk_id 순으로 정렬해 결정론적 BM25 인덱스 보장 (TOC 오염 방지 전처리 적용)
        all_docs.sort(key=lambda d: (d.metadata.get("doc_id", 0), d.metadata.get("chunk_id", 0)))
        bm25 = BM25Retriever.from_documents(all_docs, k=bm25_k, preprocess_func=_bm25_preprocess)

        return cls(
            vectorstore=vectorstore,
            bm25_retriever=bm25,
            chunk_lookup_map=lookup_map,
            domain_dict=domain_dict,
            use_window_expansion=use_window_expansion,
            window_size=window_size,
        )

    def search(self, query: str, top_k: int = 3) -> List[Document]:
        """자연어 질의를 4단계(약어 사전 → BM25+Dense → RRF → ContextualWindow)로 검색합니다."""
        # 1. 사내 약어·동의어 정규화
        normalized_query = self.domain_dict.normalize(query)

        # 2-A. BM25 키워드 검색
        bm25_docs = self.bm25_retriever.invoke(normalized_query)

        # 2-B. Dense 의미 검색 (선택적 HyDE 지원)
        dense_query = self._generate_hyde_answer(normalized_query) if self.use_hyde else normalized_query
        dense_docs = self.vectorstore.similarity_search(dense_query, k=max(6, top_k * 2))

        # 3. RRF 순위 융합으로 상위 후보 선정 (윈도우 중복 제거 여유분을 위해 top_k * 2까지 융합)
        fused_docs = reciprocal_rank_fusion(bm25_docs, dense_docs, top_k=max(6, top_k * 2))

        # 4. ContextualWindow 전후 청크 문맥 확장 (중복 윈도우 제거 후 top_k개 반환)
        if self.use_window_expansion:
            return self.window.expand(fused_docs, window_size=self.window_size)[:top_k]
        return fused_docs[:top_k]

    def _generate_hyde_answer(self, query: str) -> str:
        """hyde_prompt로 질문에 대한 가상 답변 1문장 생성 (실패 시 원 질문 반환)"""
        prompt = self.hyde_prompt.replace("{query}", query)
        try:
            response = self.llm.invoke(prompt)
            return response.content.strip()
        except Exception:
            return query

