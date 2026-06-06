"""
LAN 채팅 (lanpopup.py)

같은 네트워크 안에서 동작하는 초간단 채팅 프로그램입니다.
모든 PC가 서버 능력을 내장하고 있어서, 별도의 서버 PC 없이도 동작합니다.

  - 네트워크에 호스트(서버)가 있으면  → 자동으로 찾아서 클라이언트로 접속
  - 호스트가 없으면                    → 내가 스스로 호스트가 됨
  - 호스트가 꺼지면                    → 남은 PC 중 하나가 자동으로 새 호스트가 됨 (failover)

기능
  - 닉네임(보낸/받는 사람) 표시
  - 접속자 목록 실시간 표시
  - 전체 채팅 / 1:1(DM) / 그룹(방) 채팅
  - 새 메시지가 오면 창/작업표시줄 깜빡임 + 알림음
  - 대화 기록을 로컬 파일에 저장 (다시 열면 이전 대화가 보임)

사용법 (가장 간단 — 권장)
  각 PC에서 그냥:
      python lanpopup.py join 홍길동
  (서버를 따로 켤 필요 없이, 알아서 접속하거나 호스트가 됩니다.)

수동 모드 (원하면)
  python lanpopup.py server                 # 이 PC를 고정 호스트로
  python lanpopup.py client <서버IP> 홍길동   # 특정 서버로 직접 접속

포트는 기본 50505(채팅) / 50506(자동 탐색) 입니다. --port 로 바꿀 수 있습니다.
"""

import argparse
import json
import os
import queue
import random
import re
import socket
import sys
import threading
import time
from datetime import datetime

PORT = 50505
ENCODING = "utf-8"
BUF = 4096
DISCOVER_REQUEST = b"LANCHAT_DISCOVER?"
DISCOVER_REPLY_PREFIX = b"LANCHAT_SERVER:"


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def safe_name(text):
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


# ---------------------------------------------------------------------------
# 자동 탐색 (UDP 브로드캐스트)
# ---------------------------------------------------------------------------
def discover_server(disc_port, timeout=1.0, tries=3):
    """LAN에 '서버 있나요?'를 뿌리고, 응답한 서버의 (IP, TCP포트)를 돌려줍니다.
    없으면 None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    try:
        for _ in range(tries):
            try:
                s.sendto(DISCOVER_REQUEST, ("255.255.255.255", disc_port))
            except OSError:
                pass
            try:
                while True:
                    data, addr = s.recvfrom(1024)
                    if data.startswith(DISCOVER_REPLY_PREFIX):
                        tcp_port = int(data[len(DISCOVER_REPLY_PREFIX):])
                        return addr[0], tcp_port
            except socket.timeout:
                continue
    finally:
        s.close()
    return None


def discover_all(disc_port, timeout=0.6, tries=1):
    """LAN의 모든 호스트를 찾아 [(ip, tcp_port), ...] 로 돌려줍니다 (호스트 모니터용)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    found = {}
    try:
        for _ in range(tries):
            try:
                s.sendto(DISCOVER_REQUEST, ("255.255.255.255", disc_port))
            except OSError:
                pass
            try:
                while True:
                    data, addr = s.recvfrom(1024)
                    if data.startswith(DISCOVER_REPLY_PREFIX):
                        found[addr[0]] = int(data[len(DISCOVER_REPLY_PREFIX):])
            except socket.timeout:
                continue
    finally:
        s.close()
    return list(found.items())


def ip_key(ip):
    """IP를 정렬용 튜플로. 값이 작을수록 우선순위가 높습니다(= 호스트가 됨)."""
    try:
        return tuple(int(x) for x in ip.split("."))
    except (ValueError, AttributeError):
        return (999, 999, 999, 999)



