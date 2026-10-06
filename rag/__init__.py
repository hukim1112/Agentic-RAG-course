"""
rag: 엔터프라이즈 RAG 라이브러리 (app/ 서비스와 노트북이 공용으로 사용)

    preprocessing/  전처리: 원본 문서 → 표준 Markdown (형식별 정규화, 품질 검수, 문서 계열 설정)
    indexing/       인덱싱: 표준 Markdown → 문맥 헤더가 붙은 청크
    retrieval/      검색 기법: 사내 약어 사전, BM25 + Dense 하이브리드(RRF), 윈도우 확장
    graph/          그래프 RAG: 트리플렛 추출, NetworkX 지식 그래프, Microsoft GraphRAG
"""
