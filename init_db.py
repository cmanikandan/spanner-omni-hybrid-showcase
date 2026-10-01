"""Standalone schema and seed initializer for any Spanner Omni endpoint (init_db.py)."""

import sys
from argparse import Namespace
from manage import cmd_init

if __name__ == "__main__":
    sys.exit(cmd_init(Namespace(force=False, sim_only=False)))
