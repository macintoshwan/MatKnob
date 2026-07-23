#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m manim -qh --fps 30 --resolution 1920,1080 megknob_pipeline.py MegKnobPipeline -o megknob_signal_pipeline.mp4
cp media/videos/megknob_pipeline/1080p30/megknob_signal_pipeline.mp4 ./megknob_signal_pipeline.mp4
"$PYTHON" -m manim -qh --fps 30 --resolution 1920,1080 megknob_product.py MegKnobProduct -o megknob_product_intro.mp4
cp media/videos/megknob_product/1080p30/megknob_product_intro.mp4 ./megknob_product_intro.mp4
"$PYTHON" -m manim -qk --fps 30 --resolution 3840,2160 megknob_pipeline_3d.py MegKnobPipeline3D -o megknob_signal_pipeline_3d_4k.mp4
cp media/videos/megknob_pipeline_3d/2160p30/megknob_signal_pipeline_3d_4k.mp4 ./megknob_signal_pipeline_3d_4k.mp4
"$PYTHON" -m manim -qk --fps 30 --resolution 3840,2160 megknob_product_3d.py MegKnobProduct3D -o megknob_product_intro_3d_4k.mp4
cp media/videos/megknob_product_3d/2160p30/megknob_product_intro_3d_4k.mp4 ./megknob_product_intro_3d_4k.mp4
"$PYTHON" -m manim -qk --fps 30 --resolution 3840,2160 megknob_ble_commit_3d.py MegKnobBLECommit3D -o megknob_ble_commit_explainer_3d_4k.mp4
cp media/videos/megknob_ble_commit_3d/2160p30/megknob_ble_commit_explainer_3d_4k.mp4 ./megknob_ble_commit_explainer_3d_4k.mp4
