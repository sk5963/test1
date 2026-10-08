// FTP 경로 정규화 유틸: 항상 절대경로("/...")로 만들고 ".." 경로 탈출을 차단한다.

/**
 * 사용자가 보낸 경로를 안전한 절대 FTP 경로로 정규화한다.
 * - 역슬래시를 슬래시로 변환
 * - "." / ".." 세그먼트를 해석하되 루트 위로는 못 올라가게 막음
 * - 항상 "/"로 시작하는 경로 반환
 *
 * @param {string} input 원본 경로 (없으면 루트)
 * @returns {string} 정규화된 절대 경로
 */
export function normalizeFtpPath(input) {
  const raw = (input || '/').replace(/\\/g, '/');
  const segments = raw.split('/');
  const stack = [];

  for (const seg of segments) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      // 루트 위로는 못 올라간다.
      if (stack.length > 0) stack.pop();
      continue;
    }
    stack.push(seg);
  }

  return '/' + stack.join('/');
}

/**
 * 부모 경로를 반환한다 (브레드크럼/상위 이동용).
 * @param {string} input
 * @returns {string}
 */
export function parentFtpPath(input) {
  const normalized = normalizeFtpPath(input);
  if (normalized === '/') return '/';
  const idx = normalized.lastIndexOf('/');
  return idx <= 0 ? '/' : normalized.slice(0, idx);
}
