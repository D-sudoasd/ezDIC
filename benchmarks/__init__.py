"""Locked, headless synthetic benchmark for ezDIC.

The executable lives in :mod:`benchmarks.run_benchmark`; this package keeps
the module lazy so ``python -m benchmarks.run_benchmark`` has no runpy import
warning and does not execute benchmark setup twice.
"""
