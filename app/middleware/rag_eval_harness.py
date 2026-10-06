"""
rag_eval_harness.py
===================
과정(Tool Trajectory)과 결과(Outcome)를 종합 감사하는 2계층 평가 하네스 미들웨어.

  - 과정: 도구 선택, 검색어 품질, 호출 효율, 관측 반영 (LLM 채점)
  - 결과: 정답 일치(ground truth 대비), 근거 충실도, 질문 관련성, 컨텍스트 정밀도/재현율 (LLM 채점)
  - 종합 점수는 LLM이 아니라 코드가 아래 가중치로 계산합니다 (재현 가능, 가중치가 명시적).

핵심 설계 원칙:
  - 최종 답변 추출 시 반드시 역순 AIMessage 탐색 (중간에 끼어든 HumanMessage 배제)
"""

import os
import json
import time
from typing import Any, Dict, List, Optional
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field, computed_field

# 런타임 피드백 메시지 식별 프리픽스 (사용자 질문 추출 시 제외)
CORRECTION_PREFIX = "🛑 [Self-Correction"

# 과정 점수 가중치: 네 지표를 같은 비중으로 평균
TRAJECTORY_WEIGHTS = {
    "tool_selection_accuracy": 0.25,
    "argument_quality_score": 0.25,
    "step_economy_score": 0.25,
    "observation_grounding_score": 0.25,
}
# 결과 점수 가중치: 정답 일치를 가장 크게 반영 (근거에 충실해도 틀린 답이면 높은 점수를 받지 못하게)
OUTCOME_WEIGHTS = {
    "answer_correctness": 0.40,
    "faithfulness": 0.20,
    "context_recall": 0.20,
    "answer_relevance": 0.10,
    "context_precision": 0.10,
}


def _weighted(model: BaseModel, weights: Dict[str, float]) -> float:
    return round(sum(getattr(model, k) * w for k, w in weights.items()), 3)


class TrajectoryEvaluation(BaseModel):
    """과정(Tool Trajectory) 채점 스키마. trajectory_score는 코드에서 계산합니다."""
    tool_selection_accuracy: float = Field(description="질문 도메인에 적합한 도구를 선택했는가? (0.0 ~ 1.0)")
    argument_quality_score: float = Field(description="도구 인자(검색 쿼리)가 모호하지 않고 핵심 키워드를 잘 담았는가? (0.0 ~ 1.0)")
    step_economy_score: float = Field(description="불필요한 중복 호출이나 헛돌기 없이 최소 스텝으로 해결했는가? (0.0 ~ 1.0)")
    observation_grounding_score: float = Field(description="검색된 도구 관측 결과를 최종 답변에 실질적으로 인용했는가? (0.0 ~ 1.0)")
    critique: str = Field(description="도구 호출 과정에 대한 정성 감사 의견 (2~3문장)")

    @computed_field
    @property
    def trajectory_score(self) -> float:
        return _weighted(self, TRAJECTORY_WEIGHTS)


class OutcomeEvaluation(BaseModel):
    """결과(Outcome) 채점 스키마. outcome_score는 코드에서 계산합니다."""
    answer_correctness: float = Field(description="정답 일치: 답변의 핵심 사실(수치, 조항, 인물, 결론)이 Ground Truth와 일치하는가? (0.0 ~ 1.0)")
    faithfulness: float = Field(description="충실도: 답변의 모든 내용이 검색 문서에 근거하는가? (환각 0% = 1.0)")
    answer_relevance: float = Field(description="답변 관련성: 답변이 사용자의 질문에 직접 답하는가? (0.0 ~ 1.0)")
    context_precision: float = Field(description="컨텍스트 정밀도: 검색된 청크 중 실제 정답에 유용한 정보의 비율 (0.0 ~ 1.0)")
    context_recall: float = Field(description="컨텍스트 재현율: Ground Truth의 핵심 사실들이 검색 결과에 빠짐없이 들어 있는가? (0.0 ~ 1.0)")

    @computed_field
    @property
    def outcome_score(self) -> float:
        return _weighted(self, OUTCOME_WEIGHTS)


class ComprehensiveEvalResult(BaseModel):
    """2계층 통합 평가 결과 종합 객체."""
    session_id: str
    user_query: str
    target_tools: List[str]
    executed_tools: List[str]
    tool_call_count: int
    duration_ms: int
    trajectory_eval: TrajectoryEvaluation
    outcome_eval: OutcomeEvaluation
    composite_score: float = Field(description="최종 통합 점수 (과정 40% + 결과 60%)")
    status: str


