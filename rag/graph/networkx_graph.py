"""
networkx_graph.py
=================
NetworkX 기반 지식 그래프 모델링, Pyvis 인터랙티브 시각화 및 Multi-hop 서브그래프 검색 모듈
"""

from typing import List, Set, Tuple, Optional
import networkx as nx
from pyvis.network import Network
from rag.graph.triplet_extractor import Triplet, canonicalize_entity


def build_graph_from_triplets(triplets: List[Triplet]) -> nx.DiGraph:
    """
    온톨로지 기반 트리플렛 목록으로부터 NetworkX DiGraph를 구축합니다.
    - 각 노드에 entity_type(Person, Department, Project 등) 속성을 저장합니다.
    - 두 노드 사이에 복수의 관계가 존재하면 쉼표로 병합하여 관계 유실을 방지합니다.
    """
    graph = nx.DiGraph()
    for t in triplets:
        subj_type = getattr(t, "subject_type", "Entity")
        obj_type = getattr(t, "object_type", "Entity")
        detail = getattr(t, "detail", None)

        if not graph.has_node(t.subject):
            graph.add_node(t.subject, entity_type=subj_type)
        if not graph.has_node(t.object):
            graph.add_node(t.object, entity_type=obj_type)

        rel_text = f"{t.relation} ({detail})" if detail else t.relation

        if graph.has_edge(t.subject, t.object):
            existing = graph[t.subject][t.object].get("relation", "")
            existing_set = [r.strip() for r in existing.split(" / ") if r.strip()]
            if rel_text not in existing_set:
                existing_set.append(rel_text)
            merged = " / ".join(existing_set)
            graph[t.subject][t.object]["relation"] = merged
            graph[t.subject][t.object]["label"] = merged
        else:
            graph.add_edge(t.subject, t.object, relation=rel_text, label=rel_text)

    return graph


def visualize_pyvis(
    graph: nx.DiGraph,
    output_html: str = "knowledge_graph.html",
    height: str = "600px",
    width: str = "100%",
    title: str = "Enterprise Knowledge Graph",
) -> str:
    """
    NetworkX 그래프를 Pyvis 인터랙티브 HTML 파일로 변환하여 저장합니다.
    노드 온톨로지 유형(entity_type)에 따라 색상을 구분합니다.
    """
    net = Network(height=height, width=width, directed=True, notebook=True, cdn_resources="in_line")

    type_colors = {
        "Department": "#FFD166",   # 부서/본부 (노랑)
        "Person": "#06D6A0",       # 인물 (초록)
        "Project": "#EF476F",      # 프로젝트 (빨강)
        "PolicyOrRule": "#118AB2", # 규정/예산 (파랑)
        "RiskOrGoal": "#9B5DE5",   # 목표/리스크 (보라)
    }

    for node, attrs in graph.nodes(data=True):
        deg = graph.degree(node)
        size = 16 + (deg * 2.5)
        etype = attrs.get("entity_type", "")

        color = type_colors.get(etype)
        if not color:
            if any(k in node for k in ["본부", "팀", "부서", "위원회", "연구소"]):
                color = "#FFD166"
            elif any(k in node for k in ["수석", "책임", "선임", "전무", "상무"]):
                color = "#06D6A0"
            elif any(k in node for k in ["P-0", "프로젝트"]):
                color = "#EF476F"
            else:
                color = "#97C2FC"

        net.add_node(
            node,
            label=node,
            title=f"<b>{node}</b><br>유형: {etype or '일반'}<br>연결 수: {deg}",
            color=color,
            size=size,
        )

    for u, v, data in graph.edges(data=True):
        label = data.get("relation") or data.get("label", "")
        short_label = label.split(" (")[0]
        net.add_edge(u, v, label=short_label, title=label, arrows="to")

    net.set_options("""
    var options = {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.01,
          "springLength": 110,
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

    extracted_terms = [canonicalize_entity(e.strip()) for e in raw_content.split(",") if e.strip()]

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
    max_hops: int = 2,
) -> Tuple[List[Tuple[str, str, dict]], Set[str]]:
    """
    다중 홉(Multi-hop) BFS 그래프 검색 함수:
    시작 엔티티를 정규화하여 그래프 노드와 매칭한 뒤, max_hops 범위 내의 연결 서브그래프를 반환합니다.
    """
    start_nodes = set()
    if seed_entities:
        for s in seed_entities:
            canon = canonicalize_entity(s.strip())
            matched = False
            for node in graph.nodes:
                if canon == node or s.strip() in node or canon in node:
                    start_nodes.add(node)
                    matched = True
            if not matched and canon in graph:
                start_nodes.add(canon)
    elif query and llm:
        extracted = extract_entities_from_query(query, llm, graph)
        start_nodes.update(extracted)

    if not start_nodes:
        return [], set()

    visited = set()
    frontier = set(start_nodes)

    for _ in range(max_hops):
        next_frontier = set()
        for node in frontier:
            if node not in visited and node in graph:
                visited.add(node)
                for _, neighbor in graph.out_edges(node):
                    next_frontier.add(neighbor)
                for neighbor, _ in graph.in_edges(node):
                    next_frontier.add(neighbor)
        frontier = next_frontier - visited

    visited.update(frontier)

    sub_edges = []
    for u, v, data in graph.edges(data=True):
        if u in visited and v in visited:
            rel = data.get("relation") or data.get("label") or "관련"
            sub_edges.append((u, v, {"relation": rel, "label": rel}))

    return sub_edges, visited
