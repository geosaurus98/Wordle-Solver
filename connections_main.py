# connections_main.py
"""
Main entry point for the NYT Connections Solver.

Usage:
    python connections_main.py            # Claude + offline wordplay hints
    python connections_main.py --offline  # Offline wordplay hints only
"""

import sys

from connections_solver.interface import play_connections


def main():
    """Replays the solver until the user is done."""
    use_claude = "--offline" not in sys.argv[1:]
    while play_connections(use_claude=use_claude):
        pass
    print("\n👋 Thanks for using the Connections Solver!")


# === RUN MAIN ===
if __name__ == "__main__":
    main()
