import dis
import os
import pathlib
import sys
from typing import Optional

import gdb
from undodb.debugger_extensions import debugger_utils

import libpython

gdb.execute("alias -a pp = py-print")


def check_python_version():
    """
    Warn if the inferior's Python version does not match the debugger's Python version.
    """
    inferior_version = gdb.parse_and_eval("PY_VERSION").string()
    debugger_version = ".".join(
        map(str, (sys.version_info.major, sys.version_info.minor))
    )
    if not inferior_version.startswith(debugger_version):
        print(
            f"Warning: Mismatched Python version between "
            f"inferior ({inferior_version}) and "
            f"debugger ({debugger_version}). "
            f"The bytecode shown might be wrong."
        )


class PyDisassemble(gdb.Command):
    """
    Disassemble the bytecode for the currently selected Python frame.
    """

    def __init__(self):
        gdb.Command.__init__(self, "py-dis", gdb.COMMAND_STACK, gdb.COMPLETE_NONE)

    def invoke(self, args, from_tty):
        check_python_version()

        frame = libpython.Frame.get_selected_bytecode_frame()
        if not frame:
            print("Unable to find frame with bytecode")
            return

        frame_object = frame.get_pyop()
        # f_lasti is a wordcode index and so must be multiplied by 2 to get byte offset, see cpyton
        # commit fc840736e54da0557616882012f362b809490165.
        byte_index = frame_object.f_lasti * 2
        bytes_object = frame_object.co.pyop_field("co_code")

        varnames, names, consts, cellvars, freevars = (
            frame_object.co.pyop_field(name).proxyval(set())
            for name in (
                "co_varnames",
                "co_names",
                "co_consts",
                "co_cellvars",
                "co_freevars",
            )
        )

        dis._disassemble_bytes(
            bytes(map(ord, str(bytes_object))),
            byte_index,
            varnames,
            names,
            consts,
            cellvars + freevars,
        )


PyDisassemble()


def get_frame_function_name(frame: libpython.Frame) -> str | None:
    """
    Return the name of the Python function that corresponds to the given Python frame.
    """
    if frame.is_evalframe():
        pyop = frame.get_pyop()
        if pyop:
            return pyop.co_name.proxyval(set())
    else:
        info = frame.is_other_python_frame()
        if info:
            return str(info)
    return None


def get_evalframe_function_name() -> Optional[str]:
    """
    Attempt to return the name of the function in this eval frame.
    """
    python_frame = libpython.Frame.get_selected_python_frame()
    return get_frame_function_name(python_frame)


def get_cfunction_name() -> str:
    """
    Return the name of the C-implemented function which is executing on this cpython frame.

    This assumes we're stopped with a PyCFunctionObject object available in "func".
    """
    func_ptr = gdb.selected_frame().read_var("func")
    python_cfunction = libpython.PyCFunctionObjectPtr.from_pyobject_ptr(func_ptr)
    return python_cfunction.proxyval(set()).ml_name


class ConditionalBreakpoint(gdb.Breakpoint):
    """
    Breakpoint that will stop the inferior iff the given predicate callable returns True.
    """

    def __init__(self, *args, **kwargs):
        self.predicate = kwargs.pop("predicate")
        super().__init__(*args, **kwargs)

    def stop(self):
        return self.predicate()


def advance_function(forward: bool, function_name: str) -> None:
    """
    Continue the program forwards or backwards until the next time a Python function is called.
    """
    with debugger_utils.breakpoints_suspended():
        direction = "forwards" if forward else "backwards"
        target = (
            f"Python function '{function_name}'"
            if function_name
            else "the next Python function call"
        )
        print(f"Running {direction} until {target}.")

        breakpoints = []
        for location, get_name in [
            ("cfunction_enter_call", get_cfunction_name),
            ("_PyEval_EvalFrameDefault", get_evalframe_function_name),
        ]:
            bp = ConditionalBreakpoint(
                location,
                internal=True,
                predicate=lambda f=get_name: not function_name or f() == function_name,
            )
            bp.silent = True
            breakpoints.append(bp)
        try:
            gdb.execute("continue" if forward else "reverse-continue")
        finally:
            for bp in breakpoints:
                bp.delete()


