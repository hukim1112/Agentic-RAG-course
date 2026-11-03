"""
문맥 윈도우 확장 모듈 (Contextual Window Module)

검색된 중심 청크의 (doc_id, chunk_id) 메타데이터를 기반으로
전후 인접 청크(Window)의 본문(raw_content)을 이어 붙여,
표나 단서 조항이 청크 경계에서 잘리는 문제를 해결합니다.
"""

from typing import Dict, Iterable, List, Tuple
from langchain_core.documents import Document


class ContextualWindow:
    """(doc_id, chunk_id) 룩업 맵을 기반으로 전후 인접 청크를 확장하는 클래스"""

    def __init__(self, chunk_lookup_map: Dict[Tuple[int, int], Document]):
        self.chunk_map = chunk_lookup_map

        # 문서별 최대 chunk_id 사전 계산 (범위 초과 방지)
        self._max_chunk_per_doc: Dict[int, int] = {}
        for doc_id, chunk_id in chunk_lookup_map:
            cur_max = self._max_chunk_per_doc.get(doc_id, -1)
            self._max_chunk_per_doc[doc_id] = max(cur_max, chunk_id)

    @classmethod
    def from_documents(cls, docs: Iterable[Document]) -> "ContextualWindow":
        """Document 리스트의 (doc_id, chunk_id) 메타데이터로부터 ContextualWindow를 생성합니다."""
        lookup: Dict[Tuple[int, int], Document] = {}
        for d in docs:
            doc_id = d.metadata.get("doc_id")
            chunk_id = d.metadata.get("chunk_id")
            if doc_id is not None and chunk_id is not None:
                lookup[(int(doc_id), int(chunk_id))] = d
        return cls(lookup)

    def expand(
        self,
        target_docs: List[Document],
        window_size: int = 2,
    ) -> List[Document]:
        """검색된 target_docs를 중심으로 전/후 window_size 범위의 인접 청크 본문을 결합합니다.

        중심 청크의 문맥 헤더(doc_header)는 맨 앞에 1회만 두고,
        인접 청크들은 헤더 없는 원문(raw_content)만 순서대로 이어 붙여 헤더 중복을 방지합니다.
        """
        if window_size <= 0 or not self.chunk_map:
            return list(target_docs)

        expanded_docs: List[Document] = []
        seen_windows: set[Tuple[int, int, int]] = set()

        for doc in target_docs:
            doc_id = doc.metadata.get("doc_id")
            cid = doc.metadata.get("chunk_id")

            if doc_id is None or cid is None or (doc_id, cid) not in self.chunk_map:
                expanded_docs.append(doc)
                continue

            max_cid = self._max_chunk_per_doc.get(doc_id, 0)
            start_cid = max(0, cid - window_size)
            end_cid = min(max_cid, cid + window_size)

            # 동일한 (doc_id, start_cid, end_cid) 윈도우가 중복 생성되지 않도록 방지
            window_key = (doc_id, start_cid, end_cid)
            if window_key in seen_windows:
                continue
            seen_windows.add(window_key)

            # 1. 중심 청크의 문맥 헤더는 맨 앞에 1회만 배치 (후행 공백/줄바꿈 정리)
            center_header = doc.metadata.get("doc_header", "").rstrip()
            window_texts = [center_header] if center_header else []

            # 2. 인접 청크(start ~ end)는 raw_content만 순서대로 결합
            for idx in range(start_cid, end_cid + 1):
                neighbor = self.chunk_map.get((doc_id, idx))
                if neighbor is not None:
                    raw_text = neighbor.metadata.get("raw_content", neighbor.page_content).strip()
                    if raw_text:
                        window_texts.append(raw_text)

            combined_page_content = "\n\n".join(window_texts)

            new_meta = doc.metadata.copy()
            new_meta["window_start_chunk"] = start_cid
            new_meta["window_end_chunk"] = end_cid
            new_meta["window_expanded"] = True

            expanded_docs.append(Document(page_content=combined_page_content, metadata=new_meta))

        return expanded_docs


