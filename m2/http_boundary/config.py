"""Deployment configuration validation without importing the HTTP application."""
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.conninfo import make_conninfo

from m2.archive.store import Store


def deployment_origin(value):
    """Validate the public browser authority without trusting proxy headers."""
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and
                 parsed.hostname == parsed.hostname.lower() and
                 '.' in parsed.hostname and parsed.port is None and
                 not parsed.username and not parsed.password and
                 not parsed.path and not parsed.query and not parsed.fragment and
                 value == f'https://{parsed.hostname}' and
                 not parsed.hostname.endswith('.') and
                 all(part and part.isascii() and part.replace('-', '').isalnum()
                     and not part.startswith('-') and not part.endswith('-')
                     for part in parsed.hostname.split('.')))
    except (TypeError, ValueError):
        valid = False
    if valid:
        try:
            ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            valid = False
    if not valid:
        raise ValueError('Deployment requires an exact HTTPS DNS origin without a port or path')
    return value


def deployment_dsn(password_file, host, database, user):
    """Configuration-only resolution; never use fixture discovery in deployment."""
    path = Path(password_file)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077):
        raise ValueError('Deployment database password file must be private and absolute')
    Store._id(database)
    Store._id(user)
    if host != 'db':
        raise ValueError('Deployment database must use the private Compose service')
    secret = path.read_text(encoding='utf-8').rstrip('\n')
    if not secret or '\n' in secret or '\r' in secret:
        raise ValueError('Invalid deployment database password file')
    return make_conninfo(host=host, port=5432, dbname=database, user=user, password=secret)
