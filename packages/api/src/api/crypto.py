"""비밀값 at-rest 암호화 (Fernet 대칭키).

키 출처(우선순위): env `APP_SECRET_KEY` → `.dev/.secret_key`(없으면 생성·영속).
→ 개발은 즉시 동작하고, 키는 코드/DB 밖(파일·env)에 둔다. 운영은 env로 주입(KMS 등은 추후).

encrypt/decrypt는 무중단 이행을 위해 레거시 평문을 허용한다: 복호화가 실패하면
평문으로 간주해 그대로 반환(이후 재저장 시 암호화됨).

지배 스펙: docs/spec/010-secret-at-rest.md
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("api.crypto")

# API 응답에서 비밀 존재를 알리는 고정 마스킹(평문/암호문 미노출).
SECRET_MASK = "••••••••"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET_KEY")
    if not key:
        # crypto.py = packages/api/src/api/crypto.py → parents[4] = repo 루트
        key_path = Path(__file__).resolve().parents[4] / ".dev" / ".secret_key"
        if key_path.exists():
            key = key_path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(key)
            log.warning("APP_SECRET_KEY 미설정 — %s에 개발용 키 생성(영속). 운영은 env로 주입.", key_path)
    return Fernet(key.encode() if isinstance(key, str) else key)


def is_masked(value: str | None) -> bool:
    """마스킹 표시 값인지(편집 시 보존 판단)."""
    return bool(value) and "•" in value


def _looks_encrypted(value: str) -> bool:
    """Fernet 토큰 형태인지(v1 토큰은 base64url로 'gAAAAA'로 시작)."""
    return value.startswith("gAAAAA")


def encrypt(plaintext: str | None) -> str | None:
    """평문 → 암호문. None/빈값은 그대로 None."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(stored: str | None) -> str | None:
    """암호문 → 평문. 레거시 평문이면 그대로 반환. None은 None."""
    if not stored:
        return None
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        if _looks_encrypted(stored):
            # 암호문인데 복호화 실패 = 키 불일치/회전. 암호문을 그대로 흘려보내면(외부 전송)
            # 비밀 누출 + 설정 오류 은폐 → 명확히 실패시킨다.
            raise RuntimeError(
                "비밀 복호화 실패 — APP_SECRET_KEY가 저장 시점과 다릅니다."
            ) from None
        # Fernet 형태가 아니면 이행 전 레거시 평문으로 간주.
        return stored
