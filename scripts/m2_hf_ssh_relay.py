"""Relay HTTPS to official Hugging Face hosts over authorized SSH loopback channels."""

import argparse
import base64
import http.client
import importlib.util
import os
import secrets
import select
import shlex
import socket
import threading
import time
from contextlib import suppress
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies

from m2_hf_artifacts import now

ALLOWED_SUFFIXES = (".huggingface.co", ".hf.co", ".xethub.hf.co")
SLOTS = threading.BoundedSemaphore(64)


@lru_cache
def ssh_helper(path):
    spec = importlib.util.spec_from_file_location("m2_local_ssh_access", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def relay_password(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
            out.write(secrets.token_hex(32) + "\n")
    value = path.read_text(encoding="ascii").strip()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid relay credential")
    return value


def connect_target(channel, auth):
    channel.settimeout(15)
    request = bytearray()
    while b"\r\n\r\n" not in request and len(request) < 16384:
        chunk = channel.recv(4096)
        if not chunk:
            return None
        request.extend(chunk)
    if b"\r\n\r\n" not in request:
        return None
    headers, remainder = request.split(b"\r\n\r\n", 1)
    line, *metadata = headers.decode("ascii").split("\r\n")
    method, target, protocol = line.split()
    hostname, _, port = target.lower().rpartition(":")
    credentials = [line.partition(":")[2].strip() for line in metadata
                   if line.partition(":")[0].lower() == "proxy-authorization"]
    if len(credentials) != 1 or not secrets.compare_digest(credentials[0], auth):
        channel.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\n'
                        b'Proxy-Authenticate: Basic realm="Kurumi HF"\r\nContent-Length: 0\r\n\r\n')
        return None
    if (method != "CONNECT" or protocol not in {"HTTP/1.0", "HTTP/1.1"} or port != "443"
            or not (hostname in {"huggingface.co", "hf.co"} or hostname.endswith(ALLOWED_SUFFIXES))):
        channel.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        return None
    return hostname, remainder


def open_upstream(hostname):
    proxy = getproxies().get("https")
    if not proxy:
        return socket.create_connection((hostname, 443), timeout=15)
    url = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
    if url.scheme != "http" or not url.hostname:
        raise ValueError("controller HTTPS traffic requires an HTTP CONNECT proxy or direct TCP")
    headers = {}
    if url.username is not None:
        credentials = f"{unquote(url.username)}:{unquote(url.password or '')}".encode()
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credentials).decode()
    connection = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=15)
    connection.set_tunnel(hostname, port=443, headers=headers)
    try:
        connection.connect()
    except BaseException:
        connection.close()
        raise
    return connection.sock


def bridge(channel, auth):
    with SLOTS, channel:
        try:
            request = connect_target(channel, auth)
            if request is None:
                return
        except (OSError, EOFError, UnicodeError, ValueError):
            return
        hostname, remainder = request
        try:
            upstream = open_upstream(hostname)
        except (OSError, http.client.HTTPException, ValueError):
            with suppress(OSError, EOFError):
                channel.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        with upstream:
            try:
                channel.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if remainder:
                    upstream.sendall(remainder)
                upstream.settimeout(60)
                channel.settimeout(60)
                while True:
                    ready, _, _ = select.select([channel, upstream], [], [], 120)
                    if not ready:
                        return
                    for endpoint in ready:
                        chunk = endpoint.recv(256 << 10)
                        if not chunk:
                            return
                        other = upstream if endpoint is channel else channel
                        other.sendall(chunk)
            except (OSError, EOFError):
                return


def install_proxy_file(client, target, url):
    path = PurePosixPath(target)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("proxy file requires a dedicated absolute remote path")
    parent = shlex.quote(str(path.parent))
    _, stdout, _ = client.exec_command(f"umask 077; mkdir -p {parent} && chmod 700 {parent}")
    if stdout.channel.recv_exit_status():
        raise RuntimeError("cannot prepare private proxy configuration directory")
    temporary = str(path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp"))
    with client.open_sftp() as sftp:
        with sftp.file(temporary, "wx") as output:
            sftp.chmod(temporary, 0o600)
            output.write(url + "\n")
        sftp.posix_rename(temporary, str(path))


def enable(name, connector, port, remote_proxy_file, password):
    auth = "Basic " + base64.b64encode(f"kurumi:{password}".encode()).decode()
    while True:
        try:
            with connector() as client:
                transport = client.get_transport()
                transport.request_port_forward("127.0.0.1", port)
                install_proxy_file(client, remote_proxy_file, f"http://kurumi:{password}@127.0.0.1:{port}")
                print(f"{now()} {name} HF relay active on remote loopback TCP {port}", flush=True)
                while transport.is_active():
                    channel = transport.accept(10)
                    if channel is not None:
                        threading.Thread(target=bridge, args=(channel, auth), daemon=True).start()
        except Exception as error:
            print(f"{now()} {name} relay reconnecting after {type(error).__name__}", flush=True)
        time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-helper", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--a100-proxy-file", required=True)
    parser.add_argument("--gb10-proxy-file", required=True)
    parser.add_argument("--port", type=int, default=39287)
    args = parser.parse_args()
    helper = ssh_helper(args.ssh_helper.resolve())
    workers = []
    for name, connector, destination in (("a100", helper.a100_client, args.a100_proxy_file),
                                         ("gb10", helper.gb10_client, args.gb10_proxy_file)):
        password = relay_password(args.state_dir / f"{name}-relay.key")
        worker = threading.Thread(target=enable, args=(name, connector, args.port, destination, password), daemon=True)
        worker.start()
        workers.append(worker)
    for worker in workers:
        worker.join()


if __name__ == "__main__":
    main()