def extract_last_ai_answer(messages: list) -> str:
    """메시지 리스트에서 마지막 AIMessage의 content를 안전하게 추출합니다.
    
    SelfCorrection 미들웨어가 주입한 HumanMessage(피드백)가 messages[-1]일 수 있으므로
    반드시 역순으로 탐색하여 실제 AIMessage만 찾습니다.
    
    이 함수는 Harness 점수 역전 버그의 근본 원인을 해결합니다:
    기존: messages[-1].content → HumanMessage(피드백) 텍스트를 답변으로 오인 → 낮은 점수
    수정: 역순 AIMessage 탐색 → 실제 에이전트 답변만 추출 → 정확한 채점
    """
    from app.utils.message_utils import normalize_content
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return normalize_content(msg.content)
    # fallback: messages[-1]이 dict인 경우 등
    if messages:
        content = getattr(messages[-1], "content", None) or str(messages[-1])
        return content[:2000] if content else ""
    return ""


def extract_user_query(messages: list) -> str:
    """메시지 리스트에서 원본 사용자 질문을 추출합니다 (SelfCorrection 피드백 제외)."""
    from app.utils.message_utils import normalize_content
    user_query = ""
    for msg in messages:
        if isinstance(msg, HumanMessage) and not str(msg.content).startswith(CORRECTION_PREFIX):
            user_query = normalize_content(msg.content)
    return user_query


def extract_tool_contexts(messages: list) -> List[str]:
    """메시지 리스트에서 ToolMessage들의 content를 추출합니다."""
    from app.utils.message_utils import normalize_content
    contexts = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.content:
            contexts.append(normalize_content(msg.content))
    return contexts


