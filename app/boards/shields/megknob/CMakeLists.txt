# Copyright (c) 2026 The ZMK Contributors
# SPDX-License-Identifier: MIT

# The 128x32 SSD1306 uses a compact ASCII-only MegKnob status page. Keeping
# this shield-specific source out of the generic display implementation avoids
# relying on optional LVGL symbol glyphs that are not present in small fonts.
zephyr_library_sources_ifdef(CONFIG_ZMK_DISPLAY_STATUS_SCREEN_CUSTOM custom_status_screen.c)
