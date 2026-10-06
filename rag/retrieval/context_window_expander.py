"""
Context Window Expansion 모듈 (Chunk Window Expander Module)

검색된 청크의 (doc_id, chunk_id) 메타데이터를 기반으로,
인접한 전/후 청크(Window)를 동적으로 이어붙여 LLM 생성 시 맥락 결핍을 완전히 해소합니다.
중심 청크의 Header만 1회 유지하고 인접 청크는 raw_content만 결합하여 중복을 방지합니다.
"""

from typing import List, Dict, Tuple
from langchain_core.documents import Document


class ChunkWindowExpander:
    """(doc_id, chunk_id) 룩업 맵을 기반으로 전후 인접 청크를 동적 확장하는 클래스"""

    def __init__(self, chunk_lookup_map: Dict[Tuple[int, int], Document]):
        self.chunk_map = chunk_lookup_map
        
        # 문서별 최대 chunk_id 사전 계산 (범위 초과 방지)
        self._max_chunk_per_doc: Dict[int, int] = {}
        for (doc_id, chunk_id) in chunk_lookup_map:
            cur_max = self._max_chunk_per_doc.get(doc_id, -1)
            self._max_chunk_per_doc[doc_id] = max(cur_max, chunk_id)

    def expand_documents(
        self, 
        target_docs: List[Document], 
        window_size: int = 1
    ) -> List[Document]:
        """
        검색된 target_docs를 중심으로 전/후 window_size 범위의 청크들을 결합하여
        확장된 Document 리스트로 반환합니다.

        Args:
            target_docs: 검색된 핵심 Document 리스트
            window_size: 전후 확장할 청크 수 (기본 1: 이전1 + 중심 + 다음1 = 총 3청크 결합)

        Returns:
            주변 문맥이 결합된 Document 객체 리스트
        """
        expanded_docs = []

        for doc in target_docs:
            doc_id = doc.metadata.get("doc_id")
            cid = doc.metadata.get("chunk_id")

            # 룩업 키가 없으면 원본 그대로 유지
            if doc_id is None or cid is None or (doc_id, cid) not in self.chunk_map:
                expanded_docs.append(doc)
                continue

            max_cid = self._max_chunk_per_doc.get(doc_id, 0)
            start_cid = max(0, cid - window_size)
            end_cid = min(max_cid, cid + window_size)

            # 1. 중심 청크의 Context Header를 맨 앞에 1회만 배치
            center_header = doc.metadata.get("doc_header", "")
            window_texts = [center_header] if center_header else []

            # 2. 인접 청크(start ~ end)는 raw_content만 순서대로 결합 (헤더 중복 방지)
            for idx in range(start_cid, end_cid + 1):
                neighbor_chunk = self.chunk_map.get((doc_id, idx))
                if neighbor_chunk:
                    raw_text = neighbor_chunk.metadata.get("raw_content", neighbor_chunk.page_content)
                    window_texts.append(raw_text)

            combined_page_content = "\n\n".join(window_texts)
            
            # 3. 메타데이터 보존 및 확장 범위 기록
            new_meta = doc.metadata.copy()
            new_meta["window_start_chunk"] = start_cid
            new_meta["window_end_chunk"] = end_cid
            new_meta["window_expanded"] = True
            
            expanded_docs.append(
                Document(page_content=combined_page_content, metadata=new_meta)
            )

        return expanded_docs
