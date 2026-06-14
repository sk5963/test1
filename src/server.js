// Express 앱 진입점: 세션, 정적 파일, API 라우트를 구성한다.

import express from 'express';
import session from 'express-session';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import serversRouter from './routes/servers.js';
import filesRouter from './routes/files.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = process.env.PORT || 3000;
const SESSION_SECRET = process.env.SESSION_SECRET || 'dev-insecure-secret-change-me';

const app = express();

app.use(express.json());

app.use(
  session({
    secret: SESSION_SECRET,
    resave: false,
    saveUninitialized: false,
    cookie: {
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 1000 * 60 * 60 * 8, // 8시간
      // 운영(HTTPS)에서는 secure 쿠키 권장: NODE_ENV=production일 때 활성화
      secure: process.env.NODE_ENV === 'production',
    },
  })
);

// HTTPS 뒤(프록시/터널)에서 secure 쿠키가 동작하도록
app.set('trust proxy', 1);

// API
app.use('/api', serversRouter);
app.use('/api', filesRouter);

// 정적 프론트엔드
app.use(express.static(path.join(__dirname, '..', 'public')));

// 헬스 체크
app.get('/health', (_req, res) => res.json({ ok: true }));

// 공통 에러 핸들러 (민감정보 노출 방지)
app.use((err, _req, res, _next) => {
  console.error('[error]', err.message);
  res.status(500).json({ error: '서버 오류가 발생했습니다.' });
});

app.listen(PORT, () => {
  console.log(`FTP 모바일 뷰어 서버 실행 중: http://localhost:${PORT}`);
});
