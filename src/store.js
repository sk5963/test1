// FTP 프로필 저장소: data/servers.json 파일에 프로필 목록을 읽고 쓴다.

import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, '..', 'data');
const STORE_PATH = path.join(DATA_DIR, 'servers.json');

/**
 * 저장된 프로필 전체를 읽는다. 파일이 없으면 빈 배열.
 * @returns {Promise<Array<object>>}
 */
export async function readProfiles() {
  try {
    const raw = await fs.readFile(STORE_PATH, 'utf-8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    if (err.code === 'ENOENT') return [];
    throw err;
  }
}

/**
 * 프로필 전체를 파일에 쓴다 (디렉터리/권한 보장).
 * @param {Array<object>} profiles
 */
async function writeProfiles(profiles) {
  await fs.mkdir(DATA_DIR, { recursive: true });
  // 비밀번호가 들어가므로 소유자만 읽고 쓰도록 권한 제한 (0600)
  await fs.writeFile(STORE_PATH, JSON.stringify(profiles, null, 2), { mode: 0o600 });
  // 기존 파일이 있었다면 권한을 명시적으로 다시 설정
  await fs.chmod(STORE_PATH, 0o600).catch(() => {});
}

/**
 * 단일 프로필을 id로 조회한다 (비밀번호 포함, 내부용).
 * @param {string} id
 * @returns {Promise<object|undefined>}
 */
export async function getProfile(id) {
  const profiles = await readProfiles();
  return profiles.find((p) => p.id === id);
}

/**
 * 새 프로필을 추가한다. id가 자동 생성된다.
 * @param {object} data {label, host, port, secure, username, password}
 * @returns {Promise<object>} 생성된 프로필
 */
export async function addProfile(data) {
  const profiles = await readProfiles();
  const profile = normalize({ ...data, id: crypto.randomUUID() });
  profiles.push(profile);
  await writeProfiles(profiles);
  return profile;
}

/**
 * 기존 프로필을 수정한다. 비밀번호가 비어 있으면 기존 값을 유지한다.
 * @param {string} id
 * @param {object} data
 * @returns {Promise<object|undefined>} 수정된 프로필 또는 undefined(없음)
 */
export async function updateProfile(id, data) {
  const profiles = await readProfiles();
  const idx = profiles.findIndex((p) => p.id === id);
  if (idx === -1) return undefined;

  const existing = profiles[idx];
  const merged = normalize({
    ...data,
    id,
    // 비밀번호를 비워서 보냈으면 기존 비밀번호 유지
    password: data.password ? data.password : existing.password,
  });
  profiles[idx] = merged;
  await writeProfiles(profiles);
  return merged;
}

/**
 * 프로필을 삭제한다.
 * @param {string} id
 * @returns {Promise<boolean>} 삭제 여부
 */
export async function deleteProfile(id) {
  const profiles = await readProfiles();
  const next = profiles.filter((p) => p.id !== id);
  if (next.length === profiles.length) return false;
  await writeProfiles(next);
  return true;
}

/**
 * 프로필을 안전한 형태로 정규화한다.
 */
function normalize(data) {
  return {
    id: data.id,
    label: String(data.label || '').trim() || String(data.host || '').trim(),
    host: String(data.host || '').trim(),
    port: Number(data.port) || 21,
    secure: !!data.secure,
    username: String(data.username || '').trim(),
    password: String(data.password || ''),
  };
}

/**
 * 클라이언트에 노출할 때 비밀번호를 제거한 형태로 변환한다.
 * @param {object} profile
 * @returns {object}
 */
export function toPublic(profile) {
  const { password, ...rest } = profile;
  return { ...rest, hasPassword: !!password };
}
