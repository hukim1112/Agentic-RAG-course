"""
app/mcp/generate_database.py
============================
[사전 구축용 스크립트 - 교육생 실행 금지 / 참고용]
🚨 주의: app/database/에 4대 데이터베이스가 이미 모두 생성되어 배포되어 있으므로
         교육생은 이 스크립트를 직접 실행하지 마세요! (test_database.py를 바로 실행하세요)

1. 통합 Chroma Vector DB (Dense Embeddings) -> app/database/chroma_db
   - 컬렉션 1: enterprise_policy_store (사내 규정집)
   - 컬렉션 2: bok_industry_reports_store (한국은행 산업보고서)
2. 사내 규정집 청크 룩업 맵 & 메타데이터 -> app/database/policy_chunks.pkl
3. 엔터프라이즈 조직/프로젝트 지식 그래프 (NetworkX) -> app/database/knowledge_graph.json & nodelink.json
4. Microsoft GraphRAG 데이터베이스 -> app/database/graphrag/ (사전 빌드 아티팩트 동기화)
"""

import os
import sys
import glob
import json
import shutil
import pickle
import networkx as nx
import chromadb
from dotenv import load_dotenv

# 프로젝트 루트 경로 등록
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

from rag.contextual_headers import ContextualHeaderEnricher
from rag.networkx_graph import build_graph_from_triplets
from rag.triplet_extractor import Triplet, KnowledgeGraph, extract_triplets


DB_DIR = os.path.join(PROJECT_ROOT, "app/database")
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
GRAPHRAG_DB_DIR = os.path.join(DB_DIR, "graphrag")
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)


def build_policy_vector_db():
    """1. 사내 규정집 계층 파싱 및 통합 Chroma Vector DB 영구 저장"""
    print("\n" + "=" * 70)
    print("📦 [1/4] 사내 규정집 (Policies) Chroma Vector DB 구축 시작...")
    print("=" * 70)

    policy_dir = os.path.join(PROJECT_ROOT, "data/policies")
    policy_files = sorted(glob.glob(os.path.join(policy_dir, "*.md")))
    print(f"  • 대상 마크다운 파일 ({len(policy_files)}개):")
    for f in policy_files:
        print(f"    - {os.path.basename(f)}")

    enricher = ContextualHeaderEnricher(chunk_size=500, chunk_overlap=50)
    all_enriched_docs = []
    chunk_lookup_map = {}

    for doc_id, fpath in enumerate(policy_files):
        docs, lookup = enricher.process_file(fpath, doc_id=doc_id)
        all_enriched_docs.extend(docs)
        # 키를 직렬화 가능한 string 형태 ('docid_chunkid')로 변환
        for (did, cid), doc in lookup.items():
            chunk_lookup_map[f"{did}_{cid}"] = doc

    print(f"  • 생성된 총 청크 수: {len(all_enriched_docs)}개")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

    print(f"  • 통합 Chroma DB에 인덱싱 중: {CHROMA_DIR} (컬렉션: enterprise_policy_store) ...")
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection("enterprise_policy_store")
    except Exception:
        pass

    vectorstore = Chroma.from_documents(
        documents=all_enriched_docs,
        embedding=embeddings,
        collection_name="enterprise_policy_store",
        persist_directory=CHROMA_DIR
    )

    # 룩업 맵 저장 (Window Expansion 용도)
    lookup_file = os.path.join(DB_DIR, "policy_chunks.pkl")
    with open(lookup_file, "wb") as f:
        pickle.dump(chunk_lookup_map, f)

    print(f"  ✅ 사내 규정 Vector DB 구축 완료! (컬렉션: enterprise_policy_store)")
    print(f"  ✅ 청크 룩업 맵 저장 완료: {lookup_file}")


