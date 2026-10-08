// FTP 연결 헬퍼: 프로필 하나로 연결을 열고 작업한 뒤 항상 닫는다.
// 연결을 오래 유지하지 않고 요청마다 새로 여는 편이 안정적이다.

import { Client } from 'basic-ftp';

/**
 * 주어진 FTP 프로필로 연결한 뒤 콜백을 실행하고, 끝나면 연결을 닫는다.
 *
 * @template T
 * @param {{host:string, port?:number, secure?:boolean, username:string, password:string}} profile
 * @param {(client: import('basic-ftp').Client) => Promise<T>} fn
 * @returns {Promise<T>}
 */
export async function withFtp(profile, fn) {
  const client = new Client(30_000); // 30초 타임아웃
  // 비밀번호 등 민감정보가 로그에 찍히지 않도록 verbose 비활성화
  client.ftp.verbose = false;

  try {
    await client.access({
      host: profile.host,
      port: profile.port || 21,
      user: profile.username,
      password: profile.password,
      secure: !!profile.secure,
      // 자체서명 인증서 FTPS도 허용 (내부망 사용 대비)
      secureOptions: { rejectUnauthorized: false },
    });
    return await fn(client);
  } finally {
    client.close();
  }
}

/**
 * 프로필 접속이 가능한지 검증한다 (connect 시 사용).
 * @param {object} profile
 * @returns {Promise<void>} 실패 시 throw
 */
export async function verifyConnection(profile) {
  await withFtp(profile, async (client) => {
    // 루트 목록을 한 번 가져와 접속/인증을 확인한다.
    await client.list('/');
  });
}
