# connections_main.py
"""
Main entry point for the NYT Connections Solver.

Usage:
    python connections_main.py
"""

from connections_solver.interface import play_connections


def main():
    """Replays the solver until the user is done."""
    while play_connections():
        pass
    print("\n👋 Thanks for using the Connections Solver!")


# === RUN MAIN ===
if __name__ == "__main__":
    main()
