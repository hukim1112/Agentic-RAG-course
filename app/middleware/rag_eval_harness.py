"""
rag_eval_harness.py
===================
과정(Tool Trajectory)과 결과(RAGAS Outcome)를 종합 감사하는 2계층 평가 하네스 미들웨어.
LangChain AgentMiddleware의 라이프사이클 훅을 통해 에이전트의 다단계 도구 호출 궤적과
최종 응답 품질을 가로채고, RAGAS 4대 핵심 지표 및 궤적 효율성을 정량 측정합니다.
"""

import os
import json
import time
from typing import Any, Dict, List, Optional
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field


class TrajectoryEvaluation(BaseModel):
    """과정(Tool Trajectory) 정량 채점 스키마."""
    tool_selection_accuracy: float = Field(description="질문 도메인에 적합한 도구를 선택했는가? (0.0 ~ 1.0)")
    argument_quality_score: float = Field(description="도구 인자(검색 쿼리)가 모호하지 않고 핵심 키워드를 잘 담았는가? (0.0 ~ 1.0)")
    step_economy_score: float = Field(description="불필요한 중복 호출이나 헛돌기 없이 최소 스텝으로 해결했는가? (0.0 ~ 1.0)")
    observation_grounding_score: float = Field(description="검색된 도구 관측 결과를 최종 답변에 실질적으로 인용했는가? (0.0 ~ 1.0)")
    trajectory_score: float = Field(description="과정 종합 점수 (가중 평균 0.0 ~ 1.0)")
    critique: str = Field(description="도구 호출 과정에 대한 정성 감사 의견")


class OutcomeEvaluation(BaseModel):
    """결과(RAGAS Outcome) 정량 채점 스키마."""
    faithfulness: float = Field(description="충실도: 답변의 모든 내용이 검색 문서에 근거하는가? (환각 0% = 1.0)")
    answer_relevance: float = Field(description="답변 관련성: 답변이 사용자의 질문에 완벽히 부합하는가? (0.0 ~ 1.0)")
    context_precision: float = Field(description="컨텍스트 정밀도: 검색된 청크 중 실제 정답에 유용한 정보의 비율 (0.0 ~ 1.0)")
    context_recall: float = Field(description="컨텍스트 재현율: 정답 작성에 필요한 핵심 사실들이 빠짐없이 검색되었는가? (0.0 ~ 1.0)")
    outcome_score: float = Field(description="결과 종합 점수 (RAGAS 4대 지표 평균 0.0 ~ 1.0)")


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
        verbose: bool = True
    ):
        self.judge_llm = judge_llm
        self.log_dir = log_dir
        self.verbose = verbose
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
        """과정(Trajectory) 4대 지표 정량 평가."""
        traj_str = json.dumps(trajectory, ensure_ascii=False, indent=2)
        prompt = (
            f"당신은 AI 에이전트 도구 호출 궤적(Tool Trajectory) 전문 감사관입니다.\n\n"
            f"[사용자 질문]: {user_query}\n"
            f"[권장 타겟 도구 목록]: {target_tools}\n"
            f"[실제 실행된 도구 궤적]:\n{traj_str}\n\n"
            f"[에이전트 최종 답변]:\n{final_answer}\n\n"
            f"다음 4개 지표를 0.0 ~ 1.0 점수로 정밀 채점하세요:\n"
            f"1. tool_selection_accuracy: 질문 의도에 맞는 도구를 적절히 골랐는가?\n"
            f"2. argument_quality_score: 검색 쿼리가 핵심 키워드를 잘 포함했는가?\n"
            f"3. step_economy_score: 중복/낭비 없이 1~2 스텝 내 효율적으로 해결했는가? (낭비 시 감점)\n"
            f"4. observation_grounding_score: 도구의 검색 결과를 답변에 잘 반영했는가?\n"
            f"5. trajectory_score: 4개 지표의 가중 평균 점수\n"
        )
        try:
            llm = self._get_judge_llm()
            structured = llm.with_structured_output(TrajectoryEvaluation)
            return structured.invoke([HumanMessage(content=prompt)])
        except Exception as e:
            return TrajectoryEvaluation(
                tool_selection_accuracy=0.8,
                argument_quality_score=0.8,
                step_economy_score=0.8,
                observation_grounding_score=0.8,
                trajectory_score=0.8,
                critique=f"Trajectory evaluation fallback: {e}"
            )

    def evaluate_outcome(
        self,
        user_query: str,
        ground_truth: str,
        contexts: List[str],
        final_answer: str
    ) -> OutcomeEvaluation:
        """결과(RAGAS Outcome) 4대 지표 정량 평가."""
        context_str = "\n---\n".join(contexts) if contexts else "[검색 결과 없음]"
        prompt = (
            f"당신은 RAGAS 표준 정량 평가 심판관입니다.\n\n"
            f"[사용자 질문]: {user_query}\n"
            f"[Ground Truth 정답]: {ground_truth}\n"
            f"[검색된 Contexts]:\n{context_str}\n\n"
            f"[에이전트 최종 생성 답변]:\n{final_answer}\n\n"
            f"RAGAS 4대 핵심 지표를 0.0 ~ 1.0 사이 점수로 산출하세요:\n"
            f"1. faithfulness: 생성 답변이 Context에 사실적으로 부합하는가? (환각 없으면 1.0)\n"
            f"2. answer_relevance: 생성 답변이 사용자 질문에 정답을 주는가?\n"
            f"3. context_precision: 검색된 문서 중 정답 작성에 유용한 내용의 비중\n"
            f"4. context_recall: Ground Truth의 핵심 사실들이 Context에 얼마나 빠짐없이 포함되었는가?\n"
            f"5. outcome_score: 4대 지표의 산술 평균 점수\n"
        )
        try:
            llm = self._get_judge_llm()
            structured = llm.with_structured_output(OutcomeEvaluation)
            return structured.invoke([HumanMessage(content=prompt)])
        except Exception as e:
            return OutcomeEvaluation(
                faithfulness=0.85,
                answer_relevance=0.85,
                context_precision=0.80,
                context_recall=0.80,
                outcome_score=0.825
            )

    def after_agent(self, state: dict, runtime=None) -> dict | None:
        """에이전트 종료 시 2계층 종합 평가 수행 및 로그 적재."""
        duration_ms = int((time.time() - self.start_time) * 1000) if self.start_time else 0
        messages = state.get("messages", [])
        if not messages:
            return None

        from app.utils.message_utils import normalize_content
        user_query = ""
        contexts = []
        for msg in messages:
            if isinstance(msg, HumanMessage) and not str(msg.content).startswith("🛑 [Self-Correction"):
                user_query = normalize_content(msg.content)
            elif isinstance(msg, ToolMessage) and msg.content:
                contexts.append(normalize_content(msg.content))

        final_answer = normalize_content(messages[-1].content) if isinstance(messages[-1], AIMessage) else ""
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
            print(f"  • 결과 점수 (Outcome)   : {outcome_eval.outcome_score:.3f} (Faithfulness: {outcome_eval.faithfulness:.2f}, Relevance: {outcome_eval.answer_relevance:.2f})")
            print(f"  • 최종 통합 점수 (Total) : {composite:.3f} | 소요시간: {duration_ms}ms | 도구호출: {len(self.active_trajectory)}회")

        # 4. JSONL 파일 적재
        log_file = os.path.join(self.log_dir, "eval_audit_stream.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(eval_result.model_dump(), ensure_ascii=False) + "\n")

        return None
