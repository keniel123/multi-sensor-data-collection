"""
sensors/kinect_azure.py
Azure Kinect recording via k4arecorder.exe.

Usage:
    from sensors.kinect_azure import KinectAzureRecorder

    rec = KinectAzureRecorder()
    rec.start(r'C:\\data\\session_kinect.mkv', duration_s=10)
    # ... countdown / other work ...
    rc, log = rec.wait()
"""

import subprocess
import os


# ── Default paths and capture settings ────────────────────────────────────────
K4A_RECORDER  = r'C:\Program Files\Azure Kinect SDK v1.4.2\tools\k4arecorder.exe'
COLOR_MODE    = '720p'            # 1080p + NFOV_UNBINNED saturates USB bandwidth
DEPTH_MODE    = 'NFOV_2X2BINNED' # 320×288 — half the data of NFOV_UNBINNED (640×576)
FRAMERATE     = '30'


class KinectAzureRecorder:
    """
    Thin wrapper around k4arecorder.exe.

    k4arecorder records for exactly `--record-length` seconds then exits,
    so no explicit stop call is needed in the normal flow.
    """

    def __init__(
        self,
        recorder_path: str = K4A_RECORDER,
        color_mode:    str = COLOR_MODE,
        depth_mode:    str = DEPTH_MODE,
        framerate:     str = FRAMERATE,
    ):
        if not os.path.isfile(recorder_path):
            raise FileNotFoundError(
                f'k4arecorder.exe not found at:\n  {recorder_path}\n'
                'Install the Azure Kinect SDK and update K4A_RECORDER in sensors/kinect_azure.py'
            )
        self.recorder_path = recorder_path
        self.color_mode    = color_mode
        self.depth_mode    = depth_mode
        self.framerate     = framerate
        self._proc         = None
        self._duration_s   = 0

    # ── Public interface ───────────────────────────────────────────────────────

    def start(self, output_path: str, duration_s: int) -> subprocess.Popen:
        """
        Arm k4arecorder and begin capture.  Returns immediately.

        Args:
            output_path: Full path for the output .mkv file.
            duration_s:  Recording length in whole seconds.
        Returns:
            The underlying Popen object (rarely needed by callers).
        """
        cmd = [
            self.recorder_path,
            '--color-mode',    self.color_mode,
            '--depth-mode',    self.depth_mode,
            '--rate',          self.framerate,
            '--record-length', str(duration_s),
            output_path,
        ]
        self._duration_s = duration_s
        # Ensure the output directory exists before k4arecorder tries to write
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f'[KinectAzure] Starting: {" ".join(cmd)}')
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return self._proc

    def wait(self, extra_s: int = 10) -> tuple[int, str]:
        """
        Block until recording finishes, with a hard timeout.

        Waits up to (duration_s + extra_s) seconds, then terminates the
        process if it hasn't exited on its own.

        Returns:
            (returncode, combined_stdout_stderr_as_str)
        """
        if self._proc is None:
            return 0, '(never started)'

        timeout = self._duration_s + extra_s
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f'[KinectAzure] Timeout after {timeout}s — terminating')
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

        log = self._proc.stdout.read().decode(errors='ignore').strip()
        rc  = self._proc.returncode or 0
        print(f'[KinectAzure] Done — returncode={rc}')
        if log:
            print(f'[KinectAzure] Output:\n{log}')
        return rc, log

    def stop(self):
        """Terminate recording early (e.g. user pressed Stop)."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            print('[KinectAzure] Recording terminated early')

    @property
    def is_running(self) -> bool:
        """True if the recorder process is still alive."""
        return self._proc is not None and self._proc.poll() is None
