#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m manim -qh --fps 30 --resolution 1920,1080 megknob_pipeline.py MegKnobPipeline -o megknob_signal_pipeline.mp4
cp media/videos/megknob_pipeline/1080p30/megknob_signal_pipeline.mp4 ./megknob_signal_pipeline.mp4
"$PYTHON" -m manim -qh --fps 30 --resolution 1920,1080 megknob_product.py MegKnobProduct -o megknob_product_intro.mp4
cp media/videos/megknob_product/1080p30/megknob_product_intro.mp4 ./megknob_product_intro.mp4
