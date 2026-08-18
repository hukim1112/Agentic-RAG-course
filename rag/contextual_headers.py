"""
Contextual Chunk Header 주입 모듈 (Contextual Chunk Header Module)

문서의 장/절/조항 헤더 경로와 핵심 맥락 요약을 각 청크 상단에 접두사로 결합하여
고립된 청크의 맥락 상실(Decontextualization)을 방지하고 검색 정확도를 극대화합니다.
"""

import os
import re
from typing import List, Tuple, Dict
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


class ContextualHeaderEnricher:
    """마크다운 헤더 구조를 보존하고 전체 목차(TOC) 및 Contextual Header를 주입하는 클래스"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, include_toc: bool = True):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.include_toc = include_toc
        
        # 완전 범용화된 마크다운 헤더 분할기 (H1 ~ H4)
        self.headers_to_split_on = [
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
            ("####", "h4"),
        ]
        self.md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split_on,
            strip_headers=False
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

    def process_file(
        self, 
        file_path: str, 
        doc_id: int
    ) -> Tuple[List[Document], Dict[Tuple[int, int], Document]]:
        """
        단일 마크다운 파일을 로드하여 전체 목차(TOC) 및 Contextual Header가 주입된 청크 리스트와
        Window 확장을 위한 chunk_lookup_map을 생성하여 반환합니다.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        file_name = os.path.basename(file_path)
        
        # 1. 문서 메타 정보 파싱 (문서명, 소관부서 등)
        doc_meta = self._parse_doc_meta(raw_text, file_name)
        
        # 2. 문서 전체 목차(Table of Contents) 자동 추출 (0ms)
        doc_toc = self._extract_table_of_contents(raw_text) if self.include_toc else ""
        
        # 3. 마크다운 헤더 기반 논리 단위 1차 분할
        header_splits = self.md_splitter.split_text(raw_text)
        
        enriched_docs: List[Document] = []
        chunk_lookup_map: Dict[Tuple[int, int], Document] = {}
        global_chunk_idx = 0

        for split_doc in header_splits:
            # 4. 큰 섹션의 경우 문자 길이 기준으로 2차 분할
            sub_chunks = self.text_splitter.split_documents([split_doc])
            
            for sub_chunk in sub_chunks:
                # 5. 상위 경로(Breadcrumb Path) 동적 구성
                breadcrumb = self._build_breadcrumb(sub_chunk.metadata, doc_meta["doc_name"])
                
                # 6. Context Header 생성 (문서명 -> 소관부서 -> 전체목차 -> 현재위치경로 순서)
                header_parts = [
                    "--- Document Context Header ---",
                    f"[문서명: {doc_meta['doc_name']}]"
                ]
                if "department" in doc_meta and doc_meta["department"]:
                    header_parts.append(f"[소관부서: {doc_meta['department']}]")
                if doc_toc:
                    header_parts.append("[문서 전체 목차 (TOC)]:\n" + doc_toc)
                
                # 본문 바로 직전에 현재 위치 경로를 배치하여 결합도 극대화
                header_parts.append(f"[현재 위치 경로: {breadcrumb}]")
                header_parts.append("-------------------------------\n\n")
                context_header = "\n".join(header_parts)
                
                raw_content = sub_chunk.page_content
                full_content = context_header + raw_content
                
                new_metadata = sub_chunk.metadata.copy()
                new_metadata.update({
                    "doc_id": doc_id,
                    "chunk_id": global_chunk_idx,
                    "source_file": file_name,
                    "breadcrumb": breadcrumb,
                    "doc_header": context_header,
                    "doc_toc": doc_toc,
                    "raw_content": raw_content,
                    "department": doc_meta.get("department", "N/A"),
                })
                
                enriched_doc = Document(page_content=full_content, metadata=new_metadata)
                
                # 룩업 맵과 청크 리스트에 저장
                chunk_lookup_map[(doc_id, global_chunk_idx)] = enriched_doc
                enriched_docs.append(enriched_doc)
                global_chunk_idx += 1

        return enriched_docs, chunk_lookup_map

    def _extract_table_of_contents(self, text: str) -> str:
        """마크다운 텍스트에서 헤더 라인을 스캔하여 컴팩트한 전체 목차(TOC) 생성"""
        toc_lines = []
        for line in text.splitlines():
            line_str = line.strip()
            if line_str.startswith("# "):
                toc_lines.append(f"• {line_str[2:].strip()}")
            elif line_str.startswith("## "):
                toc_lines.append(f"  - {line_str[3:].strip()}")
            elif line_str.startswith("### "):
                toc_lines.append(f"    * {line_str[4:].strip()}")
        return "\n".join(toc_lines)

    def _parse_doc_meta(self, text: str, file_name: str) -> Dict[str, str]:
        """문서 헤더에서 제목 및 소관부서 추출 (하드코딩 제거)"""
        first_line = text.strip().split("\n")[0].replace("#", "").strip()
        doc_name = first_line if first_line else os.path.splitext(file_name)[0]
        
        dept_match = re.search(r"(?:소관부서|담당부서)[*\s:]+([^\n]+)", text)
        dept = dept_match.group(1).strip() if dept_match else None
        
        meta = {"doc_name": doc_name}
        if dept:
            meta["department"] = dept
        return meta

    def _build_breadcrumb(self, meta: Dict[str, str], default_title: str) -> str:
        """h1 ~ h4 메타데이터로부터 계층 경로를 동적으로 자동 생성"""
        headers = [meta[k].strip() for k in ["h1", "h2", "h3", "h4"] if k in meta]
        return " > ".join(headers) if headers else default_title

