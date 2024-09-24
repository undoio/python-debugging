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

The supported version of Python is currently cpython 3.10. The interpreter must have been compiled with full debug information (`-g3`) and without cpython's "computed gotos" feature.

You can use the `./setup-python` script to install a suitable version of Python with `pyenv`:

```
$ source ./setup-python
$ python --version
Python 3.10.15
```

### Usage

Use the following commands to inspect Python state:

- `py-print` (`pp`) to print Python objects
- `py-eval` (`pe`) to evaluate Python expressions
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

Switch to the Python layout in TUI mode to get a better overview of your program.

```
> layout python
```

If your Python source code does not show up you might have to use the `py-substitute-path` command
to inform the debugger about the location of your local checkout of the Python source code.
