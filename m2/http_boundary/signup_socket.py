"""Optional private edge listener; the ordinary TCP listener grants no signup.

Installation must grant only the edge service and app access to this directory's
owning group. No directory, permission, group or mount is provisioned here.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import stat

import uvicorn


@contextmanager
def signup_socket(path):
    path = Path(path)
    parent = path.parent
    info = parent.stat()
    if (parent.resolve() != parent or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or info.st_gid != os.getgid()
            or info.st_mode & 0o027 or info.st_mode & 0o700 != 0o700):
        raise ValueError('Signup socket directory must be app-owned, private and not group-writable')
    if path.exists() or path.is_symlink():
        previous = path.lstat()
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.getuid():
            raise ValueError('Refusing to replace an unowned signup path')
        # Caller has already bound the exclusive normal TCP port, so another
        # instance cannot still own this application's stale listener.
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        mask = os.umask(0o077)
        try:
            listener.bind(str(path))
        finally:
            os.umask(mask)
        identity = path.stat().st_ino
        path.chmod(0o660)
        yield listener
    finally:
        listener.close()
        if identity is not None and path.exists() and path.lstat().st_ino == identity:
            path.unlink()


def serve_with_signup(app, policy, host, port):
    config = uvicorn.Config(app, host=host, port=port, proxy_headers=False,
                            access_log=False, log_level='warning')
    # Bind TCP first; a competing running instance must prevent stale-socket cleanup.
    tcp = config.bind_socket()
    try:
        with signup_socket(policy.socket) as private:
            uvicorn.Server(config).run(sockets=[tcp, private])
    finally:
        tcp.close()
