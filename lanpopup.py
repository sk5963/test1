"""
LAN 채팅 (lanpopup.py)

같은 네트워크 안에서 동작하는 초간단 채팅 프로그램입니다.
중앙 서버 1대 + 클라이언트(채팅 창) 구조이며, 표준 라이브러리만 사용합니다.

기능
  - 닉네임(보낸/받는 사람) 표시
  - 서버 접속자 목록 실시간 표시
  - 전체 채팅 / 1:1(DM) / 그룹(방) 채팅
  - 새 메시지가 오면 창/작업표시줄 깜빡임 + 알림음
  - 대화 기록을 로컬 파일에 저장 (다시 열면 이전 대화가 보임)

사용법
  [서버] 한 PC에서 한 번만 실행 (모두가 접속할 PC):
      python lanpopup.py server
      (실행하면 서버 IP가 표시됩니다. 접속자들에게 알려주세요.)

  [클라이언트] 채팅에 참여하는 각 PC에서:
      python lanpopup.py client <서버IP> [닉네임]
      예) python lanpopup.py client 192.168.0.10 홍길동
      (닉네임을 생략하면 실행 후 물어봅니다.)

포트는 기본 50505 입니다. 서버/클라이언트 모두 --port 로 동일하게 맞추세요.
"""

import argparse
import json
import os
import queue
import re
import socket
import sys
import threading
import time
from datetime import datetime

PORT = 50505
ENCODING = "utf-8"
BUF = 4096


