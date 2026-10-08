// FTP 모바일 뷰어 클라이언트 로직 (Vanilla JS, ES module)

const PDFJS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs';
const PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs';

// ---------- DOM 참조 ----------
const el = (id) => document.getElementById(id);
const views = {
  servers: el('serversView'),
  files: el('filesView'),
  viewer: el('viewerView'),
};
const titleEl = el('title');
const backBtn = el('backBtn');
const changeServerBtn = el('changeServerBtn');

// ---------- 상태 ----------
let currentServerLabel = '';
let currentPath = '/';

// ---------- 공통 유틸 ----------
function showLoading(on) {
  el('loading').hidden = !on;
}

let toastTimer;
function toast(msg) {
  const t = el('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2800);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let data = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) data = await res.json();
  if (!res.ok) {
    const msg = (data && data.error) || `요청 실패 (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

function formatSize(bytes) {
  if (bytes == null) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let n = bytes, i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function showView(name) {
  for (const [key, node] of Object.entries(views)) {
    node.hidden = key !== name;
  }
  const inServers = name === 'servers';
  backBtn.hidden = inServers;
  changeServerBtn.hidden = inServers;
}

// ==================================================================
// 1) 서버 선택 / 관리
// ==================================================================
async function loadServers() {
  showLoading(true);
  try {
    const { servers } = await api('/api/servers');
    renderServers(servers);
    titleEl.textContent = 'FTP 서버';
    showView('servers');
  } catch (err) {
    toast(err.message);
  } finally {
    showLoading(false);
  }
}

function renderServers(servers) {
  const list = el('serverList');
  list.innerHTML = '';
  if (!servers.length) {
    list.innerHTML = '<div class="empty">저장된 FTP 서버가 없습니다.<br>아래 버튼으로 추가하세요.</div>';
    return;
  }
  for (const s of servers) {
    const card = document.createElement('div');
    card.className = 'server-card';
    card.innerHTML = `
      <div class="info">
        <div class="label">${escapeHtml(s.label)}</div>
        <div class="host">${escapeHtml(s.username)}@${escapeHtml(s.host)}:${s.port}${s.secure ? ' · FTPS' : ''}</div>
      </div>
      <div class="card-actions">
        <button class="edit" title="수정">✎</button>
        <button class="del" title="삭제">🗑</button>
      </div>`;
    card.querySelector('.info').addEventListener('click', () => connectServer(s));
    card.querySelector('.edit').addEventListener('click', (e) => { e.stopPropagation(); openModal(s); });
    card.querySelector('.del').addEventListener('click', (e) => { e.stopPropagation(); deleteServer(s); });
    list.appendChild(card);
  }
}

async function connectServer(server) {
  showLoading(true);
  try {
    await api('/api/connect', { method: 'POST', body: JSON.stringify({ id: server.id }) });
    currentServerLabel = server.label;
    currentPath = '/';
    await loadDir('/');
  } catch (err) {
    toast(err.message);
  } finally {
    showLoading(false);
  }
}

async function deleteServer(server) {
  if (!confirm(`"${server.label}" 서버를 삭제할까요?`)) return;
  showLoading(true);
  try {
    await api(`/api/servers/${server.id}`, { method: 'DELETE' });
    await loadServers();
  } catch (err) {
    toast(err.message);
  } finally {
    showLoading(false);
  }
}

// ---------- 서버 추가/수정 모달 ----------
function openModal(server) {
  const form = el('serverForm');
  form.reset();
  el('modalTitle').textContent = server ? 'FTP 서버 수정' : 'FTP 서버 추가';
  form.id.value = server ? server.id : '';
  if (server) {
    form.label.value = server.label || '';
    form.host.value = server.host || '';
    form.port.value = server.port || 21;
    form.secure.checked = !!server.secure;
    form.username.value = server.username || '';
    form.password.placeholder = '비우면 기존 비밀번호 유지';
  } else {
    form.port.value = 21;
    form.password.placeholder = '';
  }
  el('serverModal').hidden = false;
}

function closeModal() {
  el('serverModal').hidden = true;
}

async function submitServer(e) {
  e.preventDefault();
  const form = el('serverForm');
  const id = form.id.value;
  const payload = {
    label: form.label.value,
    host: form.host.value,
    port: Number(form.port.value) || 21,
    secure: form.secure.checked,
    username: form.username.value,
    password: form.password.value,
  };
  showLoading(true);
  try {
    if (id) {
      await api(`/api/servers/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
    } else {
      await api('/api/servers', { method: 'POST', body: JSON.stringify(payload) });
    }
    closeModal();
    await loadServers();
  } catch (err) {
    toast(err.message);
  } finally {
    showLoading(false);
  }
}

