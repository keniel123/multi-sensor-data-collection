"""
sensors/ti_radar.py
TI AWR2243 radar recording via the mmWave Studio Lua TCP server.

The Lua server (radar_server.lua) must be running inside mmWave Studio
before calling start().  Load it via Scripts > Open > radar_server.lua > Run.

Usage:
    from sensors.ti_radar import TIRadarRecorder

    rec = TIRadarRecorder(mmwave_config=r'C:\\path\\to\\config5.xml')
    rec.setup()               # one-time DCA1000 Ethernet config
    rec.start(r'C:\\data\\session.bin', duration_s=10)
    # ... countdown / other work (non-blocking) ...
    rc, log = rec.wait()
"""

import platform
import re
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET


def _radar_host() -> str:
    """Return Windows host IP when running in WSL, else 127.0.0.1."""
    if 'microsoft' in platform.uname().release.lower():
        try:
            out = subprocess.check_output(['cat', '/etc/resolv.conf'], text=True)
            m = re.search(r'nameserver\s+(\S+)', out)
            if m:
                return m.group(1)
        except Exception:
            pass
    return '127.0.0.1'


RADAR_SERVER_HOST = _radar_host()
RADAR_SERVER_PORT = 55000

# Fallback values used only if the mmWave Studio config XML cannot be read.
_DEFAULT_FRAME_PERIOD_MS = 30   # config5: periodicity=30ms → 33.33 fps
_DEFAULT_LOOP_COUNT      = 255  # config5: loopCount=255 chirps per frame


def _parse_mmwave_config(config_path: str) -> tuple[float, int]:
    """
    Read frame periodicity (ms) and loop count from a mmWave Studio XML config.
    Returns (frame_period_ms, loop_count) or the defaults on any error.
    """
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()

        def get(section, name):
            node = root.find(f'.//{section}/param[@name="{name}"]')
            return node.attrib['value'] if node is not None else None

        period    = get('apiname_frame_cfg', 'periodicity')
        loopcount = get('apiname_frame_cfg', 'loopCount')

        frame_period_ms = float(period)    if period    is not None else _DEFAULT_FRAME_PERIOD_MS
        loop_count      = int(loopcount)   if loopcount is not None else _DEFAULT_LOOP_COUNT

        print(f'[TIRadar] Config loaded from {config_path}: '
              f'periodicity={frame_period_ms}ms, loopCount={loop_count}')
        return frame_period_ms, loop_count

    except Exception as e:
        print(f'[TIRadar] Could not parse config XML ({e}), using defaults: '
              f'periodicity={_DEFAULT_FRAME_PERIOD_MS}ms, loopCount={_DEFAULT_LOOP_COUNT}')
        return _DEFAULT_FRAME_PERIOD_MS, _DEFAULT_LOOP_COUNT


class TIRadarRecorder:
    """
    Communicates with radar_server.lua running inside mmWave Studio.
    Recording runs in a background thread so the GUI stays responsive.

    Pass mmwave_config= with the path to your mmWave Studio XML config file
    (e.g. config5.xml) so frame timing is read automatically from the file
    rather than hardcoded.
    """

    def __init__(self,
                 host: str = RADAR_SERVER_HOST,
                 port: int = RADAR_SERVER_PORT,
                 mmwave_config: str = None):
        self.host    = host
        self.port    = port
        self._thread = None
        self._result = [None]

        if mmwave_config:
            self._frame_period_ms, self._loop_count = _parse_mmwave_config(mmwave_config)
        else:
            self._frame_period_ms = _DEFAULT_FRAME_PERIOD_MS
            self._loop_count      = _DEFAULT_LOOP_COUNT

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

        Frame timing (periodicity, loopCount) is taken from the mmWave Studio
        config XML passed at construction, not hardcoded.
        """
        duration_ms = duration_s * 1000
        cmd = f'record|{output_path}|{duration_ms}|{self._frame_period_ms}|{self._loop_count}'
        print(f'[TIRadar] Starting: {cmd}')

        self._result = [None]

        def _worker(c=cmd, tmo=duration_s + 90):
            t0 = time.time()
            print(f'[TIRadar] Waiting for Lua server (timeout {tmo}s)...')
            result = self._send(c, timeout=tmo)
            print(f'[TIRadar] Lua responded after {time.time()-t0:.1f}s')
            self._result[0] = result

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
