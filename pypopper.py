#!/usr/bin/env python
"""pypopper: a file-based pop3 server

Usage:
    python pypopper.py <port> <path_to_message_file(s)...>
"""
import logging
import os
import socket
import sys

logging.basicConfig(format="%(name)s %(levelname)s - %(message)s")
log = logging.getLogger("pypopper")
log.setLevel(logging.DEBUG)


class ChatterboxConnection(object):
    END = "\r\n"

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def sendall(self, data, END=END):
        if len(data) < 50:
            log.debug("send: %r", data)
        else:
            log.debug("send: %r...", data[:50])
        data += END
        self.conn.sendall(data)

    def recvall(self, END=END):
        data = []
        while True:
            chunk = self.conn.recv(4096)
            if not chunk:
                break
            if END in chunk:
                data.append(chunk[:chunk.index(END)])
                break
            data.append(chunk)
            if len(data) > 1:
                pair = data[-2] + data[-1]
                if END in pair:
                    data[-2] = pair[:pair.index(END)]
                    data.pop()
                    break
        log.debug("recv: %r", "".join(data))
        return "".join(data)


class Message(object):
    def __init__(self, filename):
        msg = open(filename, "r")
        try:
            self.data = data = msg.read()
            self.size = len(data)
            self.top, bot = data.split("\n\n", 1)
            self.bot = bot.split("\n")
        finally:
            msg.close()


def handleUser(unused1, unused2):
    return "+OK user accepted"


def handlePass(unused1, unused2):
    return "+OK pass accepted"


def handleStat(unused1, messages):
    size = 0
    for msg in messages:
        size += msg.size
    return "+OK %i %i" % (len(messages), size)


def handleList(data, messages):
    if data:
        try:
            msgno = int(data)
            msg = messages[msgno-1]
            return "+OK %i %i" % (msgno, msg.size)
        except Exception:
            return "-ERR bad data %s" % data

    size = 0
    s = []
    msgno = 1
    for msg in messages:
        s.append("%i %i\r\n" % (msgno, msg.size))
        size += msg.size
        msgno += 1

    s.insert(0, "+OK %i messages (%i octets)\r\n" % (len(messages), size))
    s.append('.')

    return ''.join(s)


def handleUidl(data, messages):
    if data:
        return "-ERR unhandled %s" % data

    s = []
    s.append("+OK unique-id listing follows\r\n")
    msgno = 1
    for msg in messages:
        s.append("%i %i\r\n" % (msgno, msgno))
        msgno += 1

    s.append('.')

    return ''.join(s)


def handleTop(data, messages):
    num, lines = data.split()
    try:
        num = int(num)
        lines = int(lines)
        msg = messages[num-1]
        text = msg.top + "\r\n\r\n" + "\r\n".join(msg.bot[:lines])
        return "+OK top of message follows\r\n%s\r\n." % text
    except Exception:
        return "-ERR bad data %s" % data


def handleRetr(data, messages):
    try:
        msgno = int(data)
        msg = messages[msgno-1]
        return "+OK %i octets\r\n%s\r\n." % (msg.size, msg.data)
        log.info("message %i sent", msgno)
    except Exception:
        return "-ERR bad msgno %s" % data


def handleDele(unused1, unused2):
    return "+OK message 1 deleted"


def handleNoop(unused1, unused2):
    return "+OK"


def handleQuit(unused1, unused2):
    return "+OK pypopper POP3 server signing off"


dispatch = dict(
    USER=handleUser,
    PASS=handlePass,
    STAT=handleStat,
    LIST=handleList,
    UIDL=handleUidl,
    TOP=handleTop,
    RETR=handleRetr,
    DELE=handleDele,
    NOOP=handleNoop,
    QUIT=handleQuit,
)


def serve(host, port, messages):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    try:
        if host:
            hostname = host
        else:
            hostname = "localhost"
        log.info("serving POP3 on %s:%s", hostname, port)
        while True:
            sock.listen(1)
            conn, addr = sock.accept()
            log.debug('Connected by %s', addr)
            try:
                conn = ChatterboxConnection(conn)
                conn.sendall("+OK pypopper file-based pop3 server ready")
                while True:
                    data = conn.recvall()
                    if not data:
                        break

                    list = data.split(None, 1)
                    command = list[0]
                    if len(list) > 1:
                        param = list[1]
                    else:
                        param = None

                    try:
                        cmd = dispatch[command]
                    except KeyError:
                        conn.sendall("-ERR unknown command")
                    else:
                        result = cmd(param, messages)
                        try:
                            conn.sendall(result)
                        except Exception:
                            # socket might go away during sendall
                            break

                        if cmd is handleQuit:
                            break
            finally:
                conn.close()
    except (SystemExit, KeyboardInterrupt):
        log.info("pypopper stopped")
    except Exception as ex:
        log.critical("fatal error", exc_info=ex)
    finally:
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)

    host = ""
    port = sys.argv.pop(1)
    if ":" in port:
        host = port[:port.index(":")]
        port = port[port.index(":") + 1:]

    try:
        port = int(port)
    except Exception:
        print("Unknown port:", port)
        sys.exit(1)

    messages = []
    while len(sys.argv) > 1:
        filename = sys.argv.pop(1)
        if not os.path.exists(filename):
            print("File not found:", filename)
            break

        messages.append(Message(filename))

    serve(host, port, messages)
