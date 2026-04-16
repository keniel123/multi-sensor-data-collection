"""
main.py  —  Data Collection GUI
Sensors wired: Azure Kinect (live), TI Radar (live), Infineon (stub)
"""

import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import openpyxl
import PySimpleGUI as sg

from sensors.kinect_azure import KinectAzureRecorder
from sensors.ti_radar      import TIRadarRecorder
from sensors.infineon_radar import InfineonRadarRecorder

# ── Paths ──────────────────────────────────────────────────────────────────────
_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ACTIVITIES_XL = os.path.join(_SCRIPT_DIR, 'activities.xlsx')
VIDEOS_DIR    = os.path.join(_SCRIPT_DIR, 'videos')
DATA_DIR      = os.path.join(_SCRIPT_DIR, 'data')

# Outputs must be on a local Windows drive — UNC/WSL paths (\\wsl.localhost\...)
# are too slow for Azure Kinect's continuous depth+colour stream and cause
# capturesync queue overflows.  Fall back to the script dir on non-Windows.
import platform as _platform
if _platform.system() == 'Windows':
    OUTPUTS_DIR = os.path.join(os.path.expanduser('~'), 'radar_data', 'outputs')
else:
    OUTPUTS_DIR = os.path.join(_SCRIPT_DIR, 'outputs')

PREVIEW_W, PREVIEW_H = 640, 360

# ── Button colour palette ──────────────────────────────────────────────────────
BTN_GREEN = ('white', '#2e7d32')
BTN_RED   = ('white', '#c62828')
BTN_DARK  = ('white', '#263238')
BTN_BLUE  = ('white', '#1565c0')

# ── Fonts ──────────────────────────────────────────────────────────────────────
FONT_TITLE = ('Helvetica', 18, 'bold')
FONT_LABEL = ('Helvetica', 11)
FONT_BTN   = ('Helvetica', 11, 'bold')
FONT_MONO  = ('Courier', 11)
FONT_TIME  = ('Helvetica', 28, 'bold')

# ── Load Excel data ────────────────────────────────────────────────────────────
def _load_sheet(path: str, sheet: str) -> list[str]:
    wb = openpyxl.load_workbook(path)
    ws = wb[sheet]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None and row[1] is not None:
            rows.append(f'{row[0]}  {row[1]}')
    return rows

activities  = _load_sheet(ACTIVITIES_XL, 'Activities')
experiments = _load_sheet(ACTIVITIES_XL, 'Experiments')

# ── Video preview helpers ──────────────────────────────────────────────────────
def _activity_name(entry: str) -> str:
    parts = entry.strip().split(None, 1)
    return parts[1] if len(parts) == 2 else entry.strip()

def _first_frame(video_path: str) -> bytes | None:
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    frame = cv2.resize(frame, (PREVIEW_W, PREVIEW_H))
    _, buf = cv2.imencode('.png', frame)
    return buf.tobytes()

