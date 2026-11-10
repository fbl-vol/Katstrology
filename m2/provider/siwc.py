"""Optional, disabled-by-default OSS Sign in with ChatGPT plan grant.

Only synthetic transport fixtures may exercise this module in this assignment.
A real sign-in/request needs a separate explicit user authorization and opt-in.
"""

from base64 import b64decode, b64encode, urlsafe_b64encode
from contextlib import contextmanager
from hashlib import scrypt, sha256
import hmac
import json
import os
import re
from pathlib import Path
from threading import Lock, RLock
import secrets
import time
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
JWKS = ISSUER + '/.well-known/jwks.json'
RESOURCE = 'https://api.openai.com/v1'
MODELS = RESOURCE + '/models'
RESPONSES = RESOURCE + '/responses'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


class ProviderFailure(Exception):
    def __init__(self, reason, http_status=None, request_id=None, diagnostic=None):
        self.reason = reason if isinstance(reason, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', reason) else 'provider_request_failed'
        self.http_status = http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None
        self.request_id = request_id if isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', request_id) else None
        # Only fixed parser categories and bounded shape counts may cross this boundary.
        self.diagnostic = diagnostic if isinstance(diagnostic, dict) and (
            diagnostic.get('phase') == 'completed_output' and
            isinstance(diagnostic.get('category'), str) and
            diagnostic['category'] in {'multiple_calls', 'identifier_mismatch',
                'incomplete_item', 'text_mismatch', 'unsupported_item',
                'unsupported_content_part'} and
            isinstance(diagnostic.get('output_kinds'), list) and
            len(diagnostic['output_kinds']) <= 8 and
            all(isinstance(kind, str) and kind in {'function_call', 'message', 'reasoning', 'other'}
                for kind in diagnostic['output_kinds']) and
            all(type(diagnostic.get(key)) is int and 0 <= diagnostic[key] <= 8
                for key in ('output_items', 'completed_calls', 'announced_calls',
                            'streamed_completed_items')) and
            all(type(diagnostic.get(key)) is bool for key in
                ('missing_call_id', 'duplicate_call_id', 'identifier_conflict',
                 'footer_output_present')) and
            set(diagnostic) == {'phase', 'category', 'output_kinds', 'output_items',
                'completed_calls', 'announced_calls', 'streamed_completed_items',
                'footer_output_present', 'missing_call_id', 'duplicate_call_id',
                'identifier_conflict'}) else None
        super().__init__(self.reason)

    def public(self):
        result = {'reason': self.reason, 'http_status': self.http_status,
                  'request_id': self.request_id}
        if self.diagnostic is not None:
            result['diagnostic'] = self.diagnostic
        return result


class OpenAITransport:
    """Fixed HTTPS origins, no redirects, no ambient API key or proxy discovery."""

    def __init__(self):
        self.client = httpx.Client(timeout=20, follow_redirects=False, trust_env=False)

    def token(self, data):
        response = self.client.post(TOKEN, data=data, headers={'Accept': 'application/json'})
        if response.status_code != 200:
            code = 'oauth_exchange_failed'
            try:
                code = response.json().get('error', code)
            except (ValueError, AttributeError):
                pass
            raise ProviderFailure(code, response.status_code,
                                  response.headers.get('x-request-id'))
        return response.json()

    def jwks(self):
        response = self.client.get(JWKS)
        response.raise_for_status()
        return response.json()

    def models(self, token):
        response = self.client.get(MODELS, headers={'Authorization': 'Bearer ' + token})
        if response.status_code != 200:
            raise self.failure(response)
        return response.json()

    @staticmethod
    def failure(response, reason='provider_request_failed'):
        try:
            error = response.json().get('error')
            if isinstance(error, dict) and isinstance(error.get('code'), str):
                reason = error['code']
        except (ValueError, AttributeError):
            pass
        return ProviderFailure(reason, response.status_code,
                               response.headers.get('x-request-id') or
                               response.headers.get('openai-request-id'))

    @staticmethod
    def _search_lines(response):
        """Bound search SSE before line assembly/JSON, including heartbeat waits."""
        pending, total, started = b'', 0, time.monotonic()
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > 256 * 1024 or time.monotonic() - started > 45:
                raise ProviderFailure('search_response_limit')
            pending += chunk
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                yield line.rstrip(b'\r').decode('utf-8')
        if pending:
            yield pending.decode('utf-8')

    def response_events(self, token, body, *, bounded=False):
        # Background memory uses the same credential/route, with bounded SSE framing.
        # The existing 20-second socket timeout also bounds a silent read/header wait.
        searching = any(tool.get('type') == 'web_search' for tool in body.get('tools', []))
        with self.client.stream('POST', RESPONSES, json=body, headers={
                'Authorization': 'Bearer ' + token,
                'Accept': 'text/event-stream'}) as response:
            if response.status_code != 200:
                if searching or bounded:
                    raise ProviderFailure('background_provider_request_failed' if bounded else
                                          'search_provider_request_failed', response.status_code)
                response.read()
                raise self.failure(response)
            request_id = (response.headers.get('x-request-id') or
                          response.headers.get('openai-request-id'))
            lines = self._search_lines(response) if searching or bounded else response.iter_lines()
            for line in lines:
                if not line.startswith('data: '):
                    continue
                if line[6:] == '[DONE]':
                    break  # Transport EOF is not response.completed.
                try:
                    item = json.loads(line[6:])
                except ValueError:
                    raise ProviderFailure('invalid_provider_stream', request_id=request_id) from None
                yield item, request_id

    def revoke(self, refresh, client_id):
        discovery = self.client.get(ISSUER + '/.well-known/openid-configuration')
        discovery.raise_for_status()
        settings = discovery.json()
        endpoint = settings.get('revocation_endpoint', '')
        if (settings.get('issuer') != ISSUER or not endpoint.startswith(ISSUER + '/')
                or urlparse(endpoint).hostname != 'auth.openai.com'):
            raise ProviderFailure('invalid_revocation_endpoint')
        response = self.client.post(endpoint, data={
            'token': refresh, 'token_type_hint': 'refresh_token', 'client_id': client_id})
        if response.status_code != 200:
            raise self.failure(response, 'remote_revocation_unconfirmed')

    def close(self):
        self.client.close()


class CredentialFiles:
    """No browser exposure. Atomic 0600 per-owner credentials and stable host ID."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_mode & 0o077:
            raise PermissionError('Credential directory must be private')
        self.host = self.root / 'host.json'
        if not self.host.exists():
            self._write(self.host, {'ext_agent_host_id': 'urn:uuid:' + str(uuid4())})

    def _path(self, owner):
        return self.root / (sha256(owner.encode()).hexdigest() + '.json')

    def _write(self, path, value):
        temp = self.root / ('.' + secrets.token_hex(16))
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as target:
                json.dump(value, target, ensure_ascii=False)
                target.flush(); os.fsync(target.fileno())
            os.replace(temp, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temp.unlink(missing_ok=True)

    def _read(self, path, fallback):
        if not path.exists():
            return fallback
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise PermissionError('Credential file must be private')
        return json.loads(path.read_text(encoding='utf-8'))

    def load(self, owner):
        return self._read(self._path(owner), {'selected': None, 'accounts': {}})

    def save(self, owner, record):
        self._write(self._path(owner), record)

    def host_id(self):
        return self._read(self.host, {})['ext_agent_host_id']

    def forget_disconnected(self, owner):
        """Explicit offline recovery; never overwrite or erase a renewable session."""
        record = self.load(owner)
        selected = record.get('selected')
        account = record.get('accounts', {}).get(selected) if selected else None
        if (not account or len(record['accounts']) != 1 or account.get('access_token')
                or account.get('refresh_token')):
            raise ValueError('Exactly one disconnected registration required for offline recovery')
        self.save(owner, {'selected': None, 'accounts': {}})

    @staticmethod
    def _handoff_key(passphrase, salt):
        if not isinstance(passphrase, str) or len(passphrase) < 16:
            raise ValueError('A handoff passphrase of at least 16 characters is required')
        return scrypt(passphrase.encode(), salt=salt, n=2**15, r=8, p=1,
                      dklen=32, maxmem=64 * 1024 * 1024)

    def export_selected(self, owner, destination, passphrase):
        """Encrypt only the selected registration; never include this host's ID."""
        record = self.load(owner)
        selected = record['selected']
        account = record['accounts'].get(selected) if selected else None
        if (not account or not isinstance(selected, str) or
                'chatgpt.tokens.use.direct' not in account.get('scopes', ()) or
                not account.get('refresh_token')):
            raise ValueError('No renewable selected registration for this account')
        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
        plaintext = json.dumps({'owner': owner, 'selected': selected,
                                'account': account}).encode('utf-8')
        ciphertext = AESGCM(self._handoff_key(passphrase, salt)).encrypt(nonce, plaintext, None)
        envelope = {'format': 1, 'salt': b64encode(salt).decode(),
                    'nonce': b64encode(nonce).decode(),
                    'ciphertext': b64encode(ciphertext).decode()}
        target = Path(destination)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(envelope, output)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())

    def import_selected(self, owner, source, passphrase):
        """Fresh destination only; its own host ID survives and it owns first refresh."""
        path = Path(source)
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or path.stat().st_size > 65536):
            raise ValueError('Private handoff file required')
        envelope = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(envelope, dict) or set(envelope) != {'format', 'salt', 'nonce', 'ciphertext'} or envelope['format'] != 1:
            raise ValueError('Unsupported handoff file')
        salt, nonce = b64decode(envelope['salt'], validate=True), b64decode(envelope['nonce'], validate=True)
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError('Invalid handoff file')
        payload = AESGCM(self._handoff_key(passphrase, salt)).decrypt(
            nonce, b64decode(envelope['ciphertext'], validate=True), None)
        incoming = json.loads(payload)
        selected, account = incoming['selected'], incoming['account']
        if (incoming['owner'] != owner or not isinstance(selected, str) or
                not isinstance(account, dict) or account.get('client_id') != selected or
                not isinstance(account.get('subject'), str) or not account['subject'] or
                not isinstance(account.get('refresh_token'), str) or
                not account['refresh_token'] or
                'chatgpt.tokens.use.direct' not in account.get('scopes', ())):
            raise ValueError('Selected registration does not match authenticated owner')
        record = self.load(owner)
        if record['selected'] is not None or record['accounts']:
            raise ValueError('Destination already has a registration; no overwrite')
        record['selected'] = selected
        record['accounts'] = {selected: {**account, 'access_token': None, 'expires_at': 0}}
        self.save(owner, record)


