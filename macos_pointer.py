# SPDX-License-Identifier: Apache-2.0
"""macOS pointer: moves the cursor with CoreGraphics events, same interface as the Linux uinput Pointer.

The process that posts the events needs the Accessibility permission (System Settings, Privacy & Security,
Accessibility). When MousePods runs from a terminal, macOS asks for it for the terminal app.

Pure part (CursorMath): sub-pixel accumulation, 0..1 to pixel mapping, keeping the cursor on a display.
Adapter (CoreGraphics): thin ctypes calls, no decisions.
"""
import ctypes
import ctypes.util
import logging
import time

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- pure core
def inside(point, rect):
    x, y = point
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def clamp_to_rect(point, rect):
    x, y = point
    rx, ry, rw, rh = rect
    return (min(max(x, rx), rx + rw - 1), min(max(y, ry), ry + rh - 1))


def keep_on_displays(target, current, displays):
    """Target if it lies on any display, else clamped to the display the cursor is on now.

    Displays are (x, y, width, height) in global points, as CGDisplayBounds gives them. Clamping to the
    current display (not the union) avoids parking the cursor in a gap between displays of different size.
    """
    if any(inside(target, d) for d in displays):
        return target
    home = next((d for d in displays if inside(current, d)), displays[0])
    return clamp_to_rect(target, home)


def nearest_on_displays(point, displays):
    """Point itself if it lies on a display, else the closest point on any display."""
    if any(inside(point, d) for d in displays):
        return point
    candidates = [clamp_to_rect(point, d) for d in displays]
    return min(candidates, key=lambda c: (c[0] - point[0]) ** 2 + (c[1] - point[1]) ** 2)


def bounding_box(displays):
    left = min(d[0] for d in displays)
    top = min(d[1] for d in displays)
    right = max(d[0] + d[2] for d in displays)
    bottom = max(d[1] + d[3] for d in displays)
    return (left, top, right - left, bottom - top)


class CursorMath:
    """Turns move_rel / move_abs calls into whole-pixel cursor positions, or None when nothing moves."""

    def __init__(self):
        self._fx = self._fy = 0.0
        self._last_abs = None

    def relative(self, current, dx, dy, displays):
        self._fx += dx
        self._fy += dy
        ix, iy = int(self._fx), int(self._fy)
        self._fx -= ix
        self._fy -= iy
        if not (ix or iy):
            return None
        self._last_abs = None
        return keep_on_displays((current[0] + ix, current[1] + iy), current, displays)

    def absolute(self, fx, fy, displays):
        """fx, fy in 0..1 across one canvas spanning all displays (as uinput does on Linux)."""
        x, y, w, h = bounding_box(displays)
        point = (x + round(min(max(fx, 0.0), 1.0) * (w - 1)), y + round(min(max(fy, 0.0), 1.0) * (h - 1)))
        point = nearest_on_displays(point, displays)
        if point == self._last_abs:
            return None
        self._last_abs = point
        return point


class ScrollMath:
    def __init__(self):
        self._wheel = 0.0

    def lines(self, amount):
        """Accumulates fractional lines; returns whole lines to send now (0 for none)."""
        self._wheel += amount
        n = int(self._wheel)
        self._wheel -= n
        return n


# --------------------------------------------------------------------------- CoreGraphics adapter
class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


MOUSE_MOVED = 5
BUTTON_EVENTS = {"left": (1, 2, 0), "right": (3, 4, 1), "middle": (25, 26, 2)}   # down, up, CGMouseButton
HID_EVENT_TAP = 0
SCROLL_UNIT_LINE = 1


