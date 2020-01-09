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
        self.filename = messagefile
        try:
            self.data = data = msg.read()
            self.size = len(data)
            self.head, bot = data.split("\n\n", 1)
            self.body = bot.split("\n")
        finally:
            msg.close()

        self.uid = os.path.basename(self.filename)

    def top(self, lines):
        """Return the specified number of body lines from our message"""
        return self.head + "\r\n\r\n" + "\r\n".join(self.body[:lines])

    def retr(self):
        """Return the entire message"""
        # could reconstruct this from self.head and self.body
        # (allowing self.data to be deleted)
        return self.data


class POPConnection():
    def __init__(self, connection, messages):
        self.conn = ChatterboxConnection(connection)
        self.messages = messages

    def send_banner(self):
        """Send welcome banner"""
        self.conn.sendall("+OK pypopper file-based pop3 server ready")

    def send_msg(self, *args):
        """Send a generic response"""
        strings = []
        for arg in args:
            strings.append(str(arg))
        data = " ".join(strings)
        self.conn.sendall(data)

    def send_err(self, *args):
        """Generate an error response"""
        self.send_msg("-ERR", *args)

    def send_ok(self, *args):
        """Generate a success response"""
        self.send_msg("+OK", *args)

    def _param2message(self, param):
        """Extract a message number and convert it into a message object"""
        try:
            msgno = int(param)
        except ValueError:
            self.send_err("bad number", param)
            raise ValueError

        try:
            msg = self.messages[msgno-1]
        except IndexError:
            self.send_err("bad message number", msgno)
            raise ValueError

        return (msg, msgno)

    def process_connection(self):
        """
        Process the entire client connection.
        Using a blocking single-thread system
        """
        self.send_banner()

        connected = True
        while connected:
            data = self.conn.recvall()
            if data is None:
                return
            if not data:
                continue

            connected = self.process_line(data)

    def process_line(self, line):
        """Process a command line from the client"""
        words = line.split(maxsplit=1)
        command = words.pop(0)
        if words:
            param = words[0]
        else:
            param = None

        handler = self.get_handler(command)
        result = handler(param)
        return result

    def get_handler(self, command):
        """Return the handler function for a given command name"""
        handlername = 'handle_' + command.lower()
        handler = getattr(self, handlername, None)
        if not callable(handler):
            handler = self.handle_unknown
        return handler

    def handle_unknown(self, unused1):
        self.send_err("unknown command")
        return True

    def handle_user(self, unused1):
        self.send_ok("user accepted")
        return True

    def handle_pass(self, unused1):
        self.send_ok("pass accepted")
        return True

    def handle_capa(self, unused1):
        self.send_ok("\r\n".join((
            "Capability list follows",
            "TOP",
            "USER",
            "UIDL",
            ".",
        )))
        return True

    def handle_stat(self, unused1):
        size = 0
        for msg in self.messages:
            size += msg.size
        self.send_ok(len(self.messages), size)
        return True

    def handle_list(self, data):
        if data:
            try:
                msg, msgno = self._param2message(data)
            except ValueError:
                return True

            self.send_ok(msgno, msg.size)
            return True

        size = 0
        s = []
        msgno = 1
        for msg in self.messages:
            s.append("%i %i\r\n" % (msgno, msg.size))
            size += msg.size
            msgno += 1

        s.insert(
            0, "%i messages (%i octets)\r\n" % (len(self.messages), size))
        s.append('.')

        self.send_ok(''.join(s))
        return True

    def handle_uidl(self, data):
        if data:
            try:
                msg, msgno = self._param2message(data)
            except ValueError:
                return True

            self.send_ok(msgno, msg.uid)
            return True

        s = []
        s.append("unique-id listing follows\r\n")
        msgno = 1
        for msg in self.messages:
            s.append("%i %s\r\n" % (msgno, msg.uid))
            msgno += 1

        s.append('.')

        self.send_ok(''.join(s))
        return True

    def handle_top(self, data):
        num, lines = data.split()
        try:
            msg, _ = self._param2message(num)
        except ValueError:
            return True

        try:
            lines = int(lines)
        except ValueError:
            self.send_err("bad number", lines)
            return True

        self.send_ok("top of message follows\r\n%s\r\n." % msg.top(lines))
        return True

    def handle_retr(self, data):
        try:
            msg, msgno = self._param2message(data)
        except ValueError:
            return True

        data = msg.retr()
        self.send_ok("%i octets\r\n%s\r\n." % (len(data), data))

        LOG.info("message %i sent", msgno)
        return True

    def handle_dele(self, unused1):
        self.send_ok("message 1 deleted")
        return True

    def handle_noop(self, unused1):
        self.send_ok()
        return True

    def handle_quit(self, unused1):
        self.send_ok("pypopper POP3 server signing off")
        self.conn.close()
        return False


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
                pop = POPConnection(conn, messages)
                pop.process_connection()
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
