# Setup

Use macOS 14 or later and Python 3.11. The existing native CellProfiler 4.2.8 and Temurin Java 8 assets are Intel builds. Start with an Intel Mac; do not assume an Apple Silicon machine is validated.

The asset directory must contain:

```
CellProfiler-macOS-4.2.8.zip
temurin-jre.tar.gz
models/cpsam_v2
models/cyto3
models/nucleitorch_0
```

These are supplied separately from the working lab distribution. Their hashes are recorded in `asset-checksums.json`. The GitHub checkout alone does not contain these assets. Do not replace them with arbitrary versions: the native paths and dependency versions are pinned.

From the repository folder:

```sh
python3.11 install.py --assets "/path/to/shared-release/assets" --check
python3.11 install.py --assets "/path/to/shared-release/assets"
```

The default installation is `~/Applications/CELL-O-VATER-2026.11.13`. Use `--destination "/another/empty/folder"` for a separate installation. The installer creates three Python environments and checks imports, model presence, Java and CellProfiler. Internet access is needed for Python packages. It never copies your datasets or active job state.

Alternatively put the verified assets in the ignored `assets/` directory and double-click `Install CELL-O-VATER.command`.

Open the installed `Start CELL-O-VATER.command`, `Start Batch Processing.command`, or `Start Time Series.command`. Each opens a local browser page; launchers choose an available port. Do not use the launchers inside `source/` before installing its dependencies.

For a batch, specify the raw experiment folder and separate processed experiment folder, preview batches and start. Preserve the acquisition hierarchy and README metadata. Make cloud inputs locally available. After a crash reopen the same installation and use Resume unfinished run; do not start a second copy on the same outputs.

Closing the browser does not stop processing. Keep the Mac powered and awake. Review the page's exceptions and overlays after completion. Time-series analysis consumes processed results, not the raw images.

For development, change this repository, run the relevant tests, then install into a new versioned destination. The installer does not overwrite an already completed installation. Do not edit an installation processing an active experiment.
