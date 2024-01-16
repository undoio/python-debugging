import os
import pathlib
import random
import threading
import traceback

class GlobalState:
    count = 0

# Shared variable
g_value = GlobalState()
# Lock for synchronization
lock = threading.Lock()


def thread_fn_1():
    global g_value

    iteration = 0
    while True:
        with lock:
            if iteration % (10 * 1000) == 0:
                print(f"thread 1: {iteration=}")
            old_value = g_value.count
            increment = random.randint(1, 5)
            g_value.count += increment
            assert (
                g_value.count == old_value + increment
            ), f"{g_value.count=}, {old_value=}, {increment=}"
        iteration += 1


def thread_fn_2():
    global g_value

    iteration = 0
    while True:
        if iteration % 100 == 0:
            print(f"thread 2: {iteration=}")
        g_value.count += 1
        iteration += 1


def exception_handler(args):
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    os.abort()


def list_current_directory():
    cwd = pathlib.Path(os.getcwd())
    for name in cwd.iterdir():
        print(name)


def do_some_prints():
    x = 3
    y = 4
    print(f"Hello from a function call: {x+y=}")


def main():
    print('Issuing a "print" statement')
    do_some_prints()

    print("Listing the current directory")
    list_current_directory()

    print('Running the "race.cpp" example')
    print()
    # Create two threads
    threading.excepthook = exception_handler
    thread1 = threading.Thread(target=thread_fn_1)
    thread2 = threading.Thread(target=thread_fn_2)

    # Start the threads
    thread1.start()
    thread2.start()

    # Wait for both threads to finish
    thread1.join()
    thread2.join()

    # Print the final value of the shared variable
    print(f"Final {g_value.count=}")


if __name__ == "__main__":
    main()
