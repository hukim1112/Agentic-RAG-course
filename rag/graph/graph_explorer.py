"""
graph_explorer.py
=================
Microsoft GraphRAG 인덱스 산출물을 에이전트가 단계적으로 탐색하는 그래프 탐색 도구 모듈

GraphRAG 기본 검색(Local / Global)은 검색 엔진 안에서 LLM이 답변까지 작성해 느리고,
답변 생성을 빼면 Local 맥락이 토큰 상한까지 채워져 지나치게 커집니다.
이 모듈은 같은 인덱스(entities, relationships, community_reports, text_units, lancedb 임베딩)를 쓰되,
에이전트가 필요한 만큼만 따라가도록 조회 단위를 나눕니다. 에이전트의 그래프 도구는 이 5종뿐입니다.

    graph_find_entities      질문 속 인물·부서·프로젝트를 그래프 엔티티로 연결     (탐색 시작점)
    graph_neighbors          엔티티의 1~2홉 관계, 질문과 가까운 이웃부터            (관계 탐색)
    graph_find_path          두 엔티티 사이의 최단 연결 경로                        (보고선·의존 관계)
    graph_search_communities 커뮤니티 리포트 요약 검색, Global의 Map LLM 호출 없음   (전사 개요)
    graph_read               ID로 상세 내용·원문 조회                               (근거 확인)

모든 결과 항목에 ID를 붙여, 에이전트가 필요한 항목만 graph_read로 펼쳐 보게 합니다.
  E = 엔티티, R = 관계, C = 커뮤니티 리포트, T = 원문 조각(text unit)
쿼리 시점에는 LLM을 호출하지 않고, 질문 임베딩 1회(GraphRAG 인덱싱과 같은 임베딩 모델)만 사용합니다.
"""

import os
import re
import threading
from functools import lru_cache
from typing import Annotated, Dict, List, Optional, Tuple

import lancedb
import litellm
import networkx as nx
import numpy as np
import pandas as pd
import yaml
from langchain_core.tools import tool
from pydantic import Field

from rag.graph.graphrag_tool import PROJECT_ROOT, _resolve_root_dir, load_graphrag_settings

# 설명문 자르기 기준 (목록형 결과는 짧게, 상세는 graph_read로)
_DESC_SHORT = 160
_REL_DESC = 200
_READ_MAX_CHARS = 3500
_READ_MAX_IDS = 5


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def _alias_keys(title: str) -> List[str]:
    """GraphRAG가 따로 만든 중복 엔티티를 묶는 키를 만듭니다.
    - 띄어쓰기·기호만 다른 이름: 'AGENTIC AI TEAM' = 'AGENTICAI TEAM'
    - 같은 코드 하나를 담은 이름: 'P-02' = 'PROJECT P-02' = 'P-02: 엔터프라이즈 AGENTIC RAG 플랫폼 구축'
    """
    keys = [re.sub(r"[^A-Z0-9가-힣]", "", str(title).upper())]
    codes = set(re.findall(r"\b[A-Z]{1,4}-\d{2,}\b", str(title).upper()))
    if len(codes) == 1:
        keys.append("CODE:" + codes.pop())
    return keys


