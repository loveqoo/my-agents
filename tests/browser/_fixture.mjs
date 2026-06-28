/* 브라우저 샷 self-fixture (스펙 050 Phase 3).
   영속 테스트 계정(verify032 등)에 의존하지 말고, 던짐용 super를 즉석 시드 → 프로세스 종료 시 자동 삭제.

   provisionSuper()는 매 실행 고유 `shotfix_<rand>@example.com` super를 만들고
   process.on('exit')에 teardown을 건다 — execFileSync가 sync라 exit 핸들러(동기만 허용)에서도 동작하므로
   각 샷 스크립트의 finally를 건드리지 않아도 정리가 보장된다. ADMIN_EMAIL 환경변수가 있으면 그걸
   존중해 self-fixture를 생략한다(명시 오버라이드). 삭제는 provisioner의 keep-list 가드가 한 겹 더 막는다. */
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(__dirname, '..', '..') // tests/browser → repo root
const API_DIR = path.join(REPO, 'packages', 'api')
const PROV = path.join(REPO, 'tests', '_provision_super.py')

export function provisionSuper() {
  const rand = Math.random().toString(36).slice(2, 10)
  const email = `shotfix_${rand}@example.com`
  const password = 'Shotfix1!pw'
  execFileSync('uv', ['run', 'python', PROV, 'create', email, password], {
    cwd: API_DIR,
    stdio: 'inherit',
  })
  let torn = false
  const teardown = () => {
    if (torn) return
    torn = true
    try {
      execFileSync('uv', ['run', 'python', PROV, 'delete', email], { cwd: API_DIR, stdio: 'inherit' })
    } catch (e) {
      console.log('FIXTURE_TEARDOWN_WARN', e?.message ?? e)
    }
  }
  // exit: 정상/예외 종료 모두. SIGINT/SIGTERM/SIGHUP: Ctrl-C·kill·터미널 닫힘(ssh/CI)도 정리하고 종료.
  // SIGKILL(-9)은 잡을 수 없어 고아 super가 남을 수 있다 — 단 매 실행 랜덤 이메일이라 누적만 되고
  // 자기증식하지 않으며, user-cleanup 잡이 `shotfix%@example.com` 패턴으로 일괄 청소 가능(적대 리뷰 M3).
  process.on('exit', teardown)
  process.on('SIGINT', () => { teardown(); process.exit(130) })
  process.on('SIGTERM', () => { teardown(); process.exit(143) })
  process.on('SIGHUP', () => { teardown(); process.exit(129) })
  return { email, password, teardown }
}

/* 명시적으로 끝낼 때 호출(선택) — exit 핸들러가 어차피 보장하므로 필수는 아니다. */
export function teardownSuper(fx) {
  fx?.teardown?.()
}
