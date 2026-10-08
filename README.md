# FTP 모바일 뷰어

안드로이드/아이폰 등 **모바일 웹브라우저에서 FTP 서버의 파일을 받아 보여주는 뷰어**입니다.
이미지·PDF·텍스트/코드 파일을 폰에서 바로 열어볼 수 있고, 다운로드도 됩니다.

## 동작 원리

최신 모바일 브라우저(Chrome, Safari 등)는 `ftp://` 프로토콜을 더 이상 지원하지 않습니다.
그래서 이 앱은 **백엔드(Node.js) 서버가 FTP에 대신 접속해 파일을 받아 HTTP로 중계**하는 구조입니다.

```
[폰 브라우저] ──HTTP/HTTPS──> [이 앱(백엔드)] ──FTP──> [FTP 서버]
   FTP 몰라도 됨               여기서만 FTP 사용
```

- 폰에는 **웹브라우저만** 있으면 됩니다(앱 설치 불필요).
- 여러 FTP 서버 접속 정보를 **저장해두고 골라서 접속**합니다.

## 설치 & 실행

```bash
npm install
cp .env.example .env      # SESSION_SECRET 등을 적절히 수정
npm start                 # 기본 http://localhost:3000
```

개발 중 자동 재시작: `npm run dev`

브라우저(또는 폰)에서 서버 주소로 접속 → "FTP 서버 추가"로 접속 정보를 등록 → 서버를 선택해 파일을 탐색/조회합니다.

## 환경변수 (.env)

| 변수 | 설명 |
| --- | --- |
| `SESSION_SECRET` | 세션 쿠키 서명용 시크릿. **운영 시 반드시 임의의 긴 문자열로 변경** |
| `PORT` | 서버 포트(기본 3000) |
| `NODE_ENV` | `production`이면 secure 쿠키 활성화(HTTPS 필요) |

## 지원 파일 형식 (뷰어)

- **이미지**: jpg, png, gif, webp, bmp, svg
- **PDF**: PDF.js로 렌더링
- **텍스트/코드**: txt, log, csv, md, json, xml, 각종 소스코드 등 → 구문 강조 표시
- 그 외 형식은 미리보기 대신 다운로드로 받을 수 있습니다.
- 뷰어 표시는 메모리 보호를 위해 최대 20MB까지(`src/routes/files.js`의 `MAX_VIEW_BYTES`). 더 큰 파일은 다운로드를 이용하세요.

## 폰에서 접속하기 (네트워크/배포)

FTP 서버는 **이 앱(백엔드)에서 접속 가능한 위치**에만 있으면 되고, 폰과 같은 네트워크일 필요는 없습니다.
폰은 백엔드(HTTP/HTTPS)에만 닿으면 됩니다.

- **FTP가 내부망(사설 IP)에 있는 경우**: 이 앱을 그 내부망 안의 머신(PC/NAS/라즈베리파이 등)에서 실행하고,
  백엔드만 외부에서 접근하도록 공유기 포트포워딩 또는 터널(예: ngrok, Cloudflare Tunnel)로 노출합니다.
  그러면 폰은 LTE/외부 와이파이에서도 접속할 수 있습니다.
- **FTP가 인터넷에 공개된 경우**: 이 앱을 로컬/클라우드 어디서 실행해도 됩니다.

> 두 경우 모두 FTP 계정/비밀번호가 전송되므로, 외부에 노출한다면 **HTTPS 적용을 권장**합니다.

## 보안 메모

- FTP 접속 정보는 서버의 `data/servers.json`에 저장됩니다(비밀번호 포함, 파일 권한 0600).
  이 파일은 `.gitignore`에 포함되어 커밋되지 않습니다. **평문 저장**이므로 서버 접근 통제에 유의하세요.
- API 응답과 로그에는 비밀번호가 노출되지 않습니다.
- 경로 탈출(`../`)은 서버에서 차단됩니다.
- 이 앱 자체에는 별도 로그인이 없습니다(서버 주소를 아는 사람이 사용). 공개망에 둘 경우 리버스 프록시의
  기본 인증(Basic Auth)이나 별도 인증 계층을 앞단에 두는 것을 권장합니다.

## 로컬에서 테스트용 FTP 띄우기 (선택)

테스트용 FTP가 없다면 Docker로 간단히 띄울 수 있습니다.

```bash
docker run -d --name testftp -p 21:21 -p 21000-21010:21000-21010 \
  -e FTP_USER=test -e FTP_PASS=test \
  -e PASV_ADDRESS=127.0.0.1 fauria/vsftpd
```

## 프로젝트 구조

```
src/
  server.js            Express 앱 (세션, 정적, 라우트)
  ftp.js               FTP 연결 헬퍼 (withFtp)
  store.js             FTP 프로필 저장소 (data/servers.json)
  routes/servers.js    프로필 CRUD + connect
  routes/files.js      디렉터리 목록 + 파일 중계
  util/ftpPath.js      경로 정규화/탈출 방지
  util/filetype.js     확장자→카테고리/MIME
public/
  index.html, css/styles.css, js/app.js   모바일 반응형 프론트엔드
```
