# Spec

에이전트를 생성하고 관리하는 서비스를 생성합니다.
하드코딩 된 에이전트를 만들어내는 것이 아니라, 잘 만들어진 구조속에서 에이전트를 만들 수 있도록 합니다.
다양한 MCP를 등록하고 제공 및 관리합니다.

에이전트는 다음과 같은 기능을 가지고 있습니다.
- 페르소나 (역할, 해야 할 업무 등)
- 동작할 파운데이션 모델 설정
- MCP (tools)
- 메모리 (작업 기억과 같은 에이전트 전용 메모리, 유저에 대한 메모리 등 Mem0에서 제공하는 메모리 기능)

에이전트는 A2A 프로토콜을 지원하며, 자체 MCP 뿐만 아니라 Langgraph에서 제공하는 원격의 MCP도 등록하여 사용할 수 있습니다.

## 기술 스택 및 인프라

- 언어: Python
- 데이터베이스: PostgreSQL(+ pgvector)
- Backend: Fast API를 사용하여 Agent 프로토콜을 제공
- Agent: Langgraph를 사용하여 에이전트의 기능을 구현
- Memory: Mem0
- Metric: Langfuse

## 구조

uv를 활용하여 여러 모듈을 구조적으로 관리합니다.

- Backend API
    - MCP, Agent 제공
- Admin SPA - React, Typescript, Antd
    - MCP, Agent 관리
    - 파운데이션 모델 관리