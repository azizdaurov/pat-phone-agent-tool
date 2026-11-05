"""Control an iPhone's phone calls from Windows over Bluetooth Hands-Free Profile (HFP).

The laptop plays the hands-free (car kit) role: it opens the iPhone's Handsfree
Audio Gateway RFCOMM channel and sends the standard HFP AT commands.

    python hfp_call.py status              connect, show phone status, disconnect
    python hfp_call.py dial +COUNTRY_CODE_NUMBER  dial a full international number, then stay in the shell
    python hfp_call.py shell               wait for calls and type commands

Shell commands:
    d <number>  dial          a  answer          h  hang up / reject
    r           redial last   s  status          v <0-15>  speaker volume
    at...       raw AT command (e.g. at+clcc)    q  quit (the call keeps going on the phone)

This controls calls only. Whether call audio reaches the laptop is a separate question:
Windows does not let a user program carry Bluetooth call audio (SCO).
"""
import argparse
import ctypes
import os
import queue
import re
import socket
import threading
import time

IPHONE_ADDR = os.environ.get("IPHONE_BT_ADDR")
HFP_AG_UUID = (0x0000111F, 0x0000, 0x1000, bytes.fromhex("800000805F9B34FB"))

# HF supported features sent in AT+BRSF: CLI presentation (4), remote volume (16),
# enhanced call status (32). No codec negotiation or three-way calling, which keeps
# the service-level handshake to the mandatory steps.
HF_FEATURES = 4 | 16 | 32

FINAL = ("OK", "ERROR", "+CME ERROR", "NO CARRIER", "BUSY", "NO ANSWER", "NO DIALTONE")
UNSOLICITED = ("RING", "+CIEV", "+CLIP", "+CCWA", "+VGS", "+VGM", "+BSIR", "+BCS", "+BVRA")
QUIET_INDICATORS = ("signal", "battchg")

CALLSETUP = {0: "none", 1: "incoming", 2: "dialing", 3: "ringing at other end"}
CLCC_STATUS = {0: "active", 1: "held", 2: "dialing", 3: "alerting", 4: "incoming", 5: "waiting"}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class SOCKADDR_BTH(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("addressFamily", ctypes.c_ushort), ("btAddr", ctypes.c_ulonglong),
                ("serviceClassId", GUID), ("port", ctypes.c_ulong)]


def connect_rfcomm(addr, channel=None):
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    if channel:
        sock.connect((addr, channel))
        return sock
    # Python's socket module only connects by channel number. Calling Winsock directly
    # with the service UUID and port 0 makes Windows look the channel up over SDP.
    d1, d2, d3, d4 = HFP_AG_UUID
    sa = SOCKADDR_BTH()
    sa.addressFamily = socket.AF_BLUETOOTH
    sa.btAddr = int(addr.replace(":", ""), 16)
    sa.serviceClassId = GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
    sa.port = 0
    ws2 = ctypes.WinDLL("ws2_32")
    ws2.connect.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
    if ws2.connect(sock.fileno(), ctypes.byref(sa), ctypes.sizeof(sa)) != 0:
        err = ws2.WSAGetLastError()
        sock.close()
        raise OSError(err, f"could not open the iPhone's hands-free channel (WSA error {err})")
    return sock


