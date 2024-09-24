import functools
import os

import gdb
import pygments
import pygments.lexers
import pygments.formatters

import libpython
import libpython_extensions
import tui_windows


def highlight_python(content: bytes) -> bytes:
    """
    Applies Python syntax highlighting and prepends line numbers to provided content.
    """
    return pygments.highlight(
        content, pygments.lexers.PythonLexer(), pygments.formatters.TerminalFormatter(linenos=True)
    )


@functools.cache
def get_highlighted_file_content(filename: str) -> str:
    """
    Returns the content of the Python source file with syntax highlighting.
    """
    with libpython_extensions.PythonSubstitutePath.open(os.fsencode(filename), "r") as f:
        content = f.read()
    return highlight_python(content)


def get_filename_and_line() -> tuple[str, int]:
    """
    Returns the path to the current Python source file and the current line number.
    """
    # py-list requires an actual PyEval_EvalFrameEx frame:
    frame = libpython.Frame.get_selected_bytecode_frame()
    if not frame:
        raise gdb.error("Unable to locate gdb frame for python bytecode interpreter")

    pyop = frame.get_pyop()
    if not pyop or pyop.is_optimized_out():
        raise gdb.error(libpython.UNABLE_READ_INFO_PYTHON_FRAME)

    filename = pyop.filename()
    lineno = pyop.current_line_num()
    if lineno is None:
        raise gdb.error("Unable to read python frame line number")
    return filename, lineno


@tui_windows.register_window("python-source")
class PythonSourceWindow(tui_windows.ScrollableWindow):
    title = "Python Source"

    def get_content(self):
        filename, line = get_filename_and_line()
        lines = get_highlighted_file_content(filename).splitlines()
        prefixed_lines = [(" > " if i == line else "   ") + l for i, l in enumerate(lines, start=1)]

        # Set vertical scroll offset to center the current line
        half_window_height = self._tui_window.height // 2
        self.vscroll_offset = line - half_window_height

        return "\n".join(prefixed_lines)


@tui_windows.register_window("python-backtrace")
class PythonBacktraceWindow(tui_windows.ScrollableWindow):
    title = "Python Backtrace"

    def get_content(self):
        return gdb.execute("py-bt", to_string=True)


@tui_windows.register_window("python-locals")
class PythonLocalsWindow(tui_windows.ScrollableWindow):
    title = "Local Python Variables"

    def get_content(self):
        return gdb.execute("py-locals", to_string=True)


@tui_windows.register_window("python-bytecode")
class PythonBytecodeWindow(tui_windows.ScrollableWindow):
    title = "Python Bytecode"

    def get_lines(self) -> list[str]:
        lines = gdb.execute("py-dis", to_string=True).splitlines()

        # Set vertical scroll offset to center the current line
        for index, line in enumerate(lines, start=1):
            if "-->" in line:
                half_window_height = self._tui_window.height // 2
                self.vscroll_offset = index - half_window_height

        return lines


# Define a layout with all Python windows
gdb.execute(
    " ".join(
        (
            "tui new-layout python",
            "{-horizontal {python-source 2 status 1 cmd 1} 3",
            "{python-locals 1 python-backtrace 1 python-bytecode 1 timeline 1} 2} 1",
        )
    )
)
