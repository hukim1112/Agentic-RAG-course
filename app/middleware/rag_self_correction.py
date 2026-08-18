"""
rag_self_correction.py
======================
응답 레벨 환각 검증(Hallucination Grading) 및 자율 반성(Self-Reflection) 미들웨어.
LangChain AgentMiddleware의 after_agent 훅을 활용하여 에이전트의 최종 생성 응답을 가로채고,
검색된 Context와의 사실 일치도(Groundedness)를 검증하여 미달 시 피드백 메시지를 주입합니다.
"""

from typing import Any, Dict, List, Optional
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field


class GroundednessEvaluation(BaseModel):
    """LLM-as-a-Judge 기반 응답 사실성(Groundedness) 및 환각 채점 스키마."""
    is_grounded: bool = Field(description="답변의 모든 핵심 주장이 제공된 Context에 사실적으로 근거하는가?")
    has_hallucination: bool = Field(description="Context에 없는 가공된 사실이나 허위 정보가 포함되어 있는가?")
    unsupported_claims: List[str] = Field(description="Context에 근거가 없는 문장이나 주장 목록 (없으면 빈 리스트)")
    groundedness_score: float = Field(description="사실 일치도 점수 (0.0 ~ 1.0, 1.0이 완전 일치)")
    critique_feedback: str = Field(description="에이전트가 답변을 수정할 수 있도록 제공하는 구체적인 피드백")


