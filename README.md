# 🤖 Basic Agent Template (범용 에이전트 개발 템플릿)

본 프로젝트는 프로덕션 레벨의 AI 에이전트를 신속하게 개발하고 배포하기 위한 **범용 에이전트 코드베이스 템플릿(basic_agent)**입니다.

---

## 🚀 시작하기 (환경 세팅)

로컬 WSL2(우분투) 환경에서 다음 명령어를 실행하여 의존성 패키지를 설치하고 환경을 설정하세요.

```bash
# 1. install 폴더로 이동하여 패키지 설치
cd install
pip install -r requirements.txt
```

### 환경 변수 설정
프로젝트 루트에 `.env` 파일을 생성하고 사용할 API 키를 설정하세요. (기본 설정은 `.env.example`을 참고하세요.)

```env
OPENAI_API_KEY="your-openai-api-key"
GOOGLE_API_KEY="your-gemini-api-key"
```

### 📊 관측성 설정 (LangSmith)
에이전트 실행 흐름의 레이턴시와 호출 과정을 모니터링하기 위해 LangSmith를 설정할 수 있습니다.

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY="your-langsmith-key"
LANGCHAIN_PROJECT=basic-agent
```

---

## 🖥️ 실행 방법

이 템플릿은 FastAPI 기반의 백엔드 API 서버, Streamlit 기반의 웹 채팅 UI, 그리고 터미널 기반의 CLI 테스터를 포함하고 있습니다.

### 1. 백엔드 서버(FastAPI) 가동
에이전트를 호스팅하는 API 엔드포인트를 구동합니다.
```bash
python app/server.py --port 8000
```
* 서버 실행 후 `http://localhost:8000/docs` 에서 Swagger API 명세서를 통해 테스트할 수 있습니다.

### 2. Streamlit 웹 채팅 UI 가동
인터랙티브 웹 인터페이스를 구동하여 브라우저에서 대화합니다.
```bash
streamlit run app/ui.py
```
* 웹 브라우저에서 `http://localhost:8501`에 접속하여 사이드바에서 모델 및 파라미터를 변경하며 채팅할 수 있습니다.

### 3. 터미널 테스트 CLI 가동
터미널 환경에서 가볍게 에이전트 응답을 테스트합니다.
```bash
python app/client.py
```

### 💬 내가 만든 에이전트를 웹 화면에 바로 추가하여 대화하기

이 프로젝트는 **서버를 껐다 켤 필요 없이, 에이전트 파일만 폴더에 넣으면 웹 화면이 실시간으로 알아채고 에이전트를 추가**해 줍니다. 

실습 도중 나만의 에이전트를 완성했거나 새로 만들고 싶다면, 아래의 3단계만 따라 해 보세요.

#### 1단계. 에이전트 파일 만들기
`app/agents/` 폴더 안에 원하는 이름으로 파이썬 파일(예: `my_agent.py`)을 새로 만듭니다.

#### 2단계. 에이전트 코드 작성하기 (그대로 복사해서 붙여넣기)
새로 만든 파일(`my_agent.py`) 안에 아래의 코드를 그대로 복사해서 붙여넣고 저장합니다. 

```python
# app/agents/my_agent.py

from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool
from app.utils import get_llm
from app.utils.context import AgentContext

# 1) UI에 표시될 에이전트의 소개 정보 (필수)
AGENT_METADATA = {
    "name": "my_agent", 
    "description": "더하기 도구가 탑재된 나만의 실습용 ReAct 에이전트"
}

# 2) 에이전트가 사용할 실제 도구 정의 (생략 없이 작동 가능한 도구 예시)
@tool
def add_numbers(a: int, b: int) -> int:
    """두 정수 a와 b를 더한 결과를 반환합니다. 더하기 연산이 필요할 때 사용하세요."""
    return a + b

# 3) 에이전트를 생성하는 함수 (서버가 이 함수를 찾아 실행합니다)
async def create_agent_executor():
    # 1. LLM 모델 생성 (Gemini 3.5 Flash 모델 활용)
    llm = get_llm(model_name="gemini-3.5-flash", temperature=0.0)
    
    # 2. 대화 기억 보존을 위한 체크포인터 셋업
    memory = MemorySaver()
    
    # 3. 도구 목록 정의
    tools = [add_numbers]
    
    # 4. 에이전트 최종 구축
    agent = create_agent(
        model=llm,
        tools=tools,
        checkpointer=memory,
        context_schema=AgentContext
    )
    return agent
```

#### 3단계. 웹 브라우저 새로고침하고 대화하기
1. 띄워져 있는 웹 채팅 화면([http://localhost:8501](http://localhost:8501))으로 이동하여 **새로고침(F5)**을 누릅니다.
2. 왼쪽 메뉴의 **"Select Agent" 드롭다운 상자**를 누르면, 방금 만든 `MY_AGENT`가 실시간으로 감지되어 목록에 추가되어 있습니다.
3. 해당 에이전트를 선택하고 대화를 시작해 보세요!
   *(예: "37 더하기 84는 뭐야?" 라고 물어보면 에이전트가 탑재된 `add_numbers` 도구를 호출하여 정상적으로 덧셈 결과를 답변합니다.)*

---

## 📂 프로젝트 구조

```text
basic_agent/
├── app/                    # 🧠 핵심 에이전트 애플리케이션 패키지
│   ├── agents/             #   └── 에이전트 구동기 정의 (chatbot.py, 레지스트리)
│   ├── prompts/            #   └── 프롬프트 정의 및 관리 (PromptManager)
│   ├── tools/              #   └── 에이전트 바인딩 도구 (common.py)
│   ├── utils/              #   └── 중앙 모델 팩토리 및 메시지 헬퍼 (llm.py 등)
│   ├── server.py           #   └── FastAPI API API 서버
│   ├── ui.py               #   └── Streamlit 웹 채팅 UI
│   └── client.py           #   └── 터미널용 대화형 CLI 클라이언트
│
├── configs/                # ⚙️ 로깅 및 미들웨어 관련 설정
├── skills/                 # 🛠️ 에이전트 확장용 외부 스킬 모듈
├── notebooks/              # 📗 프로토타이핑용 Jupyter Notebooks 저장소 (비어있음)
├── artifacts/              # 📂 로깅 파일 및 산출물 보관함
├── install/                # 🚀 requirements.txt 및 설치 자원
└── README.md               # 📖 본 설명서
```
