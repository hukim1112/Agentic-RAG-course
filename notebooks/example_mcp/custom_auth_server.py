"""
[부서(department) 및 직급(level) 확인 FastMCP 서버]

■ 쉽게 이해하기:
  단순히 '읽기/쓰기' 권한만 보는 게 아니라,
  "재무팀 사람인지?", "직급이 3급(팀장) 이상인지?" 등 회사 규칙에 맞춰 도구 사용을 제한합니다.

■ 준비된 테스트 토큰:
  • finance-mgr-token   → 재무팀(finance), 직급 4 (부장님) -> 재무보고서, 임원 대시보드 모두 열람 가능
  • sales-analyst-token → 영업팀(sales),   직급 2 (대리님) -> 영업 파이프라인만 열람 가능 (재무/임원 메뉴는 차단)
"""

import argparse
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.auth import AuthContext
from fastmcp.server.dependencies import get_access_token


# ── ① 부서/직급 검사기 만들기 ─────────────────────────────────────────

def require_department(dept: str):
    """'이 사람이 지정된 부서 소속인가?' 확인하는 검사기"""
    def check(ctx: AuthContext) -> bool:
        if ctx.token is None:
            return False
        # 토큰 정보에서 부서(department)를 꺼내서 비교
        return ctx.token.claims.get("department") == dept
    check.__name__ = f"require_{dept}_dept"
    return check


def require_min_level(min_level: int):
    """'이 사람 직급이 기준 이상인가?' 확인하는 검사기"""
    def check(ctx: AuthContext) -> bool:
        if ctx.token is None:
            return False
        # 토큰 정보에서 직급(level)을 꺼내서 비교
        return ctx.token.claims.get("level", 0) >= min_level
    check.__name__ = f"require_level_{min_level}_plus"
    return check


# ── ② 부서와 직급이 적힌 사원증(토큰) 등록 ────────────────────────────
verifier = StaticTokenVerifier(
    tokens={
        "finance-mgr-token": {
            "client_id": "kim@example-corp.com",
            "scopes": ["read", "write"],
            "department": "finance",   # 소속 부서: 재무팀
            "level": 4,                # 직급: 4 (부장급)
        },
        "sales-analyst-token": {
            "client_id": "lee@example-corp.com",
            "scopes": ["read"],
            "department": "sales",     # 소속 부서: 영업팀
            "level": 2,                # 직급: 2 (대리급)
        },
    }
)

app = FastMCP("Custom Auth MCP Server", auth=verifier)


# ── ③ 도구 정의 및 부서/직급 자물쇠 연결 ──────────────────────────────

# 📊 재무팀 전용 도구 (재무팀 소속 사원증만 실행 가능)
@app.tool(auth=require_department("finance"))
def get_financial_report(period: str) -> str:
    """재무팀 전용 보고서를 조회합니다. (영업팀이 부르면 차단됨)"""
    token = get_access_token()
    return f"📊 [{token.client_id}] {period} 재무보고서 조회 성공"


# 📈 임원 전용 대시보드 (직급이 3 이상인 사람만 실행 가능)
@app.tool(auth=require_min_level(3))
def get_executive_dashboard() -> str:
    """임원 전용 대시보드를 조회합니다. (직급 2급 대리님은 차단됨)"""
    token = get_access_token()
    level = token.claims.get("level", 0)
    return f"📈 [{token.client_id}] 전사 임원 대시보드 조회 성공 (직급: {level}급 확인)"


# 🔄 영업팀 전용 도구 (영업팀 소속 사원증만 실행 가능)
@app.tool(auth=require_department("sales"))
def get_sales_pipeline() -> str:
    """영업팀 전용 파이프라인을 조회합니다."""
    token = get_access_token()
    return f"🔄 [{token.client_id}] 영업 파이프라인: 진행 중 8건, 완료 12건"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Custom Auth FastMCP Server")
    parser.add_argument("--port", type=int, default=7200, help="서버 포트 (기본값: 7200)")
    args = parser.parse_args()

    print(f"🚀 Custom Auth MCP Server 시작: http://0.0.0.0:{args.port}/mcp")
    app.run(transport="http", host="0.0.0.0", port=args.port)
