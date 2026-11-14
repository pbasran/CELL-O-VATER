#!/bin/zsh
cd -- "${0:A:h}" || exit 1
./.venv/bin/python launch_app.py segmentation
if [[ $? -ne 0 ]]; then
 read "?Press Return to close…"
fi
