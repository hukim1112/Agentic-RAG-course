"""
rag.vector: 비정형 문서(Vector + BM25 하이브리드) RAG 패키지

    preprocessing/  전처리: 원본 문서 → 표준 Markdown (pdf_to_markdown, to_markdown, measure_text_coverage, AWS_PDF_OPTIONS, aws_metadata)
    indexing/       인덱싱: 문맥 헤더 청킹 및 통합 인덱싱 (ContextualHeader, index_documents)
    retrieval/      검색기: 약어 사전, 하이브리드(RRF), 윈도우 확장 (DomainDictionary, HybridRetriever, ContextualWindow)
"""

from rag.vector.indexing import ContextualHeader, index_documents
from rag.vector.preprocessing import (
    AWS_PDF_OPTIONS,
    BOK_PDF_OPTIONS,
    aws_metadata,
    bok_metadata,
    measure_text_coverage,
    pdf_to_markdown,
    to_markdown,
)
from rag.vector.retrieval import (
    DEFAULT_HYDE_PROMPT,
    ContextualWindow,
    DomainDictionary,
    HybridRetriever,
    reciprocal_rank_fusion,
)

__all__ = [
    "pdf_to_markdown",
    "to_markdown",
    "measure_text_coverage",
    "AWS_PDF_OPTIONS",
    "aws_metadata",
    "BOK_PDF_OPTIONS",
    "bok_metadata",
    "ContextualHeader",
    "index_documents",
    "ContextualWindow",
    "DomainDictionary",
    "DEFAULT_HYDE_PROMPT",
    "HybridRetriever",
    "reciprocal_rank_fusion",
]
