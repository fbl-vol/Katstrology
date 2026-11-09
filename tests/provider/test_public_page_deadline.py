"""Real http.client framing over a virtual-time socket; no external network."""
import io
import unittest
from unittest.mock import patch

from m2.provider.public_pages import fetch_page


class SocketFile(io.RawIOBase):
    def __init__(self, sock):
        self.sock = sock
        sock.files.append(self)

    def readable(self):
        return True

    def readinto(self, target):
        return self.sock.recv_into(target)


class DripSocket:
    def __init__(self, prefix, suffix, interval=4):
        self.clock = 0.0
        self.prefix, self.suffix = bytearray(prefix), bytearray(suffix)
        self.interval, self.next_byte = interval, interval
        self.timeout, self.closed, self.files = 5, False, []

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        assert address == ('8.8.8.8', 80)

    def getpeername(self):
        return ('8.8.8.8', 80)

    def sendall(self, data):
        pass

    def recv_into(self, target):
        if self.prefix:
            count = min(len(target), len(self.prefix))
            target[:count] = self.prefix[:count]
            del self.prefix[:count]
            return count
        if not self.suffix:
            return 0
        if self.clock + self.timeout < self.next_byte:
            self.clock += self.timeout
            raise TimeoutError()
        self.clock = self.next_byte
        self.next_byte += self.interval
        target[0] = self.suffix.pop(0)
        return 1

    def makefile(self, mode):
        return io.BufferedReader(SocketFile(self))

    def close(self):
        self.closed = True


class PublicFramingTests(unittest.TestCase):
    def test_status_headers_chunk_size_and_trailers_obey_deadline_and_stop(self):
        headers = b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n'
        chunked = headers + b'Transfer-Encoding: chunked\r\n\r\n'
        phases = {
            'status': (b'', headers + b'Content-Length: 2\r\n\r\nOK'),
            'headers': (headers, b'X-Drip: ' + b'x' * 50 + b'\r\nContent-Length: 2\r\n\r\nOK'),
            'chunk size': (chunked, b'2;extension=' + b'x' * 50 + b'\r\nOK\r\n0\r\n\r\n'),
            'trailers': (chunked + b'2\r\nOK\r\n0\r\n', b'X-Drip: ' + b'x' * 50 + b'\r\n\r\n'),
        }
        for phase, (prefix, suffix) in phases.items():
            for stop_at, reason, bound in ((12, 'cancelled', 12.11),
                                           (10.5, 'cancelled', 10.61), (1000, 'timeout', 20.01)):
                with self.subTest(phase=phase, reason=reason):
                    sock = DripSocket(prefix, suffix, 1 if phase in ('chunk size', 'trailers') else 4)
                    with patch('m2.provider.public_pages.socket.socket', return_value=sock), patch(
                            'm2.provider.public_pages.public_addresses', return_value=['8.8.8.8']), patch(
                            'm2.provider.public_pages.monotonic', side_effect=lambda: sock.clock):
                        result = fetch_page('http://synthetic.example/article', lambda: sock.clock >= stop_at)
                    self.assertEqual(result['reason'], reason)
                    self.assertLessEqual(sock.clock, bound)
                    self.assertTrue(sock.closed)
                    self.assertTrue(sock.files)
                    self.assertTrue(all(file.closed for file in sock.files))

    def test_normal_chunked_response_and_idle_timeout_close_every_socket_file(self):
        for interval, reason in ((0.01, None), (3, 'timeout')):
            with self.subTest(interval=interval):
                sock = DripSocket(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n'
                                  b'Transfer-Encoding: chunked\r\n\r\n',
                                  b'2\r\nOK\r\n0\r\n\r\n', interval)
                with patch('m2.provider.public_pages.socket.socket', return_value=sock), patch(
                        'm2.provider.public_pages.public_addresses', return_value=['8.8.8.8']), patch(
                        'm2.provider.public_pages.monotonic', side_effect=lambda: sock.clock):
                    result = fetch_page('http://synthetic.example/article')
                if reason:
                    self.assertEqual(result['reason'], reason)
                    self.assertLessEqual(sock.clock, 2.01)
                else:
                    self.assertEqual(result['content'], 'OK')
                self.assertTrue(sock.closed)
                self.assertTrue(all(file.closed for file in sock.files))
