// 파일 탐색(list) + 파일 중계(file) 라우트. 세션에 선택된 서버 프로필을 사용한다.

import { Router } from 'express';
import { Writable } from 'node:stream';
import { getProfile } from '../store.js';
import { withFtp } from '../ftp.js';
import { normalizeFtpPath } from '../util/ftpPath.js';
import { getCategory, getMimeType } from '../util/filetype.js';

const router = Router();

// 뷰어로 메모리에 올려 보여줄 때의 최대 크기 (텍스트/이미지/PDF view 모드)
const MAX_VIEW_BYTES = 20 * 1024 * 1024; // 20MB

// 세션에 선택된 서버 프로필을 가져오는 미들웨어
async function requireServer(req, res, next) {
  try {
    const id = req.session.serverId;
    if (!id) return res.status(401).json({ error: '먼저 서버를 선택(연결)하세요.' });
    const profile = await getProfile(id);
    if (!profile) {
      delete req.session.serverId;
      return res.status(401).json({ error: '연결된 서버 프로필이 없습니다. 다시 선택하세요.' });
    }
    req.ftpProfile = profile;
    next();
  } catch (err) {
    next(err);
  }
}

// 디렉터리 목록
router.get('/list', requireServer, async (req, res, next) => {
  const dirPath = normalizeFtpPath(req.query.path);
  try {
    const items = await withFtp(req.ftpProfile, (client) => client.list(dirPath));
    const entries = items
      .map((item) => {
        const isDir = item.isDirectory;
        return {
          name: item.name,
          type: isDir ? 'dir' : 'file',
          size: item.size,
          modifiedAt: item.modifiedAt ? item.modifiedAt.toISOString() : null,
          category: isDir ? 'dir' : getCategory(item.name),
        };
      })
      // 폴더 먼저, 그 다음 이름순
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });

    res.json({ path: dirPath, entries });
  } catch (err) {
    res.status(502).json({ error: '디렉터리를 읽을 수 없습니다.', detail: String(err.message || err) });
  }
});

// 파일 중계 (view: 인라인 표시 / download: 첨부 다운로드)
router.get('/file', requireServer, async (req, res, next) => {
  const filePath = normalizeFtpPath(req.query.path);
  const mode = req.query.mode === 'download' ? 'download' : 'view';
  const name = filePath.split('/').pop() || 'file';

  try {
    // 파일을 메모리 버퍼로 받는다 (뷰어 용도, 크기 제한 적용)
    const chunks = [];
    let total = 0;
    let tooLarge = false;

    const sink = new Writable({
      write(chunk, _enc, cb) {
        total += chunk.length;
        if (total > MAX_VIEW_BYTES) {
          tooLarge = true;
          return cb(new Error('FILE_TOO_LARGE'));
        }
        chunks.push(chunk);
        cb();
      },
    });

    try {
      await withFtp(req.ftpProfile, (client) => client.downloadTo(sink, filePath));
    } catch (err) {
      if (tooLarge) {
        return res.status(413).json({
          error: `파일이 너무 큽니다(최대 ${MAX_VIEW_BYTES / 1024 / 1024}MB). 다운로드 버튼으로 받으세요.`,
        });
      }
      throw err;
    }

    const buffer = Buffer.concat(chunks, total);
    res.setHeader('Content-Type', getMimeType(name));
    res.setHeader('Content-Length', buffer.length);
    if (mode === 'download') {
      const encoded = encodeURIComponent(name);
      res.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encoded}`);
    } else {
      res.setHeader('Content-Disposition', 'inline');
    }
    res.send(buffer);
  } catch (err) {
    res.status(502).json({ error: '파일을 가져올 수 없습니다.', detail: String(err.message || err) });
  }
});

export default router;
