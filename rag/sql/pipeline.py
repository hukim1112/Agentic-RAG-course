"""
Text2SQL 워크플로우 (LangGraph)

메인 에이전트는 자연어 질의만 넘기고, 이 워크플로우가 담당 DB 1개의 메타정보를 이용해
SQL 작성부터 실행·수정까지 책임집니다. 메인 에이전트는 스키마를 알 필요가 없습니다.

    START
      │
      ▼
    retrieve_schema   스키마 검색: 약어 정규화 → BM25+Dense → RRF → FK 확장
      │
      ▼
    link_values       값 연결: 질문 속 표현 → DB 실제 값 (값이 있는 테이블이 빠졌으면 스키마에 보강)
      │
      ▼
    generate_sql  ◀──────────────┐   SQL 생성 (DB 개요 + 관련 카드 + 값 연결 + 참고 기준값)
      │                          │
      ├─ 되묻기 필요 → END        │
      ▼                          │
    execute_sql ── 오류/0행 ─────┘   읽기 전용 실행. 실패하면 오류 메시지를 들고 재생성 (최대 max_attempts)
      │
      ▼
    END → Text2SQLResult (status, 결과 표, 실행 SQL, 적용 가정, 되묻기 후보)

최종 자연어 답변은 만들지 않습니다. 결과 표를 받은 메인 에이전트가 다른 도구 결과와 함께 답을 씁니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional, TypedDict

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from rag.sql.executor import ExecutionResult, run_readonly_query
from rag.sql.schema_retriever import SchemaRetriever
from rag.sql.semantic_layer import DatabaseProfile
from rag.sql.value_linker import ValueLinker
from rag.vector.retrieval import DomainDictionary

SQL_SYSTEM_PROMPT = """당신은 '{title}' 전용 Text2SQL 엔진입니다. 사용자 질문을 {dialect} SELECT 문 1개로 변환합니다.
오늘 날짜는 {today}입니다.

[스키마와 값]
1. [DB 개요]와 [관련 스키마]에 있는 테이블·컬럼만 사용하세요. 없는 컬럼을 지어내지 마세요.
2. 문자열 조건 값은 [허용값]과 [질문 속 값 연결]에 나온 DB 실제 값을 글자 그대로 쓰세요.
3. [관련 스키마]에 지표가 정의되어 있으면 그 SQL 식을 그대로 사용하세요.
4. "올해", "이번 달", "최근 3개월" 같은 상대적 기간은 오늘 날짜를 기준으로 계산하세요.

[조회 컬럼]
5. SELECT *는 쓰지 말고, 질문에 답하는 데 필요한 컬럼만 조회하세요.
6. 사람은 이름과 직급을, 부서·프로젝트는 코드와 이름을 함께 조회해 결과만 보고도 누구/무엇인지 알 수 있게 하세요.
7. 계산한 컬럼에는 의미가 드러나는 별칭(AS)을 붙이세요.

[결과 개수와 정렬]
8. 사용자가 개수를 지정했으면("상위 3개", "가장 큰 1건") 그 개수만큼 LIMIT을 거세요.
   지정하지 않았다면 LIMIT을 쓰지 마세요. 실행기가 최대 {max_rows}행까지만 돌려주고, 잘린 경우 전체 행 수를 함께 알립니다.
9. 목록 조회는 질문 의도에 맞는 기준으로 ORDER BY 하세요 (예: 금액·비율은 큰 순, 날짜는 최신 순, 그 외에는 코드 순).

[정확성]
10. 집계(SUM, COUNT, AVG)에 필요 없는 1:N 테이블은 JOIN하지 마세요. 행이 복제되어 합계가 부풀어 오릅니다.
11. 나눗셈의 분모가 0일 수 있으면 NULLIF(분모, 0)을 쓰고, NULL이 섞인 합계는 COALESCE로 0을 보완하세요.

[참고 기준값과 해석]
12. [참고 기준값]은 사내 규정 등 DB 밖에서 확인된 조건입니다. DB에 없는 기준값은 CASE WHEN 등으로 SQL에 직접 반영하세요.
13. 해석이 갈리면 공통 규칙의 기본 해석을 따르고, 선택한 해석을 assumptions에 한 줄씩 적으세요.
14. 기본 해석으로도 정할 수 없고 해석에 따라 결과가 크게 달라질 때만 needs_clarification을 true로 두고,
    사용자에게 물을 질문(clarification_question)과 선택지(candidates)를 채우세요. 이때 sql은 비워 둡니다.

