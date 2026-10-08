// 파일 확장자 기반으로 뷰어 카테고리와 MIME 타입을 판별한다.

const IMAGE_TYPES = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  gif: 'image/gif',
  webp: 'image/webp',
  bmp: 'image/bmp',
  svg: 'image/svg+xml',
  ico: 'image/x-icon',
};

const PDF_TYPES = {
  pdf: 'application/pdf',
};

// 텍스트로 표시할 확장자 (코드/설정/로그 포함)
const TEXT_EXTENSIONS = new Set([
  'txt', 'text', 'log', 'csv', 'tsv', 'md', 'markdown', 'rtf',
  'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'conf', 'cfg', 'env',
  'js', 'mjs', 'cjs', 'ts', 'jsx', 'tsx', 'css', 'scss', 'less', 'html', 'htm',
  'py', 'rb', 'php', 'java', 'c', 'h', 'cpp', 'hpp', 'cc', 'cs', 'go', 'rs',
  'sh', 'bash', 'zsh', 'sql', 'pl', 'lua', 'swift', 'kt', 'dart', 'r',
  'gradle', 'properties', 'gitignore', 'dockerfile', 'makefile',
]);

/**
 * 파일명에서 확장자(소문자)를 추출한다.
 * @param {string} name
 * @returns {string}
 */
export function getExtension(name) {
  const base = name.split('/').pop() || '';
  const dot = base.lastIndexOf('.');
  if (dot <= 0) {
    // 확장자가 없지만 알려진 파일명(Dockerfile, Makefile 등) 처리
    return base.toLowerCase();
  }
  return base.slice(dot + 1).toLowerCase();
}

/**
 * 파일명을 받아 뷰어 카테고리를 반환한다.
 * @param {string} name
 * @returns {'image'|'pdf'|'text'|'other'}
 */
export function getCategory(name) {
  const ext = getExtension(name);
  if (ext in IMAGE_TYPES) return 'image';
  if (ext in PDF_TYPES) return 'pdf';
  if (TEXT_EXTENSIONS.has(ext)) return 'text';
  return 'other';
}

/**
 * 파일명을 받아 응답에 쓸 Content-Type을 반환한다.
 * @param {string} name
 * @returns {string}
 */
export function getMimeType(name) {
  const ext = getExtension(name);
  if (ext in IMAGE_TYPES) return IMAGE_TYPES[ext];
  if (ext in PDF_TYPES) return PDF_TYPES[ext];
  if (TEXT_EXTENSIONS.has(ext)) return 'text/plain; charset=utf-8';
  return 'application/octet-stream';
}
