"""Compatibility shim: `python install.py ...` == `peer-consult setup ...`.

Prefer installing the package (`pipx install peer-consult` or `uv tool install peer-consult`)
and running `peer-consult setup`. From a source checkout: `pip install -e .` first.
"""
import sys

try:
    from peer_consult.installer import setup_main
except ImportError:  # pragma: no cover
    sys.exit("peer-consult is not installed in this interpreter. Run `pip install -e .` here first, then retry.")

sys.exit(setup_main(sys.argv[1:]))
