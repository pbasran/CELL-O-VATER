"""Run core tests; SciPy and Cellpose tests use their separate environments."""
import unittest
suite=unittest.TestSuite()
from pathlib import Path
for path in sorted(Path('tests').glob('test_*.py')):
 if path.stem!='test_between_wells':suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=path.name))
raise SystemExit(not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful())
