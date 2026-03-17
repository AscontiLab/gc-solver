#!/usr/bin/env bash
# Tailwind CSS bauen (minified)
set -euo pipefail
cd "$(dirname "$0")"
npx @tailwindcss/cli -i static/input.css -o static/style.css --minify
echo "CSS build fertig: static/style.css"