# ===========================================================================
# 서버
# ===========================================================================
class ChatServer:
    def __init__(self, port, reuse=True, enable_monitor=False):
        self.port = port
        self.disc_port = port + 1
        self.reuse = reuse
        self.enable_monitor = enable_monitor   # 다른(우선순위 높은) 호스트 감지 시 양보
        self.on_yield = None                   # 양보 직전 호출되는 콜백
        self.srv = None
        self.udp = None
        self.stopped = False
        self.clients = {}          # name -> socket
        self.ips = {}              # name -> ip
        self.rooms = {}            # room -> set(names)
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()

    def bind(self):
        """TCP 포트를 잡습니다. 이미 사용 중이면 OSError를 냅니다(= 호스트 선출 실패)."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.reuse:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen()
        self.srv = srv

    def serve_forever(self):
        threading.Thread(target=self._discovery_loop, daemon=True).start()
        if self.enable_monitor:
            threading.Thread(target=self._monitor_loop, daemon=True).start()
        while not self.stopped:
            try:
                conn, addr = self.srv.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    def shutdown(self):
        """서버를 정지합니다 (양보 또는 종료 시)."""
        if self.stopped:
            return
        self.stopped = True
        for sock in (self.srv, self.udp):
            try:
                sock.close()
            except Exception:
                pass
        with self.lock:
            conns = list(self.clients.values())
        for c in conns:
            try:
                c.close()
            except Exception:
                pass

    def _monitor_loop(self):
        """주기적으로 다른 호스트를 탐색해, 나보다 우선순위가 높은(IP가 낮은)
        호스트가 있으면 양보합니다. 가장 우선순위 높은 호스트는 절대 양보하지 않아
        호스트가 하나로 수렴합니다."""
        self_ip = get_local_ip()
        while not self.stopped:
            for _ in range(6):           # 약 3초마다 점검 (정지에 빠르게 반응)
                time.sleep(0.5)
                if self.stopped:
                    return
            if self._better_host_exists(discover_all(self.disc_port), self_ip):
                if self.on_yield:        # 더 우선순위 높은 호스트 발견 → 양보
                    try:
                        self.on_yield()
                    except Exception:
                        pass
                self.shutdown()
                return

    @staticmethod
    def _better_host_exists(others, self_ip):
        """others = [(ip, port), ...] 중 self보다 우선순위 높은(IP 낮은) 호스트가 있으면 True."""
        my = ip_key(self_ip)
        for ip, _p in others:
            if ip == self_ip or ip.startswith("127."):
                continue
            if ip_key(ip) < my:
                return True
        return False

    def start(self):
        self.bind()
        print(f"[서버 시작] IP: {get_local_ip()}  포트: {self.port}")
        print("자동 탐색(UDP)을 지원합니다. 다른 PC는 'python lanpopup.py join <닉네임>' 으로 접속할 수 있습니다.")
        print("(종료: Ctrl+C)")
        self.serve_forever()

    # ---- 자동 탐색 응답 ----
    def _discovery_loop(self):
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.bind(("0.0.0.0", self.disc_port))
            self.udp = u
        except OSError:
            return
        reply = DISCOVER_REPLY_PREFIX + str(self.port).encode()
        while not self.stopped:
            try:
                data, addr = u.recvfrom(1024)
            except OSError:
                break
            if data.strip().startswith(DISCOVER_REQUEST):
                try:
                    u.sendto(reply, addr)
                except OSError:
                    pass

    # ---- 개별 클라이언트 처리 ----
    def _handle(self, conn, addr):
        name = None
        try:
            msgs = iter_messages(conn)
            first = next(msgs)
            if first.get("t") != "hello":
                return
            ip = addr[0]
            if ip.startswith("127.") or ip == "::1":
                ip = get_local_ip()   # 호스트 자신의 로컬 접속은 LAN IP로 보정
            name = self._register(conn, ip, (first.get("name") or "").strip() or f"user{addr[1]}")
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

    def _register(self, conn, ip, requested):
        with self.lock:
            base, name, i = requested, requested, 2
            while name in self.clients:
                name = f"{base}_{i}"
                i += 1
            self.clients[name] = conn
            self.ips[name] = ip
            return name

    def _remove(self, name):
        with self.lock:
            self.clients.pop(name, None)
            self.ips.pop(name, None)
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
                self._send_to(name, out)
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

    def _snapshot(self):
        with self.lock:
            users = sorted(self.clients.keys())
            rooms = {r: sorted(m) for r, m in self.rooms.items() if m}
            peers = dict(self.ips)
        return users, rooms, peers

    def _broadcast_roster(self):
        users, rooms, peers = self._snapshot()
        self._broadcast({"t": "roster", "users": users, "rooms": rooms, "peers": peers})

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
# 클라이언트 네트워크 (tkinter 비의존)
# ===========================================================================
class ChatClientNet:
    def __init__(self, host, port, name, event_q):
        self.host, self.port, self.name = host, port, name
        self.event_q = event_q
        self.sock = None
        self.send_lock = threading.Lock()
        self.alive = True

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        self.sock.settimeout(None)
        send_json(self.sock, {"t": "hello", "name": self.name}, self.send_lock)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for m in iter_messages(self.sock):
                self.event_q.put(m)
        except OSError:
            pass
        finally:
            if self.alive:
                self.event_q.put({"t": "_disconnected"})

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass

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
# 접속 방법 (connector)
# ===========================================================================
def connect_to(host, port, name, event_q):
    net = ChatClientNet(host, port, name, event_q)
    net.connect()
    return net, f"접속됨 (호스트: {host})", host


def establish_auto(port, name, event_q):
    """자동 모드: 서버를 찾으면 접속, 없으면 스스로 호스트가 됩니다.
    돌려주는 값: (net, 상태문구, 호스트IP)"""
    disc_port = port + 1
    found = discover_server(disc_port)
    if not found:
        # 호스트가 없어 보이면 내가 호스트가 되어 본다 (포트 바인드로 선출).
        server = ChatServer(port, reuse=False, enable_monitor=True)
        try:
            server.bind()
        except OSError:
            server = None  # 다른 PC가 먼저 호스트가 됨 → 아래에서 다시 탐색
        if server is not None:
            # 더 우선순위 높은 호스트가 나타나면 양보(서버 종료) → 아래 재접속으로 이어짐
            server.on_yield = lambda: event_q.put(
                {"t": "_status", "text": "우선순위 높은 호스트 발견 — 양보 후 재접속합니다."})
            threading.Thread(target=server.serve_forever, daemon=True).start()
            time.sleep(0.25)
            net = ChatClientNet("127.0.0.1", port, name, event_q)
            net.connect()
            return net, f"이 PC가 호스트입니다 (IP: {get_local_ip()})", get_local_ip()
        time.sleep(random.uniform(0.3, 0.9))
        found = discover_server(disc_port)
    if not found:
        found = discover_server(disc_port, tries=4)
    host, tcp_port = found if found else ("127.0.0.1", port)
    net = ChatClientNet(host, tcp_port, name, event_q)
    net.connect()
    return net, f"접속됨 (호스트: {host})", host


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
def run_gui(port, connector, name):
    """connector(name, event_q) -> (net, 상태문구). 연결 실패 시 OSError."""
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

    state = {
        "me": name,
        "users": [],
        "rooms": {},
        "convs": {},
        "current": "all",
        "unread": set(),
        "keys": [],
        "my_rooms": set(),
        "net": None,
        "reconnecting": False,
        "host_ip": None,
        "peer_ips": {},          # name -> ip (우선순위/순번 계산용)
    }

    for key in history.existing_keys():
        state["convs"][key] = history.load(key)
    state["convs"].setdefault("all", history.load("all"))

    try:
        net, role, host_ip = connector(name, event_q)
    except OSError as e:
        messagebox.showerror("접속 실패", f"채팅에 연결하지 못했습니다.\n\n{e}")
        return
    state["net"] = net
    state["host_ip"] = host_ip

    # ---------------- UI ----------------
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

    status = tk.Label(root, text=role, anchor="w", relief="sunken")
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
        if not text or not state["net"]:
            return
        key = state["current"]
        if key == "all":
            state["net"].send_all(text)
        elif key.startswith("dm:"):
            state["net"].send_dm(key[3:], text)
        elif key.startswith("room:"):
            state["net"].send_room(key[5:], text)
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
            room = room.strip()
            state["my_rooms"].add(room)
            if state["net"]:
                state["net"].join_room(room)

    def leave_group():
        key = state["current"]
        if key.startswith("room:"):
            room = key[5:]
            state["my_rooms"].discard(room)
            if state["net"]:
                state["net"].leave_room(room)
            state["current"] = "all"

    tk.Button(btns, text="1:1 대화", command=start_dm).pack(fill="x", pady=1)
    tk.Button(btns, text="그룹 참여/만들기", command=join_group).pack(fill="x", pady=1)
    tk.Button(btns, text="그룹 나가기", command=leave_group).pack(fill="x", pady=1)

    # ---------------- 재연결 / 호스트 자동 전환 ----------------
    def start_reconnect():
        if state["reconnecting"]:
            return
        state["reconnecting"] = True

        def succession_delay():
            """우선순위(IP) 순번에 비례한 지연. 1순위(IP 최소)가 먼저 호스트가 되도록."""
            my_ip = get_local_ip()
            ips = {ip for ip in state["peer_ips"].values() if ip}
            ips.discard(state.get("host_ip"))   # 방금 사라진 호스트는 후보에서 제외
            ips.add(my_ip)
            ordered = sorted(ips, key=ip_key)
            rank = ordered.index(my_ip) if my_ip in ordered else len(ordered)
            return rank * 0.7 + random.uniform(0.0, 0.2)

        def worker():
            event_q.put({"t": "_status", "text": "연결 끊김 — 순번에 따라 호스트 승계를 시도합니다..."})
            time.sleep(succession_delay())
            for attempt in range(15):
                try:
                    new_net, new_role, new_host = connector(state["me"], event_q)
                except OSError:
                    event_q.put({"t": "_status", "text": f"재연결 시도 중... ({attempt + 1})"})
                    time.sleep(1.5)
                    continue
                state["net"] = new_net
                state["host_ip"] = new_host
                for r in list(state["my_rooms"]):   # 있던 그룹 자동 재참여
                    new_net.join_room(r)
                event_q.put({"t": "_status", "text": new_role})
                state["reconnecting"] = False
                return
            event_q.put({"t": "_status", "text": "재연결 실패. 프로그램을 다시 시작하세요."})
            state["reconnecting"] = False

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 수신 이벤트 처리 ----------------
    def handle_event(m):
        t = m.get("t")
        if t == "welcome":
            state["me"] = m["name"]
            root.title(f"LAN 채팅 - {state['me']}")
        elif t == "roster":
            state["users"] = m.get("users", [])
            state["rooms"] = {r: list(v) for r, v in m.get("rooms", {}).items()}
            state["peer_ips"] = dict(m.get("peers", {}))
            for r, mem in state["rooms"].items():
                if state["me"] in mem:
                    state["my_rooms"].add(r)
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
        elif t == "_status":
            status.config(text=m.get("text", ""))
        elif t == "_disconnected":
            status.config(text="연결이 끊어졌습니다. 재연결을 시도합니다...")
            start_reconnect()

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
    parser = argparse.ArgumentParser(description="LAN 채팅 (자동 호스트 / 서버 / 클라이언트)")
    parser.add_argument("--port", type=int, default=PORT, help=f"채팅 포트 (기본 {PORT})")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_join = sub.add_parser("join", help="자동: 호스트를 찾아 접속하거나 스스로 호스트가 됩니다 (권장)")
    p_join.add_argument("name", nargs="?", default="", help="닉네임 (생략 시 실행 후 입력)")

    sub.add_parser("server", help="이 PC를 고정 호스트(서버)로 실행합니다")

    p_client = sub.add_parser("client", help="특정 서버로 직접 접속합니다")
    p_client.add_argument("host", help="서버 IP 주소")
    p_client.add_argument("name", nargs="?", default="", help="닉네임 (생략 시 실행 후 입력)")

    args = parser.parse_args()

    if args.mode == "server":
        ChatServer(args.port).start()
    elif args.mode == "client":
        run_gui(args.port, lambda nm, q: connect_to(args.host, args.port, nm, q), args.name)
    elif args.mode == "join":
        run_gui(args.port, lambda nm, q: establish_auto(args.port, nm, q), args.name)


if __name__ == "__main__":
    main()