class CoreGraphics:
    """ctypes bindings for the few CoreGraphics and Accessibility calls the pointer needs."""

    def __init__(self):
        cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
        ax = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        vp = ctypes.c_void_p
        cg.CGEventCreate.argtypes, cg.CGEventCreate.restype = [vp], vp
        cg.CGEventGetLocation.argtypes, cg.CGEventGetLocation.restype = [vp], CGPoint
        cg.CGEventCreateMouseEvent.argtypes = [vp, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
        cg.CGEventCreateMouseEvent.restype = vp
        # Not the variadic CGEventCreateScrollWheelEvent: ctypes cannot call variadics safely on arm64.
        cg.CGEventCreateScrollWheelEvent2.argtypes = [vp, ctypes.c_uint32, ctypes.c_uint32,
                                                      ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
        cg.CGEventCreateScrollWheelEvent2.restype = vp
        cg.CGEventPost.argtypes, cg.CGEventPost.restype = [ctypes.c_uint32, vp], None
        cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                              ctypes.POINTER(ctypes.c_uint32)]
        cg.CGGetActiveDisplayList.restype = ctypes.c_int32
        cg.CGDisplayBounds.argtypes, cg.CGDisplayBounds.restype = [ctypes.c_uint32], CGRect
        cg.CGMainDisplayID.argtypes, cg.CGMainDisplayID.restype = [], ctypes.c_uint32
        ax.AXIsProcessTrusted.argtypes, ax.AXIsProcessTrusted.restype = [], ctypes.c_bool
        cf.CFRelease.argtypes, cf.CFRelease.restype = [vp], None
        self.cg, self.ax, self.cf = cg, ax, cf

    def trusted(self):
        return bool(self.ax.AXIsProcessTrusted())

    def cursor(self):
        event = self.cg.CGEventCreate(None)
        p = self.cg.CGEventGetLocation(event)
        self.cf.CFRelease(event)
        return (round(p.x), round(p.y))

    @staticmethod
    def _rect(r):
        return (round(r.origin.x), round(r.origin.y), round(r.size.width), round(r.size.height))

    def displays(self):
        ids = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32(0)
        if self.cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0 or count.value == 0:
            return [self.main_display()]
        return [self._rect(self.cg.CGDisplayBounds(ids[i])) for i in range(count.value)]

    def main_display(self):
        return self._rect(self.cg.CGDisplayBounds(self.cg.CGMainDisplayID()))

    def _post(self, event):
        self.cg.CGEventPost(HID_EVENT_TAP, event)
        self.cf.CFRelease(event)

    def move(self, point):
        self._post(self.cg.CGEventCreateMouseEvent(None, MOUSE_MOVED, CGPoint(*point), 0))

    def button(self, button, down, point):
        down_type, up_type, number = BUTTON_EVENTS[button]
        self._post(self.cg.CGEventCreateMouseEvent(None, down_type if down else up_type, CGPoint(*point), number))

    def scroll(self, lines):
        self._post(self.cg.CGEventCreateScrollWheelEvent2(None, SCROLL_UNIT_LINE, 1, lines, 0, 0))


ACCESSIBILITY_HINT = ("Accessibility permission missing: the cursor will not move. Allow your terminal app "
                      "(for example iTerm) in System Settings, Privacy & Security, Accessibility, then restart.")


class MacPointer:
    """Drop-in for Pointer (move_rel, move_abs, click, scroll, close) on macOS."""

    DISPLAY_REFRESH_S = 1.0     # pick up a monitor plugged in or out

    def __init__(self, backend=None, sleep=time.sleep, clock=time.monotonic):
        self.cg = backend or CoreGraphics()
        self._sleep = sleep
        self._clock = clock
        self._math = CursorMath()
        self._scroll = ScrollMath()
        self._displays = self.cg.displays()
        self._displays_at = clock()
        if not self.cg.trusted():
            log.warning("%s", ACCESSIBILITY_HINT)

    def displays(self):
        now = self._clock()
        if now - self._displays_at >= self.DISPLAY_REFRESH_S:
            self._displays = self.cg.displays()
            self._displays_at = now
        return self._displays

    def move_rel(self, dx, dy):
        point = self._math.relative(self.cg.cursor(), dx, dy, self.displays())
        if point is not None:
            self.cg.move(point)

    def move_abs(self, fx, fy):
        point = self._math.absolute(fx, fy, self.displays())
        if point is not None:
            self.cg.move(point)

    def click(self, button="left"):
        point = self.cg.cursor()
        self.cg.button(button, True, point)
        self._sleep(0.015)
        self.cg.button(button, False, point)

    def scroll(self, lines):
        n = self._scroll.lines(lines)
        if n:
            self.cg.scroll(n)

    def close(self):
        pass
