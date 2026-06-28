# 047 — 성공-카운터에 건 멱등성은 부분 실패를 "완료"로 오인한다

## 한 줄
멱등 스킵 게이트를 `doc_count>0` 같은 **성공분만 세는 집계 캐시**에 걸면, 부분 실패한
이전 실행(일부만 적재, 나머지 error)을 "이미 완료"로 보고 스킵 → 미완성인데 populated라
주장한다. 멱등성은 *완료된 단위의 집합*으로 판단해야 한다.

## 맥락
스펙 048 `ingest_rag_samples.py`. docs_kb에 4개 샘플을 적재. 초안의 멱등 게이트:

```python
if col.doc_count > 0:
    return "already-populated"   # ← 스킵
```

`doc_count`는 **성공 적재 시에만 증가하는 비정규화 캐시**(rag.py: error 경로는 증가 안 함).
시나리오: 1~2번 파일은 ready, 3번에서 임베딩 서버 hiccup → status=error. 이제 `doc_count==2>0`.
재실행하면 "already-populated"로 **3·4번을 영영 안 채운다**. 게다가 컬렉션을 populated라 표기.
→ "절대 중복 적재 안 함"의 절반(완전 성공 후 재실행)만 맞고, **자가치유는 거짓**.

적대 서브에이전트가 happy-path 초록 뒤에서 이걸 짚었다(#5 MAJOR, CLAIM2 반증).

## 교훈
**"하나라도 있으면 다 있다"는 가정이 함정.** 카운터·플래그·"비어있지 않음"은 *일부 진행*과
*완료*를 구분하지 못한다. 멱등성/자가치유의 올바른 키는 **기대 단위 집합 vs 실제 완료 집합의 차집합**:

```python
existing = {d["filename"]: d for d in list_documents(col)}
for fn, data in samples:
    prev = existing.get(fn)
    if prev and prev["status"] == "ready":   # 이 단위는 완료 → 스킵
        continue
    if prev:                                  # 미완료/error → 지우고 재적재(자가치유)
        delete(prev["id"])
    ingest(fn, data)
```

이러면 재실행=완전분만 스킵(중복 0), 부분상태=누락분만 복구. 라이브로 실증: 1개 삭제→재실행이
**그 1개만** 재적재.

## 메타패턴 — "서브유닛 방어는 전체를 못 묶는다"의 WHICH-set(완전성) 축
041(WHERE 바이트: 버퍼 위가 아니라 원천에서 캡), 044(WHICH URL: 가드는 최초URL만, 체인끝 아님),
046(WHICH span: per-read 타임아웃 ≠ 전체 deadline)와 같은 결. 여기선 **WHICH set**:
성공-카운터(`>0`)는 "전건 완료"를 못 묶는다 — 묶으려면 *완료 단위 집합*을 직접 비교하라.
공통 처방: "전체"를 보장하려면 전체의 *경계/원천/집합*에서 판단하고, 하위 신호(카운트·프레임·
최초URL·per-read)로 대용하지 마라. 같은 함정은 happy-path에서 늘 초록이라 **적대자만** 잡는다.

관련: [[verification-ladder-three-rungs]] · 적대 리뷰 = verification ladder의 3rung.
