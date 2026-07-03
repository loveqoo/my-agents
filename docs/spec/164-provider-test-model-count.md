# 164 — 프로바이더 연결 테스트가 항상 "모델 미발견"

## 증상
프로바이더를 연결하고 연결 테스트를 하면, 잘 붙었는데도 **"연결됨 · 모델 미발견"**이 뜬다. 정작
등록 화면(`/available-models`)에선 같은 프로바이더의 모델이 주르륵 나온다.

## 근인
프로바이더 레벨 테스트는 `_probe(base_url, key, "", "chat")`로 **빈 model_id**를 넘긴다
(providers.py:73·84 — 특정 모델이 아니라 프로바이더 도달성 확인). 그런데 `_probe`는:
```python
available = model_id in ids if model_id else False   # model_id="" → 무조건 False
detail = "연결됨" + (" · 모델 사용 가능" if available else " · 모델 미발견")
```
빈 model_id를 **무조건 미발견**으로 판정. "특정 모델이 목록에 있나"를 보는 함수를 빈 이름으로 재사용해
프로바이더 테스트가 항상 "미발견"으로 오판(스펙 158 계열 — 정상을 실패처럼 표시).

## 수정
`_probe` chat 분기에서 **model_id가 비면 목록 개수로 판정**:
- 모델 ≥1 → `modelAvailable=True`, `"연결됨 · 모델 N개 발견"`.
- 모델 0 → `modelAvailable=False`, `"연결됨 · 모델 목록 비어있음"`.
- model_id 지정 시(저장 모델 테스트)만 기존 "사용 가능 / 미발견" 정확 일치 유지.

## 검증
`tests/verify_164_provider_probe.py` — 로컬 stub /models 서버(스레드)로 실제 `_probe` 호출:
1. 빈 model_id + 모델 2개 목록 → detail "모델 2개 발견"·modelAvailable=True(before=미발견).
2. 빈 model_id + 빈 목록 → "모델 목록 비어있음"·False.
3. model_id 지정·존재 → "모델 사용 가능"·True. 부재 → "모델 미발견"·False(회귀 — 정확 일치 유지).

## OUT
- 프로바이더 테스트가 발견한 모델 목록을 응답에 담아 UI 드롭다운 채우기(현재 /available-models가 담당).
- embedding 프로바이더 테스트(현재 chat 고정 — /models 목록 확인. embedding은 저장 모델 테스트서 실호출).
