"""Dataset-path entry point for local use; the future GUI calls scan_dataset directly."""
from cell_analysis.importer import main

if __name__ == '__main__':
    raise SystemExit(main())
