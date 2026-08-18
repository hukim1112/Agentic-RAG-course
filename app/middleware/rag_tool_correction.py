"""
rag_tool_correction.py
======================
도구 레벨 자가 수정(Self-Correction) 및 쿼리 재작성(Query Rewriting) 미들웨어.
LangChain AgentMiddleware의 @wrap_tool_call을 활용하여 검색 도구 실행을 가로채고,
검색 결과 공백/실패 시 능동적으로 쿼리를 재작성하여 1회 자동 재시도를 수행합니다.
"""

import time
from typing import Any, Dict, List, Optional
from langchain.agents.middleware import AgentMiddleware, wrap_tool_call
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field


class RewrittenQuery(BaseModel):
    """LLM 기반 쿼리 정규화 및 키워드 보강 스키마."""
    original_query: str = Field(description="원래 검색 쿼리")
    is_ambiguous: bool = Field(description="쿼리가 모호하거나 비격식체/오탈자가 있는가?")
    expanded_keywords: List[str] = Field(description="추가된 핵심 동의어 및 비즈니스 키워드")
    rewritten_query: str = Field(description="정규화되고 명확해진 최종 검색 쿼리")


class RAGToolCorrectionMiddleware(AgentMiddleware):
    """
    [도구 레벨 자가 수정 미들웨어]
    1. 중복 도구 호출 방지 (Anti-Spinning Cache)
    2. 빈 검색 결과 감지 시 QueryRewriter를 통한 1회 자동 재검색 (Auto-Retry)
    3. 도구 실행 궤적(Tool Trajectory) 메트릭 캡처
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        enable_auto_retry: bool = True,
        max_tool_retries: int = 1,
        verbose: bool = True
    ):
        self.llm = llm
        self.enable_auto_retry = enable_auto_retry
        self.max_tool_retries = max_tool_retries
        self.verbose = verbose
        # 세션별 실행 궤적 및 중복 호출 방지 캐시
        self.seen_tool_calls = set()
        self.tool_trajectory_logs = []

    def _get_rewriter_llm(self):
        if self.llm is not None:
            return self.llm
        from app.utils.llm import get_llm
        return get_llm(model_name="gemini-3.5-flash", temperature=0.0)

    def rewrite_query(self, original_query: str, domain_hint: str = "general") -> str:
        """모호한 질문이나 구어체 쿼리를 공식 사내 용어 및 검색 친화적 키워드로 변환합니다."""
        try:
            llm = self._get_rewriter_llm()
            structured_llm = llm.with_structured_output(RewrittenQuery)
            
            prompt = (
                f"당신은 엔터프라이즈 RAG 검색 쿼리 최적화기(Query Rewriter)입니다.\n"
                f"사용자의 원본 검색 쿼리를 분석하여, 데이터베이스(규정/보고서/지식그래프)에서 최상의 검색 결과를 얻을 수 있도록 정규화된 쿼리를 생성하세요.\n\n"
                f"- 도메인 힌트: {domain_hint}\n"
                f"- 원본 쿼리: {original_query}\n\n"
                f"규칙:\n"
                f"1. 비격식체, 은어, 축약어를 표준 비즈니스 용어로 변환하세요 (예: '법카' -> '법인카드', '소명' -> '소명 절차 및 사유서').\n"
                f"2. 불필요한 조사나 감탄사를 제거하고 핵심 명사 위주로 재구성하세요.\n"
            )
            
            result: RewrittenQuery = structured_llm.invoke([HumanMessage(content=prompt)])
            if self.verbose:
                print(f"🔄 [QueryRewriter] '{original_query}' ➔ '{result.rewritten_query}' (확장 키워드: {result.expanded_keywords})")
            return result.rewritten_query
        except Exception as e:
            if self.verbose:
                print(f"⚠️ [QueryRewriter Error] {e} -> 원본 쿼리 유지")
            return original_query

    def _is_empty_or_failed_result(self, result: Any) -> bool:
        """도구 실행 결과가 공백이거나 실패했는지 판별합니다."""
        if result is None:
            return True
        res_str = str(result).strip()
        if not res_str or res_str == "[]" or res_str == "{}":
            return True
        empty_signals = [
            "검색 결과가 없습니다",
            "관련 문서를 찾을 수 없습니다",
            "no results found",
            "not found",
            "일치하는 정보가 없습니다",
            "0 results"
        ]
        return any(signal in res_str.lower() for signal in empty_signals)

    def wrap_tool_call(self, request, handler):
        """동기 도구 실행 가로채기."""
        tool_name = "unknown_tool"
        tool_args = {}
        if hasattr(request, "tool_call") and isinstance(request.tool_call, dict):
            tool_name = request.tool_call.get("name", "unknown_tool")
            tool_args = request.tool_call.get("args", {})
        elif hasattr(request, "name"):
            tool_name = getattr(request, "name", "unknown_tool")

        # 1. 중복 호출(Anti-Spinning) 검사
        call_signature = f"{tool_name}:{str(sorted(tool_args.items()))}"
        is_duplicate = call_signature in self.seen_tool_calls
        self.seen_tool_calls.add(call_signature)

        start_time = time.time()
        if self.verbose:
            print(f"🔧 [RAGToolCorrection] ➡️ 도구 실행: {tool_name}({tool_args})" + (" [⚠️ 중복 호출 감지]" if is_duplicate else ""))

        # 2. 1차 도구 실행
        try:
            response = handler(request)
        except Exception as e:
            response = f"Tool execution error: {e}"

        duration_ms = int((time.time() - start_time) * 1000)
        is_empty = self._is_empty_or_failed_result(response)

        # 3. 검색 결과 공백/실패 시 쿼리 재작성 & 1회 자동 재시도
        retry_performed = False
        if is_empty and self.enable_auto_retry and self.max_tool_retries > 0:
            # 쿼리 파라미터 식별 (query, question, search_query 등)
            query_key = None
            for k in ["query", "question", "search_query", "query_text", "keyword"]:
                if k in tool_args and isinstance(tool_args[k], str):
                    query_key = k
                    break

            if query_key:
                orig_query = tool_args[query_key]
                if self.verbose:
                    print(f"⚠️ [RAGToolCorrection] '{tool_name}' 검색 결과 공백 -> QueryRewriter 자가 수정 발동!")
                
                rewritten_q = self.rewrite_query(orig_query, domain_hint=tool_name)
                if rewritten_q != orig_query:
                    # 인자 교체 후 재실행
                    new_args = dict(tool_args)
                    new_args[query_key] = rewritten_q
                    
                    if hasattr(request, "tool_call") and isinstance(request.tool_call, dict):
                        request.tool_call["args"] = new_args
                    
                    retry_start = time.time()
                    try:
                        retry_response = handler(request)
                        if not self._is_empty_or_failed_result(retry_response):
                            response = retry_response
                            retry_performed = True
                            duration_ms += int((time.time() - retry_start) * 1000)
                            if self.verbose:
                                print(f"✅ [RAGToolCorrection] 자가 수정 재검색 성공! 유효 결과 획득")
                    except Exception as e:
                        if self.verbose:
                            print(f"⚠️ [RAGToolCorrection] 재시도 실패: {e}")

        # 4. Trajectory 메트릭 로깅
        log_entry = {
            "tool_name": tool_name,
            "arguments": tool_args,
            "latency_ms": duration_ms,
            "is_duplicate": is_duplicate,
            "retry_performed": retry_performed,
            "result_summary": str(response)[:300],
            "result_length": len(str(response)),
            "status": "SUCCESS" if not self._is_empty_or_failed_result(response) else "EMPTY"
        }
        self.tool_trajectory_logs.append(log_entry)
        return response

    async def awrap_tool_call(self, request, handler):
        """비동기 도구 실행 가로채기 (동기와 동일 로직)."""
        # 비동기 환경에서도 안전하게 동기 래퍼 위임
        return self.wrap_tool_call(request, handler)

    def reset_session(self):
        """세션 초기화."""
        self.seen_tool_calls.clear()
        self.tool_trajectory_logs.clear()