// ==================================================================
// 2) 파일 탐색
// ==================================================================
async function loadDir(path) {
  showLoading(true);
  try {
    const data = await api(`/api/list?path=${encodeURIComponent(path)}`);
    currentPath = data.path;
    renderBreadcrumb(currentPath);
    renderFiles(data.entries);
    titleEl.textContent = currentServerLabel || 'FTP';
    showView('files');
  } catch (err) {
    toast(err.message);
  } finally {
    showLoading(false);
  }
}

function renderBreadcrumb(path) {
  const nav = el('breadcrumb');
  nav.innerHTML = '';
  const parts = path.split('/').filter(Boolean);
  const root = document.createElement('a');
  root.textContent = '🏠 /';
  root.href = '#';
  root.addEventListener('click', (e) => { e.preventDefault(); loadDir('/'); });
  nav.appendChild(root);

  let acc = '';
  parts.forEach((part) => {
    acc += '/' + part;
    const sep = document.createElement('span');
    sep.className = 'sep';
    sep.textContent = '›';
    nav.appendChild(sep);
    const a = document.createElement('a');
    a.textContent = part;
    a.href = '#';
    const target = acc;
    a.addEventListener('click', (e) => { e.preventDefault(); loadDir(target); });
    nav.appendChild(a);
  });
}

const CATEGORY_ICON = {
  dir: '📁', image: '🖼️', pdf: '📄', text: '📝', other: '📦',
};

function renderFiles(entries) {
  const list = el('fileList');
  list.innerHTML = '';
  if (!entries.length) {
    list.innerHTML = '<li class="empty">이 폴더는 비어 있습니다.</li>';
    return;
  }
  for (const item of entries) {
    const li = document.createElement('li');
    li.className = 'file-item';
    const icon = CATEGORY_ICON[item.category] || CATEGORY_ICON.other;
    const meta = item.type === 'dir' ? '폴더' : formatSize(item.size);
    li.innerHTML = `
      <div class="fi-icon">${icon}</div>
      <div class="fi-main">
        <div class="fi-name">${escapeHtml(item.name)}</div>
        <div class="fi-meta">${meta}</div>
      </div>`;
    const fullPath = joinPath(currentPath, item.name);
    if (item.type === 'dir') {
      li.addEventListener('click', () => loadDir(fullPath));
    } else {
      li.addEventListener('click', () => openViewer(fullPath, item));
      // 다운로드 버튼
      const dl = document.createElement('button');
      dl.className = 'fi-dl';
      dl.textContent = '⤓';
      dl.title = '다운로드';
      dl.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadFile(fullPath);
      });
      li.appendChild(dl);
    }
    list.appendChild(li);
  }
}

function joinPath(dir, name) {
  return (dir === '/' ? '' : dir) + '/' + name;
}