[DB 개요]
{overview}

[관련 스키마]
{schema_context}"""


class SQLDraft(BaseModel):
    """SQL 생성 단계의 구조화된 출력"""

    sql: str = Field(default="", description="실행할 단일 SELECT 문. 되묻기가 필요하면 빈 문자열")
    assumptions: List[str] = Field(default_factory=list, description="질문 해석에 적용한 가정 (예: '승인완료 건만 집계')")
    needs_clarification: bool = Field(default=False, description="사용자에게 되물어야만 SQL을 정할 수 있으면 true")
    clarification_question: str = Field(default="", description="사용자에게 물을 질문")
    candidates: List[str] = Field(default_factory=list, description="사용자가 고를 수 있는 해석 후보")


class Text2SQLState(TypedDict, total=False):
    question: str
    context: str
    normalized_question: str
    selected_tables: List[str]
    selected_metrics: List[str]
    schema_context: str
    value_hints: str
    draft: SQLDraft
    result: ExecutionResult
    feedback: str
    attempts: int
    empty_checked: bool


@dataclass
class Text2SQLResult:
    """메인 에이전트에게 돌려줄 결과 계약. DB가 늘어나도 모든 Text2SQL 도구가 이 형식을 따릅니다."""

    status: str  # "ok" | "needs_clarification" | "error"
    question: str
    sql: str = ""
    assumptions: List[str] = field(default_factory=list)
    result: Optional[ExecutionResult] = None
    clarification_question: str = ""
    candidates: List[str] = field(default_factory=list)
    error: str = ""
    selected_tables: List[str] = field(default_factory=list)
    attempts: int = 0

    def to_text(self) -> str:
        """도구 반환용 텍스트"""
        if self.status == "needs_clarification":
            lines = [f"[status: needs_clarification] {self.clarification_question}"]
            lines += [f"- 후보: {c}" for c in self.candidates]
            return "\n".join(lines)

        lines = [f"[status: {self.status}]"]
        if self.sql:
            lines += ["실행 SQL:", "```sql", self.sql, "```"]
        if self.assumptions:
            lines.append("적용한 가정:")
            lines += [f"- {a}" for a in self.assumptions]
        if self.status == "error":
            lines.append(f"오류: {self.error}")
        elif self.result is not None:
            lines += [f"결과 ({self.result.summary()}):", self.result.to_markdown()]
        return "\n".join(lines)


class Text2SQL:
    """DB 1개를 담당하는 Text2SQL 워크플로우.

    사용 예:
        profile = DatabaseProfile.load("data/enterprise_erp_sql/semantic_layer.yaml")
        text2sql = Text2SQL(profile, llm=init_chat_model(...), embeddings=OpenAIEmbeddings(...))
        print(text2sql.invoke("클운팀 결재대기 출장 품의 목록").to_text())
    """

    def __init__(
        self,
        profile: DatabaseProfile,
        llm: BaseChatModel,
        embeddings: Optional[Embeddings] = None,
        domain_dict: Optional[DomainDictionary] = None,
        top_k: int = 3,
        max_attempts: int = 3,
        max_rows: int = 50,
    ):
        domain_dict = domain_dict or DomainDictionary(profile.synonyms)
        self.profile = profile
        self.schema_retriever = SchemaRetriever(profile, embeddings=embeddings, domain_dict=domain_dict)
        self.value_linker = ValueLinker(profile, domain_dict=domain_dict)
        self.sql_llm = llm.with_structured_output(SQLDraft)
        self.top_k = top_k
        self.max_attempts = max_attempts
        self.max_rows = max_rows
        self.graph = self._build_graph()

    @classmethod
    def from_semantic_layer(
        cls,
        semantic_layer_path: str | Path,
        llm: BaseChatModel,
        db_path: Optional[str | Path] = None,
        **kwargs,
    ) -> "Text2SQL":
        return cls(DatabaseProfile.load(semantic_layer_path, db_path=db_path), llm, **kwargs)

    def invoke(self, question: str, context: str = "") -> Text2SQLResult:
        state = self.graph.invoke({"question": question, "context": context, "attempts": 0})
        return self._to_result(state)

    async def ainvoke(self, question: str, context: str = "") -> Text2SQLResult:
        state = await self.graph.ainvoke({"question": question, "context": context, "attempts": 0})
        return self._to_result(state)

    # ------------------------------------------------------------------ 노드
    def _retrieve_schema(self, state: Text2SQLState) -> dict:
        found = self.schema_retriever.search(state["question"], top_k=self.top_k)
        return {
            "normalized_question": found.normalized_query,
            "selected_tables": found.tables,
            "selected_metrics": found.metrics,
            "schema_context": found.context,
        }

    def _link_values(self, state: Text2SQLState) -> dict:
        matches = self.value_linker.link(state["question"])
        update = {"value_hints": ValueLinker.render(matches)}

        # "클운팀"처럼 값으로만 드러나는 테이블(departments)은 스키마 검색에서 빠질 수 있으므로 보강합니다.
        tables = list(state["selected_tables"])
        value_tables = [col.split(".")[0] for m in matches for col in m.columns]
        missing = [t for t in dict.fromkeys(value_tables) if t not in tables]
        if missing:
            tables += [t for t in self.schema_retriever.expand(missing) if t not in tables]
            update["selected_tables"] = tables
            update["schema_context"] = self.schema_retriever.render(tables, state["selected_metrics"])
        return update

    def _generate_sql(self, state: Text2SQLState) -> dict:
        system = (
            SQL_SYSTEM_PROMPT.replace("{title}", self.profile.title)
            .replace("{dialect}", self.profile.dialect)
            .replace("{today}", date.today().isoformat())
            .replace("{max_rows}", str(self.max_rows))
            .replace("{overview}", self.profile.overview())
            .replace("{schema_context}", state["schema_context"])
        )
        parts = [
            f"질문: {state['question']}",
            f"[참고 기준값]\n{state.get('context') or '(없음)'}",
            f"[질문 속 값 연결]\n{state['value_hints']}",
        ]
        if state.get("feedback"):
            parts.append(f"[이전 시도 피드백]\n{state['feedback']}")
        draft = self.sql_llm.invoke([SystemMessage(system), HumanMessage("\n\n".join(parts))])
        return {"draft": draft, "attempts": state.get("attempts", 0) + 1}

    def _execute_sql(self, state: Text2SQLState) -> dict:
        sql = state["draft"].sql
        result = run_readonly_query(self.profile.db_path, sql, max_rows=self.max_rows)
        if not result.ok:
            feedback = f"이전 SQL:\n{sql}\n문제: {result.error}\n오류를 고친 SQL을 다시 작성하세요."
            return {"result": result, "feedback": feedback}
        if result.row_count == 0 and not state.get("empty_checked"):
            feedback = (
                f"이전 SQL:\n{sql}\n문제: 결과가 0행입니다. WHERE 조건 값이 [허용값]·[질문 속 값 연결]의 "
                "DB 실제 값과 글자 그대로 일치하는지 확인하세요. 0행이 맞는 답이라고 판단되면 같은 SQL을 다시 반환하세요."
            )
            return {"result": result, "feedback": feedback, "empty_checked": True}
        return {"result": result, "feedback": ""}

    # ------------------------------------------------------------------ 분기
    def _after_generate(self, state: Text2SQLState) -> str:
        return END if state["draft"].needs_clarification else "execute_sql"

    def _after_execute(self, state: Text2SQLState) -> str:
        if state.get("feedback") and state["attempts"] < self.max_attempts:
            return "generate_sql"
        return END

    def _build_graph(self):
        builder = StateGraph(Text2SQLState)
        builder.add_node("retrieve_schema", self._retrieve_schema)
        builder.add_node("link_values", self._link_values)
        builder.add_node("generate_sql", self._generate_sql)
        builder.add_node("execute_sql", self._execute_sql)
        builder.add_edge(START, "retrieve_schema")
        builder.add_edge("retrieve_schema", "link_values")
        builder.add_edge("link_values", "generate_sql")
        builder.add_conditional_edges("generate_sql", self._after_generate, ["execute_sql", END])
        builder.add_conditional_edges("execute_sql", self._after_execute, ["generate_sql", END])
        return builder.compile()

    def _to_result(self, state: Text2SQLState) -> Text2SQLResult:
        draft: SQLDraft = state["draft"]
        common = dict(
            question=state["question"],
            assumptions=draft.assumptions,
            selected_tables=state.get("selected_tables", []),
            attempts=state.get("attempts", 0),
        )
        if draft.needs_clarification:
            return Text2SQLResult(
                status="needs_clarification",
                clarification_question=draft.clarification_question,
                candidates=draft.candidates,
                **common,
            )
        result: ExecutionResult = state["result"]
        if not result.ok:
            return Text2SQLResult(status="error", sql=draft.sql, error=result.error, result=result, **common)
        return Text2SQLResult(status="ok", sql=draft.sql, result=result, **common)
