import dis
import functools
import os
import pathlib
import sys
from typing import Optional

import gdb
from src.udbpy.gdb_extensions import command
from undodb.debugger_extensions import debugger_utils

import libpython

gdb.execute("alias -a pp = py-print")


@functools.cache
def get_python_versions() -> tuple[str, str]:
    """
    Get the inferior and the debugger Python versions.
    """
    inferior_version = gdb.parse_and_eval("PY_VERSION").string()
    debugger_version = ".".join(
        map(str, (sys.version_info.major, sys.version_info.minor))
    )
    return inferior_version, debugger_version


def check_python_bytecode_version() -> None:
    """
    Warn if the inferior's Python version is not compatible with the debugger's Python version,
    with respect to bytecode.

    Bytecode should be stable for minor versions.
    """
    inferior_version, debugger_version = get_python_versions()
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
        check_python_bytecode_version()

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


@functools.cache
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


def get_opcode_number(opcode: str) -> int:
    """
    Translate opcode string to opcode number.
    """
    check_python_bytecode_version()
    try:
        return dis.opmap[opcode]
    except KeyError:
        pass
    try:
        opcode_number = int(opcode)
        if opcode_number in dis.opmap.values():
            return opcode_number
    except ValueError:
        pass
    show_opcodes = "pi import dis; dis.opmap"
    raise gdb.GdbError(
        f"Invalid opcode {opcode!r}. Run `{show_opcodes}` to see valid opcodes."
    )


def python_step_bytecode(*, forwards: bool, opcode: str | None) -> None:
    """
    Continue the program forwards or backwards until the next Python bytecode.

    Accepts an optional target opcode.
    """
    try:
        basename = "ceval.c"
        location = get_c_source_location(basename, "dispatch_opcode:")
    except ValueError:
        raise gdb.GdbError(
            f"Failed to find Python bytecode interpreter loop in {basename}"
        )
    with debugger_utils.breakpoints_suspended():
        try:
            bp = gdb.Breakpoint(location, internal=True)
            if opcode:
                opcode_number = get_opcode_number(opcode)
                bp.condition = f"opcode == {opcode_number}"
            bp.silent = True
            gdb.execute("continue" if forwards else "reverse-continue")
        finally:
            if bp is not None:
                bp.delete()


class PythonStep(gdb.Command):
    """
    Continue the program forwards until the next Python bytecode.

    A specific opcode can be given as an optional argument.
    """

    def __init__(self):
        super().__init__("py-step", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        python_step_bytecode(forwards=True, opcode=arg)


PythonStep()
gdb.execute("alias -a pys = py-step")


class PythonReverseStep(gdb.Command):
    """
    Continue the program backwards until the next Python bytecode.

    A specific opcode can be given as an optional argument.
    """

    def __init__(self):
        super().__init__("py-reverse-step", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        python_step_bytecode(forwards=False, opcode=arg)


PythonReverseStep()
gdb.execute("alias -a pyrs = py-reverse-step")
gdb.execute("alias -a py-rstep = py-reverse-step")


class PythonLastAttribute(gdb.Command):
    """
    Find the last time a Python object's attribute was assigned.

    The first argument is the name of the Python object and is mandatory.
    The second argument is the name of the attribute and is optional. If no second argument is
    given, we search for assignment to any attribute.

    Add the "-f" option to search forwards instead of backwards.

    If the command is repeated, the previous search is resumed.
    """

    _repeat_detection = command._RepeatDetection()

    object_addr: int | None = None
    attribute_name: str | None = None
    backwards: bool = True

    def __init__(self):
        super().__init__("py-last-attr", gdb.COMMAND_RUNNING)

    def invoke(self, arg, from_tty):
        is_repeated = self._repeat_detection.handle_command()
        if not is_repeated:
            args = gdb.string_to_argv(arg)
            self.backwards = True
            if "-f" in args:
                args.remove("-f")
                self.backwards = False
            object_name, *args = args
            self.attribute_name = None
            if args:
                self.attribute_name, *_ = args

            frame = libpython.Frame.get_selected_python_frame()
            if not frame:
                print("Unable to locate python frame")
                return
            pyop_frame = frame.get_pyop()
            if not pyop_frame:
                print(libpython.UNABLE_READ_INFO_PYTHON_FRAME)
                return
            pyop_var, scope = pyop_frame.get_var_by_name(object_name)
            if not pyop_var:
                print("No such Python object")
                return
            self.object_addr = pyop_var.as_address()
            print(
                "".join(
                    [
                        f"Searching ",
                        "backwards " if self.backwards else "forwards ",
                        "for changes to ",
                        f"attribute {self.attribute_name} in "
                        if self.attribute_name
                        else "",
                        f"{scope} {object_name} object.",
                    ]
                )
            )

        def predicate():
            frame = gdb.selected_frame()
            if frame.read_var("v") != self.object_addr:
                return False
            if self.attribute_name:
                name_ptr = gdb.selected_frame().read_var("name")
                name = libpython.PyObjectPtr.from_pyobject_ptr(name_ptr).proxyval(set())
                return name == self.attribute_name
            return True

        with debugger_utils.breakpoints_suspended():
            bp = ConditionalBreakpoint(
                "PyObject_SetAttr", internal=True, predicate=predicate
            )
            bp.silent = True
            try:
                gdb.execute("reverse-continue" if self.backwards else "continue")
            finally:
                bp.delete()


PythonLastAttribute()
gdb.execute("alias -a pyla = py-last-attr")


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
