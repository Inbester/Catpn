"""A stand-in for wireproxy: reads the rendered config, then serves SOCKS5.

It behaves like the real binary in the ways TunnelManager depends on —
`-s -c <path>`, a `[Socks5] BindAddress`, a log line on stderr and a
non-zero exit when the config is bad — and connects straight to the
target instead of through WireGuard. A config whose Endpoint host is
`fail.invalid` makes it exit the way wireproxy does on a bad peer; one
whose host is `silent.invalid` starts and listens but answers every
request the way wireproxy does when the peer never completes a handshake.

It also copies the config it was given to `$FAKE_WIREPROXY_SEEN`, so a
test can check exactly what reached the process, and appends every target
it connects to to `$FAKE_WIREPROXY_CONNECTS`, so a test can tell traffic
that went through the tunnel from traffic that did not.
"""

from __future__ import annotations

import asyncio
import os
import socket
import struct
import sys


def _config_path(argv: list[str]) -> str:
    return argv[argv.index("-c") + 1]


def _read(path: str) -> str:
    with open(path) as handle:
        return handle.read()


def _write(path: str, text: str, mode: str = "w") -> None:
    with open(path, mode) as handle:
        handle.write(text)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


SILENT = False


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    _version, methods = await reader.readexactly(2)
    await reader.readexactly(methods)
    writer.write(b"\x05\x00")
    if SILENT:
        await reader.read(262)
        # A reply SOCKS clients cannot parse, as wireproxy sends.
        writer.write(b"\x05\x04\x00\x00")
        await writer.drain()
        writer.close()
        return
    _ver, _cmd, _rsv, kind = await reader.readexactly(4)
    if kind == 1:
        host = socket.inet_ntoa(await reader.readexactly(4))
    elif kind == 3:
        host = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
    else:
        writer.close()
        return
    (port,) = struct.unpack("!H", await reader.readexactly(2))
    log = os.environ.get("FAKE_WIREPROXY_CONNECTS")
    if log:
        _write(log, f"{host}:{port}\n", "a")
    try:
        up_reader, up_writer = await asyncio.open_connection(host, port)
    except OSError:
        writer.write(b"\x05\x05\x00\x01" + b"\x00" * 6)
        writer.close()
        return
    writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
    await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


async def main() -> int:
    path = _config_path(sys.argv)
    text = _read(path)
    seen = os.environ.get("FAKE_WIREPROXY_SEEN")
    if seen:
        _write(seen, text)

    if "fail.invalid" in text:
        sys.stderr.write("2026/10/01 12:00:00 lookup fail.invalid: no such host\n")
        return 1

    global SILENT
    SILENT = "silent.invalid" in text

    bind = next(
        line.split("=", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().lower().startswith("bindaddress")
    )
    host, _, port = bind.rpartition(":")
    server = await asyncio.start_server(_handle, host, int(port))
    async with server:
        await server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
