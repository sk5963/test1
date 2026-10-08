# WeChat Sender

기업위챗(WeCom / 企业微信) **그룹봇 웹훅**으로 메시지를 전송하는 Python 프로그램입니다.
별도 API 심사 없이 웹훅 키만 있으면 텍스트·마크다운·이미지를 보낼 수 있습니다.

## 준비물

1. 기업위챗(WeCom) 그룹 채팅 화면에서 **그룹봇(群机器人) 추가**
2. 발급된 웹훅 URL에서 `key=` 뒤의 값을 복사
   - 예: `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd-1234` → 키는 `abcd-1234`

> 표준 라이브러리만 사용하므로 추가 설치(pip)가 필요 없습니다. (Python 3.8+)

## 사용법 (CLI)

```bash
# 텍스트
python wechat_sender.py --key <KEY> text "안녕하세요!"

# 전체 멘션과 함께
python wechat_sender.py --key <KEY> text "공지입니다" --mention @all

# 마크다운
python wechat_sender.py --key <KEY> markdown "# 배포 완료\n- 버전: v1.2.3"

# 이미지 (PNG/JPG, 2MB 이하)
python wechat_sender.py --key <KEY> image ./chart.png
```

키는 환경변수로도 지정할 수 있습니다:

```bash
export WECHAT_WEBHOOK_KEY=<KEY>
python wechat_sender.py text "키 생략 가능"
```

## 사용법 (코드)

```python
from wechat_sender import WeChatSender

sender = WeChatSender("발급받은-웹훅-키")
sender.send_text("안녕하세요!")
sender.send_markdown("# 제목\n- 항목1\n- 항목2")
sender.send_image("chart.png")
```

## 참고

- 이 방식은 **기업위챗(WeCom)** 전용입니다. 일반 개인 위챗에는 공식 전송 API가 없습니다.
- 공식계정(公众号) 템플릿 메시지나 앱 메시지가 필요하면 별도 인증/토큰 발급이 필요합니다.