class ProviderBridge:
    def __init__(self, root, transport=None):
        self.credentials = CredentialFiles(root)
        self.transport = transport or OpenAITransport()
        self.pending = {}
        self._locks = {}
        self._locks_guard = Lock()

    def _owner_lock(self, owner):
        with self._locks_guard:
            return self._locks.setdefault(owner, RLock())

    def _binding(self, owner):
        record = self.credentials.load(owner)
        selected = record['selected']
        account = record['accounts'].get(selected) if selected else None
        if (not account or 'chatgpt.tokens.use.direct' not in account.get('scopes', [])
                or not account.get('access_token') or not account.get('refresh_token')):
            raise ProviderFailure('chatgpt_plan_permission_required')
        # Only a digest crosses the admission/turn boundary; never a bearer or refresh secret.
        identity = [selected, account.get('subject'), account.get('scopes'),
                    account.get('access_token'), account.get('refresh_token')]
        return sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def binding(self, owner):
        with self._owner_lock(owner):
            return self._binding(owner)

    def access_bound(self, owner, binding):
        with self._owner_lock(owner):
            if self._binding(owner) != binding:
                raise ProviderFailure('selected_account_changed')
            token = self._access(owner)
            return token, self._binding(owner)  # Own refresh may rotate the token.

    def background_access(self, owner, binding):
        with self.background_guard(owner, binding) as token:
            return token

    @contextmanager
    def background_guard(self, owner, binding):
        """Nonwaiting credential fence, also held across the short memory commit."""
        lock = self._owner_lock(owner)
        if not lock.acquire(blocking=False):
            raise ProviderFailure('background_capacity_unavailable')
        try:
            if self._binding(owner) != binding:
                raise ProviderFailure('selected_account_changed')
            record = self.credentials.load(owner)
            account = record['accounts'][record['selected']]
            expires = account.get('expires_at')
            if (type(expires) not in (int, float) or expires < time.time() + 120):
                raise ProviderFailure('background_capacity_unavailable')
            yield account['access_token']
        finally:
            lock.release()

    def admit(self, owner, slug):
        from m2.provider.model_capacity import CatalogAdmission, resolve_capacity
        with self._owner_lock(owner):
            token = self._access(owner)
            binding = self._binding(owner)
        catalog = self._catalog(token)  # Remote wait must never reserve the Store executor.
        if self.binding(owner) != binding:
            raise ProviderFailure('selected_account_changed')
        selected = next((item for item in catalog if item['slug'] == slug), None)
        if selected is None:
            raise ProviderFailure('model_not_available_for_selected_account')
        return CatalogAdmission(owner, slug, binding, resolve_capacity(selected))

    def status(self, owner):
        record = self.credentials.load(owner)
        accounts = [{'client_id': key, 'email': value.get('email'),
                     'plan_enabled': 'chatgpt.tokens.use.direct' in value.get('scopes', [])
                     and bool(value.get('refresh_token')),
                     'selected': key == record['selected']}
                    for key, value in record['accounts'].items()]
        selected = record['accounts'].get(record['selected']) if record['selected'] else None
        if not selected:
            phase = 'not_connected'
        elif 'chatgpt.tokens.use.direct' not in selected.get('scopes', ()) and selected.get('id_token'):
            phase = 'identity_only'
        elif not selected.get('refresh_token'):
            phase = 'reauthorization_required'
        elif (not selected.get('access_token') or
              not isinstance(selected.get('expires_at'), (int, float)) or
              selected['expires_at'] < time.time() + 60):
            phase = 'refresh_required'
        else:
            phase = 'ready'
        return {'available': True, 'accounts': accounts,
                'connected': any(item['selected'] and item['plan_enabled'] for item in accounts),
                'selected': record['selected'], 'phase': phase}

    def begin(self, owner, session_digest, callback_uri, client_id=None):
        record = self.credentials.load(owner)
        if client_id is not None and client_id not in record['accounts']:
            raise ValueError('Unknown saved ChatGPT registration')
        callback = urlparse(callback_uri)
        if (callback.scheme != 'http' or callback.hostname != '127.0.0.1' or
                not callback.port or callback.path != '/auth/chatgpt/callback' or
                callback.query or callback.fragment):
            raise ValueError('Invalid fixed loopback callback')
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.pending = {key: item for key, item in self.pending.items()
                        if item['owner'] != owner and item['expires'] > time.time()}
        self.pending[state] = {'owner': owner, 'session_digest': session_digest,
                               'nonce': nonce, 'verifier': verifier, 'client_id': client_id,
                               'callback_uri': callback_uri, 'expires': time.time() + 600}
        params = {'client_id': client_id or 'dynamic_agent_client',
                  'ext_agent_host_id': self.credentials.host_id(),
                  'response_type': 'code', 'redirect_uri': callback_uri,
                  'scope': SCOPES, 'resource': RESOURCE, 'state': state, 'nonce': nonce,
                  'code_challenge_method': 'S256',
                  'code_challenge': urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
        if not client_id:
            params['agent_name_hint'] = 'Kat'
        else:
            account = record['accounts'][client_id]
            if account.get('id_token'):
                params['id_token_hint'] = account['id_token']
            if account.get('email'):
                params['login_hint'] = account['email']
        return state, AUTHORIZE + '?' + urlencode(params)

    def complete(self, state, cookie_state, query, live_session):
        attempt = self.pending.pop(state, None)
        if (not attempt or not cookie_state or not hmac.compare_digest(state, cookie_state)
                or attempt['expires'] <= time.time() or not live_session(
                    attempt['owner'], attempt['session_digest'])):
            raise ValueError('ChatGPT callback state or local session was not verified')
        if query.get('error'):
            return {'status': 'declined'}
        code, supplied_client = query.get('code'), query.get('client_id')
        issued = attempt['client_id'] or supplied_client
        if (not code or not issued or issued == 'dynamic_agent_client' or
                attempt['client_id'] and supplied_client and supplied_client != issued):
            raise ValueError('ChatGPT registration/client ID not verified')
        before_exchange = self.credentials.load(attempt['owner'])
        tokens = self.transport.token({'grant_type': 'authorization_code', 'client_id': issued,
                                       'code': code, 'code_verifier': attempt['verifier'],
                                       'redirect_uri': attempt['callback_uri'], 'resource': RESOURCE})
        if (tokens.get('token_type', '').lower() != 'bearer' or
                not isinstance(tokens.get('scope'), str) or
                not isinstance(tokens.get('expires_in'), int) or
                not 0 < tokens['expires_in'] <= 7200):
            raise ValueError('Invalid token exchange contract')
        identity = self._identity(tokens.get('id_token'), issued, attempt['nonce'])
        if identity.get('at_hash') and tokens.get('access_token'):
            digest = sha256(tokens['access_token'].encode()).digest()
            expected = urlsafe_b64encode(digest[:len(digest) // 2]).rstrip(b'=').decode()
            if not hmac.compare_digest(identity['at_hash'], expected):
                raise ValueError('Access token not bound to ID token')
        scopes = tokens.get('scope', '').split()
        account = {'client_id': issued, 'subject': identity['sub'],
                   'email': identity.get('email'), 'id_token': tokens['id_token'],
                   'scopes': scopes, 'access_token': tokens.get('access_token'),
                   'refresh_token': tokens.get('refresh_token'),
                   'expires_at': time.time() + int(tokens.get('expires_in', 0))}
        if 'chatgpt.tokens.use.direct' in scopes and not all((account['access_token'],
                                                               account['refresh_token'])):
            raise ValueError('Plan permission lacks renewable credentials')
        with self._owner_lock(attempt['owner']):
            record = self.credentials.load(attempt['owner'])
            if record != before_exchange:
                raise ValueError('Selected account changed during connection')
            prior = record['accounts'].get(issued)
            if prior and prior['subject'] != identity['sub']:
                raise ValueError('Saved account identity changed')
            record['accounts'][issued] = account
            record['selected'] = issued
            self.credentials.save(attempt['owner'], record)
            return {'status': 'connected' if 'chatgpt.tokens.use.direct' in scopes
                    else 'identity_only'}

    def _identity(self, id_token, client_id, nonce):
        if not isinstance(id_token, str):
            raise ValueError('ID token missing')
        header = jwt.get_unverified_header(id_token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
            raise ValueError('Unsupported ID token signing key')
        jwk = next((key for key in self.transport.jwks().get('keys', [])
                    if key.get('kid') == header['kid'] and key.get('kty') == 'RSA'), None)
        if not jwk:
            raise ValueError('ID token signing key not found')
        key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = jwt.decode(id_token, key, algorithms=['RS256'], issuer=ISSUER,
                            audience=client_id, leeway=5,
                            options={'require': ['iss', 'aud', 'sub', 'exp', 'iat']})
        if (not isinstance(claims['sub'], str) or not claims['sub'] or
                not hmac.compare_digest(str(claims.get('nonce', '')), nonce)):
            raise ValueError('ID token identity/nonce mismatch')
        return claims

    def choose(self, owner, client_id):
        with self._owner_lock(owner):
            record = self.credentials.load(owner)
            if client_id not in record['accounts']:
                raise KeyError('Unknown ChatGPT registration')
            record['selected'] = client_id
            self.credentials.save(owner, record)
            return self.status(owner)

    def access(self, owner):
        with self._owner_lock(owner):
            return self._access(owner)

    def _access(self, owner):
        record = self.credentials.load(owner)
        selected = record['selected']
        account = record['accounts'].get(selected) if selected else None
        if not account or 'chatgpt.tokens.use.direct' not in account['scopes']:
            raise ProviderFailure('chatgpt_plan_permission_required')
        if account['expires_at'] < time.time() + 60:
            try:
                result = self.transport.token({'grant_type': 'refresh_token',
                                               'client_id': selected,
                                               'refresh_token': account['refresh_token'],
                                               'resource': RESOURCE})
            except ProviderFailure as error:
                if error.reason in ('invalid_grant', 'invalid_refresh_token', 'token_expired',
                                    'refresh_token_expired', 'refresh_token_invalidated',
                                    'refresh_token_reused'):
                    account.update({'access_token': None, 'refresh_token': None,
                                    'expires_at': 0})
                    self.credentials.save(owner, record)
                raise
            if (result.get('token_type', '').lower() != 'bearer' or
                    not result.get('access_token') or not result.get('refresh_token') or
                    not isinstance(result.get('expires_in'), int) or
                    not 0 < result['expires_in'] <= 7200):
                raise ProviderFailure('incomplete_refresh_response')
            account.update({'access_token': result['access_token'],
                            'refresh_token': result['refresh_token'],
                            'expires_at': time.time() + int(result['expires_in']),
                            'scopes': result.get('scope', ' '.join(account['scopes'])).split()})
            self.credentials.save(owner, record)
        if ('chatgpt.tokens.use.direct' not in account['scopes'] or
                not account.get('access_token') or not account.get('refresh_token')):
            raise ProviderFailure('chatgpt_plan_permission_required')
        return account['access_token']

    def models(self, owner):
        return self._catalog(self.access(owner))

    def _catalog(self, token):
        raw = self.transport.models(token)
        models = raw.get('models', [])
        if not isinstance(models, list):
            raise ProviderFailure('invalid_model_catalog')
        listed = []
        for item in models:
            if not isinstance(item, dict) or item.get('visibility') != 'list' or not isinstance(
                    item.get('slug'), str) or not isinstance(item.get('display_name'), str):
                continue
            result = {'slug': item['slug'], 'display_name': item['display_name']}
            # Optional catalog extensions, not fields promised by the public
            # OpenAI /models schema. The resolver validates each present bound.
            for field in ('context_window', 'max_output_tokens'):
                if field in item:
                    result[field] = item[field]
            listed.append(result)
        return listed

    def revoke(self, owner):
        with self._owner_lock(owner):
            return self._revoke(owner)

    def _revoke(self, owner):
        record = self.credentials.load(owner)
        selected = record['selected']
        account = record['accounts'].get(selected) if selected else None
        if not account:
            return {'status': 'not_connected'}
        remote = 'revoked'
        if account.get('refresh_token'):
            try:
                self.transport.revoke(account['refresh_token'], selected)
            except Exception:
                remote = 'remote_revocation_unconfirmed'
        account.update({'access_token': None, 'refresh_token': None,
                        'id_token': None, 'expires_at': 0, 'scopes': []})
        self.credentials.save(owner, record)
        return {'status': 'disconnected', 'remote': remote}

    def close(self):
        self.transport.close()
