#!/bin/zsh
cd -- "${0:A:h}" || exit 1
PYTHON311="$(command -v python3.11)"
if [[ -z "$PYTHON311" && -x /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 ]]; then
 PYTHON311=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
fi
if [[ -z "$PYTHON311" ]]; then
 echo "Install Python 3.11 from python.org first. See START HERE.txt."
else
 "$PYTHON311" install.py
fi
read "?Press Return to close…"
