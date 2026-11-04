"""PyInstaller entry point; keeps package-relative imports working in a frozen app."""
from focusmic.app import main

if __name__ == "__main__":
    raise SystemExit(main())