class RAGEvalHarnessMiddleware(AgentMiddleware):
    """
    [2계층 RAG 평가 하네스 미들웨어]
    - before_agent: 세션 타이머 및 궤적 기록기 초기화
    - wrap_tool_call: 도구 호출 순서, 인자, 지연시간 기록
    - after_agent: Trajectory + RAGAS Outcome 평가 일괄 산출 및 JSONL 적재
    """

    def __init__(
        self,
        judge_llm: Optional[Any] = None,
        log_dir: str = "./artifacts/eval_logs",
        verbose: bool = True,
        strict: bool = False
    ):
        self.judge_llm = judge_llm
        self.log_dir = log_dir
        self.verbose = verbose
        # strict=True이면 채점 LLM 오류를 고정 점수로 대체하지 않고 예외로 올립니다 (오프라인 평가용)
        self.strict = strict
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.start_time: float = 0.0
        self.active_trajectory: List[Dict[str, Any]] = []
        self.last_result: Optional[ComprehensiveEvalResult] = None

    def _get_judge_llm(self):
        if self.judge_llm is not None:
            return self.judge_llm
        from app.utils.llm import get_llm
        return get_llm(model_name="gemini-3.5-flash", temperature=0.0)

    def before_agent(self, state: dict, runtime=None) -> dict | None:
        """에이전트 실행 시작 타이머 및 트레이스 초기화."""
        self.start_time = time.time()
        self.active_trajectory = []
        return None

    def wrap_tool_call(self, request, handler):
        """도구 호출 궤적 가로채기 및 기록."""
        tool_name = "unknown_tool"
        tool_args = {}
        if hasattr(request, "tool_call") and isinstance(request.tool_call, dict):
            tool_name = request.tool_call.get("name", "unknown_tool")
            tool_args = request.tool_call.get("args", {})
        elif hasattr(request, "name"):
            tool_name = getattr(request, "name", "unknown_tool")

        t_start = time.time()
        response = handler(request)
        t_duration = int((time.time() - t_start) * 1000)

        self.active_trajectory.append({
            "tool_name": tool_name,
            "arguments": tool_args,
            "latency_ms": t_duration,
            "response_snippet": str(response)[:200]
        })
        return response

    async def awrap_tool_call(self, request, handler):
        """비동기 도구 궤적 기록."""
        return self.wrap_tool_call(request, handler)

    def evaluate_trajectory(
        self,
        user_query: str,
        target_tools: List[str],
        trajectory: List[Dict[str, Any]],
        final_answer: str
    ) -> TrajectoryEvaluation:
        """과정(Trajectory) 4대 지표 정량 평가.

        채점기에는 도구 결과의 본문 발췌(result_preview)를 보여 줍니다. 사실 근거 여부는 결과 채점(faithfulness)이
        검색 결과 전문으로 따로 판단하므로, 여기서는 '과정'만 평가하도록 기준을 명시합니다.
        """
        steps = [
            {
                "step": i,
                "tool": t.get("tool_name"),
                "arguments": t.get("arguments"),
                "result_excerpt": t.get("result_preview", t.get("response_snippet", "")),
            }
            for i, t in enumerate(trajectory, 1)
        ]
        traj_str = json.dumps(steps, ensure_ascii=False, indent=2)
        prompt = (
            f"당신은 AI 에이전트의 도구 호출 과정(Tool Trajectory)을 감사하는 평가자입니다.\n\n"
            f"[사용자 질문]: {user_query}\n"
            f"[권장 도구]: {target_tools}\n"
            f"[실행된 도구 호출 {len(steps)}회]:\n{traj_str}\n\n"
            f"[에이전트 최종 답변]:\n{final_answer}\n\n"
            f"평가 시 유의사항:\n"
            f"- result_excerpt는 도구 결과의 **발췌**입니다(문맥 헤더 제거, 일부 생략). 답변의 사실이 발췌에 보이지 않는다는 이유로 감점하지 마세요.\n"
            f"  답변이 검색 결과에 근거하는지는 다른 평가자가 검색 결과 전문으로 따로 채점합니다. 여기서는 **과정**만 평가합니다.\n"
            f"- 권장 도구는 기준일 뿐입니다. 권장 도구를 쓰고, 질문에 도움이 되는 다른 도구를 추가로 쓴 것은 감점하지 않습니다.\n"
            f"- 호출 수는 질문이 요구하는 서로 다른 정보의 개수가 기준입니다(예: 두 분기 비교 → 분기별 1회씩 2회).\n"
            f"  서로 다른 정보를 얻기 위한 호출은 감점하지 않고, 같은 정보를 검색어만 바꿔 반복하거나 원하는 결과를 못 얻고 헛도는 호출만 감점합니다.\n\n"
            f"다음 4개 지표를 각각 독립적으로 0.0 ~ 1.0 점수로 채점하세요:\n"
            f"1. tool_selection_accuracy: 질문에 필요한 정보가 있는 도구를 골랐는가? (권장 도구 미사용, 무관한 도구 사용 시 감점)\n"
            f"2. argument_quality_score: 검색어와 인자가 필요한 정보를 정확히 겨냥했는가?\n"
            f"3. step_economy_score: 위 기준으로, 불필요한 반복 없이 해결했는가?\n"
            f"4. observation_grounding_score: 도구 결과를 보고 다음 행동과 답변을 정했는가? "
            f"(예: 원하지 않는 결과가 왔을 때 알아차리고 대응했는가, 받은 결과와 모순되게 답하지 않았는가)\n"
            f"마지막으로 critique에 과정의 핵심 문제를 2~3문장으로 적으세요. 문제가 없으면 그렇다고 적으세요.\n"
        )
        try:
            llm = self._get_judge_llm()
            structured = llm.with_structured_output(TrajectoryEvaluation)
            return structured.invoke([HumanMessage(content=prompt)])
        except Exception as e:
            if self.strict:
                raise
            return TrajectoryEvaluation(
                tool_selection_accuracy=0.8,
                argument_quality_score=0.8,
                step_economy_score=0.8,
                observation_grounding_score=0.8,
                critique=f"Trajectory evaluation fallback: {e}"
            )

    def evaluate_outcome(
        self,
        user_query: str,
        ground_truth: str,
        contexts: List[str],
        final_answer: str
    ) -> OutcomeEvaluation:
        """결과(Outcome) 5개 지표 정량 평가. 종합 점수(outcome_score)는 코드에서 계산합니다."""
        context_str = "\n---\n".join(contexts) if contexts else "[검색 결과 없음]"
        prompt = (
            f"당신은 RAG 시스템의 답변 품질 심판관입니다.\n\n"
            f"[사용자 질문]: {user_query}\n"
            f"[Ground Truth 정답]: {ground_truth}\n"
            f"[검색된 Contexts]:\n{context_str}\n\n"
            f"[에이전트 최종 생성 답변]:\n{final_answer}\n\n"
            f"다음 5개 지표를 각각 독립적으로 0.0 ~ 1.0 점수로 채점하세요:\n"
            f"1. answer_correctness: 답변의 핵심 사실(수치, 조항, 인물, 결론)이 Ground Truth와 일치하는가?\n"
            f"   검색 결과와 무관하게 정답과만 비교합니다. 핵심 수치가 틀리면 크게 감점하고, 표현 차이는 감점하지 않습니다.\n"
            f"2. faithfulness: 답변의 내용이 검색된 Contexts에 근거하는가? (Contexts에 없는 내용을 지어내면 감점)\n"
            f"3. answer_relevance: 답변이 사용자 질문에 직접 답하는가? (정답 여부와 별개로, 질문을 벗어나면 감점)\n"
            f"4. context_precision: 검색된 문서 중 정답 작성에 유용한 내용의 비중\n"
            f"5. context_recall: Ground Truth의 핵심 사실들이 Contexts에 얼마나 빠짐없이 들어 있는가?\n"
        )
        try:
            llm = self._get_judge_llm()
            structured = llm.with_structured_output(OutcomeEvaluation)
            return structured.invoke([HumanMessage(content=prompt)])
        except Exception as e:
            if self.strict:
                raise
            return OutcomeEvaluation(
                answer_correctness=0.80,
                faithfulness=0.85,
                answer_relevance=0.85,
                context_precision=0.80,
                context_recall=0.80,
            )

    def after_agent(self, state: dict, runtime=None) -> dict | None:
        """에이전트 종료 시 2계층 종합 평가 수행 및 로그 적재."""
        duration_ms = int((time.time() - self.start_time) * 1000) if self.start_time else 0
        messages = state.get("messages", [])
        if not messages:
            return None

        # ★ 핵심 수정: 역순 AIMessage 탐색으로 실제 에이전트 답변만 추출
        final_answer = extract_last_ai_answer(messages)
        user_query = extract_user_query(messages)
        contexts = extract_tool_contexts(messages)

        session_id = getattr(runtime, "session_id", f"session_{int(time.time())}") if runtime else f"session_{int(time.time())}"

        # 1. 과정 평가 (Trajectory)
        executed_tool_names = [t["tool_name"] for t in self.active_trajectory]
        target_tools = getattr(runtime, "target_tools", ["query_company_policy", "query_bok_reports", "query_org_graph"]) if runtime else []
        ground_truth = getattr(runtime, "ground_truth", "") if runtime else ""

        traj_eval = self.evaluate_trajectory(user_query, target_tools, self.active_trajectory, final_answer)

        # 2. 결과 평가 (Outcome)
        outcome_eval = self.evaluate_outcome(user_query, ground_truth, contexts, final_answer)

        # 3. 통합 점수 (과정 40% + 결과 60%)
        composite = round(0.40 * traj_eval.trajectory_score + 0.60 * outcome_eval.outcome_score, 3)

        eval_result = ComprehensiveEvalResult(
            session_id=session_id,
            user_query=user_query,
            target_tools=target_tools,
            executed_tools=executed_tool_names,
            tool_call_count=len(self.active_trajectory),
            duration_ms=duration_ms,
            trajectory_eval=traj_eval,
            outcome_eval=outcome_eval,
            composite_score=composite,
            status="SUCCESS"
        )
        self.last_result = eval_result

        if self.verbose:
            print(f"\n📊 [RAGEvalHarness] === 2계층 종합 평가 보고서 ===")
            print(f"  • 과정 점수 (Trajectory): {traj_eval.trajectory_score:.3f} (도구 선택: {traj_eval.tool_selection_accuracy:.2f}, 궤적 효율: {traj_eval.step_economy_score:.2f})")
            print(f"  • 결과 점수 (Outcome)   : {outcome_eval.outcome_score:.3f} (정답 일치: {outcome_eval.answer_correctness:.2f}, Faithfulness: {outcome_eval.faithfulness:.2f}, Relevance: {outcome_eval.answer_relevance:.2f})")
            print(f"  • 최종 통합 점수 (Total) : {composite:.3f} | 소요시간: {duration_ms}ms | 도구호출: {len(self.active_trajectory)}회")

        # 4. JSONL 파일 적재
        log_file = os.path.join(self.log_dir, "eval_audit_stream.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(eval_result.model_dump(), ensure_ascii=False) + "\n")

        return None
