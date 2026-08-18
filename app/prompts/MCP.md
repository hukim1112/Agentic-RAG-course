# Enterprise MCP Server Registry

이 문서는 에이전트가 `file_read` 도구를 통해 참조할 수 있는 사내 및 외부 MCP 서버의 엔드포인트 목록입니다.

| 서버명 (Server Name) | 전송 프로토콜 (Transport) | HTTP 엔드포인트 URL | 설명 및 주요 제공 기능 |
| :--- | :--- | :--- | :--- |
| **Enterprise-RAG-Server** | Stateless Streamable HTTP | `http://localhost:8010/mcp` | 사내 복무/출장 규정 검색, 조직도 관계 그래프(2-Hop BFS) 탐색, GraphRAG Global/Local 심층 분석 |
| **Finance-Market-Server** | Stateless Streamable HTTP | `http://localhost:8020/mcp` | 실시간 환율, 주요 기업(NVDA, TSLA, 삼성전자 등) 주가 및 재무 지표 조회 (예시 서버) |

---

## 💡 에이전트 사용 가이드 (How to Connect)
1. 도구 목록 조회가 필요할 때:
   ```bash
   python skills/mcp/scripts/list_tools.py --url http://localhost:8010/mcp
   ```
2. 특정 도구 실행이 필요할 때:
   ```bash
   python skills/mcp/scripts/execute_tool.py --url http://localhost:8010/mcp --tool <TOOL_NAME> --args '<JSON_STRING>'
   ```