class PythonAdvanceFunction(gdb.Command):
    """
    Continue the program until the given Python function is called.
    """

    def __init__(self):
        super().__init__("py-advance-function", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        advance_function(True, arg)


PythonAdvanceFunction()
gdb.execute("alias -a pya = py-advance")


class PythonReverseAdvanceFunction(gdb.Command):
    """
    Continue the program backwards until the given Python function is called.
    """

    def __init__(self):
        super().__init__("py-reverse-advance-function", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        advance_function(False, arg)


PythonReverseAdvanceFunction()
gdb.execute("alias -a pyra = py-reverse-advance")


def get_c_source_location(basename: str, content: str) -> str:
    """
    Return linespec for a file matching the given basename and line matching the given content.

    The basename is against source files currently known to the debugger. The content is matched
    against the first matching filename.

    Raises a ValueError if the file or content wasn't found.
    """
    sources = gdb.execute(f"info sources {basename}", to_string=True).splitlines()
    filename, *_ = (f for f in sources if basename in f)
    lines = pathlib.Path(filename).read_text().splitlines()
    for lineno, line in enumerate(lines):
        if content in line:
            return f"{basename}:{lineno}"
    raise ValueError(f"Failed to find {content=} in {basename=}")


def python_step_bytecode(*, forwards: bool) -> None:
    """
    Continue the program forwards or backwards until the next Python bytecode.
    """
    if getattr(python_step_bytecode, "location", None) is None:
        try:
            basename = "ceval.c"
            python_step_bytecode.location = get_c_source_location(
                basename, "dispatch_opcode:"
            )
        except ValueError:
            raise gdb.GdbError(
                f"Failed to find Python bytecode interpreter loop in {basename}"
            )

    with debugger_utils.breakpoints_suspended():
        bp = gdb.Breakpoint(python_step_bytecode.location, internal=True)
        bp.silent = True
        try:
            gdb.execute("continue" if forwards else "reverse-continue")
        finally:
            bp.delete()


class PythonStep(gdb.Command):
    """
    Continue the program forwards until the next Python bytecode.
    """

    def __init__(self):
        super().__init__("py-step", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        python_step_bytecode(forwards=True)


PythonStep()
gdb.execute("alias -a pys = py-step")


class PythonReverseStep(gdb.Command):
    """
    Continue the program backwards until the next Python bytecode.
    """

    def __init__(self):
        super().__init__("py-reverse-step", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        python_step_bytecode(forwards=False)


PythonReverseStep()
gdb.execute("alias -a pyrs = py-reverse-step")
gdb.execute("alias -a py-rstep = py-reverse-step")


class PythonSubstitutePath(gdb.Command):
    """
    Define path substitutions for Python files.

    When given zero arguments, prints the current substitutions.
    When given "clear" as the argument, removes current substitutions.
    When given two arguments "original" and "substitution", installs a new substitution rule.
    """

    substitutions: list[tuple[str, str]] = []

    def __init__(self):
        super().__init__("py-substitute-path", gdb.COMMAND_FILES)

    def invoke(self, arg, from_tty):
        if not arg:
            print("The current substitutions are:")
            for original, substitution in self.substitutions:
                print(f"  {original} -> {substitution}")
            return

        if arg == "clear":
            self.substitutions.clear()
            print("All substitutions have been removed.")
            return

        try:
            original, substitution = gdb.string_to_argv(arg)
        except ValueError:
            raise ValueError(
                "This command expects two arguments: original path and substitution path."
            )
        self.substitutions.append((original, substitution))

    @classmethod
    def open(cls, path_bytes: bytes, *args):
        """
        Wrapper for the "open" function, substituing paths defined by py-substitute-path
        """
        path = os.fsdecode(path_bytes)
        for original, substitution in cls.substitutions:
            if original in path:
                path = path.replace(original, substitution)
                break
        return open(os.fsencode(path), *args)


PythonSubstitutePath()
# Define a customised open implementation in the libpython module to substitute filename paths.
setattr(libpython, "open", PythonSubstitutePath.open)
