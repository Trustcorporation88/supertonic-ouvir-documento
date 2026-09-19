"""Resource controls independent of model downloads."""
import asyncio
import ipaddress
import os
from pathlib import Path
import subprocess
import tempfile
import time


class ResourceError(Exception):
    pass


class Cancelled(Exception):
    pass


class BodyLimitMiddleware:
    """Limit actual ASGI bytes before multipart parsing, including chunked bodies."""
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        total = 0
        exceeded = False
        async def limited_receive():
            nonlocal total, exceeded
            message = await receive()
            total += len(message.get('body', b''))
            if total > self.max_bytes:
                exceeded = True
                # Let multipart close its temporary files on its normal error path.
                from starlette.formparsers import MultiPartException
                raise MultiPartException('Request body too large')
            return message
        async def guarded_send(message):
            if exceeded:
                if message['type'] == 'http.response.start':
                    message = {'type': 'http.response.start', 'status': 413,
                               'headers': [(b'content-type', b'application/json')]}
                elif message['type'] == 'http.response.body':
                    message = {'type': 'http.response.body', 'body': b'{"error":{"message":"Upload muito grande.","code":"file_too_large"}}', 'more_body': False}
            await send(message)
        await self.app(scope, limited_receive, guarded_send)


async def save_upload(upload, directory, limit):
    """Copy bounded blocks, never retain the upload in a Job; always close input."""
    fd, name = tempfile.mkstemp(prefix='upload-', dir=directory)
    path = Path(name)
    total = 0
    try:
        with os.fdopen(fd, 'wb') as target:
            while True:
                block = await upload.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ResourceError('file_too_large')
                target.write(block)
        if not total:
            raise ResourceError('empty_file')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def trusted_peer(host, configured):
    try:
        ip = ipaddress.ip_address(host)
        return any(ip in ipaddress.ip_network(item.strip()) for item in configured.split(',') if item.strip())
    except ValueError:
        return False


def run_process(command, check_cancel, timeout=1800):
    """No stdout/stderr accumulation. Kill and reap children on timeout/cancel."""
    with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
        deadline = time.monotonic() + timeout
        try:
            while proc.poll() is None:
                check_cancel()
                if time.monotonic() > deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
                time.sleep(.1)
            check_cancel()
            if proc.returncode:
                raise subprocess.CalledProcessError(proc.returncode, command)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
