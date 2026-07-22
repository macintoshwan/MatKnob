"""Manim film: MegKnob's 24-channel Hall-voltage data pipeline."""

from __future__ import annotations

import math

import numpy as np
from manim import *

config.background_color = "#071018"

BG = "#071018"
PANEL = "#0D1A24"
PANEL_2 = "#122430"
GRID = "#1A3442"
INK = "#DDEBF2"
MUTED = "#6F8996"
CYAN = "#22D3EE"
YELLOW = "#F8C537"
MAGENTA = "#F05BC8"
GREEN = "#53E6A1"
ORANGE = "#FF8A4C"
RED = "#FF5D73"
PURPLE = "#9D8CFF"
MONO = "Menlo"
SANS = "Arial"

FRAME_LEFT = -7.05
FRAME_RIGHT = 7.05
FRAME_TOP = 3.85
FRAME_BOTTOM = -3.85
CONTENT_TOP = 3.10
CONTENT_BOTTOM = -3.55
PANEL_WIDTH = 5.72
STAGE_WIDTH = 6.72
PANEL_HEIGHT = 5.95
LEFT_CENTER = -3.58
RIGHT_CENTER = 3.33
CONTENT_Y = -0.22


class MegKnobPipeline(Scene):
    def construct(self):
        self.camera.background_color = BG
        self.add(self.background_grid())
        self.intro()
        self.hall_scene()
        self.mux_scene()
        self.adc_scene()
        self.scan_scene()
        self.packet_scene()
        self.usb_scene()
        self.decode_scene()
        self.plot_scene()
        self.final_scene()

    # ---------- shared visual language ----------
    def background_grid(self):
        lines = VGroup()
        for x in np.arange(-7.5, 7.6, 0.5):
            lines.add(Line([x, -4, 0], [x, 4, 0], stroke_width=0.45, color=GRID, stroke_opacity=0.24))
        for y in np.arange(-4, 4.1, 0.5):
            lines.add(Line([-7.5, y, 0], [7.5, y, 0], stroke_width=0.45, color=GRID, stroke_opacity=0.24))
        return lines

    def label(self, text, size=28, color=INK, weight=NORMAL, font=SANS,
              max_width=None, max_height=None):
        """Create text and guarantee that it fits its allocated box."""
        mob = Text(text, font=font, font_size=size, color=color, weight=weight)
        if max_width is not None and mob.width > max_width:
            mob.scale_to_fit_width(max_width)
        if max_height is not None and mob.height > max_height:
            mob.scale_to_fit_height(max_height)
        return mob

    def fit_inside(self, mob, box, x_pad=0.22, y_pad=0.22):
        """Scale and center a group inside a panel without clipping."""
        max_w = box.width - 2 * x_pad
        max_h = box.height - 2 * y_pad
        if mob.width > max_w:
            mob.scale_to_fit_width(max_w)
        if mob.height > max_h:
            mob.scale_to_fit_height(max_h)
        mob.move_to(box)
        return mob

    def top_title(self, index, title, kicker):
        number = self.label(f"{index:02d}", 20, YELLOW, BOLD, MONO, max_width=0.52)
        name = self.label(title, 28, INK, BOLD, max_width=5.4)
        sub = self.label(kicker.upper(), 12, MUTED, BOLD, MONO, max_width=5.7)
        title_group = VGroup(number, name, sub).arrange(RIGHT, buff=0.25, aligned_edge=DOWN)
        if title_group.width > 12.9:
            title_group.scale_to_fit_width(12.9)
        title_group.move_to([FRAME_LEFT + title_group.width / 2 + 0.24, 3.55, 0])
        rule = Line([FRAME_LEFT + 0.2, 3.22, 0], [FRAME_RIGHT - 0.2, 3.22, 0], color=GRID, stroke_width=1.2)
        return VGroup(title_group, rule)

    def code_panel(self, function, lines, highlights=()):
        box = RoundedRectangle(width=PANEL_WIDTH, height=PANEL_HEIGHT, corner_radius=0.16,
                               fill_color=PANEL, fill_opacity=0.96, stroke_color=GRID, stroke_width=1.2)
        dots = VGroup(*[Dot(radius=0.052, color=c) for c in (RED, YELLOW, GREEN)]).arrange(RIGHT, buff=0.10)
        dots.move_to(box.get_corner(UL) + RIGHT * 0.34 + DOWN * 0.27)
        fn = self.label(function, 16, CYAN, BOLD, MONO, max_width=4.45, max_height=0.3)
        fn.move_to(box.get_top() + DOWN * 0.29)
        rule_y = box.get_top()[1] - 0.58
        rule = Line([box.get_left()[0] + 0.18, rule_y, 0], [box.get_right()[0] - 0.18, rule_y, 0],
                    color=GRID, stroke_width=1)
        code = VGroup()
        available_width = box.width - 0.54
        for i, source in enumerate(lines):
            color = YELLOW if i in highlights else INK
            txt = self.label(source, 15, color, NORMAL, MONO, max_width=available_width, max_height=0.34)
            code.add(txt)
        code.arrange(DOWN, aligned_edge=LEFT, buff=0.20)
        available_height = box.height - 1.15
        if code.height > available_height:
            code.scale_to_fit_height(available_height)
        code.move_to([box.get_left()[0] + 0.27 + code.width / 2, rule_y - 0.27 - code.height / 2, 0])
        return VGroup(box, dots, fn, rule, code)

    def stage(self, width=STAGE_WIDTH, height=PANEL_HEIGHT):
        return RoundedRectangle(width=width, height=height, corner_radius=0.16, fill_color="#09151E",
                                fill_opacity=0.93, stroke_color=GRID, stroke_width=1.2)

    def split_layout(self, code, visual):
        code.move_to([LEFT_CENTER, CONTENT_Y, 0])
        visual.move_to([RIGHT_CENTER, CONTENT_Y, 0])

    def wipe(self, *groups, run_time=0.55):
        mobs = [g for g in groups if g is not None]
        self.play(*[FadeOut(g, shift=LEFT * 0.18) for g in mobs], run_time=run_time)

    def pulse(self, mob, color=YELLOW, scale=1.08):
        return Succession(mob.animate.set_color(color).scale(scale), mob.animate.set_color(CYAN).scale(1 / scale))

    # ---------- scenes ----------
    def intro(self):
        pipeline_names = ["MAGNET", "HALL", "MUX × 3", "SAADC", "62 BYTE", "USB", "PYTHON", "PLOT"]
        boxes = VGroup()
        for name in pipeline_names:
            b = RoundedRectangle(width=1.38, height=0.62, corner_radius=0.12, fill_color=PANEL_2,
                                 fill_opacity=1, stroke_color=GRID, stroke_width=1.1)
            t = self.label(name, 14, INK, BOLD, MONO).move_to(b)
            boxes.add(VGroup(b, t))
        boxes.arrange(RIGHT, buff=0.22).scale(0.9).move_to(DOWN * 1.15)
        arrows = VGroup(*[
            Arrow(boxes[i].get_right(), boxes[i + 1].get_left(), buff=0.04, color=MUTED,
                  stroke_width=2, max_tip_length_to_length_ratio=0.22)
            for i in range(len(boxes) - 1)
        ])
        kicker = self.label("MEGKNOB / ZMK", 17, YELLOW, BOLD, MONO)
        title = self.label("FROM MAGNETIC FIELD", 50, INK, BOLD, max_width=11.8)
        title2 = self.label("TO LIVE WAVEFORM", 50, CYAN, BOLD, max_width=11.8)
        title_group = VGroup(kicker, title, title2).arrange(DOWN, buff=0.12).move_to(UP * 1.25)
        subtitle = self.label("24 CHANNELS  ·  ONE REAL-TIME DATA STREAM", 16, MUTED, BOLD, MONO)
        subtitle.next_to(title_group, DOWN, buff=0.35)
        dot = Dot(boxes[0].get_center(), radius=0.09, color=YELLOW).set_z_index(5)
        self.play(FadeIn(kicker, shift=UP * 0.15), Write(title), Write(title2), run_time=1.5)
        self.play(FadeIn(subtitle), LaggedStart(*[FadeIn(b, shift=UP * 0.12) for b in boxes], lag_ratio=0.07),
                  Create(arrows), run_time=1.3)
        self.add(dot)
        for box in boxes[1:]:
            self.play(dot.animate.move_to(box.get_center()), box[0].animate.set_stroke(CYAN, 2.2), run_time=0.22)
        self.wait(0.5)
        self.wipe(title_group, subtitle, boxes, arrows, dot)

    def hall_scene(self):
        header = self.top_title(1, "MAGNET → VOLTAGE", "kscan_adc_mux_pressed()")
        code = self.code_panel("kscan_adc_mux_pressed()", [
            "if (was_pressed)",
            "    return sample_mv < 1400;",
            "else",
            "    return sample_mv < 900;",
            "// 3 stable scans confirm state",
        ], highlights=(1, 3))
        stage = self.stage()
        self.split_layout(code, stage)
        sensor = RoundedRectangle(width=1.7, height=0.42, corner_radius=0.08, fill_color=CYAN,
                                  fill_opacity=0.25, stroke_color=CYAN).move_to(stage.get_center() + LEFT * 1.7 + DOWN * 1.62)
        sensor_t = self.label("LINEAR HALL", 13, CYAN, BOLD, MONO).move_to(sensor)
        stem = RoundedRectangle(width=0.72, height=1.5, corner_radius=0.1, fill_color=PANEL_2,
                                fill_opacity=1, stroke_color=INK).move_to(sensor.get_center() + UP * 1.55)
        magnet = RoundedRectangle(width=0.58, height=0.48, corner_radius=0.06, fill_color=MAGENTA,
                                  fill_opacity=0.8, stroke_color=MAGENTA).move_to(stem.get_bottom() + UP * 0.33)
        magnet_t = self.label("N  S", 12, BG, BOLD, MONO).move_to(magnet)
        cap = RoundedRectangle(width=1.8, height=0.48, corner_radius=0.1, fill_color="#314654",
                               fill_opacity=1, stroke_color=INK).move_to(stem.get_top() + UP * 0.18)
        graph_box = RoundedRectangle(width=3.2, height=2.3, corner_radius=0.08, stroke_color=GRID,
                                     fill_color=BG, fill_opacity=0.8).move_to(stage.get_center() + RIGHT * 1.45 + UP * 0.1)
        x0, y0 = graph_box.get_left()[0] + 0.28, graph_box.get_bottom()[1] + 0.3
        x1, y1 = graph_box.get_right()[0] - 0.18, graph_box.get_top()[1] - 0.25
        press_y = y0 + (0.9 / 2.2) * (y1 - y0)
        release_y = y0 + (1.4 / 2.2) * (y1 - y0)
        threshold_band = Rectangle(width=x1 - x0, height=release_y - press_y, fill_color=YELLOW,
                                   fill_opacity=0.08, stroke_opacity=0).move_to([(x0 + x1) / 2, (press_y + release_y) / 2, 0])
        p_line = DashedLine([x0, press_y, 0], [x1, press_y, 0], color=YELLOW, dash_length=0.08)
        r_line = DashedLine([x0, release_y, 0], [x1, release_y, 0], color=ORANGE, dash_length=0.08)
        p_lab = self.label("PRESS 0.9 V", 11, YELLOW, BOLD, MONO).next_to(p_line, UP, buff=0.03).align_to(p_line, LEFT)
        r_lab = self.label("RELEASE 1.4 V", 11, ORANGE, BOLD, MONO).next_to(r_line, UP, buff=0.03).align_to(r_line, LEFT)
        tracker = ValueTracker(0)
        curve = always_redraw(lambda: VMobject(color=CYAN, stroke_width=3).set_points_smoothly([
            [interpolate(x0, x1, u), interpolate(y0 + 0.72 * (y1-y0), y0 + 0.18 * (y1-y0),
             min(1, max(0, (u * 1.15)))), 0] for u in np.linspace(0, max(0.02, tracker.get_value()), 50)
        ]))
        point = always_redraw(lambda: Dot(curve.get_end(), radius=0.07, color=YELLOW))
        state = self.label("RELEASED", 18, GREEN, BOLD, MONO).move_to(stage.get_center() + RIGHT * 1.45 + DOWN * 1.65)
        visual = VGroup(stage, sensor, sensor_t, stem, magnet, magnet_t, cap, graph_box, threshold_band,
                        p_line, r_line, p_lab, r_lab, curve, point, state)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(VGroup(stage, sensor, sensor_t, stem, magnet, magnet_t, cap,
                  graph_box, threshold_band, p_line, r_line, p_lab, r_lab, state)), run_time=1)
        self.add(curve, point)
        self.play(tracker.animate.set_value(1), VGroup(cap, stem, magnet, magnet_t).animate.shift(DOWN * 0.83), run_time=2.4,
                  rate_func=smooth)
        pressed = self.label("PRESSED", 18, YELLOW, BOLD, MONO).move_to(state)
        self.play(Transform(state, pressed), Flash(point, color=YELLOW, flash_radius=0.32), run_time=0.45)
        self.wait(0.5)
        self.wipe(header, code, visual)

    def mux_scene(self):
        header = self.top_title(2, "SELECT 3 OF 24", "kscan_adc_mux_set_address()")
        code = self.code_panel("kscan_adc_mux_set_address()", [
            "changed = current ^ address;",
            "for (bit = 0; bit < 3; bit++) {",
            "    if (changed & BIT(bit))",
            "        gpio_pin_set_dt(...);",
            "}",
            "k_busy_wait(10); // µs",
        ], highlights=(0, 2, 5))
        stage = self.stage()
        self.split_layout(code, stage)
        chips = VGroup()
        channel_dots = []
        for row, chip_name in enumerate(("U26", "U27", "U28")):
            body = RoundedRectangle(width=3.65, height=1.25, corner_radius=0.1, fill_color=PANEL_2,
                                    fill_opacity=1, stroke_color=GRID)
            body.move_to(stage.get_center() + UP * (1.55 - row * 1.55) + RIGHT * 0.55)
            name = self.label(chip_name, 16, INK, BOLD, MONO).next_to(body.get_left(), RIGHT, buff=0.16)
            dots = VGroup()
            for col in range(8):
                d = Dot(radius=0.075, color=MUTED).move_to(body.get_left() + RIGHT * (1.05 + col * 0.31))
                lab = self.label(str(col), 9, MUTED, NORMAL, MONO).next_to(d, DOWN, buff=0.07)
                dots.add(VGroup(d, lab)); channel_dots.append(d)
            out = Dot(body.get_right() + LEFT * 0.2, radius=0.08, color=CYAN)
            chips.add(VGroup(body, name, dots, out))
        addr = VGroup(*[VGroup(RoundedRectangle(width=0.66, height=0.42, corner_radius=0.06, fill_color=PANEL,
                                               fill_opacity=1, stroke_color=GRID),
                                  self.label(f"S{i}", 13, MUTED, BOLD, MONO)) for i in range(3)])
        for g in addr: g[1].move_to(g[0])
        addr.arrange(RIGHT, buff=0.16).move_to(stage.get_bottom() + UP * 0.42 + LEFT * 2.05)
        gray_text = self.label("GRAY ORDER", 10, MUTED, BOLD, MONO)
        gray_sequence = self.label("0  1  3  2  6  7  5  4", 12, INK, BOLD, MONO, max_width=3.25)
        gray_group = VGroup(gray_text, gray_sequence).arrange(DOWN, buff=0.06)
        gray_group.move_to(stage.get_bottom() + UP * 0.43 + RIGHT * 1.35)
        visual = VGroup(stage, chips, addr, gray_group)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(visual), run_time=1)
        gray = [0, 1, 3, 2, 6, 7, 5, 4]
        last = 0
        for n, col in enumerate(gray):
            bits = [(col >> i) & 1 for i in range(3)]
            changed = col ^ last if n else 0
            anims = []
            for i, g in enumerate(addr):
                anims.append(g[0].animate.set_fill(YELLOW if bits[i] else PANEL, opacity=1)
                             .set_stroke(YELLOW if bits[i] else GRID))
                g[1].set_color(BG if bits[i] else MUTED)
                if changed & (1 << i): anims.append(Indicate(g, color=YELLOW, scale_factor=1.08))
            for row in range(3):
                for c in range(8):
                    anims.append(chips[row][2][c][0].animate.set_color(CYAN if c == col else MUTED)
                                 .scale(1.35 if c == col else (1 / 1.35 if c == last and c != col else 1)))
            self.play(*anims, run_time=0.28)
            last = col
        settle = self.label("SETTLE  10 µs", 15, YELLOW, BOLD, MONO).move_to(stage.get_center() + RIGHT * 1.9 + DOWN * 2.2)
        self.play(FadeIn(settle), Circumscribe(settle, color=YELLOW), run_time=0.6)
        self.wait(0.35)
        self.wipe(header, code, visual, settle)

    def adc_scene(self):
        header = self.top_title(3, "THREE AT ONCE", "kscan_adc_mux_read_channels()")
        code = self.code_panel("kscan_adc_mux_read_channels()", [
            "batch_seq.channels = BIT(0)|BIT(5)|BIT(7);",
            "adc_read(adc, &batch_seq);",
            "sample_index = POPCOUNT(lower_channels);",
            "samples_mv[row] = samples[sample_index];",
            "adc_raw_to_millivolts_dt(...);",
        ], highlights=(1, 4))
        stage = self.stage(); self.split_layout(code, stage)
        inputs = VGroup()
        colors = (CYAN, MAGENTA, GREEN)
        for i, (name, val, color) in enumerate(zip(("AIN7", "AIN5", "AIN0"), (1784, 926, 1321), colors)):
            y = stage.get_top()[1] - 1.1 - i * 1.28
            src = self.label(name, 15, color, BOLD, MONO).move_to([stage.get_left()[0] + 0.55, y, 0])
            wave = VMobject(color=color, stroke_width=2.4)
            xs = np.linspace(stage.get_left()[0] + 1.05, stage.get_center()[0] - 0.35, 55)
            wave.set_points_smoothly([[x, y + 0.12 * math.sin((x - xs[0]) * 8 + i), 0] for x in xs])
            inputs.add(VGroup(src, wave))
        adc = RoundedRectangle(width=1.55, height=3.75, corner_radius=0.12, fill_color=PANEL_2,
                               fill_opacity=1, stroke_color=CYAN, stroke_width=1.6).move_to(stage.get_center() + RIGHT * 0.35)
        adc_t = VGroup(self.label("nRF52840", 13, MUTED, BOLD, MONO), self.label("SAADC", 25, CYAN, BOLD, MONO),
                       self.label("12 BIT", 13, YELLOW, BOLD, MONO), self.label("3 µs ACQ", 13, YELLOW, BOLD, MONO))
        adc_t.arrange(DOWN, buff=0.17).move_to(adc)
        values = VGroup()
        for i, (raw, color) in enumerate(zip((2029, 1053, 1503), colors)):
            box = RoundedRectangle(width=1.45, height=0.65, corner_radius=0.08, fill_color=PANEL,
                                   fill_opacity=1, stroke_color=color)
            txt = self.label(f"{raw:04d}", 18, color, BOLD, MONO).move_to(box)
            values.add(VGroup(box, txt))
        values.arrange(DOWN, buff=0.54).move_to(stage.get_center() + RIGHT * 2.25)
        mv_labels = VGroup(*[self.label(f"{v} mV", 13, INK, BOLD, MONO).next_to(values[i], DOWN, buff=0.08)
                             for i, v in enumerate((1784, 926, 1321))])
        arrows = VGroup(*[Arrow(inputs[i].get_right(), adc.get_left() + UP * (1.25 - i * 1.25), buff=0.05,
                                     color=colors[i], stroke_width=2.2) for i in range(3)],
                        *[Arrow(adc.get_right() + UP * (1.25 - i * 1.25), values[i].get_left(), buff=0.06,
                                color=colors[i], stroke_width=2.2) for i in range(3)])
        visual = VGroup(stage, inputs, adc, adc_t, values, mv_labels, arrows)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(VGroup(stage, inputs, adc, adc_t)), run_time=1)
        self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.08), run_time=1)
        self.play(LaggedStart(*[FadeIn(v, shift=RIGHT * 0.15) for v in values], lag_ratio=0.15), run_time=0.8)
        self.play(FadeIn(mv_labels), *[Flash(v[0], color=colors[i], flash_radius=0.55) for i, v in enumerate(values)], run_time=0.8)
        self.wait(0.5); self.wipe(header, code, visual)

    def scan_scene(self):
        header = self.top_title(4, "8 × 3 = 24", "kscan_adc_mux_read()")
        code = self.code_panel("kscan_adc_mux_read()", [
            "for (order = 0; order < 8; order++) {",
            "    col = gray_order[order];",
            "    set_address(col);",
            "    read_channels(samples_mv);",
            "    idx = row * 8 + col;",
            "    voltages_mv[idx] = sample_mv;",
            "}",
        ], highlights=(1, 4, 5))
        stage = self.stage(); self.split_layout(code, stage)
        matrix = VGroup(); cells = {}
        start_x = stage.get_left()[0] + 0.9; start_y = stage.get_top()[1] - 1.15
        for r in range(3):
            row_label = self.label(f"U{26+r}", 13, (CYAN, MAGENTA, GREEN)[r], BOLD, MONO)
            row_label.move_to([stage.get_left()[0] + 0.38, start_y - r * 0.72, 0]); matrix.add(row_label)
            for c in range(8):
                sq = RoundedRectangle(width=0.55, height=0.5, corner_radius=0.05, fill_color=PANEL,
                                      fill_opacity=1, stroke_color=GRID)
                sq.move_to([start_x + c * 0.63, start_y - r * 0.72, 0])
                txt = self.label("—", 11, MUTED, NORMAL, MONO).move_to(sq)
                group = VGroup(sq, txt); matrix.add(group); cells[(r, c)] = group
        col_labs = VGroup(*[self.label(f"Y{c}", 10, MUTED, BOLD, MONO).move_to([start_x + c * 0.63, start_y + 0.42, 0]) for c in range(8)])
        strip = VGroup()
        strip_cells = []
        for i in range(24):
            color = (CYAN, MAGENTA, GREEN)[i // 8]
            sq = Rectangle(width=0.215, height=0.42, fill_color=color, fill_opacity=0.13, stroke_color=color, stroke_width=0.7)
            strip.add(sq); strip_cells.append(sq)
        strip.arrange(RIGHT, buff=0.025).move_to(stage.get_bottom() + UP * 0.9)
        order_label = self.label("SCAN ORDER", 11, MUTED, BOLD, MONO).next_to(strip, UP, buff=0.24).align_to(strip, LEFT)
        metrics = VGroup(self.label("1216 SCANS/S", 14, YELLOW, BOLD, MONO),
                         self.label("0.822 ms / SCAN", 11, MUTED, BOLD, MONO)).arrange(DOWN, buff=0.06)
        metrics.move_to(stage.get_bottom() + UP * 0.38 + RIGHT * 2.02)
        visual = VGroup(stage, matrix, col_labs, strip, order_label, metrics)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(VGroup(stage, matrix, col_labs, strip, order_label)), run_time=1)
        gray = [0, 1, 3, 2, 6, 7, 5, 4]
        vals = [[1760, 1690, 1810, 1430, 1715, 1650, 1790, 1740],
                [1650, 920, 1720, 1580, 1800, 1520, 1690, 1750],
                [1710, 1660, 1740, 1680, 1770, 1590, 1730, 820]]
        for col in gray:
            anims = []
            for r in range(3):
                cell = cells[(r, col)]
                new = self.label(str(vals[r][col]), 10, (CYAN, MAGENTA, GREEN)[r], BOLD, MONO).move_to(cell[1])
                anims.extend([cell[0].animate.set_fill((CYAN, MAGENTA, GREEN)[r], opacity=0.18)
                              .set_stroke((CYAN, MAGENTA, GREEN)[r]), Transform(cell[1], new),
                              Flash(cell, color=YELLOW, flash_radius=0.34, line_length=0.1)])
            self.play(*anims, run_time=0.27)
        self.play(LaggedStart(*[Indicate(s, color=YELLOW, scale_factor=1.18) for s in strip_cells], lag_ratio=0.025),
                  FadeIn(metrics), run_time=1.2)
        self.wait(0.45); self.wipe(header, code, visual)

    def packet_scene(self):
        header = self.top_title(5, "24 VALUES → 62 BYTES", "hall_stream_enqueue() + crc16()")
        code = self.code_panel("hall_stream_enqueue()", [
            "frame.magic = {'M', 'K'};",
            "frame.version = 3;",
            "frame.sequence = sequence++;",
            "frame.timestamp_us = timestamp();",
            "frame.samples_mv[i] = voltages_mv[i];",
            "frame.crc = crc16(&frame, 60);",
            "k_msgq_put(queue, &frame, K_NO_WAIT);",
        ], highlights=(0, 4, 5, 6))
        stage = self.stage(); self.split_layout(code, stage)
        specs = [("MK", 2, YELLOW), ("META", 4, PURPLE), ("SEQ", 2, ORANGE), ("TIME", 4, GREEN),
                 ("24 × mV", 48, CYAN), ("CRC", 2, MAGENTA)]
        widths = (0.48, 0.62, 0.48, 0.62, 3.55, 0.48)
        fields = VGroup()
        cursor = stage.get_left()[0] + 0.25
        for (name, nbytes, color), width in zip(specs, widths):
            rect = Rectangle(width=width, height=1.02, fill_color=color, fill_opacity=0.18,
                             stroke_color=color, stroke_width=1.2)
            rect.move_to([cursor + width / 2, stage.get_center()[1] + 0.95, 0])
            cursor += width
            text = self.label(name, 9 if width < 0.7 else 12, color, BOLD, MONO,
                              max_width=width - 0.08, max_height=0.38).move_to(rect)
            byte = self.label(f"{nbytes}B", 8, MUTED, BOLD, MONO, max_width=width).next_to(rect, DOWN, buff=0.08)
            fields.add(VGroup(rect, text, byte))
        total = self.label("FIXED 62-BYTE FRAME", 13, INK, BOLD, MONO, max_width=5.2)
        total.move_to(stage.get_center() + UP * 2.10)
        queue = VGroup()
        for i in range(4):
            q = RoundedRectangle(width=1.05, height=0.72, corner_radius=0.08, fill_color=PANEL,
                                 fill_opacity=1, stroke_color=GRID)
            t = self.label(f"#{104+i}", 13, CYAN, BOLD, MONO).move_to(q)
            queue.add(VGroup(q, t))
        queue.arrange(RIGHT, buff=0.17).move_to(stage.get_center() + DOWN * 1.28 + LEFT * 0.38)
        qlabel = self.label("BOUNDED QUEUE  ·  DROP OLDEST", 11, MUTED, BOLD, MONO, max_width=4.8)
        qlabel.next_to(queue, UP, buff=0.18)
        crc_beam = Line(fields[0][0].get_left(), fields[-2][0].get_right(), color=MAGENTA, stroke_width=4)
        crc_beam.next_to(fields, UP, buff=0.18)
        visual = VGroup(stage, fields, total, queue, qlabel, crc_beam)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(stage), FadeIn(total), run_time=1)
        self.play(LaggedStart(*[GrowFromEdge(f, LEFT) for f in fields], lag_ratio=0.12), run_time=1.4)
        self.play(Create(crc_beam), Flash(fields[-1], color=MAGENTA, flash_radius=0.45), run_time=0.9)
        self.play(FadeIn(qlabel), LaggedStart(*[FadeIn(q, shift=RIGHT * 0.2) for q in queue], lag_ratio=0.12), run_time=1)
        incoming = queue[-1].copy().move_to(stage.get_center() + DOWN * 1.28 + RIGHT * 2.38)
        incoming[1].become(self.label("#108", 13, YELLOW, BOLD, MONO).move_to(incoming[0]))
        self.play(FadeIn(incoming, shift=RIGHT * 0.2), queue[0].animate.set_opacity(0.15), run_time=0.6)
        target = queue[-1].get_center()
        self.play(FadeOut(queue[0], shift=LEFT * 0.5), queue.animate.shift(LEFT * 1.22),
                  incoming.animate.move_to(target), run_time=0.7)
        self.wait(0.35); self.wipe(header, code, visual, incoming)

    def usb_scene(self):
        header = self.top_title(6, "SCAN DOES NOT WAIT", "kscan_adc_mux_uart_callback()")
        code = self.code_panel("kscan_adc_mux_uart_callback()", [
            "if (!uart_irq_tx_ready(uart)) return;",
            "sent = uart_fifo_fill(uart,",
            "    bytes + tx_offset,",
            "    sizeof(frame) - tx_offset);",
            "tx_offset += sent;",
            "uart_irq_tx_disable(uart);",
        ], highlights=(1, 3, 5))
        stage = self.stage(); self.split_layout(code, stage)
        scan_track = Line(stage.get_left() + RIGHT * 0.45 + UP * 1.25, stage.get_right() + LEFT * 0.45 + UP * 1.25,
                          color=GRID, stroke_width=4)
        tx_track = Line(stage.get_left() + RIGHT * 0.45 + DOWN * 0.15, stage.get_right() + LEFT * 0.45 + DOWN * 0.15,
                        color=GRID, stroke_width=4)
        scan_label = self.label("ADC SCAN LOOP", 12, YELLOW, BOLD, MONO).next_to(scan_track, UP, buff=0.16).align_to(scan_track, LEFT)
        tx_label = self.label("CDC TX IRQ", 12, CYAN, BOLD, MONO).next_to(tx_track, UP, buff=0.16).align_to(tx_track, LEFT)
        fifo = RoundedRectangle(width=3.8, height=0.75, corner_radius=0.1, fill_color=PANEL_2, fill_opacity=1,
                                stroke_color=CYAN).move_to(stage.get_center() + DOWN * 1.45)
        fifo_t = self.label("UART FIFO → 1024 B CDC RING BUFFER", 12, CYAN, BOLD, MONO).move_to(fifo)
        dtr = VGroup(RoundedRectangle(width=1.2, height=0.48, corner_radius=0.08, fill_color=GREEN, fill_opacity=0.18,
                                     stroke_color=GREEN), self.label("DTR  ON", 12, GREEN, BOLD, MONO))
        dtr[1].move_to(dtr[0]); dtr.move_to(stage.get_bottom() + UP * 0.38 + LEFT * 2.1)
        usb = self.label("USB CDC", 15, INK, BOLD, MONO).move_to(stage.get_bottom() + UP * 0.38 + RIGHT * 2.0)
        dots1 = VGroup(*[Dot(radius=0.065, color=YELLOW) for _ in range(7)])
        dots2 = VGroup(*[Dot(radius=0.065, color=CYAN) for _ in range(5)])
        for i, d in enumerate(dots1): d.move_to(scan_track.point_from_proportion(i / 7))
        for i, d in enumerate(dots2): d.move_to(tx_track.point_from_proportion(i / 5))
        visual = VGroup(stage, scan_track, tx_track, scan_label, tx_label, fifo, fifo_t, dtr, usb, dots1, dots2)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(VGroup(stage, scan_track, tx_track, scan_label, tx_label, fifo, fifo_t, dtr, usb)), run_time=1)
        self.play(LaggedStart(*[FadeIn(d, scale=0.3) for d in dots1], lag_ratio=0.09), run_time=0.8)
        self.play(*[d.animate.shift(RIGHT * 0.65) for d in dots1], LaggedStart(*[FadeIn(d) for d in dots2], lag_ratio=0.1), run_time=0.8)
        frame = RoundedRectangle(width=0.9, height=0.42, corner_radius=0.06, fill_color=CYAN, fill_opacity=0.25,
                                 stroke_color=CYAN).move_to(tx_track.get_right())
        ft = self.label("62 B", 12, CYAN, BOLD, MONO).move_to(frame)
        packet = VGroup(frame, ft)
        self.play(FadeOut(dots2), FadeIn(packet, scale=0.7), fifo.animate.set_fill(CYAN, opacity=0.2), run_time=0.8)
        self.play(packet.animate.move_to(fifo), Flash(fifo, color=CYAN, flash_radius=1.8),
                  Indicate(usb, color=YELLOW), run_time=0.7)
        self.wait(0.35); self.wipe(header, code, visual, packet)

    def decode_scene(self):
        header = self.top_title(7, "FIND · VERIFY · UNPACK", "decode_frames()")
        code = self.code_panel("decode_frames()", [
            "start = buffer.find(b\"MK\")",
            "if len(buffer) < 62: break",
            "if crc16(raw[:-2]) != crc:",
            "    del buffer[0]; continue",
            "fields = FRAME.unpack(raw)",
            "values = tail[:24]",
        ], highlights=(0, 2, 4, 5))
        stage = self.stage(); self.split_layout(code, stage)
        raw = ["7F", "13", "M", "K", "03", "01", "03", "18", "68", "00", "…", "C4", "2A"]
        bytes_g = VGroup()
        for token in raw:
            rect = RoundedRectangle(width=0.42, height=0.54, corner_radius=0.04, fill_color=PANEL,
                                    fill_opacity=1, stroke_color=GRID)
            txt = self.label(token, 10, MUTED, BOLD, MONO).move_to(rect)
            bytes_g.add(VGroup(rect, txt))
        bytes_g.arrange(RIGHT, buff=0.055).move_to(stage.get_center() + UP * 1.65)
        viewfinder = SurroundingRectangle(VGroup(bytes_g[2], bytes_g[3]), color=YELLOW, buff=0.06, stroke_width=2)
        steps = VGroup()
        for name, color in (("1  FIND  MK", YELLOW), ("2  CHECK  CRC", MAGENTA), ("3  UNPACK  <...", CYAN)):
            b = RoundedRectangle(width=4.6, height=0.62, corner_radius=0.08, fill_color=PANEL_2,
                                 fill_opacity=1, stroke_color=color, stroke_width=1.1)
            t = self.label(name, 15, color, BOLD, MONO).move_to(b)
            steps.add(VGroup(b, t))
        steps.arrange(DOWN, buff=0.22).move_to(stage.get_center() + DOWN * 0.15)
        channels = VGroup()
        for i in range(24):
            color = (CYAN, MAGENTA, GREEN)[i // 8]
            bar = Rectangle(width=0.18, height=0.25 + 0.5 * (0.5 + 0.5 * math.sin(i * 1.7)),
                            fill_color=color, fill_opacity=0.65, stroke_width=0)
            channels.add(bar)
        channels.arrange(RIGHT, buff=0.045, aligned_edge=DOWN).move_to(stage.get_bottom() + UP * 0.62)
        visual = VGroup(stage, bytes_g, viewfinder, steps, channels)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(stage), LaggedStart(*[FadeIn(b, shift=RIGHT * 0.08) for b in bytes_g], lag_ratio=0.05), run_time=1.2)
        self.play(Create(viewfinder), bytes_g[2][1].animate.set_color(YELLOW), bytes_g[3][1].animate.set_color(YELLOW), run_time=0.6)
        self.play(FadeIn(steps[0], shift=UP * 0.12), run_time=0.4)
        self.play(FadeIn(steps[1], shift=UP * 0.12), Flash(steps[1], color=GREEN, flash_radius=1.4), run_time=0.6)
        self.play(FadeIn(steps[2], shift=UP * 0.12), run_time=0.45)
        self.play(LaggedStart(*[GrowFromEdge(ch, DOWN) for ch in channels], lag_ratio=0.025), run_time=1.1)
        self.wait(0.45); self.wipe(header, code, visual)

    def plot_scene(self):
        header = self.top_title(8, "MILLIVOLTS → LIVE CURVES", "SerialReader.run() + redraw()")
        code = self.code_panel("ScopeWindow.redraw()", [
            "chunk = device.read(512)",
            "pending.extend(decode_frames(buffer))",
            "points = history[-window:]",
            "if len(points) > 1000: downsample()",
            "curve.setData(x, data[:, ch] / 1000.0)",
            "timer.start(40)  # 25 FPS",
        ], highlights=(0, 1, 4, 5))
        stage = self.stage(); self.split_layout(code, stage)
        graph = RoundedRectangle(width=5.75, height=3.25, corner_radius=0.08, fill_color="#061018",
                                 fill_opacity=1, stroke_color=GRID).move_to(stage.get_center() + UP * 0.55)
        grid = VGroup()
        for i in range(1, 10):
            x = interpolate(graph.get_left()[0], graph.get_right()[0], i / 10)
            grid.add(Line([x, graph.get_bottom()[1], 0], [x, graph.get_top()[1], 0], color=GRID, stroke_width=0.6))
        for i in range(1, 6):
            y = interpolate(graph.get_bottom()[1], graph.get_top()[1], i / 6)
            grid.add(Line([graph.get_left()[0], y, 0], [graph.get_right()[0], y, 0], color=GRID, stroke_width=0.6))
        curves = VGroup()
        x0, x1 = graph.get_left()[0] + 0.12, graph.get_right()[0] - 0.12
        colors = (CYAN, MAGENTA, GREEN, YELLOW, ORANGE, PURPLE)
        for i in range(12):
            baseline = graph.get_bottom()[1] + 0.35 + (i % 6) * 0.49
            points = []
            for u in np.linspace(0, 1, 150):
                dip = -0.78 * math.exp(-((u - 0.66) / 0.08) ** 2) if i == 2 else 0
                y = baseline + 0.055 * math.sin(u * 24 + i * 0.7) + dip
                points.append([interpolate(x0, x1, u), y, 0])
            curve = VMobject(color=colors[i % len(colors)], stroke_width=1.45, stroke_opacity=0.8)
            curve.set_points_smoothly(points); curves.add(curve)
        metrics = VGroup(
            self.label("SCAN 1216 Hz", 11, YELLOW, BOLD, MONO),
            self.label("RX 1171 fps", 11, CYAN, BOLD, MONO),
            self.label("JITTER 0.040 ms", 11, GREEN, BOLD, MONO),
            self.label("USB 72.9 kB/s", 11, MAGENTA, BOLD, MONO),
        ).arrange(RIGHT, buff=0.24).move_to(stage.get_bottom() + UP * 0.32)
        pipeline = VGroup(*[VGroup(RoundedRectangle(width=1.2, height=0.44, corner_radius=0.06, fill_color=PANEL,
                                                   fill_opacity=1, stroke_color=c),
                                      self.label(t, 10, c, BOLD, MONO))
                            for t, c in (("SERIAL", YELLOW), ("QUEUE 64", MAGENTA), ("GUI 25 FPS", CYAN))])
        for g in pipeline: g[1].move_to(g[0])
        pipeline.arrange(RIGHT, buff=0.25).move_to(stage.get_top() + DOWN * 0.36)
        pipe_arrows = VGroup(*[Arrow(pipeline[i].get_right(), pipeline[i+1].get_left(), buff=0.04,
                                           color=MUTED, stroke_width=1.6) for i in range(2)])
        visual = VGroup(stage, graph, grid, curves, metrics, pipeline, pipe_arrows)
        self.add(header)
        self.play(FadeIn(code, shift=RIGHT * 0.15), FadeIn(VGroup(stage, graph, grid, pipeline, pipe_arrows)), run_time=1)
        self.play(LaggedStart(*[Create(curve) for curve in curves], lag_ratio=0.08), run_time=2.4)
        self.play(FadeIn(metrics, shift=UP * 0.12), Circumscribe(curves[2], color=YELLOW), run_time=0.9)
        self.wait(0.6); self.wipe(header, code, visual)

    def final_scene(self):
        names = ["MAGNET", "HALL", "4051 × 3", "SAADC", "24 × mV", "62 B", "USB CDC", "PYTHON", "PLOT"]
        colors = [MAGENTA, MAGENTA, YELLOW, GREEN, CYAN, PURPLE, CYAN, ORANGE, YELLOW]
        nodes = VGroup()
        for name, color in zip(names, colors):
            box = RoundedRectangle(width=1.25, height=0.68, corner_radius=0.1, fill_color=PANEL_2,
                                   fill_opacity=1, stroke_color=color, stroke_width=1.25)
            txt = self.label(name, 11, color, BOLD, MONO).move_to(box)
            nodes.add(VGroup(box, txt))
        nodes.arrange(RIGHT, buff=0.17).scale(0.86).move_to(DOWN * 0.25)
        arrows = VGroup(*[Arrow(nodes[i].get_right(), nodes[i+1].get_left(), buff=0.03, color=MUTED,
                                      stroke_width=1.5, max_tip_length_to_length_ratio=0.2) for i in range(len(nodes)-1)])
        kicker = self.label("THE COMPLETE SIGNAL PIPELINE", 15, YELLOW, BOLD, MONO).move_to(UP * 2.25)
        title = self.label("ONE PRESS. 24 CHANNELS.", 43, INK, BOLD, max_width=11.5).move_to(UP * 1.45)
        rate = self.label("1216 SCANS / SECOND", 34, CYAN, BOLD, MONO).next_to(title, DOWN, buff=0.2)
        footer = self.label("MEGKNOB  /  ZMK  /  REAL-TIME HALL TELEMETRY", 13, MUTED, BOLD, MONO).to_edge(DOWN, buff=0.42)
        dot = Dot(nodes[0].get_center(), radius=0.095, color=YELLOW).set_z_index(5)
        self.play(FadeIn(kicker), Write(title), Write(rate), run_time=1.3)
        self.play(LaggedStart(*[FadeIn(n, shift=UP * 0.1) for n in nodes], lag_ratio=0.06), Create(arrows), run_time=1.2)
        self.add(dot)
        for node in nodes[1:]:
            self.play(dot.animate.move_to(node.get_center()), node[0].animate.set_fill(node[0].get_stroke_color(), opacity=0.18), run_time=0.18)
        self.play(FadeIn(footer), Flash(dot, color=YELLOW, flash_radius=0.55), run_time=0.6)
        self.wait(1.5)
        self.play(FadeOut(VGroup(kicker, title, rate, nodes, arrows, dot, footer)), run_time=1)
