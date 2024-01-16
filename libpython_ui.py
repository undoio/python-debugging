import subprocess

import gdb


def highlight_python(text):
    """
    Pipe bytes through the highlight program to add Python syntax highlighting.
    """
    if getattr(highlight_python, "failed", False):
        return text
    result = subprocess.run(
        ["highlight", "--syntax=python", "--out-format=ansi"],
        stdout=subprocess.PIPE,
        input=text,
        check=False,
    )
    if result.returncode:
        print("Failed to provide syntax highlighting for Python.")
        print("Please install the `highlight` program.")
        highlight_python.failed = True
        return text
    return result.stdout


def register_window(name):
    """
    Register a TUI window and define a new layout for it.
    """

    def decorator(cls):
        gdb.register_window_type(name, cls)
        gdb.execute(f"tui new-layout {name} {name} 1 status 1 cmd 1")
        return cls

    return decorator


class Window:
    title: str | None = None

    def __init__(self, tui_window):
        self._tui_window = tui_window
        self._tui_window.title = self.title
        gdb.events.before_prompt.connect(self.render)

    def get_lines(self):
        raise NotImplementedError()

    def render(self):
        if not self._tui_window.is_valid():
            return

        # Truncate output
        lines = self.get_lines()[:self._tui_window.height]
        lines = (line[:self._tui_window.width - 1] for line in lines)

        output = "\n".join(lines)
        self._tui_window.write(output, True)

    def close(self):
        gdb.events.before_prompt.disconnect(self.render)


@register_window("python-source")
class PythonSourceWindow(Window):
    title = "Python Source"

    def get_lines(self):
        python_source = gdb.execute("py-list", to_string=True).encode("utf-8")
        return highlight_python(python_source).decode("utf-8").splitlines()


@register_window("python-backtrace")
class PythonBacktraceWindow(Window):
    title = "Python Backtrace"

    def get_lines(self):
        return gdb.execute("py-bt", to_string=True).splitlines()


@register_window("python-locals")
class PythonLocalsWindow(Window):
    title = "Local Python Variables"

    def get_lines(self):
        return gdb.execute("py-locals", to_string=True).splitlines()


@register_window("python-bytecode")
class PythonBytecodeWindow(Window):
    title = "Python Bytecode"

    def get_lines(self):
        lines = gdb.execute("py-dis", to_string=True).splitlines()
        total_lines = len(lines)
        height = self._tui_window.height
        if total_lines < height:
            return lines

        current_line = None
        for index, line in enumerate(lines, 1):
            if "-->" in line:
                current_line = index
                break
        else:
            return lines[:height]

        first_half = height // 2
        second_half = height - first_half
        if current_line < first_half:
            return lines[:height]
        if current_line + second_half > total_lines:
            return lines[-height:]
        return lines[current_line - first_half : current_line + second_half]


# Define a layout with all Python windows
gdb.execute(
    " ".join(
        (
            "tui new-layout python",
            "python-backtrace 2",
            "{-horizontal python-bytecode 1 python-locals 1} 2",
            "python-source 2",
            "status 1 cmd 1",
        )
    )
)
