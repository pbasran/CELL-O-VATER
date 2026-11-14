# VAIDER-RADAR CELL-O-VATER

Local macOS application for Cellpose-SAM segmentation, CellProfiler measurements, and time-series comparison of microscopy images.

## Workflows

- **Segmentation:** select a dataset path, review settings, generate cell masks, overlays and per-cell feature tables.
- **Batch processing:** process acquisition folders, reuse the model, stage inputs locally and resume verified completed groups after interruption.
- **Time series:** compare cell counts, total segmented area and measured features across acquisition times and wells.

## Install and run

See [Setup](docs/SETUP.md). Python environments, model weights and native runtimes are installed locally; they are not committed to this repository. This source release requires the separately supplied, checksum-verified runtime assets.

After installation, open one of the three `.command` launchers in the installation folder. Processing runs on your Mac without a chat session. Keep source images outside the software folder and choose a separate processed-data destination.

## Repository layout

| Folder | Contents |
| --- | --- |
| `source/cell_analysis` | Import, segmentation, measurements, QC and analysis |
| `source/web` | Segmentation, batch and time-series interfaces |
| `source/profiles`, `source/schema` | Imaging profiles and metadata schemas |
| `source/tests` | Python and browser-logic tests |
| `docs` | Installation, operation and publishing instructions |
| `assets` | Ignored local runtime assets; no datasets |

## Scope and limitations

Current inference is CPU-based. The packaged native runtimes were used on Intel macOS; Apple Silicon compatibility has not been independently validated. Windows GPU workers are not implemented in this release.

Batch mode analyzes independent image fields; cell identifiers do not establish lineage. Counts are cells in the imaged field, not the whole well. Scratches, fiducial halos, blur and lighting artifacts can produce incorrect contours: review representative overlays before interpreting growth. Physical units require verified pixel calibration.

Crash recovery skips verified completed processing groups. An interrupted group may need to run again. Free disk space is checked, but available space can change while other applications or cloud synchronization run.

## Publishing

See [Publishing](docs/PUBLISHING.md). No open-source license has been selected for the lab-authored code. Third-party packages and model weights retain their own licenses; see THIRD-PARTY-NOTICES.txt.
