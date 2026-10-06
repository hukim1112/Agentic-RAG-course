"""
통합 인덱싱 진입점: 여러 형식의 문서를 같은 파이프라인으로 청크로 만듭니다.

    원본 문서 (.md / .pdf / .txt)
        → [전처리] rag.preprocessing.to_markdown  (표준 Markdown)
        → [청킹]   ContextualHeaderEnricher       (문맥 헤더 + 목차 주입)
        → Document 청크 + 윈도우 확장용 룩업 맵
"""

import os
from typing import Callable, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from rag.indexing.contextual_headers import ContextualHeaderEnricher
from rag.preprocessing.normalize import to_markdown


def index_documents(
    paths: List[str],
    enricher: Optional[ContextualHeaderEnricher] = None,
    doc_id_start: int = 0,
    pdf_options: Optional[dict] = None,
    extra_metadata: Optional[Callable[[str, dict], dict]] = None,
    work_dir: str = "artifacts/normalized",
) -> Tuple[List[Document], Dict[Tuple[int, int], Document]]:
    """여러 문서를 같은 파이프라인으로 정규화하고 청킹합니다.

    Args:
        paths: 인덱싱할 문서 경로 목록 (.md / .pdf / .txt 혼용 가능)
        enricher: 청킹기. None이면 기본 설정의 ContextualHeaderEnricher 사용
        doc_id_start: 첫 문서의 doc_id (여러 컬렉션을 합칠 때 충돌 방지용)
        pdf_options: pdf_to_markdown에 전달할 옵션
        extra_metadata: (path, normalize_metadata) → 청크에 추가할 메타데이터 dict
        work_dir: 정규화된 Markdown을 저장할 폴더 (검수용)

    Returns:
        (청크 리스트, {(doc_id, chunk_id): 청크} 룩업 맵)
    """
    enricher = enricher or ContextualHeaderEnricher()
    os.makedirs(work_dir, exist_ok=True)

    all_docs: List[Document] = []
    lookup: Dict[Tuple[int, int], Document] = {}
    for offset, path in enumerate(paths):
        md_text, meta = to_markdown(path, pdf_options)

        md_path = os.path.join(work_dir, os.path.splitext(os.path.basename(path))[0] + ".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)

        docs, doc_lookup = enricher.process_file(md_path, doc_id=doc_id_start + offset)
        extra = extra_metadata(path, meta) if extra_metadata else {}
        for d in docs:
            d.metadata["source_file"] = os.path.basename(path)
            d.metadata.update(extra)
        all_docs.extend(docs)
        lookup.update(doc_lookup)
    return all_docs, lookup
