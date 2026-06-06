"""
LAN 팝업 메신저 (초간단)

같은 네트워크 안에서 한쪽이 보낸 메시지를 받는 쪽 화면에 팝업으로 띄워줍니다.
외부 라이브러리 없이 Python 표준 라이브러리(socket, tkinter)만 사용합니다.

[받는 쪽] 팝업을 띄울 PC에서 먼저 실행:
    python lanpopup.py recv
    (실행하면 자기 IP가 표시됩니다. 보내는 쪽에 알려주세요.)

[보내는 쪽] 메시지를 보낼 때:
    python lanpopup.py send 192.168.0.10 "점심 먹으러 갈까요?"
    (192.168.0.10 자리에 받는 쪽 PC의 IP를 넣으세요.)

포트는 기본 50505 입니다. 바꾸려면 --port 옵션을 쓰세요.
"""

import argparse
import queue
import socket
import threading

PORT = 50505           # 기본 포트
ENCODING = "utf-8"
BUF = 4096


def get_local_ip():
    """이 PC의 LAN IP 주소를 추정해서 돌려줍니다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 실제로 패킷을 보내지는 않고, 라우팅용 IP만 알아냅니다.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 받는 쪽 (서버 + 팝업)
# ---------------------------------------------------------------------------
def run_receiver(port):
    msg_queue = queue.Queue()

    def server_loop():
        """백그라운드 스레드: 들어오는 메시지를 받아 큐에 넣습니다."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen()
        while True:
            conn, addr = srv.accept()
            with conn:
                chunks = []
                while True:
                    data = conn.recv(BUF)
                    if not data:
                        break
                    chunks.append(data)
            text = b"".join(chunks).decode(ENCODING, errors="replace")
            msg_queue.put((addr[0], text))

    threading.Thread(target=server_loop, daemon=True).start()

    # 팝업은 tkinter로 띄웁니다. tkinter는 반드시 메인 스레드에서 동작해야 하므로
    # 큐를 주기적으로 확인하면서 새 메시지가 오면 팝업을 보여줍니다.
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()  # 메인 창은 숨기고 팝업만 사용

    def poll():
        try:
            while True:
                sender_ip, text = msg_queue.get_nowait()
                # 팝업을 항상 맨 앞으로 가져오기
                root.attributes("-topmost", True)
                messagebox.showinfo(f"새 메시지 ({sender_ip})", text)
        except queue.Empty:
            pass
        root.after(300, poll)

    my_ip = get_local_ip()
    print(f"[수신 대기 중] 내 IP: {my_ip}  포트: {port}")
    print("보내는 쪽에 위 IP를 알려주세요. (종료: Ctrl+C)")
    root.after(300, poll)
    root.mainloop()


# ---------------------------------------------------------------------------
# 보내는 쪽 (클라이언트)
# ---------------------------------------------------------------------------
def run_sender(host, message, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        s.sendall(message.encode(ENCODING))
    print(f"[전송 완료] {host}:{port} -> {message!r}")


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="LAN 팝업 메신저")
    parser.add_argument("--port", type=int, default=PORT, help=f"포트 (기본 {PORT})")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("recv", help="메시지를 받아 팝업을 띄웁니다")

    p_send = sub.add_parser("send", help="메시지를 보냅니다")
    p_send.add_argument("host", help="받는 쪽 PC의 IP 주소")
    p_send.add_argument("message", help="보낼 메시지 (공백 포함 시 따옴표로 감싸세요)")

    args = parser.parse_args()

    if args.mode == "recv":
        run_receiver(args.port)
    elif args.mode == "send":
        run_sender(args.host, args.message, args.port)


if __name__ == "__main__":
    main()