function downloadFile(path) {
  const url = `/api/file?path=${encodeURIComponent(path)}&mode=download`;
  const a = document.createElement('a');
  a.href = url;
  a.download = path.split('/').pop() || 'file';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ==================================================================
// 3) 뷰어
// ==================================================================
async function openViewer(path, item) {
  const name = item.name;
  const container = el('viewerContent');
  container.innerHTML = '';
  titleEl.textContent = name;
  el('downloadLink').href = `/api/file?path=${encodeURIComponent(path)}&mode=download`;
  el('downloadLink').setAttribute('download', name);
  showView('viewer');

  const viewUrl = `/api/file?path=${encodeURIComponent(path)}&mode=view`;

  if (item.category === 'image') {
    const img = document.createElement('img');
    img.src = viewUrl;
    img.alt = name;
    img.onerror = () => { container.innerHTML = '<div class="empty">이미지를 불러올 수 없습니다.</div>'; };
    container.appendChild(img);
    return;
  }

  if (item.category === 'pdf') {
    await renderPdf(viewUrl, container);
    return;
  }

  if (item.category === 'text') {
    await renderText(viewUrl, name, container);
    return;
  }

  // 그 외: 브라우저에 표시 불가 → 다운로드 안내
  container.innerHTML =
    '<div class="empty">미리보기를 지원하지 않는 형식입니다.<br>아래 다운로드 버튼을 이용하세요.</div>';
}

async function renderText(url, name, container) {
  showLoading(true);
  try {
    const res = await fetch(url);
    if (!res.ok) {
      let msg = '텍스트를 불러올 수 없습니다.';
      try { const d = await res.json(); if (d.error) msg = d.error; } catch {}
      container.innerHTML = `<div class="empty">${escapeHtml(msg)}</div>`;
      return;
    }
    const text = await res.text();
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = text;
    pre.appendChild(code);
    container.appendChild(pre);
    // 구문 강조 (hljs 전역)
    if (window.hljs) {
      try { window.hljs.highlightElement(code); } catch {}
    }
  } catch (err) {
    container.innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  } finally {
    showLoading(false);
  }
}

let pdfLibPromise;
function loadPdfLib() {
  if (!pdfLibPromise) {
    pdfLibPromise = import(PDFJS_URL).then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
      return lib;
    });
  }
  return pdfLibPromise;
}

async function renderPdf(url, container) {
  showLoading(true);
  try {
    const pdfjsLib = await loadPdfLib();
    const res = await fetch(url);
    if (!res.ok) {
      container.innerHTML = '<div class="empty">PDF를 불러올 수 없습니다.</div>';
      return;
    }
    const buf = await res.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    const maxWidth = Math.min(container.clientWidth || window.innerWidth, 900);
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const viewport0 = page.getViewport({ scale: 1 });
      const scale = maxWidth / viewport0.width;
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      container.appendChild(canvas);
      await page.render({ canvasContext: ctx, viewport }).promise;
    }
  } catch (err) {
    container.innerHTML = `<div class="empty">PDF 렌더링 실패: ${escapeHtml(err.message)}</div>`;
  } finally {
    showLoading(false);
  }
}

// ==================================================================
// 네비게이션 / 이벤트
// ==================================================================
function goBack() {
  if (!views.viewer.hidden) {
    // 뷰어 → 파일 목록
    loadDir(currentPath);
  } else if (!views.files.hidden) {
    if (currentPath !== '/') {
      const parent = currentPath.slice(0, currentPath.lastIndexOf('/')) || '/';
      loadDir(parent);
    } else {
      // 루트 → 서버 목록
      loadServers();
    }
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// 이벤트 바인딩
backBtn.addEventListener('click', goBack);
changeServerBtn.addEventListener('click', () => {
  api('/api/disconnect', { method: 'POST' }).finally(loadServers);
});
el('addServerBtn').addEventListener('click', () => openModal(null));
el('cancelModalBtn').addEventListener('click', closeModal);
el('serverForm').addEventListener('submit', submitServer);
el('serverModal').addEventListener('click', (e) => {
  if (e.target.id === 'serverModal') closeModal();
});

// 시작
loadServers();
