#!/bin/bash

# 스크립트가 위치한 디렉토리로 이동하여 경로 문제를 방지합니다.
cd "$(dirname "$0")"

echo "🚀 Github Codespaces 환경 전체 설치를 시작합니다..."

# 1. Yarn GPG 키 만료 문제 우회 후 시스템 패키지 설치
echo "🔄 시스템 패키지 업데이트 및 설치 중..."
sudo rm -f /etc/apt/sources.list.d/yarn.list
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    fonts-nanum fonts-nanum-coding fonts-nanum-extra \
    fontconfig locales

# 2. 폰트 캐시 갱신 및 한국어 로케일 설정
echo "🔤 폰트 캐시 갱신 및 한국어 로케일 설정 중..."
sudo fc-cache -fv
sudo sed -i 's/# ko_KR.UTF-8/ko_KR.UTF-8/' /etc/locale.gen
sudo locale-gen

# 3. Python 의존성 설치 (requirements.txt가 있을 경우)
if [ -f "requirements.txt" ]; then
    echo "🐍 Python 패키지 설치 중..."
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt 파일을 찾을 수 없어 Python 패키지 설치를 건너뜁니다."
fi

# 4. 실행 권한 부여
echo "🔐 스크립트 실행 권한 부여 중..."
chmod +x install_hangul.sh

# 5. .env 파일 생성 (.env.example 복사 + Chainlit 시크릿 자동 생성)
if [ ! -f "../.env" ]; then
    cp ../.env.example ../.env
    # Chainlit JWT 인증 시크릿 자동 생성
    SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/your_chainlit_secret_here/$SECRET/" ../.env
    # Enterprise RAG MCP 서버 인증 토큰 자동 생성
    MCP_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/your_mcp_token_here/$MCP_TOKEN/" ../.env
    echo "📄 .env 파일이 생성되었습니다. API 키를 설정해 주세요."
    echo "🔑 CHAINLIT_AUTH_SECRET, ENTERPRISE_RAG_MCP_TOKEN이 자동 생성되었습니다."
else
    echo "📄 .env 파일이 이미 존재합니다. 덮어쓰지 않습니다."
fi

# 6. 완료 메시지
echo "---------------------------------------------------------"
echo "✅ 전체 환경 설정 및 의존성 설치가 성공적으로 완료되었습니다!"
echo "---------------------------------------------------------"