def _blank_frame() -> bytes:
    img = np.full((PREVIEW_H, PREVIEW_W, 3), 30, dtype=np.uint8)
    cv2.putText(img, 'No demonstration video',
                (PREVIEW_W // 2 - 160, PREVIEW_H // 2 - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1, cv2.LINE_AA)
    cv2.putText(img, 'Place <Activity_Name>.mp4 in videos/',
                (PREVIEW_W // 2 - 205, PREVIEW_H // 2 + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (70, 70, 70), 1, cv2.LINE_AA)
    _, buf = cv2.imencode('.png', img)
    return buf.tobytes()

def load_preview(activity_entry: str) -> bytes:
    name  = _activity_name(activity_entry)
    vpath = os.path.join(VIDEOS_DIR, name + '.mp4')
    frame = _first_frame(vpath) if os.path.isfile(vpath) else None
    return frame if frame else _blank_frame()

# ── Layout ─────────────────────────────────────────────────────────────────────
sg.theme('DarkGrey13')

sensors_frame = sg.Frame('Sensors', [
    [sg.Checkbox('TI Radar (77 GHz)',         default=True,  key='77_front_check',     font=FONT_LABEL, pad=(6, 5))],
    [sg.Checkbox('Azure Kinect',              default=False, key='azure_kinect_check', font=FONT_LABEL, pad=(6, 5))],
    [sg.Checkbox('Infineon Radar  (60 GHz)',  default=False, key='infineon_check',     font=FONT_LABEL, pad=(6, 5))],
], font=FONT_LABEL, pad=(8, 8))

session_frame = sg.Frame('Session', [
    [
        sg.Text('Subject',    size=(9, 1), font=FONT_LABEL),
        sg.InputText('', key='subject', size=(14, 1), font=FONT_MONO),
    ],
    [
        sg.Text('Experiment', size=(9, 1), font=FONT_LABEL),
        sg.Combo(experiments, default_value=experiments[0] if experiments else '',
                 key='exp_list', size=(20, 1), font=FONT_MONO, readonly=True),
        sg.Text('  Duration (s)', font=FONT_LABEL),
        sg.InputText('', key='duration', size=(8, 1), font=FONT_MONO),
    ],
], font=FONT_LABEL, pad=(8, 8), expand_x=True)

activity_frame = sg.Frame('Activity', [
    [sg.Combo(activities,
              default_value=activities[0] if activities else '',
              key='class_list', size=(60, 1), font=FONT_MONO,
              enable_events=True, readonly=True)],
], font=FONT_LABEL, pad=(8, 4), expand_x=True)

_initial_preview = load_preview(activities[0]) if activities else _blank_frame()

demo_frame = sg.Frame('Demonstration', [
    [sg.Image(data=_initial_preview, key='-VIDEO-', size=(PREVIEW_W, PREVIEW_H))],
    [
        sg.Button('◀  Prev', key='prev_activity', font=FONT_BTN, size=(10, 1), button_color=BTN_DARK),
        sg.Button('▶  Play', key='play_video',    font=FONT_BTN, size=(10, 1), button_color=BTN_BLUE),
        sg.Button('Next  ▶', key='next_activity', font=FONT_BTN, size=(10, 1), button_color=BTN_DARK),
    ],
], font=FONT_LABEL, pad=(8, 8))

status_frame = sg.Frame('Status', [
    [sg.Text('●  Ready', key='status_text', font=FONT_LABEL, size=(50, 2),
             text_color='#4caf50')],
    [
        sg.Text('', key='rec_indicator', font=('Helvetica', 11, 'bold'),
                size=(14, 1), text_color='#ef5350'),
        sg.Text('', key='time', font=FONT_TIME, size=(8, 1),
                justification='right', text_color='#90caf9'),
    ],
    [sg.Multiline('', key='files_text', font=('Courier', 9),
                  size=(60, 7), expand_x=True,
                  disabled=True, background_color='#1a1a1a', text_color='#b0bec5')],
], font=FONT_LABEL, pad=(8, 8), expand_x=True, expand_y=True)

layout = [
    [sg.Text('Data Collection GUI', font=FONT_TITLE, pad=(12, 10))],
    [sensors_frame, session_frame],
    [activity_frame],
    [demo_frame, status_frame],
    [sg.HorizontalSeparator(pad=(0, 6))],
    [
        sg.Button('Setup Radar',          key='Setup Radar',         font=FONT_BTN, size=(16, 2), button_color=BTN_DARK),
        sg.Button('▶  Start Recording',   key='1. Start Recording',  font=FONT_BTN, size=(20, 2), button_color=BTN_GREEN),
        sg.Button('■  Stop Recording',    key='2. Stop Recording',   font=FONT_BTN, size=(18, 2), button_color=BTN_RED,
                  disabled=True),
        sg.Push(),
        sg.Exit(font=FONT_BTN, size=(10, 2), button_color=BTN_DARK),
    ],
]

window = sg.Window('Data Collection GUI', layout, size=(1400, 820),
                   finalize=True, resizable=True)

# ── Sensor instances (created once, reused per recording) ─────────────────────
try:
    kinect = KinectAzureRecorder()
    _kinect_available = True
except FileNotFoundError as e:
    _kinect_available = False
    print(f'[Warning] {e}')

ti_radar  = TIRadarRecorder()
inf_radar = InfineonRadarRecorder()

# ── State ──────────────────────────────────────────────────────────────────────
_recording = False          # guard against double-start

# ── Helpers ────────────────────────────────────────────────────────────────────
def set_status(msg: str, color: str = '#4caf50'):
    window['status_text'].update(msg, text_color=color)
    window.refresh()

def _set_buttons(recording: bool):
    """Grey out / restore buttons based on recording state."""
    window['1. Start Recording'].update(disabled=recording)
    window['Setup Radar'].update(disabled=recording)
    window['2. Stop Recording'].update(disabled=not recording)
    window.refresh()

def _set_timer(text: str, color: str = '#90caf9'):
    window['time'].update(text, text_color=color)

def _set_rec_indicator(text: str, color: str = '#ef5350'):
    window['rec_indicator'].update(text, text_color=color)

def current_index(values) -> int:
    try:
        return activities.index(values['class_list'])
    except ValueError:
        return 0

def set_activity(idx: int):
    idx = max(0, min(idx, len(activities) - 1))
    window['class_list'].update(value=activities[idx])
    window['-VIDEO-'].update(data=load_preview(activities[idx]))

def _exp_name(values) -> str:
    """Full experiment name, e.g. 'Exp_Baseline'."""
    return _activity_name(values['exp_list']) if values['exp_list'] else 'Exp_Unknown'

def _build_session_paths(values) -> tuple[str, str]:
    """
    Return (save_dir, file_prefix) for the current session.

    Directory layout:
        outputs/<experiment>/<subject>/<activity>/

    File prefix: YYYY_MM_DD_HH_MM_SS  (folder already carries the labels)

    Example:
        save_dir   = .../outputs/Exp_Baseline/subj3/Activity_Hello/
        file_prefix = 2026_04_16_14_30_00
    """
    exp      = _exp_name(values)
    subj     = f'subj{values["subject"].strip()}'
    activity = _activity_name(values['class_list']) if values['class_list'] else 'Activity_Unknown'
    ts       = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')

    save_dir = os.path.join(OUTPUTS_DIR, exp, subj, activity)
    os.makedirs(save_dir, exist_ok=True)
    return save_dir, ts

def _append_files(save_dir: str):
    """List all files in save_dir in the status panel."""
    import glob
    lines = []
    for i, f in enumerate(sorted(glob.glob(os.path.join(save_dir, '*'))), 1):
        if os.path.isfile(f):
            size = os.path.getsize(f)
            unit = 'MB' if size >= 1_000_000 else 'KB'
            val  = round(size / (1e6 if unit == 'MB' else 1e3), 1)
            lines.append(f'{i}. {os.path.basename(f)}  →  {val} {unit}')
    window['files_text'].update('\n'.join(lines) if lines else '(no files found)')

# ── Recording worker ────────────────────────────────────────────────────────────
def _run_recording(values, save_dir: str, ts: str, duration_s: int):
    """Runs in a background thread. Starts sensors, runs countdown, waits."""
    global _recording

    base = os.path.join(save_dir, ts)

    # ── Start sensors ──────────────────────────────────────────────────────────
    if values['azure_kinect_check']:
        if _kinect_available:
            kinect.start(base + '_kinect.mkv', duration_s)
        else:
            window.write_event_value('-STATUS-', ('⚠  k4arecorder.exe not found', '#ef5350'))

    if values['77_front_check']:
        ti_radar.start(base + '.bin', duration_s)

    if values['infineon_check']:
        inf_radar.start(base + '_inf.bin', duration_s)

    # ── Countdown on the GUI (via events) ─────────────────────────────────────
    for t in range(duration_s, 0, -1):
        window.write_event_value('-TIMER-', t)
        time.sleep(1)

    # ── Wait for sensors to finish ─────────────────────────────────────────────
    errors = []

    if values['azure_kinect_check'] and _kinect_available:
        rc, log = kinect.wait()
        if rc != 0:
            errors.append(f'Kinect (rc={rc})')

    if values['77_front_check']:
        rc, resp = ti_radar.wait()
        if rc != 0:
            errors.append(f'TI Radar: {resp}')

    if values['infineon_check']:
        inf_radar.wait()

    # ── Report saved files ─────────────────────────────────────────────────────
    window.write_event_value('-FILES-', save_dir)
    if errors:
        window.write_event_value('-STATUS-', (f'⚠  Errors: {", ".join(errors)}', '#ef5350'))
    else:
        window.write_event_value('-STATUS-', ('●  Recording saved', '#4caf50'))
    window.write_event_value('-RECORD-DONE-', None)
    _recording = False

# ── Event loop ─────────────────────────────────────────────────────────────────
while True:
    event, values = window.read()

    if event in (None, 'Exit'):
        if _recording:
            kinect.stop()
            ti_radar.stop()
            inf_radar.stop()
        break

    # ── Preview navigation ─────────────────────────────────────────────────────
    if event == 'class_list':
        window['-VIDEO-'].update(data=load_preview(values['class_list']))

    elif event == 'prev_activity':
        set_activity(current_index(values) - 1)

    elif event == 'next_activity':
        set_activity(current_index(values) + 1)

    elif event == 'play_video':
        name = _activity_name(values['class_list'])
        set_status(f'▶  Play: {name}  (video playback coming soon)', '#ffb74d')

    # ── Background thread → GUI events ────────────────────────────────────────
    elif event == '-TIMER-':
        t = values['-TIMER-']           # int seconds remaining
        mins, secs = divmod(t, 60)
        _set_timer(f'{mins}:{secs:02d}')

    elif event == '-RECORD-DONE-':
        _set_buttons(recording=False)
        _set_rec_indicator('')
        _set_timer('')

    elif event == '-STATUS-':
        msg, color = values['-STATUS-']
        set_status(msg, color)

    elif event == '-FILES-':
        _append_files(values['-FILES-'])

    # ── Setup Radar ────────────────────────────────────────────────────────────
    elif event == 'Setup Radar':
        set_status('⟳  Connecting to radar Lua server...', '#ffb74d')
        resp = ti_radar._send('setup', timeout=15)
        if resp == 'setup_ok':
            set_status('●  Radar ready', '#4caf50')
        else:
            set_status(f'⚠  {resp}', '#ef5350')

    # ── Start Recording ────────────────────────────────────────────────────────
    elif event == '1. Start Recording':
        if _recording:
            set_status('⚠  Recording already in progress', '#ffb74d')
            continue

        if not values['subject'].strip():
            set_status('⚠  Enter a subject name / number', '#ef5350')
            continue
        if not values['duration'].strip().isdigit():
            set_status('⚠  Enter a valid duration (whole seconds)', '#ef5350')
            continue

        duration_s   = int(values['duration'])
        save_dir, ts = _build_session_paths(values)

        # 3-2-1 countdown in the status bar before locking buttons
        _set_timer('')
        _set_rec_indicator('')
        for count in [3, 2, 1]:
            set_status(f'Starting in  {count}...', '#ffb74d')
            time.sleep(1)
        set_status('', '#4caf50')

        _recording = True
        _set_buttons(recording=True)
        _set_rec_indicator('⬤  Recording')
        mins, secs = divmod(duration_s, 60)
        _set_timer(f'{mins}:{secs:02d}')
        window.refresh()

        threading.Thread(
            target=_run_recording,
            args=(values, save_dir, ts, duration_s),
            daemon=True,
        ).start()

    # ── Stop Recording ─────────────────────────────────────────────────────────
    elif event == '2. Stop Recording':
        if _recording:
            kinect.stop()
            ti_radar.stop()
            inf_radar.stop()
            _recording = False
            _set_buttons(recording=False)
            _set_rec_indicator('')
            _set_timer('')
            set_status('■  Stopped by user', '#ffb74d')

window.close()