def get_local_ip():
    """이 PC의 LAN IP 주소를 추정해서 돌려줍니다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def safe_name(text):
    """파일 이름으로 안전한 문자열로 바꿉니다."""
    return re.sub(r"[^\w.\-]", "_", text) or "_"


# ---------------------------------------------------------------------------
# 줄 단위(JSON) 프로토콜 헬퍼
# ---------------------------------------------------------------------------
def send_json(sock, obj, lock=None):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode(ENCODING)
    if lock is not None:
        with lock:
            sock.sendall(data)
    else:
        sock.sendall(data)


def iter_messages(sock):
    """소켓에서 개행으로 구분된 JSON 객체를 하나씩 돌려줍니다."""
    buf = b""
    while True:
        data = sock.recv(BUF)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line.decode(ENCODING))
            except (ValueError, UnicodeDecodeError):
                continue


# ===========================================================================
# 서버
# ===========================================================================
class ChatServer:
    def __init__(self, port):
        self.port = port
        self.clients = {}          # name -> socket
        self.rooms = {}            # room -> set(names)
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen()
        print(f"[서버 시작] IP: {get_local_ip()}  포트: {self.port}")
        print("접속자들에게 위 IP/포트를 알려주세요. (종료: Ctrl+C)")
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    # ---- 개별 클라이언트 처리 ----
    def _handle(self, conn, addr):
        name = None
        try:
            msgs = iter_messages(conn)
            first = next(msgs)
            if first.get("t") != "hello":
                return
            name = self._register(conn, (first.get("name") or "").strip() or f"user{addr[1]}")
            send_json(conn, {"t": "welcome", "name": name}, self.send_lock)
            print(f"[접속] {name} ({addr[0]})")
            self._broadcast({"t": "sys", "text": f"{name} 님이 입장했습니다."})
            self._broadcast_roster()
            for m in msgs:
                self._process(name, m)
        except (OSError, StopIteration):
            pass
        except Exception as e:  # noqa: BLE001
            print("클라이언트 처리 오류:", e)
        finally:
            if name:
                self._remove(name)

    def _register(self, conn, requested):
        with self.lock:
            base, name, i = requested, requested, 2
            while name in self.clients:
                name = f"{base}_{i}"
                i += 1
            self.clients[name] = conn
            return name

    def _remove(self, name):
        with self.lock:
            self.clients.pop(name, None)
            for members in self.rooms.values():
                members.discard(name)
            self.rooms = {r: m for r, m in self.rooms.items() if m}
        print(f"[퇴장] {name}")
        self._broadcast({"t": "sys", "text": f"{name} 님이 나갔습니다."})
        self._broadcast_roster()

    def _process(self, name, m):
        t = m.get("t")
        text = m.get("text", "")
        ts = time.time()
        if t == "all":
            self._broadcast({"t": "msg", "scope": "all", "from": name, "text": text, "ts": ts})
        elif t == "dm":
            to = m.get("to")
            out = {"t": "msg", "scope": "dm", "from": name, "to": to, "text": text, "ts": ts}
            self._send_to(to, out)
            if to != name:
                self._send_to(name, out)   # 보낸 사람 화면에도 표시되도록 echo
        elif t == "join":
            room = (m.get("room") or "").strip()
            if room:
                with self.lock:
                    self.rooms.setdefault(room, set()).add(name)
                self._broadcast_roster()
        elif t == "leave":
            room = (m.get("room") or "").strip()
            with self.lock:
                if room in self.rooms:
                    self.rooms[room].discard(name)
                    if not self.rooms[room]:
                        del self.rooms[room]
            self._broadcast_roster()
        elif t == "room":
            room = (m.get("room") or "").strip()
            with self.lock:
                members = list(self.rooms.get(room, ()))
            out = {"t": "msg", "scope": "room", "room": room, "from": name, "text": text, "ts": ts}
            for member in members:
                self._send_to(member, out)

    # ---- 전송 헬퍼 ----
    def _snapshot(self):
        with self.lock:
            users = sorted(self.clients.keys())
            rooms = {r: sorted(m) for r, m in self.rooms.items() if m}
        return users, rooms

    def _broadcast_roster(self):
        users, rooms = self._snapshot()
        self._broadcast({"t": "roster", "users": users, "rooms": rooms})

    def _broadcast(self, obj):
        with self.lock:
            conns = list(self.clients.values())
        for c in conns:
            try:
                send_json(c, obj, self.send_lock)
            except OSError:
                pass

    def _send_to(self, name, obj):
        with self.lock:
            conn = self.clients.get(name)
        if conn:
            try:
                send_json(conn, obj, self.send_lock)
            except OSError:
                pass


# ===========================================================================
# 클라이언트 네트워크 (tkinter 비의존 → 단독 테스트 가능)
# ===========================================================================
class ChatClientNet:
    def __init__(self, host, port, name, event_q):
        self.host, self.port, self.name = host, port, name
        self.event_q = event_q
        self.sock = None
        self.send_lock = threading.Lock()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port))
        send_json(self.sock, {"t": "hello", "name": self.name}, self.send_lock)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for m in iter_messages(self.sock):
                self.event_q.put(m)
        except OSError:
            pass
        finally:
            self.event_q.put({"t": "_disconnected"})

    def _send(self, obj):
        try:
            send_json(self.sock, obj, self.send_lock)
        except OSError:
            self.event_q.put({"t": "_disconnected"})

    def send_all(self, text):
        self._send({"t": "all", "text": text})

    def send_dm(self, to, text):
        self._send({"t": "dm", "to": to, "text": text})

    def send_room(self, room, text):
        self._send({"t": "room", "room": room, "text": text})

    def join_room(self, room):
        self._send({"t": "join", "room": room})

    def leave_room(self, room):
        self._send({"t": "leave", "room": room})


# ===========================================================================
# 로컬 대화 기록 저장
# ===========================================================================
class History:
    def __init__(self, me):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lanpopup_history")
        self.dir = os.path.join(base, safe_name(me))
        os.makedirs(self.dir, exist_ok=True)

    def _file(self, key):
        return os.path.join(self.dir, safe_name(key) + ".jsonl")

    def append(self, key, rec):
        with open(self._file(key), "a", encoding=ENCODING) as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def load(self, key):
        path = self._file(key)
        out = []
        if os.path.exists(path):
            with open(path, encoding=ENCODING) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            pass
        return out

    def existing_keys(self):
        """저장된 대화 키 목록 (파일명 기반)."""
        keys = []
        if os.path.isdir(self.dir):
            for fn in os.listdir(self.dir):
                if fn.endswith(".jsonl"):
                    keys.append(fn[:-len(".jsonl")])
        return keys


# ===========================================================================
# 작업표시줄/창 깜빡임 (Windows)
# ===========================================================================
def flash_window(win, start):
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

        FLASHW_STOP, FLASHW_ALL, FLASHW_TIMER = 0, 3, 4
        flags = (FLASHW_ALL | FLASHW_TIMER) if start else FLASHW_STOP
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, flags, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


# ===========================================================================
# 클라이언트 GUI
# ===========================================================================
def run_client(host, port, name):
    import tkinter as tk
    from tkinter import simpledialog, messagebox

    root = tk.Tk()
    root.withdraw()

    if not name:
        name = simpledialog.askstring("닉네임", "사용할 닉네임을 입력하세요:", parent=root)
        if not name:
            return
    name = name.strip()

    history = History(name)
    event_q = queue.Queue()
    net = ChatClientNet(host, port, name, event_q)

    # 상태
    state = {
        "me": name,
        "users": [],
        "rooms": {},                 # room -> [members]
        "convs": {},                 # key -> [records]
        "current": "all",
        "unread": set(),
        "keys": [],                  # 리스트박스와 대응하는 키 목록
    }

    # 저장된 이전 대화 미리 로드
    for key in history.existing_keys():
        state["convs"][key] = history.load(key)
    state["convs"].setdefault("all", history.load("all"))

    try:
        net.connect()
    except OSError as e:
        messagebox.showerror("접속 실패", f"{host}:{port} 에 접속하지 못했습니다.\n서버가 켜져 있는지 확인하세요.\n\n{e}")
        return

    # ---------------- UI 구성 ----------------
    root.deiconify()
    root.title(f"LAN 채팅 - {name}")
    root.geometry("720x460")

    paned = tk.PanedWindow(root, sashrelief="raised")
    paned.pack(fill="both", expand=True)

    left = tk.Frame(paned, width=200)
    tk.Label(left, text="대화 / 접속자", font=("", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 0))
    conv_list = tk.Listbox(left, exportselection=False)
    conv_list.pack(fill="both", expand=True, padx=6, pady=6)
    btns = tk.Frame(left)
    btns.pack(fill="x", padx=6, pady=(0, 6))
    paned.add(left)

    right = tk.Frame(paned)
    title_lbl = tk.Label(right, text="전체 (모두)", font=("", 12, "bold"), anchor="w")
    title_lbl.pack(fill="x", padx=8, pady=(8, 0))
    display = tk.Text(right, state="disabled", wrap="word")
    display.pack(fill="both", expand=True, padx=8, pady=6)
    entry_frame = tk.Frame(right)
    entry_frame.pack(fill="x", padx=8, pady=(0, 8))
    msg_entry = tk.Entry(entry_frame, font=("", 11))
    msg_entry.pack(side="left", fill="x", expand=True)
    paned.add(right)

    status = tk.Label(root, text="연결됨", anchor="w", relief="sunken")
    status.pack(fill="x", side="bottom")

    # ---------------- 헬퍼 ----------------
    def label_for(key):
        if key == "all":
            base = "전체 (모두)"
        elif key.startswith("dm:"):
            other = key[3:]
            online = "" if other in state["users"] else " (오프라인)"
            base = f"👤 {other}{online}"
        elif key.startswith("room:"):
            base = f"👥 {key[5:]}"
        else:
            base = key
        return ("● " + base) if key in state["unread"] else base

    def conv_keys():
        keys = ["all"]
        my_rooms = sorted(r for r, mem in state["rooms"].items() if state["me"] in mem)
        keys += [f"room:{r}" for r in my_rooms]
        partners = {u for u in state["users"] if u != state["me"]}
        for k in state["convs"]:
            if k.startswith("dm:"):
                partners.add(k[3:])
        keys += [f"dm:{p}" for p in sorted(partners)]
        return keys

    def rebuild_list():
        state["keys"] = conv_keys()
        conv_list.delete(0, "end")
        for k in state["keys"]:
            conv_list.insert("end", label_for(k))
        if state["current"] in state["keys"]:
            idx = state["keys"].index(state["current"])
            conv_list.selection_clear(0, "end")
            conv_list.selection_set(idx)

    def render():
        key = state["current"]
        title_lbl.config(text=label_for(key).lstrip("● "))
        display.config(state="normal")
        display.delete("1.0", "end")
        for rec in state["convs"].get(key, []):
            ts = datetime.fromtimestamp(rec.get("ts", time.time())).strftime("%H:%M")
            sender = rec.get("from", "?")
            who = "나" if sender == state["me"] else sender
            display.insert("end", f"[{ts}] {who}: {rec.get('text','')}\n")
        display.see("end")
        display.config(state="disabled")

    def select_current(key):
        state["current"] = key
        state["unread"].discard(key)
        if key not in state["convs"]:
            state["convs"][key] = history.load(key)
        rebuild_list()
        render()

    def on_select(_event=None):
        sel = conv_list.curselection()
        if sel:
            select_current(state["keys"][sel[0]])

    conv_list.bind("<<ListboxSelect>>", on_select)

    def notify(key):
        state["unread"].add(key)
        rebuild_list()
        flash_window(root, start=True)
        try:
            root.bell()
        except Exception:
            pass

    def clear_flash(_event=None):
        flash_window(root, start=False)
        if state["current"]:
            state["unread"].discard(state["current"])
            rebuild_list()

    root.bind("<FocusIn>", clear_flash)

    # ---------------- 보내기 ----------------
    def do_send(_event=None):
        text = msg_entry.get().strip()
        if not text:
            return
        key = state["current"]
        if key == "all":
            net.send_all(text)
        elif key.startswith("dm:"):
            net.send_dm(key[3:], text)
        elif key.startswith("room:"):
            net.send_room(key[5:], text)
        msg_entry.delete(0, "end")

    msg_entry.bind("<Return>", do_send)
    tk.Button(entry_frame, text="보내기", command=do_send).pack(side="left", padx=(6, 0))

    def start_dm():
        target = simpledialog.askstring("1:1 대화", "대화할 상대 닉네임:", parent=root)
        if target and target.strip():
            select_current(f"dm:{target.strip()}")

    def join_group():
        room = simpledialog.askstring("그룹 참여/만들기", "방 이름:", parent=root)
        if room and room.strip():
            net.join_room(room.strip())

    def leave_group():
        key = state["current"]
        if key.startswith("room:"):
            net.leave_room(key[5:])
            state["current"] = "all"

    tk.Button(btns, text="1:1 대화", command=start_dm).pack(fill="x", pady=1)
    tk.Button(btns, text="그룹 참여/만들기", command=join_group).pack(fill="x", pady=1)
    tk.Button(btns, text="그룹 나가기", command=leave_group).pack(fill="x", pady=1)

    # ---------------- 수신 이벤트 처리 ----------------
    def handle_event(m):
        t = m.get("t")
        if t == "welcome":
            state["me"] = m["name"]
            root.title(f"LAN 채팅 - {state['me']}")
        elif t == "roster":
            state["users"] = m.get("users", [])
            state["rooms"] = {r: list(v) for r, v in m.get("rooms", {}).items()}
            rebuild_list()
        elif t == "msg":
            scope = m.get("scope")
            if scope == "all":
                key = "all"
            elif scope == "dm":
                other = m["from"] if m["from"] != state["me"] else m.get("to")
                key = f"dm:{other}"
            elif scope == "room":
                key = f"room:{m.get('room')}"
            else:
                return
            rec = {"from": m.get("from"), "text": m.get("text", ""),
                   "ts": m.get("ts", time.time()), "scope": scope}
            state["convs"].setdefault(key, []).append(rec)
            history.append(key, rec)
            if key == state["current"]:
                render()
            else:
                notify(key)
            if key not in state["keys"]:
                rebuild_list()
        elif t == "sys":
            rec = {"from": "[알림]", "text": m.get("text", ""), "ts": time.time(), "scope": "all"}
            state["convs"].setdefault("all", []).append(rec)
            if state["current"] == "all":
                render()
        elif t == "_disconnected":
            status.config(text="연결이 끊어졌습니다. 프로그램을 다시 시작하세요.")

    def poll():
        try:
            while True:
                handle_event(event_q.get_nowait())
        except queue.Empty:
            pass
        root.after(150, poll)

    rebuild_list()
    render()
    root.after(150, poll)
    root.mainloop()


# ===========================================================================
def main():
    parser = argparse.ArgumentParser(description="LAN 채팅 (서버/클라이언트)")
    parser.add_argument("--port", type=int, default=PORT, help=f"포트 (기본 {PORT})")
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("server", help="채팅 서버를 실행합니다")

    p_client = sub.add_parser("client", help="채팅 클라이언트(창)를 실행합니다")
    p_client.add_argument("host", help="서버 IP 주소")
    p_client.add_argument("name", nargs="?", default="", help="닉네임 (생략 시 실행 후 입력)")

    args = parser.parse_args()

    if args.mode == "server":
        ChatServer(args.port).start()
    elif args.mode == "client":
        run_client(args.host, args.port, args.name)


if __name__ == "__main__":
    main()
