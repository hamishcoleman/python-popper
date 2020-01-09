#!/usr/bin/env python3
"""pypopper: a file-based pop3 server

Usage:
    python pypopper.py <port> <path_to_message_file(s)...>
"""
import logging
import os
import socket
import sys

logging.basicConfig(format="%(name)s %(levelname)s - %(message)s")
LOG = logging.getLogger("pypopper")
LOG.setLevel(logging.DEBUG)


class ChatterboxConnection():
    end = "\r\n"

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def sendall(self, data, end=end):
        if len(data) < 50:
            LOG.debug("send: %r", data)
        else:
            LOG.debug("send: %r...", data[:50])
        data = bytes(data + end, 'utf-8')
        self.conn.sendall(data)

    def recvall(self, end=end):
        data = []
        while True:
            chunk = self.conn.recv(4096)
            if not chunk:
                # the connection has gone away
                if data:
                    # return what data we do have
                    break
                return None

            try:
                chunk = chunk.decode('utf-8')
            except UnicodeDecodeError:
                LOG.debug("unicode error with %s" % chunk)
                break

            if end in chunk:
                data.append(chunk[:chunk.index(end)])
                # FIXME: we are throwing away the rest of the chunk here
                break
            data.append(chunk)
            if len(data) > 1:
                pair = data[-2] + data[-1]
                if end in pair:
                    data[-2] = pair[:pair.index(end)]
                    data.pop()
                    break
        LOG.debug("recv: %r", "".join(data))
        return "".join(data)


class Message():
    def __init__(self, messagefile):
        msg = open(messagefile, "r")
        try:
            self.data = data = msg.read()
            self.size = len(data)
            self.top, bot = data.split("\n\n", 1)
            self.bot = bot.split("\n")
        finally:
            msg.close()


class POPConnection():
    def __init__(self, connection, messages):
        self.conn = connection
        self.messages = messages

    def get_handler(self, command):
        handlername = 'handle_' + command.lower()
        handler = getattr(self, handlername, None)
        if not callable(handler):
            handler = self.handle_unknown
        return handler

    def handle_unknown(self, unused1, unused2):
        return "-ERR unknown command"

    def handle_user(self, unused1, unused2):
        return "+OK user accepted"

    def handle_pass(self, unused1, unused2):
        return "+OK pass accepted"

    def handle_stat(self, unused1, messagelist):
        size = 0
        for msg in messagelist:
            size += msg.size
        return "+OK %i %i" % (len(messagelist), size)

    def handle_list(self, data, messagelist):
        if data:
            try:
                msgno = int(data)
            except ValueError:
                return "-ERR bad number %s" % data
            try:
                msg = messagelist[msgno-1]
            except IndexError:
                return "-ERR bad message number %i" % msgno

            return "+OK %i %i" % (msgno, msg.size)

        size = 0
        s = []
        msgno = 1
        for msg in messagelist:
            s.append("%i %i\r\n" % (msgno, msg.size))
            size += msg.size
            msgno += 1

        s.insert(
            0, "+OK %i messages (%i octets)\r\n" % (len(messagelist), size))
        s.append('.')

        return ''.join(s)

    def handle_uidl(self, data, messagelist):
        if data:
            return "-ERR unhandled %s" % data

        s = []
        s.append("+OK unique-id listing follows\r\n")
        msgno = 1
        for msg in messagelist:
            s.append("%i %i\r\n" % (msgno, msgno))
            msgno += 1

        s.append('.')

        return ''.join(s)

    def handle_top(self, data, messagelist):
        num, lines = data.split()
        try:
            num = int(num)
            lines = int(lines)
        except ValueError:
            return "-ERR bad number %s" % data
        try:
            msg = messagelist[num-1]
        except IndexError:
            return "-ERR bad message number %i" % num

        text = msg.top + "\r\n\r\n" + "\r\n".join(msg.bot[:lines])
        return "+OK top of message follows\r\n%s\r\n." % text

    def handle_retr(self, data, messagelist):
        try:
            msgno = int(data)
        except ValueError:
            return "-ERR bad number %s" % data
        try:
            msg = messagelist[msgno-1]
        except IndexError:
            return "-ERR bad message number %i" % msgno

        LOG.info("message %i sent", msgno)
        return "+OK %i octets\r\n%s\r\n." % (msg.size, msg.data)

    def handle_dele(self, unused1, unused2):
        return "+OK message 1 deleted"

    def handle_noop(self, unused1, unused2):
        return "+OK"

    def handle_quit(self, unused1, unused2):
        self.conn.close()
        return "+OK pypopper POP3 server signing off"


def serve(host, port, messages):
    if host:
        hostname = host
    else:
        hostname = "localhost"

    LOG.info("serving POP3 on %s:%s", hostname, port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    try:
        while True:
            sock.listen(1)
            conn, addr = sock.accept()
            LOG.debug('Connected by %s', addr)
            try:
                conn = ChatterboxConnection(conn)
                conn.sendall("+OK pypopper file-based pop3 server ready")
                pop = POPConnection(conn, messages)
                while True:
                    data = conn.recvall()
                    if data is None:
                        break
                    if not data:
                        continue

                    words = data.split(None, 1)
                    command = words[0]
                    if len(words) > 1:
                        param = words[1]
                    else:
                        param = None

                    handler = pop.get_handler(command)
                    if handler is not None:
                        result = handler(param, messages)
                        try:
                            conn.sendall(result)
                        except Exception:
                            # socket might go away during sendall
                            break
            finally:
                conn.close()
    except (SystemExit, KeyboardInterrupt):
        LOG.info("pypopper stopped")
    except Exception as ex:
        LOG.critical("fatal error", exc_info=ex)
    finally:
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)

    HOST = ""
    PORT = sys.argv.pop(1)
    if ":" in PORT:
        HOST = PORT[:PORT.index(":")]
        PORT = PORT[PORT.index(":") + 1:]

    try:
        PORT = int(PORT)
    except Exception:
        print("Unknown port:", PORT)
        sys.exit(1)

    MESSAGES = []
    while len(sys.argv) > 1:
        FILENAME = sys.argv.pop(1)
        if not os.path.exists(FILENAME):
            print("File not found:", FILENAME)
            break

        MESSAGES.append(Message(FILENAME))

    serve(HOST, PORT, MESSAGES)
