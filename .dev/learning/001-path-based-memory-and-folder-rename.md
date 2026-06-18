# 001 — 경로 기반 메모리의 한계와 폴더 리네임

날짜: 2026-06-19

## 배운 것
- Claude Code의 영속 메모리는 **프로젝트 절대경로**를 키로 저장된다.
  (예: `~/.claude/projects/-Users-anthony-Repository-github-loveqoo-my-agent/memory/`)
- 따라서 **폴더 이름/경로를 바꾸면 메모리 키가 달라져, 기존 메모리가 다음 세션에서 로드되지 않는다**(고아 상태).

## 그래서 우리의 원칙
- 폴더 이동/리네임에도 살아남아야 하는 **프로젝트 맥락은 경로 기반 메모리가 아니라 저장소 안에 남긴다.**
  - 운영 규칙/프로젝트 컨텍스트 → `CLAUDE.md`
  - 학습/문제 해결 흔적 → `.dev/learning/`, `.dev/troubleshooting/`
  - 스펙·결정·회고 → `docs/{spec,adr,retrospect}/`
- 저장소는 git 원격(`loveqoo/my-agents`)에도 푸시되어 이중으로 보존된다.

## 진행한 결정/사실
- 로컬 폴더명 `my-agent`(단수)와 원격 `loveqoo/my-agents`(복수)가 불일치했음.
- 해결: **로컬 폴더를 `my-agents`로 리네임하여 원격과 일치시킨다.**
- 리네임 후에도 git 원격 연결(`.git/` 내부 설정)은 그대로 유지되므로 push/pull에 영향 없음.
- 단, 리네임 후 경로가 바뀌므로 위 메모리 경로의 기존 메모리는 새 세션에서 사용 불가 → 본 문서가 그 역할을 대신한다.
