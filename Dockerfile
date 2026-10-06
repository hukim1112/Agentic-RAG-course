# ===============================================================================
# Enterprise Agentic RAG Course - GitHub Codespaces & DevContainer Base Image
# LangChain, LangGraph, Chroma, GraphRAG, FastMCP, Chainlit
# ===============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=ko_KR.UTF-8 \
    LC_ALL=ko_KR.UTF-8

# 1. 필수 시스템 빌드 도구 및 한글 폰트/로케일 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    build-essential \
    procps \
    net-tools \
    ffmpeg \
    fonts-nanum \
    fonts-nanum-extra \
    fontconfig \
    locales \
    && sed -i '/ko_KR.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=ko_KR.UTF-8 \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 2. Node.js 22 LTS 설치 (Stdio MCP 서버 실행용: npx -y wikipedia-mcp)
#    wikipedia-mcp를 전역 설치해 두어 첫 npx 실행 시 다운로드 지연을 없앱니다.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g wikipedia-mcp && \
    npm cache clean --force && \
    rm -rf /var/lib/apt/lists/*

# 3. Python 라이브러리 전체 일괄 사전 설치
COPY install/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# 4. 서비스 포트 명시
#    8000: FastAPI Backend API
#    8010: Enterprise RAG FastMCP Server
#    8080: Chainlit Chat UI
#    8888: Jupyter Notebook
EXPOSE 8000 8010 8080 8888

CMD ["/bin/bash"]
