---
name: mcp
description: MCP 서버의 도구 목록을 조회하고 도구를 실행하는 CLI 스킬. 사내 규정, 산업 보고서, 조직도 등 MCP 서버가 제공하는 데이터가 필요할 때 사용한다. 서버 URL과 인증 방식은 skills/mcp/references/mcp_servers.json에 있다.
---

# Model Context Protocol (MCP) Interface Skill

MCP 서버(Streamable HTTP / SSE / Stdio)의 도구를 조회하고 실행하는 CLI 스크립트 모음입니다.
사용할 서버의 URL과 인증 방식은 레지스트리 `skills/mcp/references/mcp_servers.json`에서 먼저 확인하세요.

## 인증 (Authentication)

인증이 필요한 서버는 `--token-env <환경변수명>` 옵션을 붙입니다.
- 토큰 **값**이 아니라 토큰이 담긴 **환경 변수 이름**을 넘깁니다. (예: `--token-env ENTERPRISE_RAG_MCP_TOKEN`)
- 스크립트가 환경 변수(또는 `.env`)에서 토큰을 직접 읽으므로, 토큰 값을 출력하거나 명령어에 적지 마세요.
- 인증 없이 호출하면 서버가 `401 Unauthorized`로 거부합니다.

---

### 1. list_tools.py
- **용도**: 서버가 제공하는 도구 목록과 입력 스키마(JSON Schema)를 조회합니다.
- **경로**: `skills/mcp/scripts/list_tools.py`
- **인자**:
  - `--url <URL>`: MCP 서버 URL (필수)
  - `--token-env <환경변수명>`: 인증 토큰이 담긴 환경 변수 이름 (인증 서버만)
- **예시**:
  ```bash
  # 1. 인증이 필요한 사내 Enterprise RAG HTTP 서버
  python skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp --token-env ENTERPRISE_RAG_MCP_TOKEN

  # 2. 로컬 Stdio 기반 공개 Wikipedia 서버
  python skills/mcp/scripts/list_tools.py --url "npx -y wikipedia-mcp"
  ```

---

### 2. execute_tool.py
- **용도**: 도구 하나를 JSON 인자로 실행하고 결과를 반환합니다.
- **경로**: `skills/mcp/scripts/execute_tool.py`
- **인자**:
  - `--url <URL>`: MCP 서버 URL (필수)
  - `--tool <TOOL_NAME>`: 실행할 도구 이름 (필수)
  - `--args '<JSON>'`: 도구 입력 스키마에 맞는 JSON 문자열 (필수)
  - `--token-env <환경변수명>`: 인증 토큰이 담긴 환경 변수 이름 (인증 서버만)
- **예시**:
  ```bash
  # 1. 사내 Enterprise RAG 서버 도구 실행
  python skills/mcp/scripts/execute_tool.py \
    --url http://localhost:8010/mcp \
    --token-env ENTERPRISE_RAG_MCP_TOKEN \
    --tool search_company_policy \
    --args '{"query": "당일 출장 일비 감액 기준"}'

  # 2. 로컬 Stdio 기반 공개 Wikipedia 서버 도구 실행
  python skills/mcp/scripts/execute_tool.py \
    --url "npx -y wikipedia-mcp" \
    --tool search \
    --args '{"query": "Artificial Intelligence"}'
  ```
- **주의**: 입력 스키마가 객체 하나(`params`)로 묶인 도구는 `{"params": {...}}` 형태로 넘깁니다.
  ```bash
  --tool search_graph_relations --args '{"params": {"seed_entity": "김철수 수석", "max_hops": 2}}'
  ```

## 출력 형식
두 스크립트 모두 `{"status": "SUCCESS" | "ERROR", ...}` 형태의 JSON을 출력합니다.
`ERROR`일 때는 `message`를 읽고 URL, 도구 이름, 인자 형식, 인증 옵션을 점검하세요.
