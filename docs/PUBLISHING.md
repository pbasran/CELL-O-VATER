# Publish your working copy

This folder is a local Git repository. No remote is configured and nothing has been uploaded.

1. Open GitHub Desktop and choose File → Add Local Repository. Select this folder.
2. Review the Changes list. It should contain only application code, tests, configuration templates, documentation and web assets.
3. Make the initial commit, then choose Publish repository. A private repository is appropriate until you choose the license and sharing policy.
4. Keep runtime assets, model weights, environments, source images, outputs, logs and job state out of commits; `.gitignore` excludes them.

No open-source license is assigned automatically. Choose one before presenting this as an open-source release. Dependencies retain their own licenses and are installed or supplied separately.

The runtime assets must be provisioned separately for a new user. This repository is not a standalone binary distribution. See Setup for the exact asset manifest and installer.

For tests, use the installed Python environments with this checkout as the working directory:

```sh
cd source
/path/to/installation/.venv/bin/python test_core.py
/path/to/installation/.venv-cellpose-sam/bin/python -m unittest discover -s tests -p test_between_wells.py
/path/to/installation/.venv-cellpose/bin/python -m unittest discover -s tests -p test_cellpose_preprocessing.py
node tests/test_time_course.cjs
node tests/test_activity_ui.cjs
```

Some integration tests require models, native runtimes or test images. See VALIDATION.txt for the checks actually performed when preparing this copy.
