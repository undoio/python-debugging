### What am I looking at

This repository contains UDB extensions for debugging Python programs.

The extensions are built on top of the `cpython` [GDB
library](https://github.com/python/cpython/blob/main/Tools/gdb/libpython.py).

### Install

Clone the repository or copy the following files into your current working directory

- `libpython.gdb`
- `libpython.py`
- `libpython_extensions.py`
- `libpython_ui.py`
- `tui_windows.py`

and start UDB while sourcing the `libpython.gdb` file from the same directory

```
$ udb --ex "source ./libpython.gdb"
```

The version of the `libpython.py` library must generally match the version of Python you want to
debug. These extensions are built around the 3.10 version of the `libpython.py` library.

### Usage

Use the following commands to inspect Python state:

- `py-print` (`pp`) to print Python objects
- `py-list` to list Python source code
- `py-bt` to show Python backtrace
- `py-locals` to show local Python variables
- `py-dis` to list Python bytecode disassembly

Use the following commands to navigate:

- `py-step` (`pys`) to step Python bytecode
- `py-reverse-step` (`pyrs`) to step Python bytecode backwards
- `py-advance-function` (`pya`) to continue until the next Python function call
- `py-reverse-advance-function` (`pyra`) to continue backwards until the previous Python function call
- `py-last-attr` (`pyla`) to search backwards or forwards until an object attribute is assigned

The `py-step` and `py-reverse-step` commands take an optional argument specifying the Python bytecode opcode to step until.

The `py-advance-function` and `py-reverse-advance-function` commands take an optional argument specifying which function to advance to.

The `py-last-attr` command takes an optional argument to specify which attribute name to search for.

---

Switch to the Python layout in TUI mode to get a better overview of your program. This layout automatically shows the output from `py-list`, `py-dis`, `py-locals` and `py-bt`:

```
> layout python
```

If your Python source code does not show up you might have to use the `py-substitute-path` command
to inform the debugger about the location of your local checkout of the Python source code.
