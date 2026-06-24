-- mem0 벡터 스토어용 pgvector 확장. 신규 DB 초기화 시 자동 실행(docker-entrypoint-initdb.d).
-- 기존 볼륨에는 실행되지 않으므로, 그 경우 한 번 수동 실행하거나 mem0가 자체 생성한다.
CREATE EXTENSION IF NOT EXISTS vector;
