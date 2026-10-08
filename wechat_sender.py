"""기업위챗(WeCom) 그룹봇 웹훅으로 메시지를 전송하는 모듈.

웹훅 키만 있으면 별도 심사 없이 텍스트/마크다운/이미지 메시지를 보낼 수 있습니다.
키는 기업위챗 그룹 채팅 > 그룹봇 추가 시 발급되는 URL의 ``key`` 파라미터입니다.

사용 예 (코드):
    sender = WeChatSender("발급받은-웹훅-키")
    sender.send_text("안녕하세요!")
    sender.send_markdown("# 제목\\n- 항목1\\n- 항목2")

사용 예 (CLI):
    python wechat_sender.py --key <KEY> text "안녕하세요"
    python wechat_sender.py --key <KEY> markdown "# 제목"
    WECHAT_WEBHOOK_KEY=<KEY> python wechat_sender.py text "키는 환경변수로도 가능"
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request
from typing import Optional, Sequence

WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


class WeChatError(Exception):
    """위챗 API 호출이 실패했을 때 발생하는 예외."""


class WeChatSender:
    """기업위챗 그룹봇 웹훅 클라이언트."""

    def __init__(self, key: str, *, timeout: float = 10.0) -> None:
        if not key:
            raise ValueError("웹훅 키가 필요합니다.")
        self.key = key
        self.timeout = timeout

    def _post(self, payload: dict) -> dict:
        """웹훅에 JSON 페이로드를 전송하고 응답을 반환한다."""
        url = f"{WEBHOOK_URL}?key={self.key}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:  # 네트워크/연결 오류
            raise WeChatError(f"네트워크 오류: {exc}") from exc

        # 위챗은 HTTP 200으로 응답하면서 본문의 errcode로 결과를 알려준다.
        if result.get("errcode", 0) != 0:
            raise WeChatError(
                f"전송 실패 (errcode={result.get('errcode')}): "
                f"{result.get('errmsg', '알 수 없는 오류')}"
            )
        return result

    def send_text(
        self,
        content: str,
        *,
        mentioned_list: Optional[Sequence[str]] = None,
        mentioned_mobile_list: Optional[Sequence[str]] = None,
    ) -> dict:
        """일반 텍스트 메시지를 전송한다.

        mentioned_list: 멘션할 사용자 ID 목록 (전체 멘션은 ``["@all"]``).
        mentioned_mobile_list: 멘션할 전화번호 목록.
        """
        text: dict = {"content": content}
        if mentioned_list:
            text["mentioned_list"] = list(mentioned_list)
        if mentioned_mobile_list:
            text["mentioned_mobile_list"] = list(mentioned_mobile_list)
        return self._post({"msgtype": "text", "text": text})

    def send_markdown(self, content: str) -> dict:
        """마크다운 메시지를 전송한다. (제목, 목록, 색상 강조 등 지원)"""
        return self._post({"msgtype": "markdown", "markdown": {"content": content}})

    def send_image(self, image_path: str) -> dict:
        """로컬 이미지 파일을 전송한다. (PNG/JPG, 2MB 이하)"""
        with open(image_path, "rb") as fp:
            raw = fp.read()
        payload = {
            "msgtype": "image",
            "image": {
                "base64": base64.b64encode(raw).decode("utf-8"),
                "md5": hashlib.md5(raw).hexdigest(),
            },
        }
        return self._post(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="기업위챗(WeCom) 그룹봇으로 메시지를 전송합니다."
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("WECHAT_WEBHOOK_KEY"),
        help="웹훅 키 (또는 환경변수 WECHAT_WEBHOOK_KEY 사용)",
    )
    sub = parser.add_subparsers(dest="msgtype", required=True)

    p_text = sub.add_parser("text", help="텍스트 메시지")
    p_text.add_argument("content", help="보낼 내용")
    p_text.add_argument(
        "--mention", nargs="*", default=None, help="멘션할 사용자 ID (전체는 @all)"
    )

    p_md = sub.add_parser("markdown", help="마크다운 메시지")
    p_md.add_argument("content", help="보낼 마크다운 내용")

    p_img = sub.add_parser("image", help="이미지 메시지")
    p_img.add_argument("path", help="이미지 파일 경로")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.key:
        print("오류: 웹훅 키가 없습니다. --key 또는 WECHAT_WEBHOOK_KEY로 지정하세요.",
              file=sys.stderr)
        return 2

    sender = WeChatSender(args.key)
    try:
        if args.msgtype == "text":
            sender.send_text(args.content, mentioned_list=args.mention)
        elif args.msgtype == "markdown":
            sender.send_markdown(args.content)
        elif args.msgtype == "image":
            sender.send_image(args.path)
    except (WeChatError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print("전송 성공 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
