"""
networkx_graph.py
=================
NetworkX 기반 지식 그래프 모델링, Pyvis 인터랙티브 시각화 및 Multi-hop 서브그래프 검색 모듈
"""

import os
from typing import List, Dict, Set, Tuple, Optional
import networkx as nx
from pyvis.network import Network
from rag.triplet_extractor import Triplet, KnowledgeGraph


def build_graph_from_triplets(triplets: List[Triplet]) -> nx.DiGraph:
    """트리플렛 목록으로부터 NetworkX DiGraph를 구축합니다."""
    graph = nx.DiGraph()
    for t in triplets:
        graph.add_node(t.subject)
        graph.add_node(t.object)
        graph.add_edge(t.subject, t.object, label=t.relation)
    return graph


def visualize_pyvis(
    graph: nx.DiGraph,
    output_html: str = "knowledge_graph.html",
    height: str = "600px",
    width: str = "100%",
    title: str = "Enterprise Knowledge Graph"
) -> str:
    """
    NetworkX 그래프를 Pyvis 인터랙티브 HTML 파일로 변환하여 저장합니다.
    노드 드래그, 줌, 호버 툴팁 및 물리(Physics) 시뮬레이션을 지원합니다.
    """
    net = Network(height=height, width=width, directed=True, notebook=True, cdn_resources="in_line")
    
    # 노드 및 엣지 추가
    for node in graph.nodes():
        # 노드 중심도(Degree)에 따른 크기 차등
        deg = graph.degree(node)
        size = 15 + (deg * 3)
        
        # 색상 규칙 (키워드 기반 도메인 스타일링)
        color = "#97C2FC" # 기본 파랑
        if any(k in node for k in ["본부", "팀", "부서"]):
            color = "#FFD166" # 부서 (노랑)
        elif any(k in node for k in ["수석", "책임", "선임", "전무", "상무", "팀장", "본부장"]):
            color = "#06D6A0" # 인물 (초록)
        elif any(k in node for k in ["프로젝트", "P-", "RAG", "마이그레이션", "플랫폼", "거버넌스"]):
            color = "#EF476F" # 프로젝트 (붉은색)
        elif any(k in node for k in ["원", "예산", "리스크", "목표"]):
            color = "#118AB2" # 메트릭/속성 (진파랑)
            
        net.add_node(
            node,
            label=node,
            title=f"<b>{node}</b><br>연결 수: {deg}",
            color=color,
            size=size
        )

    for u, v, data in graph.edges(data=True):
        label = data.get("label", "")
        net.add_edge(u, v, label=label, title=label, arrows="to")

    # 물리 엔진 설정 (부드러운 스프링 레이아웃)
    net.set_options("""
    var options = {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -50,
          "centralGravity": 0.01,
          "springLength": 100,
          "springConstant": 0.08
        },
        "maxVelocity": 50,
        "solver": "forceAtlas2Based",
        "timestep": 0.35,
        "stabilization": {"iterations": 150}
      },
      "interaction": {
        "hover": true,
        "navigationButtons": true,
        "zoomView": true
      }
    }
    """)
    
    net.save_graph(output_html)
    return output_html


def extract_entities_from_query(query: str, llm, graph: nx.DiGraph) -> List[str]:
    """LLM을 사용하여 자연어 질문에서 핵심 엔티티를 식별하고 그래프 노드와 매칭합니다."""
    prompt = (
        "다음 사용자 질문에서 핵심 고유명사, 인물명, 부서명, 직책명, 프로젝트명 등의 엔티티를 추출하세요.\n"
        "추출된 엔티티는 쉼표(,)로 구분된 한 줄로만 출력하세요.\n\n"
        f"[질문]: {query}\n\n[엔티티 목록]:"
    )
    resp = llm.invoke(prompt)
    raw_content = resp.content if isinstance(resp.content, str) else str(resp.content)
    
    extracted_terms = [e.strip() for e in raw_content.split(",") if e.strip()]
    
    # 그래프 노드와 매칭 (부분 일치 또는 포함 관계)
    matched_nodes = set()
    for term in extracted_terms:
        for node in graph.nodes:
            if term.lower() in node.lower() or node.lower() in term.lower():
                matched_nodes.add(node)
                
    return list(matched_nodes)


def multi_hop_search(
    graph: nx.DiGraph,
    seed_entities: Optional[List[str]] = None,
    query: Optional[str] = None,
    triplets: Optional[List[Triplet]] = None,
    llm: Optional[any] = None,
    max_hops: int = 2
) -> Tuple[List[Tuple[str, str, dict]], Set[str]]:
    """
    다중 홉(Multi-hop) BFS 그래프 검색 함수:
    
    1. 시작 노드 결정:
       - seed_entities가 주어지면 해당 노드 목록을 직접 사용
       - query와 llm이 주어지면 LLM을 통해 질문에서 엔티티를 자동 추출하여 매칭
    
    2. BFS 탐색:
       - max_hops 범위 내의 인접 노드 및 연결 엣지(In/Out)를 모두 수집
    
    3. 반환값:
       - (subgraph_edges, visited_entities) 튜플 반환
         (각 엣지는 (u, v, {'relation': ...}) 형태)
    """
    # 1. 시작 엔티티 식별
    start_nodes = set()
    if seed_entities:
        for s in seed_entities:
            # 완전 일치 또는 부분 일치하는 그래프 노드 검색
            matched = False
            for node in graph.nodes:
                if s.strip() == node or s.strip() in node or node in s.strip():
                    start_nodes.add(node)
                    matched = True
            if not matched and s.strip() in graph:
                start_nodes.add(s.strip())
    elif query and llm:
        extracted = extract_entities_from_query(query, llm, graph)
        start_nodes.update(extracted)
    
    if not start_nodes:
        return [], set()

    # 2. BFS 너비 우선 탐색
    visited = set()
    frontier = set(start_nodes)

    for _ in range(max_hops):
        next_frontier = set()
        for node in frontier:
            if node not in visited and node in graph:
                visited.add(node)
                # Out-edges
                for _, neighbor in graph.out_edges(node):
                    next_frontier.add(neighbor)
                # In-edges
                for neighbor, _ in graph.in_edges(node):
                    next_frontier.add(neighbor)
        frontier = next_frontier - visited

    visited.update(frontier)

    # 3. 방문된 노드 간의 서브그래프 엣지 수집
    sub_edges = []
    for u, v, data in graph.edges(data=True):
        if u in visited and v in visited:
            rel = data.get("relation") or data.get("label") or "관련"
            sub_edges.append((u, v, {"relation": rel, "label": rel}))

    return sub_edges, visited
