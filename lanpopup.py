"""
LAN 팝업 메신저 (초간단)

같은 네트워크 안에서 한쪽이 보낸 메시지를 받는 쪽 화면에 팝업으로 띄워줍니다.
팝업은 사용자가 "확인" 또는 "답장"을 누를 때까지 깜빡이며 주의를 끕니다.
외부 라이브러리 없이 Python 표준 라이브러리(socket, tkinter)만 사용합니다.

[받는 쪽] 팝업을 띄울 PC에서 먼저 실행:
    python lanpopup.py recv
    (실행하면 자기 IP가 표시됩니다. 보내는 쪽에 알려주세요.)

[보내는 쪽] 메시지를 보낼 때:
    python lanpopup.py send 192.168.0.10 "점심 먹으러 갈까요?"
    (192.168.0.10 자리에 받는 쪽 PC의 IP를 넣으세요.)

* 답장 기능: 받은 팝업에서 "답장"을 누르면 보낸 사람에게 메시지를 되돌려 보냅니다.
  단, 보낸 사람 PC에서도 `python lanpopup.py recv` 가 떠 있어야 답장 팝업을 받습니다.

포트는 기본 50505 입니다. 바꾸려면 --port 옵션을 쓰세요.
"""

import argparse
import queue
import socket
import sys
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
# Windows 작업표시줄 아이콘 깜빡임 (FlashWindowEx)
# ---------------------------------------------------------------------------
def _hwnd_of(win):
    """tkinter 창의 실제 최상위 윈도우 핸들(HWND)을 구합니다."""
    import ctypes
    return ctypes.windll.user32.GetParent(win.winfo_id())


def flash_taskbar(win, start):
    """작업표시줄 아이콘을 계속 깜빡이게(start=True) 하거나 멈춥니다(start=False).
    Windows가 아니거나 실패하면 조용히 무시합니다."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwnd", ctypes.c_void_p),
                ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_uint),
            ]

        FLASHW_STOP = 0
        FLASHW_ALL = 3          # 제목 표시줄 + 작업표시줄
        FLASHW_TIMER = 4        # 멈출 때까지 계속
        flags = (FLASHW_ALL | FLASHW_TIMER) if start else FLASHW_STOP

        info = FLASHWINFO(
            ctypes.sizeof(FLASHWINFO),
            _hwnd_of(win),
            flags,
            0,
            0,
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 팝업 창 (깜빡임 + 확인 / 답장)
# ---------------------------------------------------------------------------
def show_popup(root, sender_ip, text, port):
    import tkinter as tk
    from tkinter import messagebox

    win = tk.Toplevel(root)
    win.title(f"새 메시지 ({sender_ip})")
    win.geometry("380x230")
    win.attributes("-topmost", True)
    win.lift()
    try:
        win.focus_force()
    except Exception:
        pass

    msg_lbl = tk.Label(win, text=text, wraplength=340, justify="left",
                       font=("", 13), padx=15, pady=15)
    msg_lbl.pack(fill="both", expand=True)

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=12)

    # --- 깜빡임 제어 ---
    state = {"on": True, "running": True}

    def do_blink():
        if not state["running"]:
            return
        color = "#ffe08a" if state["on"] else "#ffffff"
        win.configure(bg=color)
        msg_lbl.configure(bg=color)
        btn_frame.configure(bg=color)
        state["on"] = not state["on"]
        win.after(450, do_blink)

    def stop_blink():
        if not state["running"]:
            return
        state["running"] = False
        for w in (win, msg_lbl, btn_frame):
            w.configure(bg="#ffffff")
        flash_taskbar(win, start=False)

    # --- 버튼 동작 ---
    def on_ok():
        stop_blink()
        win.destroy()

    def on_reply():
        stop_blink()
        for child in btn_frame.winfo_children():
            child.destroy()

        entry = tk.Entry(win, font=("", 12))
        entry.pack(fill="x", padx=15)
        entry.focus_set()

        def send_reply(event=None):
            reply = entry.get().strip()
            if reply:
                try:
                    run_sender(sender_ip, reply, port)
                except Exception as e:
                    messagebox.showerror("전송 실패",
                                         f"{sender_ip} 로 답장을 보내지 못했습니다.\n"
                                         f"상대가 'recv'로 떠 있는지 확인하세요.\n\n{e}")
            win.destroy()

        tk.Button(win, text="보내기", width=10, command=send_reply).pack(pady=10)
        entry.bind("<Return>", send_reply)

    tk.Button(btn_frame, text="확인", width=8, command=on_ok).pack(side="left", padx=6)
    tk.Button(btn_frame, text="답장", width=8, command=on_reply).pack(side="left", padx=6)

    # 닫기(X) 버튼도 확인과 동일하게 처리 (깜빡임 정리)
    win.protocol("WM_DELETE_WINDOW", on_ok)

    # 깜빡임 시작 (작업표시줄 + 창 배경)
    flash_taskbar(win, start=True)
    do_blink()


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

    root = tk.Tk()
    root.withdraw()  # 메인 창은 숨기고 팝업만 사용

    def poll():
        try:
            while True:
                sender_ip, text = msg_queue.get_nowait()
                show_popup(root, sender_ip, text, port)
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
