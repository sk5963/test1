// FTP 프로필 관리 + 서버 선택(connect) 라우트.

import { Router } from 'express';
import {
  readProfiles,
  getProfile,
  addProfile,
  updateProfile,
  deleteProfile,
  toPublic,
} from '../store.js';
import { verifyConnection } from '../ftp.js';

const router = Router();

// 저장된 프로필 목록 (비밀번호 제외)
router.get('/servers', async (req, res, next) => {
  try {
    const profiles = await readProfiles();
    res.json({
      servers: profiles.map(toPublic),
      connectedId: req.session.serverId || null,
    });
  } catch (err) {
    next(err);
  }
});

// 프로필 추가
router.post('/servers', async (req, res, next) => {
  try {
    const { label, host, port, secure, username, password } = req.body || {};
    if (!host || !username) {
      return res.status(400).json({ error: '호스트와 사용자명은 필수입니다.' });
    }
    const profile = await addProfile({ label, host, port, secure, username, password });
    res.status(201).json(toPublic(profile));
  } catch (err) {
    next(err);
  }
});

// 프로필 수정
router.put('/servers/:id', async (req, res, next) => {
  try {
    const { label, host, port, secure, username, password } = req.body || {};
    if (!host || !username) {
      return res.status(400).json({ error: '호스트와 사용자명은 필수입니다.' });
    }
    const profile = await updateProfile(req.params.id, {
      label, host, port, secure, username, password,
    });
    if (!profile) return res.status(404).json({ error: '프로필을 찾을 수 없습니다.' });
    res.json(toPublic(profile));
  } catch (err) {
    next(err);
  }
});

// 프로필 삭제
router.delete('/servers/:id', async (req, res, next) => {
  try {
    const ok = await deleteProfile(req.params.id);
    if (!ok) return res.status(404).json({ error: '프로필을 찾을 수 없습니다.' });
    // 현재 연결된 서버를 지웠다면 세션 선택도 해제
    if (req.session.serverId === req.params.id) {
      delete req.session.serverId;
    }
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

// 서버 선택(연결): 프로필로 실제 접속을 검증한 뒤 세션에 저장
router.post('/connect', async (req, res, next) => {
  try {
    const { id } = req.body || {};
    const profile = await getProfile(id);
    if (!profile) return res.status(404).json({ error: '프로필을 찾을 수 없습니다.' });

    try {
      await verifyConnection(profile);
    } catch (err) {
      return res.status(502).json({
        error: 'FTP 접속에 실패했습니다. 주소/계정/비밀번호를 확인하세요.',
        detail: String(err.message || err),
      });
    }

    req.session.serverId = id;
    res.json({ ok: true, server: toPublic(profile) });
  } catch (err) {
    next(err);
  }
});

// 연결 해제
router.post('/disconnect', (req, res) => {
  delete req.session.serverId;
  res.json({ ok: true });
});

export default router;
