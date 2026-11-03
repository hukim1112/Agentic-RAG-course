"""
문맥 헤더 청킹 모듈 (Contextual Header Chunking Module)

표준 Markdown 문서를 H1~H4 논리 단위로 1차 분할하고 문자 길이로 2차 분할한 뒤,
문서명·소관부서·전체 목차(TOC)·현재 위치 경로(Breadcrumb)를 각 청크 상단에 주입하여
탈맥락화(Decontextualization)를 해결합니다.
"""

import os
import re
from typing import Dict, List, Optional, Tuple, Union
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


class ContextualHeader:
    """표준 Markdown 계층 청킹 및 문맥 헤더(TOC, Breadcrumb) 주입 클래스"""

    DEFAULT_TOC: Dict[str, int] = {"search": 2, "read": 3}

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 0,
        toc: Optional[Union[Dict[str, int], int, bool]] = None,
        include_toc: bool = True,
    ):
        """
        Args:
            chunk_size: 청크 최대 글자 수
            chunk_overlap: 청크 간 겹침 글자 수
            toc: 검색용(search)과 읽기용(read) 목차 최대 깊이 설정 (예: {"search": 2, "read": 3}).
                 정수 전달 시 search/read 모두 해당 깊이로 설정하며, False 전달 시 목차를 제외합니다.
            include_toc: 하위 호환용 플래그 (False이면 toc={"search": 0, "read": 0}과 동일)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.include_toc = include_toc

        if not include_toc or toc is False:
            self.toc = {"search": 0, "read": 0}
        elif isinstance(toc, int):
            self.toc = {"search": toc, "read": toc}
        elif isinstance(toc, dict):
            self.toc = {
                "search": toc.get("search", self.DEFAULT_TOC["search"]),
                "read": toc.get("read", self.DEFAULT_TOC["read"]),
            }
        else:
            self.toc = self.DEFAULT_TOC.copy()

        self.headers_to_split_on = [
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
            ("####", "h4"),
        ]
        self.md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split_on,
            strip_headers=False,
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def chunk_file(
        self,
        file_path: str,
        doc_id: int,
    ) -> Tuple[List[Document], Dict[Tuple[int, int], Document]]:
        """단일 Markdown 파일을 청킹하고 문맥 헤더가 주입된 청크 리스트와 윈도우 확장용 룩업 맵을 반환합니다."""
        with open(file_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        file_name = os.path.basename(file_path)
        doc_meta = self.parse_doc_meta(raw_text, file_name)
        search_toc = self.extract_toc(raw_text, max_level=self.toc["search"])
        read_toc = self.extract_toc(raw_text, max_level=self.toc["read"])

        header_splits = self.md_splitter.split_text(raw_text)

        enriched_docs: List[Document] = []
        chunk_lookup_map: Dict[Tuple[int, int], Document] = {}
        global_chunk_idx = 0

        for split_doc in header_splits:
            sub_chunks = self.text_splitter.split_documents([split_doc])

            for sub_chunk in sub_chunks:
                breadcrumb = self.build_breadcrumb(sub_chunk.metadata, doc_meta["doc_name"])

                search_header = self.build_header(doc_meta, breadcrumb, search_toc)
                read_header = self.build_header(doc_meta, breadcrumb, read_toc)

                raw_content = sub_chunk.page_content
                full_content = search_header + raw_content

                new_metadata = sub_chunk.metadata.copy()
                new_metadata.update({
                    "doc_id": doc_id,
                    "chunk_id": global_chunk_idx,
                    "source_file": file_name,
                    "breadcrumb": breadcrumb,
                    "doc_header": read_header,
                    "raw_content": raw_content,
                    "department": doc_meta.get("department", "N/A"),
                })

                enriched_doc = Document(page_content=full_content, metadata=new_metadata)
                chunk_lookup_map[(doc_id, global_chunk_idx)] = enriched_doc
                enriched_docs.append(enriched_doc)
                global_chunk_idx += 1

        return enriched_docs, chunk_lookup_map

    def build_header(self, doc_meta: Dict[str, str], breadcrumb: str, toc: str = "") -> str:
        """문서 메타데이터, 목차(TOC), 현재 위치 경로(Breadcrumb)를 조합하여 문맥 헤더 문자열을 생성합니다."""
        header_parts = [
            "--- Document Context Header ---",
            f"[문서명: {doc_meta['doc_name']}]",
        ]
        if doc_meta.get("department"):
            header_parts.append(f"[소관부서: {doc_meta['department']}]")
        if toc:
            header_parts.append("[문서 전체 목차 (TOC)]:\n" + toc)

        header_parts.append(f"[현재 위치 경로: {breadcrumb}]")
        header_parts.append("-------------------------------")
        return "\n".join(header_parts) + "\n\n"

    def extract_toc(self, text: str, max_level: int = 3) -> str:
        """마크다운 텍스트에서 H1 ~ H{max_level} 헤더 라인을 스캔하여 문서 목차(TOC)를 생성합니다.

        Args:
            text: 마크다운 원문 텍스트
            max_level: 포함할 최대 헤더 깊이 (0: 목차 제외, 1: H1, 2: H1~H2, 3: H1~H3, 4: H1~H4)
        """
        if max_level <= 0:
            return ""
        toc_lines = []
        for line in text.splitlines():
            line_str = line.strip()
            if max_level >= 1 and line_str.startswith("# "):
                toc_lines.append(f"• {line_str[2:].strip()}")
            elif max_level >= 2 and line_str.startswith("## "):
                toc_lines.append(f"  - {line_str[3:].strip()}")
            elif max_level >= 3 and line_str.startswith("### "):
                toc_lines.append(f"    * {line_str[4:].strip()}")
            elif max_level >= 4 and line_str.startswith("#### "):
                toc_lines.append(f"      · {line_str[5:].strip()}")
        return "\n".join(toc_lines)

    def parse_doc_meta(self, text: str, file_name: str) -> Dict[str, str]:
        """문서 상단에서 문서명과 소관부서를 추출합니다.

        첫 줄이 단일 H1 제목(`# 문서명`)이면 이를 문서명으로 사용하고,
        여러 섹션이それぞれ H1으로 시작하는 보고서(예: BOK 산업보고서)나 일반 문서는 파일명을 사용합니다.
        """
        default_name = os.path.splitext(file_name)[0]
        non_empty = [ln.strip() for ln in text.splitlines() if ln.strip()]
        h1_lines = [ln for ln in non_empty if ln.startswith("# ")]

        if len(h1_lines) == 1:
            doc_name = h1_lines[0][2:].replace("*", "").strip() or default_name
        else:
            doc_name = default_name

        dept_match = re.search(r"(?:소관부서|담당부서)[*\s:]+([^\n]+)", text)
        dept = dept_match.group(1).strip() if dept_match else None

        meta = {"doc_name": doc_name}
        if dept:
            meta["department"] = dept
        return meta

    def build_breadcrumb(self, meta: Dict[str, str], default_title: str) -> str:
        """h1~h4 메타데이터로부터 계층 경로(Breadcrumb)를 생성합니다."""
        headers = [meta[k].strip() for k in ("h1", "h2", "h3", "h4") if k in meta and meta[k].strip()]
        if not headers:
            return default_title
        if default_title and headers[0] != default_title:
            headers = [default_title] + headers
        return " > ".join(headers)


