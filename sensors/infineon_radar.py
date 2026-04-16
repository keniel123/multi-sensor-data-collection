"""
sensors/infineon_radar.py
Infineon 60 GHz radar recording — stub placeholder.

Replace the body of start() / wait() / stop() once the Infineon
SDK / CLI interface is confirmed.

Usage:
    from sensors.infineon_radar import InfineonRadarRecorder

    rec = InfineonRadarRecorder()
    rec.start(r'C:\\data\\session_inf.bin', duration_s=10)
    rc, log = rec.wait()
"""


class InfineonRadarRecorder:
    """Stub recorder for the Infineon 60 GHz radar."""

    def __init__(self):
        self._running = False

    def start(self, output_path: str, duration_s: int):
        print(f'[InfineonRadar] start() — NOT YET IMPLEMENTED')
        print(f'  output_path={output_path}  duration_s={duration_s}')
        self._running = True

    def wait(self) -> tuple[int, str]:
        self._running = False
        return 0, 'stub: not implemented'

    def stop(self):
        self._running = False
        print('[InfineonRadar] stop() — NOT YET IMPLEMENTED')

    @property
    def is_running(self) -> bool:
        return self._running
