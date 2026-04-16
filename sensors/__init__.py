"""
sensors/
Modular sensor recording backends.

Each module exposes a single class with a consistent interface:
    .start(output_path, duration_s)  -> starts recording (non-blocking)
    .wait()                          -> blocks until done, returns (returncode, log_str)
    .stop()                          -> terminate early if still running
"""
