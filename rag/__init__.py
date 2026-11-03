"""
rag: 엔터프라이즈 멀티모달 RAG 라이브러리 (app/ 서비스와 노트북이 공용으로 사용)

    vector/         비정형 문서(Vector + BM25 하이브리드) RAG
      ├── preprocessing/  전처리: 원본 문서(.pdf, .md) → 표준 Markdown 정규화 및 품질 검수
      ├── indexing/       인덱싱: 표준 Markdown → 문맥 헤더(ContextualHeader) 청킹 및 벡터 적재
      └── retrieval/      검색기: 사내 약어 사전, BM25 + Dense 하이브리드(RRF), 윈도우 확장
    graph/          관계/전사 맥락(Graph) RAG: 트리플렛 추출, NetworkX 지식 그래프, Microsoft GraphRAG
    sql/            정형 ERP DB(Text2SQL) RAG: 테이블 스키마 탐색 및 읽기 전용 SQL 질의
"""
