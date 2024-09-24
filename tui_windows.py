import re
from typing import Callable

import gdb


# A pattern to match an ANSI escape sequence
ANSI_PATTERN = re.compile(r"(\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))")


def truncate_ansi_string(string: str, start: int, length: int) -> str:
    """
    Truncate a string to a specified range of characters.

    Characters that are part of ANSI escape sequencs do not count towards the length of the string.
    ANSI escape sequences are retained within the returned string, even if they are outside of the
    specified range.

    >>> truncate_ansi_string("abcdef", -1, -1)
    Traceback (most recent call last):
    ...
    ValueError: start and length must be non-negative
    >>> truncate_ansi_string("abcdef", 0, 0)
    ''
    >>> truncate_ansi_string("abcdef", 2, 3)
    'cde'
    >>> print(truncate_ansi_string("\x1b[31mhello\x1b[0m", 0, 3))
    \x1b[31mhel\x1b[0m
    >>> print(truncate_ansi_string(" \x1b[1mabc\x1b[0mdef\x1b[35;1mghi\x1b[0m", 2, 3))
    \x1b[1mbc\x1b[0md\x1b[35;1m\x1b[0m
    >>> print(truncate_ansi_string(" \x1b[1mabc\x1b[0mdef\x1b[35;1mghi\x1b[0m", 5, 2))
    \x1b[1m\x1b[0mef\x1b[35;1m\x1b[0m
    """
    if start < 0 or length < 0:
        raise ValueError("start and length must be non-negative")
    output = []
    position = 0
    end = start + length
    for component in re.split(ANSI_PATTERN, string):
        if re.match(ANSI_PATTERN, component):
            # ANSI sequences don't count towards the length, but should still be emitted.
            output.append(component)
        else:
            # This is some normal text.
            remaining_to_start = max(0, start - position)
            if len(component) <= remaining_to_start:
                # Skip this component, it's completely before the start of the output
                position += len(component)
                continue
            elif remaining_to_start and len(component) > remaining_to_start:
                # Skip the part of the component which is before the start of the output range, then
                # carry on to process the remainder of the component as usual.
                component = component[remaining_to_start:]
                position += remaining_to_start
            remaining_to_end = max(0, end - position)
            if remaining_to_end <= 0:
                # No more space left. Keep going to consume any remaining ANSI sequences.
                pass
            if len(component) <= remaining_to_end:
                output.append(component)
            else:
                # The component is too long to fit in the output, split it up
                output.append(component[:remaining_to_end])
            position += len(component)
    return "".join(output)


def register_window(name: str) -> Callable:
    """
    Create a decorator to register a TUI window class and define a new layout for it.
    """

    def decorator(cls):
        gdb.register_window_type(name, cls)
        gdb.execute(f"tui new-layout {name} {name} 1 status 1 cmd 1")
        return cls

    return decorator


class ScrollableWindow:
    """
    Base class for displaying simple content in a scrollable TUI window.

    Subclasses must:
    - Override the `get_content` method.
    - Define a `title` attribute.
    """

    title: str | None = None

    def __init__(self, tui_window) -> None:
        self._tui_window = tui_window
        self._tui_window.title = self.title

        # When scrolling we use cached lines to avoid regenerating the content.
        self.use_cached_lines = False
        self.cached_lines = None
        self.vscroll_offset = 0
        self.hscroll_offset = 0

        gdb.events.before_prompt.connect(self.render)

    def close(self) -> None:
        gdb.events.before_prompt.disconnect(self.render)

    def get_content(self) -> str:
        """
        Return the content to be displayed in this window.

        Either this method or the get_lines method must be implemented by subclasses.
        """
        raise NotImplementedError()

    def get_lines(self) -> list[str]:
        """
        Return the content to be displayed in this window as a list of lines.

        Either this method or the get_lines method must be implemented by subclasses.
        """
        return self.get_content().splitlines()

    def get_lines_or_error(self) -> list[str]:
        """
        Return the content to be displayed in this window as a list of lines, or exception
        message if a gdb.error occurs.
        """
        try:
            return self.get_lines()
        except gdb.error as exc:
            return [str(exc)]

    def get_viewport_content(self) -> str:
        """
        Return the content that should be displayed in the window, taking into account the
        current window size and scroll offsets.
        """
        if self.use_cached_lines and self.cached_lines is not None:
            lines, content_height, content_width = self.cached_lines
            self.use_cached_lines = False
        else:
            lines = self.get_lines_or_error()
            if lines:
                content_height = len(lines)
                content_width = max(len(ANSI_PATTERN.sub("", l)) for l in lines)
                self.cached_lines = (lines, content_height, content_width)

        if not lines:
            return ""

        # Limit scroll to the content height
        window_height = self._tui_window.height
        self.vscroll_offset = min(content_height - window_height, self.vscroll_offset)
        self.vscroll_offset = max(0, self.vscroll_offset)

        # Truncate content vertically
        free_height = window_height - content_height
        if free_height < 0:
            # We have to truncate the height, after adjusting for scroll.
            scrolled_free_height = window_height - (content_height - self.vscroll_offset)
            if scrolled_free_height >= 0:
                lines = lines[self.vscroll_offset :]
            else:
                lines = lines[self.vscroll_offset : self.vscroll_offset + window_height]

        # Limit scroll to the content width
        window_width = self._tui_window.width - 1
        self.hscroll_offset = min(content_width - window_width, self.hscroll_offset)
        self.hscroll_offset = max(0, self.hscroll_offset)

        # Truncate content horizontally
        truncated_lines = [
            truncate_ansi_string(l, self.hscroll_offset, window_width) for l in lines
        ]

        return "\n".join(truncated_lines)

    def render(self) -> None:
        if not self._tui_window.is_valid():
            return
        output = self.get_viewport_content()
        self._tui_window.write(output, True)

    def vscroll(self, num: int) -> None:
        self.vscroll_offset += num
        self.use_cached_lines = True
        self.render()

    def hscroll(self, num: int) -> None:
        self.hscroll_offset += num
        self.use_cached_lines = True
        self.render()


@register_window("locals")
class LocalsWindow(ScrollableWindow):
    title = "Local Variables"

    def get_content(self) -> str:
        return gdb.execute("info locals", to_string=True, styled=True)


@register_window("backtrace")
class BacktraceWindow(ScrollableWindow):
    title = "Backtrace"

    def get_content(self) -> str:
        return gdb.execute("backtrace", to_string=True, styled=True)


@register_window("threads")
class ThreadsWindow(ScrollableWindow):
    title = "Threads"

    def get_content(self) -> str:
        return gdb.execute("info threads", to_string=True, styled=True)


@register_window("breakpoints")
class BreakpointsWindow(ScrollableWindow):
    title = "Breakpoints"

    def get_content(self) -> str:
        return gdb.execute("info breakpoints", to_string=True, styled=True)


@register_window("timeline")
class TimelineWindow(ScrollableWindow):
    title = "Timeline"

    def get_content(self) -> str:
        return gdb.execute("info timeline", to_string=True, styled=True)


gdb.execute(
    " ".join(
        (
            "tui new-layout many-windows",
            "{-horizontal {src 2 status 1 cmd 1} 3",
            "{locals 1 backtrace 1 threads 1 timeline 1} 2} 1",
        )
    )
)

gdb.execute(
    " ".join(
        (
            "tui new-layout many-windows-split",
            "{-horizontal {src 2 asm 2 status 1 cmd 1} 3",
            "{locals 1 backtrace 1 threads 1 timeline 1} 2} 1",
        )
    )
)
