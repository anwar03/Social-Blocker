#!/usr/bin/env python3
"""Convenience launcher so you can run ./socialblocker.py without installing.

    sudo ./socialblocker.py status
    sudo ./socialblocker.py focus 90 --whitelist --locked
    sudo ./socialblocker.py gui        # opens the desktop GUI
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if len(sys.argv) > 1 and sys.argv[1] == "gui":
    from socialblocker.gui import main
    main()
else:
    from socialblocker.cli import main
    main()
