"""
[권한별 도구 접근 제어 FastMCP 서버]

■ 쉽게 이해하기:
  1. 인증 (너 누구야?): 사원증(토큰)을 확인해서 회사 사람인지 봅니다.
  2. 인가 (너 이거 해도 돼?): 사원증에 적힌 권한(read, write, delete)을 보고 각 도구의 실행을 허락/거절합니다.

■ 준비된 테스트 사원증(토큰):
  • admin-token-001   → 관리자 (읽기, 쓰기, 삭제 모두 가능)
  • analyst-token-002 → 분석가 (오직 '읽기'만 가능, 수정/삭제 시도시 에러 발생)
  • writer-token-003  → 작성자 (읽기, 쓰기 가능, 삭제는 불가)
"""

import argparse
import json
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.server.auth import require_scopes
from fastmcp.server.dependencies import get_access_token


# ── ① 사원증(토큰) 목록 등록 ─────────────────────────────────────────
# 개발 및 테스트를 위해 임시로 사원증 지갑을 만듭니다.
verifier = StaticTokenVerifier(
    tokens={
        "admin-token-001": {
            "client_id": "admin@example-corp.com",
            "scopes": ["read", "write", "delete", "admin"],
        },
        "analyst-token-002": {
            "client_id": "analyst@example-corp.com",
            "scopes": ["read"],
        },
        "writer-token-003": {
            "client_id": "writer@example-corp.com",
            "scopes": ["read", "write"],
        },
    }
)

app = FastMCP("Secure MCP Server", auth=verifier)


# ── ② 도구별 자물쇠(권한) 채우기 ──────────────────────────────────────

# 📖 읽기 도구: 'read' 권한이 있는 사원증만 실행 가능
@app.tool(auth=require_scopes("read"))
def query_data(table: str, limit: int = 5) -> str:
    """데이터를 조회합니다. ('read' 권한 필요)"""
    # 지금 이 함수를 호출한 사람이 누구인지 확인
    token = get_access_token()
    data = [{"id": i, "value": i * 100} for i in range(1, limit + 1)]
    return f"[{token.client_id}] {table} 조회 성공:\n" + json.dumps(data, indent=2, ensure_ascii=False)


# ✍️ 수정 도구: 'write' 권한이 있는 사원증만 실행 가능
# (analyst-token으로 부르면 권한이 없어서 403 에러로 자동 차단됩니다)
@app.tool(auth=require_scopes("write"))
def update_record(record_id: int, field: str, new_value: str) -> str:
    """데이터를 수정합니다. ('write' 권한 필요)"""
    token = get_access_token()
    return f"✅ [{token.client_id}] 레코드 {record_id} 수정 완료: {field}={new_value}"


# 🗑️ 삭제 도구: 'delete'와 'admin' 권한이 둘 다 있어야만 실행 가능 (최고 관리자 전용)
@app.tool(auth=require_scopes("delete", "admin"))
def delete_record(record_id: int, reason: str) -> str:
    """데이터를 삭제합니다. ('delete'와 'admin' 권한 둘 다 필요)"""
    token = get_access_token()
    return f"🗑️ [{token.client_id}] 레코드 {record_id} 삭제 완료 (사유: {reason})"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secure FastMCP Server")
    parser.add_argument("--port", type=int, default=7100, help="서버 포트 (기본값: 7100)")
    args = parser.parse_args()

    print(f"🚀 Secure MCP Server 시작: http://0.0.0.0:{args.port}/mcp")
    app.run(transport="http", host="0.0.0.0", port=args.port)