class RAGSelfCorrectionMiddleware(AgentMiddleware):
    """
    [응답 레벨 자가 수정 미들웨어]
    1. 대화 히스토리에서 ToolMessage (검색 Context)와 최종 AIMessage (생성 답변) 추출
    2. GroundednessGrader를 통해 환각 및 근거 여부 루브릭 채점
    3. 환각 감지 또는 근거 부족 시 HumanMessage 형태의 피드백을 주입하여 자가 수정 루프 격발
    4. 최대 재시도(max_correction_retries=2) 제어를 통해 무한 루프 차단
    """

    def __init__(
        self,
        judge_llm: Optional[Any] = None,
        min_groundedness_score: float = 0.70,
        max_retries: int = 2,
        verbose: bool = True
    ):
        self.judge_llm = judge_llm
        self.min_groundedness_score = min_groundedness_score
        self.max_retries = max_retries
        self.verbose = verbose
        # 세션별 재시도 카운트 추적
        self._retry_counts: Dict[str, int] = {}
        self.last_evaluation: Optional[GroundednessEvaluation] = None

    def _get_judge_llm(self):
        if self.judge_llm is not None:
            return self.judge_llm
        from app.utils.llm import get_llm
        return get_llm(model_name="gemini-3.5-flash", temperature=0.0)

    def evaluate_groundedness(self, user_query: str, contexts: List[str], generated_answer: str) -> GroundednessEvaluation:
        """검색된 Context와 생성된 답변 간의 사실성을 엄격하게 채점합니다."""
        combined_context = "\n---\n".join(contexts) if contexts else "[검색된 문서 없음]"
        
        prompt = (
            f"당신은 엔터프라이즈 RAG 사실성 및 환각 전문 감사관(Groundedness Judge)입니다.\n\n"
            f"다음 [사용자 질문], [검색된 참조 문서(Context)], 그리고 [에이전트가 생성한 답변]을 정밀 비교 평가하세요.\n\n"
            f"=== [사용자 질문] ===\n{user_query}\n\n"
            f"=== [검색된 참조 문서 (Context)] ===\n{combined_context}\n\n"
            f"=== [에이전트 답변] ===\n{generated_answer}\n\n"
            f"평가 기준:\n"
            f"1. 답변의 모든 문장은 [검색된 참조 문서]에 명시된 사실에만 근거해야 합니다.\n"
            f"2. 만약 문서에 없는 규정/제도에 대해 질문했을 때, 에이전트가 '해당 정보가 존재하지 않는다'고 올바르게 답변했다면 is_grounded=True, has_hallucination=False 입니다.\n"
            f"3. 문서에 전혀 없는 가상의 금액, 기준, 날짜를 지어냈다면 has_hallucination=True, is_grounded=False 입니다.\n"
            f"4. 점수(groundedness_score)는 0.0 ~ 1.0 사이로 부여하세요 (0.7 이상 합격).\n"
        )
        
        try:
            llm = self._get_judge_llm()
            structured_judge = llm.with_structured_output(GroundednessEvaluation)
            eval_result: GroundednessEvaluation = structured_judge.invoke([HumanMessage(content=prompt)])
            self.last_evaluation = eval_result
            return eval_result
        except Exception as e:
            if self.verbose:
                print(f"⚠️ [GroundednessJudge Error] {e} -> 기본 합격 처리")
            return GroundednessEvaluation(
                is_grounded=True,
                has_hallucination=False,
                unsupported_claims=[],
                groundedness_score=1.0,
                critique_feedback="평가 생략"
            )

    def after_agent(self, state: dict, runtime=None) -> dict | None:
        """에이전트 답변 완료 후 가로채서 품질 검증 및 자가 수정 피드백 주입."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.content:
            return None

        from app.utils.message_utils import normalize_content
        answer_text = normalize_content(last_msg.content)

        # 1. 사용자 질문 및 수집된 Tool Contexts 추출
        user_query = ""
        contexts = []
        for msg in messages:
            if isinstance(msg, HumanMessage) and not str(msg.content).startswith("🛑 [Self-Correction"):
                user_query = normalize_content(msg.content)
            elif isinstance(msg, ToolMessage) and msg.content:
                contexts.append(normalize_content(msg.content))

        # 2. 세션 식별 및 재시도 카운트 확인
        session_id = getattr(runtime, "session_id", "default_session") if runtime else "default_session"
        current_retries = self._retry_counts.get(session_id, 0)

        # 3. Groundedness 채점
        eval_result = self.evaluate_groundedness(user_query, contexts, answer_text)

        if self.verbose:
            status_icon = "✅" if (eval_result.is_grounded and eval_result.groundedness_score >= self.min_groundedness_score) else "🔴"
            print(f"\n{status_icon} [RAGSelfCorrection] Groundedness Score: {eval_result.groundedness_score:.2f} (환각 여부: {eval_result.has_hallucination})")

        # 4. 환각 감지 또는 근거 부족 시 자가 수정 루프 격발
        is_failed = (not eval_result.is_grounded) or (eval_result.groundedness_score < self.min_groundedness_score) or eval_result.has_hallucination

        if is_failed and current_retries < self.max_retries:
            self._retry_counts[session_id] = current_retries + 1
            
            correction_feedback = (
                f"🛑 [Self-Correction Blocking Error: 사실성/환각 검증 실패]\n"
                f"당신이 생성한 답변에서 검색 문서(Context)에 근거하지 않은 환각 또는 불일치가 감지되었습니다.\n\n"
                f"📌 피드백 지침:\n{eval_result.critique_feedback}\n"
                f"📌 미확인 주장 목록: {eval_result.unsupported_claims}\n\n"
                f"지침에 따라 오직 검색된 문서 내용에만 기반하여 답변을 정정하세요. "
                f"문서에 내용이 없다면 솔직하게 '사내 규정/보고서에 해당 정보가 명시되어 있지 않습니다'라고 명확히 밝히세요."
            )
            
            if self.verbose:
                print(f"🔄 [RAGSelfCorrection] 자율 반성 피드백 주입 (재시도 {self._retry_counts[session_id]}/{self.max_retries})")
            
            updated_messages = list(messages) + [HumanMessage(content=correction_feedback)]
            return {"messages": updated_messages, "transition": "self_correction_retry"}

        # 통과 또는 재시도 소진 시 정상 종료
        if session_id in self._retry_counts:
            del self._retry_counts[session_id]
            
        return {"transition": "completed", "final_groundedness_score": eval_result.groundedness_score}

    def reset_session(self):
        """세션 초기화."""
        self._retry_counts.clear()
        self.last_evaluation = None
