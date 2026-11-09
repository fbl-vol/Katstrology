"""Credential-free, IP-pinned public HTTP reads. No proxies, cookies or scripts."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import socket
import ssl
from threading import BoundedSemaphore
from time import monotonic
from urllib.parse import urljoin, urlsplit

from m2.provider.web_search import public_url

MAX_BYTES = 256 * 1024
MAX_TEXT = 24000
_resolvers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='public-dns')
_dns_slots = BoundedSemaphore(2)


class PageFailure(Exception):
    pass


def public_addresses(host, port, cancelled, deadline=None):
    # Bound queued DNS work as well as caller wait. A timed-out OS lookup can
    # finish later, but cannot create a socket or grow an unbounded task queue.
    if not _dns_slots.acquire(blocking=False):
        raise PageFailure('dns_busy')
    future = _resolvers.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    future.add_done_callback(lambda _: _dns_slots.release())
    deadline = min(deadline, monotonic() + 5) if deadline is not None else monotonic() + 5
    while True:
        if cancelled():
            raise PageFailure('cancelled')
        try:
            records = future.result(timeout=min(.1, max(.001, deadline - monotonic())))
            break
        except FutureTimeout:
            if monotonic() >= deadline:
                raise PageFailure('dns_timeout') from None
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not safe_address(address) for address in addresses):
        raise PageFailure('blocked_address')
    return addresses


def safe_address(address):
    ip = ipaddress.ip_address(address)
    if '%' in address or (ip.version == 6 and any(ip in ipaddress.ip_network(prefix)
            for prefix in ('64:ff9b::/96', '64:ff9b:1::/48'))):
        return False
    return (ip.is_global and not ip.is_multicast and not ip.is_reserved and
            not ip.is_unspecified and not getattr(ip, 'ipv4_mapped', None) and
            not getattr(ip, 'sixtofour', None) and not getattr(ip, 'teredo', None))


class DeadlineReader(io.RawIOBase):
    """Guard every socket read, including reads hidden inside HTTP framing.

    Keep the original makefile alive for socket ownership, but do not read via
    SocketIO: a polling timeout permanently poisons its buffered read state.
    """
    def __init__(self, sock, keepalive, remaining):
        self.sock, self.keepalive, self.remaining = sock, keepalive, remaining
        self.idle_timeout = 5

    def readable(self):
        return True

    def readinto(self, target):
        idle_deadline = monotonic() + self.idle_timeout
        while True:
            remaining = min(self.remaining(), idle_deadline - monotonic())
            if remaining <= 0:
                raise PageFailure('timeout')
            self.sock.settimeout(min(.1, remaining))
            try:
                count = self.sock.recv_into(target)
            except TimeoutError:
                continue
            self.remaining()
            return count

    def close(self):
        try:
            self.keepalive.close()
        finally:
            super().close()


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, secure, timeout, *, deadline=None, cancelled=lambda: False):
        super().__init__(host, port, timeout=timeout)
        self.address, self.secure = address, secure
        self.deadline = deadline if deadline is not None else monotonic() + timeout
        self.cancelled = cancelled
        self.response_class = self.response

    def remaining(self):
        if self.cancelled():
            raise PageFailure('cancelled')
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise PageFailure('timeout')
        return remaining

    def response(self, sock, *args, **kwargs):
        response = http.client.HTTPResponse(sock, *args, **kwargs)
        self.response_reader = DeadlineReader(sock, response.fp, self.remaining)
        response.fp = io.BufferedReader(self.response_reader)
        return response

    def getresponse(self):
        response = super().getresponse()
        self.response_reader.idle_timeout = 2  # Preserve the stricter body/framing inactivity bound.
        return response

    def connect(self):
        family = socket.AF_INET6 if ':' in self.address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(min(self.timeout, self.remaining()))
            sock.connect((self.address, self.port))
            if sock.getpeername()[0] != self.address:
                raise PageFailure('peer_address_changed')
            sock.settimeout(min(self.timeout, self.remaining()))
            self.sock = (ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
                         if self.secure else sock)
            self.sock.settimeout(min(self.timeout, self.remaining()))
        except BaseException:
            sock.close()
            raise


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored, self.focus, self.title_depth = 0, 0, 0
        self.text, self.article, self.title = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'form', 'noscript', 'svg', 'template'):
            self.ignored += 1
        if tag in ('article', 'main'):
            self.focus += 1
        if tag == 'title':
            self.title_depth += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3'):
            self.handle_data('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'form', 'noscript', 'svg', 'template'):
            self.ignored = max(0, self.ignored - 1)
        if tag in ('article', 'main'):
            self.focus = max(0, self.focus - 1)
        if tag == 'title':
            self.title_depth = max(0, self.title_depth - 1)

    def handle_data(self, data):
        if self.title_depth:
            self.title.append(data)
        if not self.ignored and not self.title_depth:
            self.text.append(data)
            if self.focus:
                self.article.append(data)


def extract(raw, media_type, charset):
    if charset.lower() not in ('utf-8', 'utf8', 'us-ascii', 'iso-8859-1', 'windows-1252'):
        raise PageFailure('unsupported_charset')
    text = raw.decode(charset, errors='replace')
    title, method = '', 'plain_text'
    if media_type == 'text/html':
        parser = ArticleText()
        parser.feed(text)
        title = ' '.join(''.join(parser.title).split())[:240]
        text = ''.join(parser.article or parser.text)
        method = 'article_or_main_text' if parser.article else 'document_text_fallback'
    text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
    if not text:
        raise PageFailure('extraction_failed')
    content = text.encode()[:MAX_TEXT].decode('utf-8', errors='ignore')
    return {'content': content, 'title': title, 'extraction': method,
            'source_truncated': len(text.encode()) > MAX_TEXT,
            'content_sha256': sha256(content.encode()).hexdigest(),
            'content_kind': 'untrusted_public_page_text', 'publication_date': None,
            'coverage': 'Visible static response only, not proof of a complete article. '
                        'Access notices or client-rendered omissions may remain.'}


def fetch_page(requested_url, cancelled=lambda: False):
    result = {'requested_url': requested_url, 'final_url': requested_url,
              'retrieved_at': datetime.now(timezone.utc).isoformat(), 'provider': 'public_http'}
    deadline, url = monotonic() + 20, requested_url
    try:
        for redirect in range(4):
            if cancelled():
                raise PageFailure('cancelled')
            if not public_url(url):
                raise PageFailure('blocked_url')
            parsed = urlsplit(url)
            host = parsed.hostname.encode('idna').decode('ascii')
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            addresses = public_addresses(host, port, cancelled, deadline)
            if monotonic() >= deadline:
                raise PageFailure('timeout')
            # Connect exactly once to a validated literal address. No DNS occurs
            # between validation and connect, including after each redirect.
            connection = PinnedConnection(host, port, addresses[0], parsed.scheme == 'https',
                                          min(5, deadline - monotonic()),
                                          deadline=deadline, cancelled=cancelled)
            response = None
            try:
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
                connection.request('GET', path, headers={'User-Agent': 'KatPublicReader/1',
                    'Accept': 'text/html, text/plain', 'Accept-Encoding': 'identity',
                    'Connection': 'close'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location or redirect == 3:
                        raise PageFailure('redirect_limit')
                    target = urljoin(url, location)
                    if parsed.scheme == 'https' and urlsplit(target).scheme != 'https':
                        raise PageFailure('unsafe_redirect')
                    url = target
                    continue
                result['final_url'] = url
                if response.status != 200:
                    raise PageFailure('blocked_or_paywalled' if response.status in (401, 402, 403)
                                      else 'http_unavailable')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise PageFailure('unsupported_content_encoding')
                media = response.headers.get_content_type()
                if media not in ('text/html', 'text/plain'):
                    raise PageFailure('unsupported_content_type')
                raw = bytearray()
                while True:
                    if cancelled():
                        raise PageFailure('cancelled')
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise PageFailure('timeout')
                    block = response.read1(min(8192, MAX_BYTES + 1 - len(raw)))
                    if not block:
                        break
                    raw.extend(block)
                    if len(raw) > MAX_BYTES:
                        raise PageFailure('source_byte_limit')
                result.update(extract(bytes(raw), media, response.headers.get_content_charset('utf-8')))
                identity = '\0'.join((requested_url, url, result['retrieved_at'], result['content_sha256']))
                result['source_id'] = sha256(identity.encode()).hexdigest()
                return {**result, 'status': 'partial' if result['source_truncated'] else 'ok',
                        'source_bytes': len(raw), 'media_type': media}
            finally:
                if response is not None:
                    response.close()
                connection.close()
    except PageFailure as exc:
        return {**result, 'status': 'unavailable', 'reason': str(exc)}
    except TimeoutError:
        return {**result, 'status': 'unavailable', 'reason': 'timeout'}
    except (OSError, ValueError, http.client.HTTPException, UnicodeError):
        return {**result, 'status': 'unavailable', 'reason': 'network_or_format_failure'}