class HFP:
    def __init__(self, sock, on_event=print):
        self.sock = sock
        self.on_event = on_event
        self.responses = queue.Queue()
        self.indicators = []
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        while self.alive:
            try:
                data = self.sock.recv(1024)
            except OSError:
                data = b""
            if not data:
                if self.alive:
                    self.on_event("-- phone closed the connection")
                self.alive = False
                self.responses.put(None)
                return
            buf += data
            while b"\r" in buf:
                raw, _, buf = buf.partition(b"\r")
                line = raw.strip(b"\n").decode(errors="replace").strip()
                if not line:
                    continue
                if line.startswith(UNSOLICITED):
                    self._event(line)
                else:
                    self.responses.put(line)

    def _event(self, line):
        if line.startswith("+CIEV"):
            idx, val = (int(x) for x in line.split(":", 1)[1].split(","))
            name = self.indicators[idx - 1] if 0 < idx <= len(self.indicators) else f"#{idx}"
            if name in QUIET_INDICATORS:
                return
            if name == "callsetup":
                line = f"-- call setup: {CALLSETUP.get(val, val)}"
            elif name == "call":
                line = "-- call connected" if val else "-- call ended"
            else:
                line = f"-- {name} = {val}"
        elif line.startswith("+CLIP"):
            line = f"-- caller: {line.split(':', 1)[1].split(',')[0].strip()}"
        elif line == "RING":
            line = "-- RING (type 'a' to answer, 'h' to reject)"
        self.on_event(line)

    def cmd(self, at, timeout=10, check=True):
        if not self.alive:
            raise ConnectionError("not connected")
        self.sock.sendall((at + "\r").encode())
        lines, deadline = [], time.monotonic() + timeout
        while True:
            try:
                line = self.responses.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError(f"{at}: no reply from phone") from None
            if line is None:
                raise ConnectionError(f"{at}: connection closed")
            if line.startswith(FINAL):
                if check and line != "OK":
                    raise RuntimeError(f"{at}: {line}")
                return lines, line
            lines.append(line)

    def setup(self):
        """HFP service-level connection: features, indicators, event reporting."""
        lines, _ = self.cmd(f"AT+BRSF={HF_FEATURES}")
        self.ag_features = int(lines[0].split(":")[1]) if lines else 0
        lines, _ = self.cmd("AT+CIND=?")
        self.indicators = re.findall(r'\("([^"]+)"', lines[0])
        self.cmd("AT+CIND?")
        self.cmd("AT+CMER=3,0,0,1")
        self.cmd("AT+CLIP=1", check=False)
        self.cmd("AT+CMEE=1", check=False)

    def status(self):
        self.cmd("AT+COPS=3,0", check=False)
        lines, _ = self.cmd("AT+COPS?", check=False)
        operator = re.findall(r'"([^"]*)"', lines[0]) if lines else []
        print(f"operator : {operator[0] if operator else 'unknown'}")
        lines, _ = self.cmd("AT+CIND?")
        values = lines[0].split(":", 1)[1].split(",")
        for name, val in zip(self.indicators, values):
            print(f"{name:9}: {val.strip()}")
        print(f"AG feature bits: {self.ag_features}")
        lines, _ = self.cmd("AT+CLCC", check=False)
        calls = [l for l in lines if l.startswith("+CLCC")]
        if not calls:
            print("calls    : none")
        for c in calls:
            f = [x.strip().strip('"') for x in c.split(":", 1)[1].split(",")]
            who = f[5] if len(f) > 5 and f[5] else "hidden"
            way = "outgoing" if f[1] == "0" else "incoming"
            print(f"call {f[0]}   : {way}, {CLCC_STATUS.get(int(f[2]), f[2])}, {who}")

    def dial(self, number):
        if not re.fullmatch(r"\+?[0-9*#]+", number):
            raise ValueError(f"not a dialable number: {number!r}")
        _, res = self.cmd(f"ATD{number};", timeout=20, check=False)
        print(f"dial {number}: {res}")

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


def shell(hfp):
    print("commands: d <number> | a | h | r | s | v <0-15> | at... | q")
    while hfp.alive:
        try:
            line = input("hfp> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        word, _, rest = line.partition(" ")
        try:
            if word == "q":
                break
            elif word == "d":
                hfp.dial(rest.replace(" ", ""))
            elif word == "a":
                print("answer:", hfp.cmd("ATA", check=False)[1])
            elif word == "h":
                print("hang up:", hfp.cmd("AT+CHUP", check=False)[1])
            elif word == "r":
                print("redial:", hfp.cmd("AT+BLDN", timeout=20, check=False)[1])
            elif word == "s":
                hfp.status()
            elif word == "v":
                print("volume:", hfp.cmd(f"AT+VGS={int(rest)}", check=False)[1])
            elif word.lower().startswith("at"):
                lines, res = hfp.cmd(line.upper(), check=False)
                print("\n".join(lines + [res]))
            else:
                print("unknown command")
        except (RuntimeError, TimeoutError, ValueError, ConnectionError) as e:
            print("error:", e)


def main():
    p = argparse.ArgumentParser(description="Control calls on an iPhone over Bluetooth HFP.")
    p.add_argument("--addr", default=IPHONE_ADDR, required=not IPHONE_ADDR, help="iPhone Bluetooth address, or set IPHONE_BT_ADDR")
    p.add_argument("--channel", type=int, help="RFCOMM channel (skips the SDP lookup)")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("dial").add_argument("number")
    sub.add_parser("shell")
    args = p.parse_args()

    print(f"connecting to {args.addr} ...")
    hfp = HFP(connect_rfcomm(args.addr, args.channel))
    try:
        hfp.setup()
        print("connected (hands-free link up)")
        if args.action == "status":
            hfp.status()
        else:
            if args.action == "dial":
                hfp.dial(args.number)
            shell(hfp)
    finally:
        hfp.close()


if __name__ == "__main__":
    main()
