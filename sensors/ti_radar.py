"""
sensors/ti_radar.py
TI AWR2243 radar recording via the mmWave Studio Lua TCP server.

The Lua server (radar_server.lua) must be running inside mmWave Studio
before calling start().  Load it via Scripts > Open > radar_server.lua > Run.

Usage:
    from sensors.ti_radar import TIRadarRecorder

    rec = TIRadarRecorder()
    rec.setup()               # one-time DCA1000 Ethernet config
    rec.start(r'C:\\data\\session.bin', duration_s=10)
    # ... countdown / other work (non-blocking) ...
    rc, log = rec.wait()
"""

import socket
import threading


RADAR_SERVER_HOST = '127.0.0.1'
RADAR_SERVER_PORT = 55000


class TIRadarRecorder:
    """
    Communicates with radar_server.lua running inside mmWave Studio.
    Recording runs in a background thread so the GUI stays responsive.
    """

    def __init__(self, host: str = RADAR_SERVER_HOST, port: int = RADAR_SERVER_PORT):
        self.host    = host
        self.port    = port
        self._thread = None
        self._result = [None]   # [response_str]

    # ── Public interface ───────────────────────────────────────────────────────

    def setup(self, timeout: float = 15.0) -> str:
        """
        Send 'setup' command: configures DCA1000 Ethernet + capture mode.
        Blocking.  Returns the server response string.
        """
        resp = self._send('setup', timeout=timeout)
        print(f'[TIRadar] setup -> {resp}')
        return resp

    def ping(self) -> bool:
        """Return True if the Lua server is reachable."""
        return self._send('ping', timeout=3) == 'pong'

    def start(self, output_path: str, duration_s: int):
        """
        Arm DCA1000 and trigger radar frame in a background thread.
        Returns immediately — call wait() to block until done.

        Args:
            output_path: Full Windows path for the .bin file
                         (DCA strips .bin and appends _Raw_0.bin automatically).
            duration_s:  Recording length in seconds.
        """
        duration_ms = duration_s * 1000
        cmd = f'record|{output_path}|{duration_ms}'
        print(f'[TIRadar] Starting: {cmd}')

        self._result = [None]

        def _worker(c=cmd, tmo=duration_s + 15):
            self._result[0] = self._send(c, timeout=tmo)

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def wait(self) -> tuple[int, str]:
        """
        Block until the radar recording thread finishes.

        Returns:
            (0, response_str) on success, (1, error_str) on failure.
        """
        if self._thread is None:
            return 0, '(never started)'
        self._thread.join(timeout=120)
        resp = self._result[0] or 'error: no response'
        rc   = 0 if resp == 'record_done' else 1
        print(f'[TIRadar] Done — {resp}')
        return rc, resp

    def stop(self):
        """No-op stub: the Lua server controls stop via duration."""
        print('[TIRadar] stop() called — recording is duration-controlled by Lua server')

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _send(self, command: str, timeout: float = 10.0) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=5) as s:
                s.sendall((command + '\n').encode())
                s.settimeout(timeout)
                return s.recv(256).decode().strip()
        except ConnectionRefusedError:
            return 'error: Lua server not running — open radar_server.lua in mmWave Studio and press Run'
        except Exception as e:
            return f'error: {e}'
