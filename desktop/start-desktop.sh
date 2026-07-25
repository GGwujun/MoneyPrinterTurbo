#!/usr/bin/env sh
# MoneyPrinterTurbo Desktop — Launcher (macOS / Linux)
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

echo "***** MoneyPrinterTurbo Desktop *****"
echo ""
echo "Starting Electron app..."
echo "The Streamlit backend will start automatically."
echo ""

# Ensure npm dependencies are installed
if [ ! -d "node_modules" ]; then
  echo "Installing npm dependencies..."
  npm install
fi

npm start
