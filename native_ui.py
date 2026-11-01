"""Compatibility wrapper: run the packaged FocusMic UI from the source tree."""
from focusmic.app import main

if __name__ == "__main__":
    raise SystemExit(main())