def build_knowledge_graph_db():
    """2. 조직/프로젝트 원천 데이터로부터 지식 그래프 구축 및 app/database/ 영구 저장"""
    print("\n" + "=" * 70)
    print("📦 [2/4] 엔터프라이즈 조직 지식 그래프 (Knowledge Graph) 구축 시작...")
    print("=" * 70)

    graph_text_file = os.path.join(PROJECT_ROOT, "data/graph/org_relationships.txt")
    if not os.path.exists(graph_text_file):
        print(f"  ⚠️ 그래프 원천 파일이 없습니다: {graph_text_file}")
        return

    with open(graph_text_file, "r", encoding="utf-8") as f:
        raw_text = f.read()

    print(f"  • 원천 텍스트 로드 ({len(raw_text)}자): {os.path.basename(graph_text_file)}")
    print("  • LLM 기반 트리플렛 구조화 추출 실행 중...")

    kg_result = extract_triplets(raw_text)
    triplets = kg_result.triplets
    print(f"  • 추출된 총 트리플렛 수: {len(triplets)}개")

    # NetworkX 그래프 구축
    G = build_graph_from_triplets(triplets)
    print(f"  • 생성된 NetworkX 그래프: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

    # NetworkX NodeLink 데이터 저장 (app/database/knowledge_graph_nodelink.json)
    graph_nodelink_file = os.path.join(DB_DIR, "knowledge_graph_nodelink.json")
    with open(graph_nodelink_file, "w", encoding="utf-8") as f:
        json.dump(nx.node_link_data(G), f, ensure_ascii=False, indent=2)

    print(f"  ✅ 지식 그래프 NetworkX NodeLink 저장 완료: {graph_nodelink_file}")


def build_bok_vector_db():
    """3. 한국은행(BOK) 산업보고서 통합 Chroma Vector DB 구축"""
    print("\n" + "=" * 70)
    print("📦 [3/4] 한국은행 (BOK) 주력산업 모니터링 보고서 Vector DB 구축 시작...")
    print("=" * 70)

    bok_dir = os.path.join(PROJECT_ROOT, "data/bok_major_industry_reports")
    bok_files = sorted(glob.glob(os.path.join(bok_dir, "*.pdf")))
    print(f"  • 대상 PDF 파일 ({len(bok_files)}개):")
    for f in bok_files:
        print(f"    - {os.path.basename(f)}")

    # PyMuPDF4LLM 기반 PDF 텍스트 추출 및 청킹
    try:
        import pymupdf4llm
        bok_docs = []
        for doc_id, pdf_path in enumerate(bok_files):
            fname = os.path.basename(pdf_path)
            md_text = pymupdf4llm.to_markdown(pdf_path)
            # 페이지별 청킹
            splitter = ContextualHeaderEnricher(chunk_size=600, chunk_overlap=60)
            temp_md_path = f"/tmp/norm_{fname}.md"
            with open(temp_md_path, "w", encoding="utf-8") as f:
                f.write(md_text)
            docs, _ = splitter.process_file(temp_md_path, doc_id=doc_id)
            bok_docs.extend(docs)

        print(f"  • 추출된 BOK 청크 수: {len(bok_docs)}개")

        embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        print(f"  • 통합 Chroma DB에 인덱싱 중: {CHROMA_DIR} (컬렉션: bok_industry_reports_store) ...")
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        try:
            client.delete_collection("bok_industry_reports_store")
        except Exception:
            pass

        vectorstore = Chroma.from_documents(
            documents=bok_docs,
            embedding=embeddings,
            collection_name="bok_industry_reports_store",
            persist_directory=CHROMA_DIR
        )
        print(f"  ✅ BOK 보고서 Vector DB 구축 완료! (컬렉션: bok_industry_reports_store)")
    except Exception as e:
        print(f"  ⚠️ BOK 보고서 인덱싱 건너뜀 (오류: {e})")


def build_graphrag_db():
    """4. Microsoft GraphRAG 데이터베이스 app/database/graphrag/ 로 복사 및 동기화"""
    print("\n" + "=" * 70)
    print("📦 [4/4] Microsoft GraphRAG 데이터베이스 구축 및 app/database/graphrag/ 동기화...")
    print("=" * 70)

    src_graphrag = os.path.join(PROJECT_ROOT, "data/graphrag")
    if not os.path.exists(src_graphrag):
        print(f"  ⚠️ 원천 GraphRAG 디렉토리가 없습니다: {src_graphrag}")
        return

    os.makedirs(GRAPHRAG_DB_DIR, exist_ok=True)
    
    # data/graphrag 내의 모든 아티팩트(output, settings.yaml, cache, input 등)를 app/database/graphrag 로 복사
    copied_items = []
    for item in os.listdir(src_graphrag):
        s = os.path.join(src_graphrag, item)
        d = os.path.join(GRAPHRAG_DB_DIR, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
            copied_items.append(f"{item}/")
        else:
            shutil.copy2(s, d)
            copied_items.append(item)

    print(f"  • 동기화된 항목 ({len(copied_items)}개): {', '.join(copied_items)}")
    print(f"  ✅ Microsoft GraphRAG DB 영구 저장 완료: {GRAPHRAG_DB_DIR}")


if __name__ == "__main__":
    print("🚀 [엔터프라이즈 RAG 데이터베이스 생성기 가동]\n")
    build_policy_vector_db()
    build_knowledge_graph_db()
    build_bok_vector_db()
    build_graphrag_db()
    print("\n" + "=" * 70)
    print("🎉 4대 엔터프라이즈 RAG 데이터베이스가 app/database/ 에 성공적으로 영구 저장되었습니다!")
    print(f"  1. 통합 Chroma Vector DB   : {CHROMA_DIR}")
    print("     - 컬렉션: 'enterprise_policy_store' & 'bok_industry_reports_store'")
    print(f"  2. 청크 룩업 맵 (Pickle)    : {os.path.join(DB_DIR, 'policy_chunks.pkl')}")
    print(f"  3. 지식 그래프 (NodeLink)   : {os.path.join(DB_DIR, 'knowledge_graph_nodelink.json')}")
    print(f"  4. Microsoft GraphRAG DB    : {GRAPHRAG_DB_DIR}")
    print("=" * 70)
