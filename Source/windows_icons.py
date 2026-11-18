"""Keep native Windows window icons at their intended resolution."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class WindowsWindowIcons:
    """Own correctly sized HICONs for the lifetime of a Tk window.

    Tk's ICO loader can enlarge the first (16px) image for both window icons.
    LoadImage selects the actual size from the ICO instead. Retain the handles
    and reapply them when Tk remaps its native wrapper for full-screen mode.
    """

    def __init__(self, window, icon_path):
        self.window = window
        self.path = str(icon_path)
        self.handles = {}
        self.pending = None
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                       wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.api.LoadImageW.restype = wintypes.HANDLE
        self.api.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM]
        self.api.SendMessageW.restype = wintypes.LPARAM
        self.api.DestroyIcon.argtypes = [wintypes.HANDLE]
        window.bind('<Map>', self._mapped, add='+')
        window.bind('<Destroy>', self._destroyed, add='+')
        self._schedule()

    def apply(self):
        self.pending = None
        hwnd = self.api.GetAncestor(self.window.winfo_id(), 2)  # GA_ROOT
        if not hwnd:
            return
        for kind, metric in ((0, 49), (1, 11)):  # ICON_SMALL / ICON_BIG
            width = self.api.GetSystemMetrics(metric)
            height = self.api.GetSystemMetrics(metric + 1)
            size = (width, height)
            if size not in self.handles:
                handle = self.api.LoadImageW(None, self.path, 1, width, height, 0x10)
                if not handle:
                    continue  # Keep Tk's fallback when the native load fails.
                self.handles[size] = handle
            self.api.SendMessageW(hwnd, 0x0080, kind, self.handles[size])  # WM_SETICON

    def _mapped(self, event):
        if event.widget is self.window:
            self._schedule()

    def _schedule(self):
        if self.pending is None:
            self.pending = self.window.after_idle(self.apply)

    def _destroyed(self, event):
        if event.widget is self.window:
            if self.pending is not None:
                self.window.after_cancel(self.pending)
                self.pending = None
            for handle in self.handles.values():
                self.api.DestroyIcon(handle)
            self.handles.clear()
