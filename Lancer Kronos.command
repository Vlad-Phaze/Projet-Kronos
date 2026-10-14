#!/bin/bash
cd "$(dirname "$0")"
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
python3 "launch_kronos.py"
status=$?
if [ "$status" -ne 0 ]; then
  echo ""
  echo "Kronos s'est arrêté (code $status). Appuie sur Entrée pour fermer."
  read -r _
fi