class GraphExplorer:
    """하나의 GraphRAG 프로젝트(root_dir) 인덱스를 메모리에 올려 두고 조회하는 탐색기"""

    def __init__(self, abs_root: str):
        out_dir = os.path.join(abs_root, "output")
        self.entities = pd.read_parquet(os.path.join(out_dir, "entities.parquet")).set_index("title", drop=False)
        self.relationships = pd.read_parquet(os.path.join(out_dir, "relationships.parquet"))
        self.reports = pd.read_parquet(os.path.join(out_dir, "community_reports.parquet"))
        self.text_units = pd.read_parquet(os.path.join(out_dir, "text_units.parquet"))

        # ID 체계: 사람이 읽는 번호(human_readable_id) + 접두어
        self._entity_by_hrid = {int(r.human_readable_id): t for t, r in self.entities.iterrows()}
        self._title_by_uuid = dict(zip(self.entities["id"], self.entities["title"]))
        self._tu_hrid_by_uuid = dict(zip(self.text_units["id"], self.text_units["human_readable_id"]))
        self._rel_by_hrid = self.relationships.set_index("human_readable_id", drop=False)
        self._report_by_hrid = self.reports.set_index("human_readable_id", drop=False)
        self._report_hrid_by_uuid = dict(zip(self.reports["id"], self.reports["human_readable_id"]))
        self._tu_by_hrid = self.text_units.set_index("human_readable_id", drop=False)

        self._titles_by_key: Dict[str, List[str]] = {}
        for title in self.entities["title"]:
            for key in _alias_keys(title):
                self._titles_by_key.setdefault(key, []).append(title)

        # 관계 그래프: GraphRAG 관계는 source/target이 있지만 의미상 양방향이므로 무방향 그래프로 탐색합니다.
        self.graph = nx.Graph()
        for rel in self.relationships.itertuples():
            self.graph.add_edge(rel.source, rel.target, rel_hrid=int(rel.human_readable_id), weight=float(rel.weight))
        # 같은 대상으로 보이는 중복 엔티티끼리 '같은 대상' 연결(rel_hrid=None)을 추가합니다.
        # 이 연결이 없으면 'P-02: …'와 'PROJECT P-02'처럼 이름만 다른 노드에서 그래프가 끊겨 경로를 찾지 못합니다.
        for titles in self._titles_by_key.values():
            for other in titles[1:]:
                if titles[0] != other and not self.graph.has_edge(titles[0], other):
                    self.graph.add_edge(titles[0], other, rel_hrid=None, weight=0.0)

        # GraphRAG가 인덱싱 때 만든 임베딩을 그대로 재사용합니다.
        db = lancedb.connect(os.path.join(out_dir, "lancedb"))
        self._entity_table = db.open_table("entity_description")
        self._report_table = db.open_table("community_full_content")
        self._embedding_model, self._embedding_api_key = self._load_embedding_model(abs_root)
        # 관계 임베딩은 질문 기반 순위를 매길 때만 필요하므로 처음 필요할 때 읽습니다.
        # (임베딩 API를 쓸 수 없어도 ID 조회·경로 찾기는 동작)
        self._out_dir = out_dir
        self._rel_vec_cache: Optional[Dict[int, np.ndarray]] = None

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------
    @staticmethod
    def _load_embedding_model(abs_root: str) -> Tuple[str, Optional[str]]:
        """settings.yaml의 임베딩 모델을 읽습니다. 인덱싱과 같은 모델이어야 벡터 공간이 맞습니다."""
        with open(os.path.join(abs_root, "settings.yaml"), "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)["embedding_models"]["default_embedding_model"]
        api_key = cfg.get("api_key", "")
        env_match = re.fullmatch(r"\$\{(\w+)\}", str(api_key))
        if env_match:
            api_key = os.getenv(env_match.group(1))
        return f"{cfg['model_provider']}/{cfg['model']}", api_key

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        vectors = []
        for i in range(0, len(texts), 100):
            resp = litellm.embedding(model=self._embedding_model, input=texts[i:i + 100], api_key=self._embedding_api_key)
            vectors += [d["embedding"] for d in resp.data]
        vectors = np.asarray(vectors, dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    @lru_cache(maxsize=256)
    def _embed(self, text: str) -> np.ndarray:
        return self._embed_batch([text])[0]

    def _rel_vec(self) -> Dict[int, np.ndarray]:
        if self._rel_vec_cache is None:
            self._rel_vec_cache = self._load_relationship_vectors(self._out_dir)
        return self._rel_vec_cache

    def _load_relationship_vectors(self, out_dir: str) -> Dict[int, np.ndarray]:
        """관계 설명 임베딩을 읽습니다. GraphRAG는 관계 임베딩을 만들지 않으므로, 처음 한 번 만들어 output/에 저장합니다.

        이웃 순위를 '이웃 엔티티'가 아니라 '관계 설명'과 질문의 유사도로 매기기 위해 씁니다.
        ('총괄 프로젝트'라는 질문은 'manages and oversees the P-02 project'라는 관계 설명과 가깝습니다.)
        """
        cache_path = os.path.join(out_dir, "graph_explorer_relationship_vectors.npz")
        hrids = self.relationships["human_readable_id"].astype(int).to_numpy()
        if os.path.exists(cache_path):
            cached = np.load(cache_path)
            if np.array_equal(cached["hrids"], hrids):
                return dict(zip(hrids.tolist(), cached["vectors"]))
        texts = [f"{r.source} - {r.target}: {r.description}" for r in self.relationships.itertuples()]
        vectors = self._embed_batch(texts)
        np.savez(cache_path, hrids=hrids, vectors=vectors)
        return dict(zip(hrids.tolist(), vectors))

    def _group(self, title: str) -> List[str]:
        """title과 같은 대상으로 보이는 엔티티 묶음 (title이 맨 앞)"""
        group = [title]
        for key in _alias_keys(title):
            group += [t for t in self._titles_by_key.get(key, []) if t not in group]
        return group

    def _tu_hrids(self, uuids) -> List[int]:
        return sorted({int(self._tu_hrid_by_uuid[u]) for u in uuids if u in self._tu_hrid_by_uuid})

    def _tu_refs(self, uuids, limit: int = 3) -> str:
        hrids = self._tu_hrids(uuids)
        refs = ",".join(f"T{h}" for h in hrids[:limit])
        return refs + ("…" if len(hrids) > limit else "")

    def _evidence_footer(self, rel_hrids: List[int], limit: int = 5) -> str:
        """결과에 나온 관계들의 근거 원문을 모아, 한 번의 graph_read로 읽도록 안내합니다.
        (원문을 하나씩 따로 읽으면 LLM 왕복이 늘어 응답이 느려집니다)"""
        counts: Dict[int, int] = {}
        for rel_hrid in rel_hrids:
            for t in self._tu_hrids(self._rel_by_hrid.loc[rel_hrid].text_unit_ids):
                counts[t] = counts.get(t, 0) + 1
        top = [f"T{t}" for t, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]]
        if not top:
            return ""
        return (f"\n근거 원문 (많이 인용된 순): {', '.join(top)}\n"
                f"예산·날짜 같은 수치가 필요하면 graph_read(ids={top[:3]})처럼 필요한 ID를 한 번에 읽으세요.")

    def _search_entities(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """임베딩 유사도 + 질문에 나온 코드(P-02 등) 정확 일치로 엔티티를 찾습니다."""
        query_vec = self._embed(query)
        hits = self._entity_table.search(query_vec).distance_type("cosine").limit(top_k * 2).to_pandas()
        scored = {self._title_by_uuid[u]: 1.0 - d for u, d in zip(hits["id"], hits["_distance"]) if u in self._title_by_uuid}
        for code in re.findall(r"[A-Z]+-\d+", query.upper()):
            for title in self.entities["title"]:
                if re.search(rf"\b{re.escape(code)}\b", title):
                    scored[title] = max(scored.get(title, 0.0), 1.0)
        return sorted(scored.items(), key=lambda x: x[1], reverse=True)[:top_k]

    def resolve_entity(self, ref: str) -> Tuple[Optional[str], str]:
        """'E22', 정확한 엔티티 이름, 또는 자연어 이름('AgenticAI팀')을 엔티티 제목으로 바꿉니다.

        자연어 이름은 임베딩으로 연결하되, 1·2위 후보가 서로 다른 대상이고 점수 차가 작으면
        잘못 고르지 않도록 연결하지 않고 후보 목록을 돌려줍니다.
        """
        ref = ref.strip()
        m = re.fullmatch(r"[Ee](\d+)", ref)
        if m:
            title = self._entity_by_hrid.get(int(m.group(1)))
            return title, "" if title else f"엔티티 {ref}가 없습니다."
        if ref.upper() in self.entities.index:
            return ref.upper(), ""
        for key in _alias_keys(ref):
            if key in self._titles_by_key:
                return self._titles_by_key[key][0], ""
        found = self._search_entities(ref, top_k=5)
        if not found:
            return None, f"'{ref}'에 해당하는 엔티티를 찾지 못했습니다."
        best, best_score = found[0]
        rivals = [(t, s) for t, s in found[1:] if t not in self._group(best)]
        if rivals and best_score - rivals[0][1] < 0.05:
            candidates = "\n".join(self._entity_line(t, s) for t, s in found)
            return None, f"'{ref}'에 해당하는 엔티티가 여러 개입니다. 맞는 E번호로 다시 호출하세요.\n{candidates}"
        return best, f"('{ref}' → {best}로 연결했습니다. 다르면 graph_find_entities로 확인하세요.)"

    def _entity_line(self, title: str, score: Optional[float] = None) -> str:
        e = self.entities.loc[title]
        score_txt = f", 유사도 {score:.2f}" if score is not None else ""
        return (f"E{int(e.human_readable_id)} {title} [{e.type}, 연결 {int(e.degree)}{score_txt}] "
                f"— {_clip(e.description, _DESC_SHORT)}")

    def _rel_line(self, rel_hrid: int, desc_limit: int = _REL_DESC) -> str:
        r = self._rel_by_hrid.loc[rel_hrid]
        return (f"R{rel_hrid} {r.source} ─ {r.target} [가중치 {r.weight:.0f}] "
                f"{_clip(r.description, desc_limit)} (근거 {self._tu_refs(r.text_unit_ids)})")

    # ------------------------------------------------------------------
    # 탐색 기능
    # ------------------------------------------------------------------
    def find_entities(self, query: str, top_k: int = 5) -> str:
        found = self._search_entities(query, top_k)
        if not found:
            return f"'{query}'와 관련된 엔티티를 찾지 못했습니다."
        lines = [f"### '{query}' 관련 엔티티 {len(found)}개 (유사도 순)"]
        lines += [self._entity_line(title, score) for title, score in found]
        lines.append("\n다음 단계: graph_neighbors(entity='E번호')로 관계를 펼치거나, graph_find_path로 두 엔티티를 잇습니다.")
        return "\n".join(lines)

    def neighbors(self, entity: str, query: str = "", hops: int = 1, top_k: int = 12) -> str:
        title, note = self.resolve_entity(entity)
        if title is None:
            return note
        # 같은 대상으로 보이는 중복 엔티티는 한 노드처럼 함께 펼칩니다.
        seeds = [t for t in self._group(title) if t in self.graph]
        if not seeds:
            return f"{title}에 연결된 관계가 없습니다."
        query_vec = self._embed(query) if query.strip() else None
        rel_vec = self._rel_vec() if query_vec is not None else {}

        def rank(edges):
            # 질문이 있으면 관계 설명과 질문의 유사도 순, 없으면 관계 가중치 순
            def score(edge):
                data = edge[2]
                sim = float(np.dot(query_vec, rel_vec[data["rel_hrid"]])) if query_vec is not None else 0.0
                return sim, data["weight"]
            return sorted(edges, key=score, reverse=True)

        def relations(nodes, exclude):
            # '같은 대상' 연결은 관계가 아니므로 목록에서 뺍니다.
            return [(m, n, self.graph[m][n]) for m in nodes for n in self.graph.neighbors(m)
                    if n not in exclude and self.graph[m][n]["rel_hrid"] is not None]

        hop1 = rank(relations(seeds, set(seeds)))
        lines = []
        if note:
            lines.append(note)
        if len(seeds) > 1:
            lines.append(f"(같은 대상으로 보이는 엔티티 {', '.join(seeds)}를 함께 펼쳤습니다.)")
        lines.append(f"### {title}의 1홉 관계 {min(top_k, len(hop1))}/{len(hop1)}개"
                     + (f" ('{query}'와 가까운 순)" if query_vec is not None else " (가중치 순)"))
        lines += [self._rel_line(d["rel_hrid"]) for _, _, d in hop1[:top_k]]
        shown = [d["rel_hrid"] for _, _, d in hop1[:top_k]]

        if hops >= 2:
            # 2홉은 질문과 가까운 1홉 이웃 몇 개에서만 넓혀 결과 크기를 제한합니다.
            seen = set(seeds)
            frontier = [n for _, n, _ in hop1[:5]]
            seen.update(n for _, n, _ in hop1)
            hop2 = rank(relations(frontier, seen))
            lines.append(f"\n### 2홉 관계 {min(top_k, len(hop2))}/{len(hop2)}개 (상위 1홉 이웃 {', '.join(frontier)} 경유)")
            lines += [self._rel_line(d["rel_hrid"], desc_limit=140) for _, _, d in hop2[:top_k]]
            shown += [d["rel_hrid"] for _, _, d in hop2[:top_k]]

        lines.append(self._evidence_footer(shown))
        return "\n".join(lines)

    def find_path(self, source: str, target: str, max_hops: int = 4) -> str:
        src, src_note = self.resolve_entity(source)
        tgt, tgt_note = self.resolve_entity(target)
        if src is None or tgt is None:
            return "\n\n".join(n for n in (src_note, tgt_note) if n)
        # 중복 엔티티 묶음끼리 가장 짧게 이어지는 쌍을 고릅니다.
        pairs = []
        for s in self._group(src):
            for t in self._group(tgt):
                if s in self.graph and t in self.graph and nx.has_path(self.graph, s, t):
                    pairs.append((nx.shortest_path_length(self.graph, s, t), s, t))
        if not pairs:
            return f"{src}와 {tgt} 사이에 연결 경로가 없습니다."
        _, src, tgt = min(pairs)
        paths = []
        for path in nx.all_shortest_paths(self.graph, src, tgt):
            paths.append(path)
            if len(paths) == 3:
                break
        if len(paths[0]) - 1 > max_hops:
            return f"{src}와 {tgt}의 최단 경로가 {len(paths[0]) - 1}홉으로 max_hops({max_hops})보다 깁니다."

        lines = [n for n in (src_note, tgt_note) if n]
        lines.append(f"### {src} → {tgt} 최단 경로 {len(paths)}개 ({len(paths[0]) - 1}홉)")
        shown = []
        for i, path in enumerate(paths, start=1):
            lines.append(f"\n경로 {i}: " + " → ".join(path))
            for a, b in zip(path, path[1:]):
                rel_hrid = self.graph[a][b]["rel_hrid"]
                if rel_hrid is None:
                    lines.append(f"  ≡ {a} = {b} (이름만 다른 같은 대상)")
                    continue
                shown.append(rel_hrid)
                lines.append("  " + self._rel_line(rel_hrid, desc_limit=150))
        lines.append(self._evidence_footer(shown))
        return "\n".join(lines)

    def search_communities(self, query: str, top_k: int = 3, level: Optional[int] = None) -> str:
        query_vec = self._embed(query)
        hits = self._report_table.search(query_vec).distance_type("cosine").limit(max(top_k * 5, 20)).to_pandas()
        lines, count = [], 0
        for uid, dist in zip(hits["id"], hits["_distance"]):
            hrid = self._report_hrid_by_uuid.get(uid)
            if hrid is None:
                continue
            c = self._report_by_hrid.loc[hrid]
            if level is not None and int(c.level) != level:
                continue
            lines.append(f"C{hrid} [level {c.level}, 중요도 {c['rank']}, 유사도 {1 - dist:.2f}] {c.title}\n"
                         f"  {_clip(c.summary, 500)}")
            count += 1
            if count == top_k:
                break
        if not lines:
            return f"'{query}'와 관련된 커뮤니티 리포트를 찾지 못했습니다."
        header = f"### '{query}' 관련 커뮤니티 리포트 {count}개 (level 0 = 큰 묶음, 숫자가 클수록 세부)"
        return header + "\n" + "\n".join(lines) + "\n\n세부 발견 사항은 graph_read(ids=['C번호'])로 확인합니다."

    def read(self, ids: List[str]) -> str:
        blocks = []
        for ref in ids[:_READ_MAX_IDS]:
            m = re.fullmatch(r"\s*([ERCTercts])(\d+)\s*", ref)
            if not m:
                blocks.append(f"[{ref}] ID 형식이 아닙니다. E·R·C·T + 번호 형식으로 넣으세요 (예: E22, T5).")
                continue
            kind, num = m.group(1).upper(), int(m.group(2))
            blocks.append(self._read_one(kind, num))
        if len(ids) > _READ_MAX_IDS:
            blocks.append(f"(한 번에 {_READ_MAX_IDS}개까지만 읽습니다. 나머지 {len(ids) - _READ_MAX_IDS}개는 다시 호출하세요.)")
        return "\n\n".join(blocks)

    def _read_one(self, kind: str, num: int) -> str:
        if kind == "E" and num in self._entity_by_hrid:
            e = self.entities.loc[self._entity_by_hrid[num]]
            return (f"[E{num}] {e.title} ({e.type}, 연결 {int(e.degree)})\n"
                    f"{_clip(e.description, _READ_MAX_CHARS)}\n근거 원문: {self._tu_refs(e.text_unit_ids, limit=10)}")
        if kind == "R" and num in self._rel_by_hrid.index:
            r = self._rel_by_hrid.loc[num]
            return (f"[R{num}] {r.source} ─ {r.target} (가중치 {r.weight:.0f})\n"
                    f"{r.description}\n근거 원문: {self._tu_refs(r.text_unit_ids, limit=10)}")
        if kind == "C" and num in self._report_by_hrid.index:
            c = self._report_by_hrid.loc[num]
            return f"[C{num}] level {c.level}, 중요도 {c['rank']}\n{_clip_block(c.full_content, _READ_MAX_CHARS)}"
        if kind == "T" and num in self._tu_by_hrid.index:
            return f"[T{num}] 원문 조각\n{_clip_block(self._tu_by_hrid.loc[num].text, _READ_MAX_CHARS)}"
        return f"[{kind}{num}] 해당 ID가 없습니다."


def _clip_block(text: str, limit: int) -> str:
    """줄바꿈을 유지한 채 길이만 자릅니다. (리포트·원문은 표와 목록 구조가 의미를 가짐)"""
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + "\n…(이하 생략)"


# ------------------------------------------------------------------------------
# 프로세스당 한 번만 로드해 재사용합니다.
# ------------------------------------------------------------------------------
_EXPLORERS: Dict[str, GraphExplorer] = {}
_EXPLORERS_LOCK = threading.Lock()


def get_graph_explorer(root_dir: Optional[str] = None) -> GraphExplorer:
    settings = load_graphrag_settings()
    abs_root = _resolve_root_dir(root_dir or os.path.join(PROJECT_ROOT, settings["root_dir"]))
    with _EXPLORERS_LOCK:
        if abs_root not in _EXPLORERS:
            _EXPLORERS[abs_root] = GraphExplorer(abs_root)
        return _EXPLORERS[abs_root]


def _safe(fn, *args, **kwargs) -> str:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        return f"[Graph Explorer Error]: {type(e).__name__}: {e}"


# ==============================================================================
# LangGraph / FastMCP 공용 에이전트 도구
# ==============================================================================

@tool
def graph_find_entities(
    query: Annotated[str, Field(description="찾을 인물·부서·프로젝트 이름이나 이를 담은 질문. 예: 'AgenticAI팀', '김철수 수석'")],
    top_k: Annotated[int, Field(description="반환할 엔티티 수", ge=1, le=10)] = 5,
) -> str:
    """
    전사 지식 그래프(조직도, 보고선·결재선, 전략 프로젝트 P-01~P-06)에서 질문 속 인물·부서·프로젝트에 해당하는 엔티티를 찾습니다.
    그래프 탐색의 시작점입니다. 그래프의 엔티티 이름은 영문(예: 'AGENTIC AI TEAM', 'KIM CHUL-SOO')이므로 한국어 이름도 이 도구로 먼저 연결하세요.

    반환 형태: 엔티티마다 한 줄씩 'E번호 이름 [유형, 연결 수, 유사도] — 설명 요약'을 반환합니다. E번호를 다른 graph_* 도구에 넘기세요.
    """
    return _safe(lambda: get_graph_explorer().find_entities(query, top_k))


@tool
def graph_neighbors(
    entity: Annotated[str, Field(description="펼칠 엔티티. 'E22' 같은 ID 또는 엔티티 이름")],
    query: Annotated[str, Field(description="알고 싶은 내용 (예: '예산과 승인권자'). 이와 가까운 이웃부터 보여줍니다")] = "",
    hops: Annotated[int, Field(description="1 = 직접 연결된 관계만, 2 = 이웃의 이웃까지", ge=1, le=2)] = 1,
    top_k: Annotated[int, Field(description="홉마다 반환할 관계 수", ge=1, le=30)] = 12,
) -> str:
    """
    지식 그래프에서 한 엔티티와 연결된 관계(소속, 보고, 담당, 승인, 의존 등)를 펼칩니다.
    '이 팀이 맡은 프로젝트', '이 프로젝트의 PM·승인권자·의존 프로젝트'처럼 한 대상에서 뻗어 나가는 질문에 사용하세요.
    여러 대상을 펼쳐야 하면 대상마다 이 도구를 한 턴에 병렬로 호출하세요.

    반환 형태: 관계마다 한 줄씩 'R번호 엔티티 ─ 엔티티 [가중치] 관계 설명 (근거 T번호)'를 반환하고,
    마지막 줄에 근거 원문 T번호를 모아 보여줍니다. 수치가 필요하면 그 T번호들을 graph_read 한 번으로 함께 읽으세요.
    """
    return _safe(lambda: get_graph_explorer().neighbors(entity, query, hops, top_k))


@tool
def graph_find_path(
    source: Annotated[str, Field(description="출발 엔티티 (ID 또는 이름)")],
    target: Annotated[str, Field(description="도착 엔티티 (ID 또는 이름)")],
    max_hops: Annotated[int, Field(description="허용할 최대 경로 길이", ge=1, le=6)] = 4,
) -> str:
    """
    지식 그래프에서 두 엔티티를 잇는 최단 연결 경로를 찾습니다.
    보고선(누가 누구에게 보고하는가), 결재 라인, 두 프로젝트·부서 사이의 연결 관계처럼 '둘 사이가 어떻게 이어지는가'를 묻는 질문에 사용하세요.

    반환 형태: 최단 경로 최대 3개와 각 경로를 이루는 관계(R번호, 관계 설명, 근거 T번호)를 반환합니다.
    """
    return _safe(lambda: get_graph_explorer().find_path(source, target, max_hops))


@tool
def graph_search_communities(
    query: Annotated[str, Field(description="알고 싶은 주제. 예: '전사 보안 거버넌스 리스크'")],
    top_k: Annotated[int, Field(description="반환할 리포트 수", ge=1, le=10)] = 3,
    level: Annotated[Optional[int], Field(description="리포트 계층. 0 = 큰 묶음(전사 개요), 1~2 = 세부. 생략하면 전체에서 검색")] = None,
) -> str:
    """
    GraphRAG가 인덱싱 때 만든 커뮤니티 리포트(관련 엔티티 묶음의 요약 보고서)를 검색합니다.
    특정 대상보다 '전사적으로 어떤 리스크·과제가 있나'처럼 넓은 주제를 개괄할 때 사용하세요.
    GraphRAG Global Search와 달리 리포트를 다시 요약하는 LLM 호출이 없어 빠릅니다.

    반환 형태: 리포트마다 'C번호 [계층, 중요도, 유사도] 제목'과 요약문을 반환합니다. 세부 발견 사항은 graph_read로 확인하세요.
    """
    return _safe(lambda: get_graph_explorer().search_communities(query, top_k, level))


@tool
def graph_read(
    ids: Annotated[List[str], Field(description="읽을 ID 목록 (최대 5개). 예: ['T3', 'R27', 'C13']")],
) -> str:
    """
    다른 graph_* 도구가 반환한 ID의 상세 내용을 읽습니다.
    E = 엔티티 전체 설명, R = 관계 전체 설명, C = 커뮤니티 리포트 본문, T = 원문 조각(예산·날짜·조항 등 원래 문서 그대로).
    답변에 쓸 수치나 인용 근거가 필요할 때 사용하세요.
    읽을 ID가 여러 개면 하나씩 따로 호출하지 말고 ids에 함께 넣어 한 번에 읽으세요 (최대 5개).

    반환 형태: ID마다 상세 내용 블록을 반환합니다. 블록 하나는 최대 약 3,500자입니다.
    """
    return _safe(lambda: get_graph_explorer().read(ids))


graph_explorer_tools = [
    graph_find_entities,
    graph_neighbors,
    graph_find_path,
    graph_search_communities,
    graph_read,
]
