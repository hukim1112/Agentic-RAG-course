"""
[실제 상용 서비스용: RSA 비대칭키 JWT 서명 검증 서버]

■ 쉽게 이해하기:
  1. 사내 공식 로그인 서버(IdP)가 자기만 아는 '비밀도장(Private Key)'으로 전자 사원증(JWT)을 발급합니다.
  2. 우리 FastMCP 서버는 회사에서 나눠준 '공개된 도장 모양(Public Key)'만 가지고,
     에이전트가 들고 온 사원증이 진짜 위조 없는 사원증인지 1초 만에 확인합니다.
"""

import argparse
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth import require_scopes
from fastmcp.server.dependencies import get_access_token

# 우리 회사 공식 로그인 발급처 이름
ISSUER = "https://auth.example-corp.com"
AUDIENCE = "mcp-enterprise-server"


def create_app(public_key: str) -> FastMCP:
    # ── ① 공개키(도장 모양)로 진짜 토큰인지 검사하는 검증기 생성 ──
    jwt_verifier = JWTVerifier(
        public_key=public_key,
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    app = FastMCP("JWT MCP Server", auth=jwt_verifier)

    # ── ② 도구 정의 (JWT 서명 검증 + 권한 검사) ──
    @app.tool(auth=require_scopes("read"))
    def secure_query(table: str) -> str:
        """진짜 사원증(JWT)이 있고, 'read' 권한이 있어야 실행 가능"""
        token = get_access_token()
        return (
            f"✅ 조회 성공\n"
            f"  사용자: {token.client_id}\n"
            f"  부서:   {token.claims.get('department', 'N/A')}\n"
            f"  직급:   {token.claims.get('level', 0)}\n"
            f"  역할:   {token.claims.get('role', 'N/A')}\n"
            f"  테이블: {table}"
        )

    @app.tool(auth=require_scopes("write"))
    def secure_update(record_id: int, value: str) -> str:
        """진짜 사원증(JWT)이 있고, 'write' 권한이 있어야 실행 가능"""
        token = get_access_token()
        return f"✅ [{token.client_id}] 레코드 {record_id} 수정 완료: {value}"

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JWT FastMCP Server")
    parser.add_argument("--port", type=int, default=7300, help="서버 포트 (기본값: 7300)")
    parser.add_argument("--public-key-file", type=str, required=True,
                        help="회사 로그인 서버의 RSA 공개키 파일 경로 (.pem/.pub)")
    args = parser.parse_args()

    with open(args.public_key_file, "r") as f:
        public_key = f.read().strip()

    print(f"🚀 JWT MCP Server 시작: http://0.0.0.0:{args.port}/mcp")
    app = create_app(public_key)
    app.run(transport="http", host="0.0.0.0", port=args.port)
