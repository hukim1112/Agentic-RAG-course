"""
app/mcp/build_database.py
=========================
엔터프라이즈 RAG 데이터베이스 빌드 스크립트 (Mission 02)

노트북 2_Indexing.ipynb에서 배운 파이프라인을 그대로 사용해 app/database/를 구축합니다.
비정형 문서는 형식(.md / .pdf)과 상관없이 rag.indexing.index_documents()
한 함수를 거쳐 인덱싱됩니다.

빌드 대상 (--targets):
  policy   : data/policies/*.md          → Chroma 컬렉션 'enterprise_policy_store'
  bok      : data/bok_major_industry_reports/*.pdf → Chroma 컬렉션 'bok_industry_reports_store'
  graph    : data/graph/org_relationships.txt → app/database/knowledge_graph_nodelink.json
  graphrag : data/graphrag/ (사전 빌드 산출물) → app/database/graphrag/

사용 예:
  python app/mcp/build_database.py                      # policy + graph (기본, 1~2분)
  python app/mcp/build_database.py --targets bok        # BOK 보고서 154페이지 (수 분 소요)
  python app/mcp/build_database.py --targets policy --extra-docs data/new_documents

빌드 결과가 마음에 들지 않으면 사전 구축본으로 되돌릴 수 있습니다:
  git checkout -- app/database
"""

import os
import sys
import glob
import json
import shutil
import argparse

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

import chromadb
import networkx as nx
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from rag.indexing import ContextualHeaderEnricher, index_documents
from rag.preprocessing import BOK_PDF_OPTIONS, bok_metadata
from rag.graph.networkx_graph import build_graph_from_triplets
from rag.graph.triplet_extractor import extract_triplets

DB_DIR = "app/database"
CHROMA_DIR = os.path.join(DB_DIR, "chroma_db")
EMBEDDING_MODEL = "text-embedding-3-large"


def _rebuild_collection(name: str, docs) -> None:
    """같은 이름의 컬렉션을 지우고 새 청크로 다시 만듭니다."""
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection(name)
    except Exception:
        pass
    Chroma.from_documents(
        documents=docs,
        embedding=OpenAIEmbeddings(model=EMBEDDING_MODEL),
        collection_name=name,
        persist_directory=CHROMA_DIR,
    )


def _strip_for_chroma(docs):
    """Chroma 메타데이터는 str/int/float/bool만 허용하므로 그 외 값은 제거합니다."""
    for d in docs:
        d.metadata = {k: v for k, v in d.metadata.items() if isinstance(v, (str, int, float, bool))}
    return docs


def build_policy(extra_dirs):
    paths = sorted(glob.glob("data/policies/*.md"))
    for extra in extra_dirs:
        paths += sorted(glob.glob(os.path.join(extra, "*.md")) + glob.glob(os.path.join(extra, "*.pdf")))
    print(f"📦 [policy] 사내 규정 {len(paths)}개 문서 인덱싱")
    for p in paths:
        print(f"    - {p}")
    docs, _ = index_documents(paths, ContextualHeaderEnricher(chunk_size=500, chunk_overlap=50), doc_id_start=0)
    _rebuild_collection("enterprise_policy_store", _strip_for_chroma(docs))
    print(f"  ✅ enterprise_policy_store: {len(docs)}개 청크")


def build_bok():
    paths = sorted(glob.glob("data/bok_major_industry_reports/*.pdf"))
    print(f"📦 [bok] 한국은행 보고서 {len(paths)}개 PDF 정규화 및 인덱싱 (수 분 소요)")
    docs, _ = index_documents(
        paths,
        ContextualHeaderEnricher(chunk_size=600, chunk_overlap=60),
        doc_id_start=100,
        pdf_options=BOK_PDF_OPTIONS,
        extra_metadata=bok_metadata,
    )
    _rebuild_collection("bok_industry_reports_store", _strip_for_chroma(docs))
    print(f"  ✅ bok_industry_reports_store: {len(docs)}개 청크")


def build_graph():
    with open("data/graph/org_relationships.txt", "r", encoding="utf-8") as f:
        raw_text = f.read()
    print("📦 [graph] LLM 트리플렛 추출로 조직 지식 그래프 구축")
    triplets = extract_triplets(raw_text).triplets
    graph = build_graph_from_triplets(triplets)
    with open(os.path.join(DB_DIR, "knowledge_graph_nodelink.json"), "w", encoding="utf-8") as f:
        json.dump(nx.node_link_data(graph), f, ensure_ascii=False, indent=2)
    print(f"  ✅ knowledge_graph_nodelink.json: 트리플렛 {len(triplets)}개, "
          f"노드 {graph.number_of_nodes()}개, 엣지 {graph.number_of_edges()}개")


def sync_graphrag():
    src, dst = "data/graphrag", os.path.join(DB_DIR, "graphrag")
    print("📦 [graphrag] 사전 빌드된 Microsoft GraphRAG 산출물 동기화")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  ✅ {dst}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enterprise RAG database builder")
    parser.add_argument("--targets", nargs="+", default=["policy", "graph"],
                        choices=["policy", "bok", "graph", "graphrag"], help="빌드할 대상")
    parser.add_argument("--extra-docs", nargs="*", default=[],
                        help="policy 컬렉션에 함께 인덱싱할 추가 문서 폴더 (.md / .pdf)")
    args = parser.parse_args()

    os.makedirs(CHROMA_DIR, exist_ok=True)
    builders = {
        "policy": lambda: build_policy(args.extra_docs),
        "bok": build_bok,
        "graph": build_graph,
        "graphrag": sync_graphrag,
    }
    for target in args.targets:
        builders[target]()
    print("🎉 빌드 완료. 'python app/mcp/test_database.py'로 검색을 검증하세요.")
