"""Hold Windows awake for the length of a scheduled run.

Task Scheduler's "wake the computer to run this task" only wakes the machine
long enough to start the process. On a Modern Standby laptop the system drops
straight back into standby and cuts the network by policy seconds later: the
2026-09-07 00:00 run woke at 00:36:51, was back in standby the same second,
started at 00:36:58, lost its network to "Connectivity state in standby:
Disconnected, Reason: Policy Setting" at 00:37:05, and died after one portal.
Windows reports that as STATUS_CONTROL_C_EXIT (0xC000013A) in a Task Scheduler
column, so the run simply stops happening and nothing says why.

SetThreadExecutionState alone is not enough there -- on a connected-standby
system ES_SYSTEM_REQUIRED does not keep a process running.
PowerRequestExecutionRequired is the request type documented for that case, so
take it first and keep SetThreadExecutionState as the fallback for machines
that predate it.

Every script refresh-tenders.bat runs holds its own request, not just the
scraper: the scrape is the long pole, but the build and the upload after it
would run unprotected once the scraper's request is dropped at exit.

    from keepawake import keep_awake
    keep_awake()          # released automatically when the process exits
"""
from __future__ import annotations

import atexit
import ctypes
import sys

POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1
PowerRequestSystemRequired = 1
PowerRequestExecutionRequired = 3

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

_request = None          # handle held for the run; closed by release_awake()


def _create_request(reason):
    """Take a PowerRequestExecutionRequired handle, or None if unavailable."""
    from ctypes import wintypes

    class _Detailed(ctypes.Structure):
        _fields_ = [("LocalizedReasonModule", wintypes.HMODULE),
                    ("LocalizedReasonId", wintypes.ULONG),
                    ("ReasonStringCount", wintypes.ULONG),
                    ("ReasonStrings", ctypes.POINTER(wintypes.LPWSTR))]

    class _Reason(ctypes.Union):
        _fields_ = [("Detailed", _Detailed),
                    ("SimpleReasonString", wintypes.LPWSTR)]

    class _ReasonContext(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG),
                    ("Flags", wintypes.DWORD),
                    ("Reason", _Reason)]

    k32 = ctypes.windll.kernel32
    k32.PowerCreateRequest.argtypes = [ctypes.POINTER(_ReasonContext)]
    k32.PowerCreateRequest.restype = wintypes.HANDLE
    k32.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
    k32.PowerSetRequest.restype = wintypes.BOOL

    ctx = _ReasonContext(Version=0,
                         Flags=POWER_REQUEST_CONTEXT_SIMPLE_STRING)
    ctx.Reason.SimpleReasonString = reason
    handle = k32.PowerCreateRequest(ctypes.byref(ctx))
    if not handle or handle == ctypes.c_void_p(-1).value:
        return None
    if not k32.PowerSetRequest(handle, PowerRequestExecutionRequired):
        k32.CloseHandle(handle)
        return None
    k32.PowerSetRequest(handle, PowerRequestSystemRequired)   # older machines
    return handle


def keep_awake(reason="india-tenders scheduled run", log=None):
    """Keep the machine out of standby until this process exits.

    Registers its own release, so callers need nothing at the other end.
    Best effort: on anything but Windows, or if the calls fail, carry on --
    but say so, because a silent failure here is a run that dies at midnight
    with only a hex code to show for it.
    """
    global _request
    if not sys.platform.startswith("win"):
        return False
    if _request is not None:
        return True
    try:
        _request = _create_request(reason)
    except Exception:                                      # noqa: BLE001
        _request = None
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:                                      # noqa: BLE001
        pass
    atexit.register(release_awake)
    if _request is None:
        msg = ("warning: no power request held -- a Modern Standby laptop can "
               "still sleep mid-run")
        (log or (lambda m: print(m, file=sys.stderr)))(msg)
        return False
    return True


def release_awake():
    """Let the machine sleep normally again. Safe to call more than once."""
    global _request
    if not sys.platform.startswith("win"):
        return
    try:
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        if _request:
            k32.PowerClearRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.PowerClearRequest(_request, PowerRequestExecutionRequired)
            k32.PowerClearRequest(_request, PowerRequestSystemRequired)
            k32.CloseHandle(_request)
            _request = None
        k32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:                                      # noqa: BLE001
        pass
