import itertools
import shutil
import sys
import threading
import time


class BottomRightSpinner:
    """Animated spinner pinned to the bottom-right of the terminal.

    Writes directly to stderr using ANSI cursor-save/restore so it doesn't
    disturb stdout or the _PaddedWriter left-margin. Positions on the last
    terminal line to match where prompt_toolkit's hint-text toolbar sits.
    """

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, text: str = "Thinking..."):
        self.text = text
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            size = shutil.get_terminal_size()
            label = f"{frame} {self.text}"
            col = max(1, size.columns - len(label) + 1)
            sys.stderr.write(
                f"\033[s"                           # save cursor
                f"\033[{size.lines};{col}H"         # move to bottom-right
                f"\033[K"                           # clear to end of line
                f"\033[2m{label}\033[0m"            # dim text
                f"\033[u"                           # restore cursor
            )
            sys.stderr.flush()
            time.sleep(0.1)
        # Clear the spinner line on exit
        size = shutil.get_terminal_size()
        sys.stderr.write(
            f"\033[s"
            f"\033[{size.lines};1H"
            f"\033[2K"
            f"\033[u"
        )
        sys.stderr.flush()

    def __enter__(self) -> "BottomRightSpinner":
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
