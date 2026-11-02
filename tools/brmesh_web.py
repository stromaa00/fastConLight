"""Web frontend for brmesh_debug: drive an ESP32 transmitter from the browser.

    pip install aioesphomeapi aiohttp
    python tools/brmesh_web.py            # then open http://127.0.0.1:8099

BRMESH_HOST, BRMESH_KEY and BRMESH_PHONE_KEY prefill the connection form.
Listens on localhost only unless --bind is given.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import os
from pathlib import Path

from aiohttp import WSMsgType, web

import brmesh_debug as debug

PAGE = Path(__file__).with_name("brmesh_web.html")


class Session:
    """The current ESP32 connection and the browsers watching it."""

    def __init__(self) -> None:
        self.dbg: debug.Debugger | None = None
        self.sockets: set[web.WebSocketResponse] = set()
        self.history: deque[dict] = deque(maxlen=1000)
        self.lock = asyncio.Lock()

    def emit(self, kind: str, text: str) -> None:
        event = {"kind": kind, "text": text}
        self.history.append(event)
        message = json.dumps(event)
        for ws in list(self.sockets):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(message))

    def state(self) -> dict:
        dbg = self.dbg
        if dbg is None:
            return {"connected": False}
        info = dbg.info
        return {
            "connected": True,
            "device": {
                "name": info.name,
                "model": info.model,
                "esphome": info.esphome_version,
                "mac": info.mac_address,
                "action": dbg.action.name if dbg.action else None,
            },
            "phone_key": dbg.phone_key.hex().upper(),
            "duration": dbg.duration_ms,
            "interval": dbg.interval_ms,
            "interval_supported": dbg.interval_action is not None,
            "show_all": dbg.show_all,
            "watch": dbg.watch,
            "light_types": [
                [code, name] for code, name in sorted(debug.protocol.LIGHT_TYPE_NAMES.items())
            ],
            "discovered": [
                {
                    "name": found.name,
                    "did": did,
                    "type": debug.protocol.device_type_name(found.device_type),
                    "type_code": found.device_type,
                    "key": found.key.hex().upper(),
                    "address": found.mesh_address,
                    "pending": dbg.pending_binds.get(did),
                    "seen": did in dbg.seen,
                    "heartbeat": found.mesh_address in dbg.heartbeats,
                    "identity": f"{found.name}-{did}-{found.device_type:04X}-{found.key.hex().upper()}",
                }
                for did, found in dbg.discovered.items()
            ],
            "heartbeats": [
                {"address": address, "group": group, "rssi": rssi, "time": time}
                for address, (group, rssi, time) in sorted(dbg.heartbeats.items())
            ],
        }

    async def connect(self, form: dict) -> None:
        await self.disconnect()
        args = argparse.Namespace(
            host=form["host"].strip(),
            port=int(form.get("port") or 6053),
            key=form.get("key", "").strip() or None,
            action=form.get("action") or "send_brmesh",
            phone_key=form.get("phone_key") or "A1A2A3A4",
            duration=int(form.get("duration") or 1000),
        )
        dbg = debug.Debugger(args, self.emit)
        self.emit("info", f"Connecting to {args.host}:{args.port} ...")
        await dbg.connect()
        if form.get("interval"):
            try:
                await dbg.set_interval(int(form["interval"]))
            except RuntimeError as err:
                self.emit("error", str(err))
        dbg.start_logs()
        dbg.start_sniffing()
        self.dbg = dbg

    async def disconnect(self) -> None:
        if self.dbg is not None:
            dbg, self.dbg = self.dbg, None
            await dbg.close()
            self.emit("info", "Disconnected.")


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(PAGE)


async def defaults(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "host": os.environ.get("BRMESH_HOST", ""),
            "key": os.environ.get("BRMESH_KEY", ""),
            "phone_key": os.environ.get("BRMESH_PHONE_KEY", "A1A2A3A4"),
        }
    )


async def state(request: web.Request) -> web.Response:
    return web.json_response(request.app["session"].state())


async def connect(request: web.Request) -> web.Response:
    session: Session = request.app["session"]
    async with session.lock:
        try:
            await session.connect(await request.json())
        except Exception as err:  # noqa: BLE001 - shown in the page
            session.dbg = None
            session.emit("error", f"Connection failed: {err}")
            return web.json_response({"ok": False, "error": str(err)})
    return web.json_response({"ok": True})


async def disconnect(request: web.Request) -> web.Response:
    session: Session = request.app["session"]
    async with session.lock:
        await session.disconnect()
    return web.json_response({"ok": True})


async def command(request: web.Request) -> web.Response:
    """Run one shell command line, as typed in brmesh_debug's shell."""
    session: Session = request.app["session"]
    line = (await request.json()).get("line", "")
    if session.dbg is None:
        session.emit("error", "Not connected.")
        return web.json_response({"ok": False})
    session.emit("cmd", f"> {line}")
    try:
        await debug.run_line(session.dbg, line)
    except (ValueError, IndexError) as err:
        session.emit("error", f"Invalid arguments: {err}")
        return web.json_response({"ok": False})
    except Exception as err:  # noqa: BLE001 - shown in the page
        session.emit("error", f"Error: {err}")
        return web.json_response({"ok": False})
    return web.json_response({"ok": True})


async def websocket(request: web.Request) -> web.WebSocketResponse:
    session: Session = request.app["session"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    for event in session.history:
        await ws.send_str(json.dumps(event))
    session.sockets.add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        session.sockets.discard(ws)
    return ws


async def on_shutdown(app: web.Application) -> None:
    await app["session"].disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Web frontend for brmesh_debug")
    parser.add_argument("--bind", default="127.0.0.1", help="address to listen on")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    app = web.Application()
    app["session"] = Session()
    app.on_shutdown.append(on_shutdown)
    app.add_routes(
        [
            web.get("/", index),
            web.get("/ws", websocket),
            web.get("/api/defaults", defaults),
            web.get("/api/state", state),
            web.post("/api/connect", connect),
            web.post("/api/disconnect", disconnect),
            web.post("/api/command", command),
        ]
    )
    print(f"BRMesh debug frontend on http://{args.bind}:{args.port}")
    web.run_app(app, host=args.bind, port=args.port, print=None)


if __name__ == "__main__":
    main()
