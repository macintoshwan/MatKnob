"""A concise product film for the MegKnob magnetic keyboard."""

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
PURPLE = "#9D8CFF"
RED = "#FF5D73"
MONO = "Menlo"
SANS = "Arial"


class MegKnobProduct(Scene):
    def construct(self):
        self.camera.background_color = BG
        self.add(self.background_grid())
        keyboard = self.keyboard()
        self.opening(keyboard)
        self.magnetic_keys(keyboard)
        self.knob_and_rgb(keyboard)
        self.controller(keyboard)
        self.dual_transport(keyboard)
        self.telemetry(keyboard)
        self.live_tuning()
        self.closing(keyboard)

    def text(self, value, size=28, color=INK, weight=NORMAL, font=SANS, max_width=None):
        mob = Text(value, font=font, font_size=size, color=color, weight=weight)
        if max_width is not None and mob.width > max_width:
            mob.scale_to_fit_width(max_width)
        return mob

    def background_grid(self):
        lines = VGroup()
        for x in np.arange(-7.5, 7.6, 0.5):
            lines.add(Line([x, -4, 0], [x, 4, 0], color=GRID, stroke_width=0.45, stroke_opacity=0.22))
        for y in np.arange(-4, 4.1, 0.5):
            lines.add(Line([-7.5, y, 0], [7.5, y, 0], color=GRID, stroke_width=0.45, stroke_opacity=0.22))
        return lines

    def pill(self, value, color=CYAN):
        label = self.text(value, 12, color, BOLD, MONO)
        box = RoundedRectangle(width=label.width + 0.42, height=0.38, corner_radius=0.16,
                               fill_color=color, fill_opacity=0.09, stroke_color=color, stroke_width=1)
        label.move_to(box)
        return VGroup(box, label)

    def title(self, kicker, heading, detail):
        a = self.text(kicker, 14, YELLOW, BOLD, MONO)
        b = self.text(heading, 39, INK, BOLD, max_width=12.5)
        c = self.text(detail, 15, MUTED, BOLD, MONO, max_width=12.2)
        group = VGroup(a, b, c).arrange(DOWN, buff=0.13)
        group.to_edge(UP, buff=0.34)
        return group

    def keyboard(self):
        board = RoundedRectangle(width=7.4, height=4.05, corner_radius=0.34,
                                 fill_color=PANEL, fill_opacity=1, stroke_color=CYAN,
                                 stroke_width=1.6)
        inner = RoundedRectangle(width=7.08, height=3.72, corner_radius=0.25,
                                 stroke_color=GRID, stroke_width=1.1)
        keys = VGroup()
        labels = ["TAB", "Q", "W", "E", "R", "FN", "A", "S", "D", "F",
                  "SHIFT", "Z", "X", "C", "BSP", "CTRL", "WIN", "ALT", "SPACE"]
        positions = []
        for row, count in enumerate((5, 5, 4, 5)):
            offset = 0.0 if row != 2 else -0.38
            for col in range(count):
                positions.append((-2.35 + col * 1.02 + offset, 1.20 - row * 0.88))
        for i, ((x, y), value) in enumerate(zip(positions, labels)):
            width = 0.91 if i != 18 else 1.35
            key = RoundedRectangle(width=width, height=0.72, corner_radius=0.11,
                                   fill_color=PANEL_2, fill_opacity=1, stroke_color=GRID, stroke_width=1.1)
            key.move_to([x, y, 0])
            label = self.text(value, 10 if len(value) < 5 else 8, INK, BOLD, MONO).move_to(key)
            keys.add(VGroup(key, label))
        knob_rings = VGroup(
            Circle(radius=0.70, fill_color="#09151E", fill_opacity=1, stroke_color=PURPLE, stroke_width=2.2),
            Circle(radius=0.49, fill_color=PANEL_2, fill_opacity=1, stroke_color=GRID, stroke_width=1.2),
            Line([0, 0.20, 0], [0, 0.49, 0], color=YELLOW, stroke_width=3),
        ).move_to([2.65, 0.78, 0])
        usb = VGroup(
            RoundedRectangle(width=0.78, height=0.30, corner_radius=0.06,
                             fill_color=BG, fill_opacity=1, stroke_color=MUTED),
            self.text("USB-C", 8, MUTED, BOLD, MONO),
        )
        usb[1].move_to(usb[0]); usb.move_to(board.get_top() + DOWN * 0.05 + RIGHT * 1.35)
        rgb = board.copy().set_fill(opacity=0).set_stroke(MAGENTA, width=12, opacity=0.16)
        product = VGroup(rgb, board, inner, keys, knob_rings, usb)
        product.keys = keys
        product.knob = knob_rings
        product.rgb = rgb
        return product

    def wipe(self, *mobs, run_time=0.55):
        self.play(*[FadeOut(m, shift=LEFT * 0.15) for m in mobs], run_time=run_time)

    def opening(self, keyboard):
        product = keyboard.copy().scale(0.87).move_to(DOWN * 0.55)
        kicker = self.text("MEGKNOB / ZMK", 15, YELLOW, BOLD, MONO).move_to(UP * 3.02)
        title = self.text("MAGNETIC CONTROL, REIMAGINED.", 45, INK, BOLD, max_width=12.2).move_to(UP * 2.32)
        subtitle = self.text("19 HALL KEYS  ·  ROTARY CONTROL  ·  BUILT TO TUNE", 15, MUTED, BOLD, MONO)
        subtitle.move_to(UP * 1.75)
        self.play(FadeIn(kicker, shift=UP * 0.15), Write(title), FadeIn(subtitle), run_time=1.4)
        self.play(FadeIn(product, shift=UP * 0.22), product.rgb.animate.set_stroke(CYAN, opacity=0.28), run_time=1.2)
        self.play(LaggedStart(*[Indicate(key[0], color=CYAN, scale_factor=1.04) for key in product.keys],
                              lag_ratio=0.035), run_time=1.5)
        self.wait(0.45)
        self.wipe(kicker, title, subtitle, product)

    def magnetic_keys(self, keyboard):
        header = self.title("01 / MAGNETIC INPUT", "19 KEYS. ANALOG AT THE CORE.",
                            "EACH PRESS BECOMES A VOLTAGE — THEN A PRECISE HID EVENT")
        product = keyboard.copy().scale(0.55).move_to(LEFT * 3.25 + DOWN * 0.52)
        cut = RoundedRectangle(width=5.2, height=4.25, corner_radius=0.24, fill_color=PANEL,
                               fill_opacity=0.96, stroke_color=GRID).move_to(RIGHT * 3.2 + DOWN * 0.5)
        cap = RoundedRectangle(width=2.35, height=0.66, corner_radius=0.11, fill_color=PANEL_2,
                               fill_opacity=1, stroke_color=CYAN).move_to(cut.get_center() + UP * 1.15)
        stem = Rectangle(width=0.64, height=1.05, fill_color=PANEL_2, fill_opacity=1,
                         stroke_color=CYAN).next_to(cap, DOWN, buff=0)
        magnet = RoundedRectangle(width=0.48, height=0.35, corner_radius=0.05, fill_color=MAGENTA,
                                  fill_opacity=0.85, stroke_color=MAGENTA).next_to(stem, DOWN, buff=0)
        hall = RoundedRectangle(width=1.7, height=0.42, corner_radius=0.07, fill_color=CYAN,
                                fill_opacity=0.16, stroke_color=CYAN).move_to(cut.get_center() + DOWN * 1.45)
        hall_label = self.text("LINEAR HALL SENSOR", 11, CYAN, BOLD, MONO).move_to(hall)
        voltage = self.text("1880 mV", 22, YELLOW, BOLD, MONO).next_to(hall, RIGHT, buff=0.28)
        arrow = Arrow(magnet.get_bottom(), hall.get_top(), buff=0.1, color=MAGENTA, stroke_width=2)
        visual = VGroup(cut, cap, stem, magnet, hall, hall_label, voltage, arrow)
        self.play(FadeIn(header), FadeIn(product, shift=RIGHT * 0.15), FadeIn(visual, shift=LEFT * 0.15), run_time=1.0)
        for idx in (1, 7, 12, 18):
            self.play(product.keys[idx][0].animate.set_fill(CYAN, opacity=0.3).shift(DOWN * 0.06), run_time=0.18)
            self.play(product.keys[idx][0].animate.set_fill(PANEL_2, opacity=1).shift(UP * 0.06), run_time=0.16)
        self.play(VGroup(cap, stem, magnet).animate.shift(DOWN * 0.55),
                  Transform(voltage, self.text("720 mV", 22, GREEN, BOLD, MONO).move_to(voltage)), run_time=0.9)
        state = self.pill("PRESSED", GREEN).next_to(hall, DOWN, buff=0.36)
        self.play(FadeIn(state, scale=0.85), Flash(hall, color=GREEN, flash_radius=0.8), run_time=0.65)
        self.wait(0.4); self.wipe(header, product, visual, state)

    def knob_and_rgb(self, keyboard):
        header = self.title("02 / TACTILE CONTROL", "TURN. PRESS. GLOW.",
                            "A TRUE QUADRATURE ENCODER WITH A FULL RGB STATUS LANGUAGE")
        product = keyboard.copy().scale(0.82).move_to(DOWN * 0.54)
        actions = VGroup(self.pill("VOLUME", CYAN), self.pill("MUTE", YELLOW), self.pill("RGB", MAGENTA))
        actions.arrange(RIGHT, buff=0.35).move_to(DOWN * 3.2)
        self.play(FadeIn(header), FadeIn(product, shift=UP * 0.16), run_time=1)
        self.play(Rotate(product.knob, angle=PI * 1.2), Circumscribe(actions[0], color=CYAN), run_time=1.2)
        self.play(product.knob.animate.scale(0.91), run_time=0.18)
        self.play(product.knob.animate.scale(1 / 0.91), Circumscribe(actions[1], color=YELLOW), run_time=0.28)
        self.play(FadeIn(actions), product.rgb.animate.set_stroke(MAGENTA, opacity=0.55), run_time=0.5)
        for color in (PURPLE, CYAN, GREEN, MAGENTA):
            self.play(product.rgb.animate.set_stroke(color, opacity=0.48), run_time=0.28)
        self.wait(0.35); self.wipe(header, product, actions)

    def controller(self, keyboard):
        header = self.title("03 / THE ENGINE", "ONE NRF52840. EVERY PATH.",
                            "SCAN · FILTER · USB · BLUETOOTH · RGB · CONFIGURATION")
        product = keyboard.copy().scale(0.52).set_opacity(0.22).move_to(DOWN * 0.48)
        chip = RoundedRectangle(width=3.2, height=2.15, corner_radius=0.16, fill_color=PANEL_2,
                                fill_opacity=1, stroke_color=CYAN, stroke_width=2).move_to(DOWN * 0.4)
        chip_name = self.text("nRF52840", 28, INK, BOLD, MONO).move_to(chip)
        pins = VGroup()
        for y in np.linspace(-1.0, 1.0, 7):
            pins.add(Line(chip.get_left() + [0, y, 0], chip.get_left() + LEFT * 0.42 + [0, y, 0], color=GRID))
            pins.add(Line(chip.get_right() + [0, y, 0], chip.get_right() + RIGHT * 0.42 + [0, y, 0], color=GRID))
        labels = VGroup(*[self.pill(t, c) for t, c in (("24-CH SCAN", YELLOW), ("USB", CYAN),
                                                        ("BLE", PURPLE), ("RGB", MAGENTA), ("FLASH", GREEN))])
        labels.arrange(RIGHT, buff=0.24).move_to(DOWN * 2.45)
        beams = VGroup(*[Line(label.get_top(), chip.get_bottom(), color=label[0].get_stroke_color(),
                                  stroke_width=1.5, stroke_opacity=0.45) for label in labels])
        self.play(FadeIn(header), FadeIn(product), GrowFromCenter(chip), Write(chip_name), Create(pins), run_time=1.2)
        self.play(LaggedStart(*[FadeIn(label, shift=UP * 0.12) for label in labels], lag_ratio=0.1),
                  Create(beams), run_time=1.1)
        self.play(Flash(chip, color=CYAN, flash_radius=1.8), run_time=0.8)
        self.wait(0.4); self.wipe(header, product, chip, chip_name, pins, labels, beams)

    def host(self, name, color):
        screen = RoundedRectangle(width=2.3, height=1.55, corner_radius=0.15, fill_color=PANEL,
                                  fill_opacity=1, stroke_color=color)
        base = Line(screen.get_bottom() + LEFT * 0.55 + DOWN * 0.23,
                    screen.get_bottom() + RIGHT * 0.55 + DOWN * 0.23, color=color, stroke_width=3)
        label = self.text(name, 13, color, BOLD, MONO).move_to(screen)
        return VGroup(screen, base, label)

    def dual_transport(self, keyboard):
        header = self.title("04 / DUAL TRANSPORT", "USB HID + BLE HID", "BOTH ENABLED · SELECT THE OUTPUT YOU NEED")
        product = keyboard.copy().scale(0.45).move_to(DOWN * 0.6)
        wired = self.host("USB HOST", CYAN).move_to(LEFT * 4.8 + DOWN * 0.6)
        wireless = self.host("BLE HOST", PURPLE).move_to(RIGHT * 4.8 + DOWN * 0.6)
        cable = CubicBezier(product.get_left(), LEFT * 1.0 + DOWN * 0.4, RIGHT * 1.0 + DOWN * 0.4,
                            wired.get_right(), color=CYAN, stroke_width=3)
        arcs = VGroup(*[Arc(radius=r, start_angle=-PI / 3, angle=2 * PI / 3, color=PURPLE,
                            stroke_width=2) for r in (0.55, 0.82, 1.08)])
        arcs.rotate(PI / 2).move_to(RIGHT * 2.4 + DOWN * 0.55)
        ready = VGroup(self.pill("WIRED READY", GREEN), self.pill("WIRELESS READY", GREEN))
        ready[0].next_to(wired, DOWN, buff=0.38); ready[1].next_to(wireless, DOWN, buff=0.38)
        dot1 = Dot(product.get_left(), radius=0.08, color=CYAN)
        dot2 = Dot(product.get_right(), radius=0.08, color=PURPLE)
        self.play(FadeIn(header), FadeIn(product), FadeIn(wired), FadeIn(wireless), Create(cable), Create(arcs), run_time=1.2)
        self.add(dot1, dot2)
        self.play(MoveAlongPath(dot1, cable), dot2.animate.move_to(wireless.get_left()), run_time=1.2)
        self.play(FadeIn(ready, shift=UP * 0.12), Flash(dot1, color=GREEN), Flash(dot2, color=GREEN), run_time=0.7)
        self.wait(0.45); self.wipe(header, product, wired, wireless, cable, arcs, ready, dot1, dot2)

    def telemetry(self, keyboard):
        header = self.title("05 / COMPOSITE USB", "HID FOR CONTROL. CDC FOR INSIGHT.",
                            "THE KEYBOARD KEEPS WORKING WHILE 24 CHANNELS STREAM LIVE")
        product = keyboard.copy().scale(0.38).move_to(LEFT * 4.8 + DOWN * 0.5)
        dashboard = RoundedRectangle(width=7.2, height=4.6, corner_radius=0.22, fill_color=PANEL,
                                     fill_opacity=0.96, stroke_color=GRID).move_to(RIGHT * 2.5 + DOWN * 0.45)
        tracks = VGroup(
            Arrow(product.get_right(), dashboard.get_left() + UP * 1.05, buff=0.12, color=YELLOW, stroke_width=2.5),
            Arrow(product.get_right(), dashboard.get_left() + DOWN * 0.15, buff=0.12, color=CYAN, stroke_width=2.5),
        )
        track_labels = VGroup(self.pill("HID", YELLOW), self.pill("CDC", CYAN))
        track_labels[0].next_to(tracks[0], UP, buff=0.05); track_labels[1].next_to(tracks[1], DOWN, buff=0.05)
        matrix = VGroup()
        for row in range(3):
            for col in range(8):
                cell = RoundedRectangle(width=0.43, height=0.30, corner_radius=0.04,
                                        fill_color=PANEL_2, fill_opacity=1, stroke_color=GRID, stroke_width=0.8)
                cell.move_to(dashboard.get_left() + RIGHT * (0.75 + col * 0.50) + UP * (1.42 - row * 0.39))
                matrix.add(cell)
        plot = Rectangle(width=6.35, height=1.75, stroke_color=GRID, fill_color="#09151E", fill_opacity=1)
        plot.move_to(dashboard.get_center() + DOWN * 0.95)
        curves = VGroup()
        for i, color in enumerate((CYAN, MAGENTA, GREEN, YELLOW, PURPLE)):
            points = []
            for u in np.linspace(0, 1, 100):
                dip = -0.52 * math.exp(-((u - 0.62) / 0.075) ** 2) if i == 2 else 0
                x = plot.get_left()[0] + u * plot.width
                y = plot.get_center()[1] + (i - 2) * 0.25 + 0.035 * math.sin(u * 22 + i) + dip
                points.append([x, y, 0])
            curve = VMobject(color=color, stroke_width=1.7).set_points_smoothly(points)
            curves.add(curve)
        metric = self.text("24 CHANNELS  ·  LIVE mV  ·  CRC VERIFIED", 11, MUTED, BOLD, MONO)
        metric.move_to(dashboard.get_bottom() + UP * 0.25)
        self.play(FadeIn(header), FadeIn(product), FadeIn(dashboard), Create(tracks), FadeIn(track_labels), run_time=1.1)
        self.play(LaggedStart(*[FadeIn(cell) for cell in matrix], lag_ratio=0.025), run_time=0.9)
        self.play(LaggedStart(*[Create(curve) for curve in curves], lag_ratio=0.12), FadeIn(metric), run_time=1.8)
        self.play(Circumscribe(matrix, color=YELLOW), Circumscribe(curves[2], color=GREEN), run_time=0.8)
        self.wait(0.4); self.wipe(header, product, dashboard, tracks, track_labels, matrix, plot, curves, metric)

    def live_tuning(self):
        header = self.title("06 / RUNTIME CONFIG", "TUNE IT LIVE. SAVE IT ONCE.",
                            "CHANGE THRESHOLDS OVER CDC — NO REFLASH REQUIRED")
        graph = RoundedRectangle(width=6.35, height=4.5, corner_radius=0.22, fill_color=PANEL,
                                 fill_opacity=0.96, stroke_color=GRID).move_to(LEFT * 3.25 + DOWN * 0.45)
        config_panel = RoundedRectangle(width=5.3, height=4.5, corner_radius=0.22, fill_color=PANEL,
                                        fill_opacity=0.96, stroke_color=GRID).move_to(RIGHT * 3.45 + DOWN * 0.45)
        curve_points = []
        for u in np.linspace(0, 1, 130):
            x = graph.get_left()[0] + 0.35 + u * (graph.width - 0.7)
            y = graph.get_center()[1] + 0.65 - 2.0 * math.exp(-((u - 0.56) / 0.14) ** 2)
            curve_points.append([x, y, 0])
        curve = VMobject(color=CYAN, stroke_width=2.6).set_points_smoothly(curve_points)
        press_y = graph.get_center()[1] + 0.05
        release_y = graph.get_center()[1] + 0.60
        press = DashedLine([graph.get_left()[0] + 0.25, press_y, 0], [graph.get_right()[0] - 0.25, press_y, 0], color=YELLOW)
        release = DashedLine([graph.get_left()[0] + 0.25, release_y, 0], [graph.get_right()[0] - 0.25, release_y, 0], color=ORANGE)
        press_label = self.text("PRESS 900 mV", 11, YELLOW, BOLD, MONO).next_to(press, UP, buff=0.05).align_to(press, LEFT)
        release_label = self.text("RELEASE 1400 mV", 11, ORANGE, BOLD, MONO).next_to(release, UP, buff=0.05).align_to(release, LEFT)
        panel_title = self.text("DEVICE CONFIG", 17, INK, BOLD, MONO).move_to(config_panel.get_top() + DOWN * 0.45)
        rows = VGroup()
        for label, value, color in (("PRESS", "900 mV", YELLOW), ("RELEASE", "1400 mV", ORANGE),
                                     ("STABLE", "3 SCANS", CYAN)):
            row = RoundedRectangle(width=4.35, height=0.64, corner_radius=0.1,
                                   fill_color=PANEL_2, fill_opacity=1, stroke_color=color, stroke_width=1)
            left = self.text(label, 12, MUTED, BOLD, MONO).move_to(row.get_left() + RIGHT * 0.55)
            right = self.text(value, 13, color, BOLD, MONO).move_to(row.get_right() + LEFT * 0.68)
            rows.add(VGroup(row, left, right))
        rows.arrange(DOWN, buff=0.22).move_to(config_panel.get_center() + UP * 0.15)
        buttons = VGroup(self.pill("APPLY NOW", GREEN), self.pill("SAVE TO FLASH", PURPLE))
        buttons.arrange(RIGHT, buff=0.24).move_to(config_panel.get_bottom() + UP * 0.53)
        command = Arrow(config_panel.get_left(), graph.get_right(), buff=0.22, color=GREEN, stroke_width=2.4)
        self.play(FadeIn(header), FadeIn(graph), FadeIn(config_panel), Create(curve), Create(press), Create(release),
                  FadeIn(press_label), FadeIn(release_label), FadeIn(panel_title), FadeIn(rows), FadeIn(buttons), run_time=1.2)
        self.play(press.animate.shift(UP * 0.38), press_label.animate.shift(UP * 0.38),
                  rows[0][2].animate.set_color(GREEN), run_time=0.9)
        self.play(Create(command), Circumscribe(buttons[0], color=GREEN), run_time=0.65)
        saved = self.pill("SAVED", GREEN).next_to(config_panel, DOWN, buff=0.24)
        self.play(Circumscribe(buttons[1], color=PURPLE), FadeIn(saved, scale=0.85), run_time=0.65)
        self.wait(0.45); self.wipe(header, graph, config_panel, curve, press, release, press_label,
                                   release_label, panel_title, rows, buttons, command, saved)

    def closing(self, keyboard):
        product = keyboard.copy().scale(0.77).move_to(DOWN * 0.25)
        kicker = self.text("MEGKNOB", 17, YELLOW, BOLD, MONO).move_to(UP * 3.20)
        title = self.text("CONTROL. OBSERVE. TUNE.", 43, INK, BOLD, max_width=11.8).move_to(UP * 2.55)
        cards = VGroup()
        for name, detail, color in (("CONTROL", "19 HALL KEYS + KNOB", CYAN),
                                    ("OBSERVE", "24-CH LIVE TELEMETRY", MAGENTA),
                                    ("TUNE", "RUNTIME CONFIG", GREEN)):
            box = RoundedRectangle(width=3.55, height=0.82, corner_radius=0.14,
                                   fill_color=PANEL_2, fill_opacity=0.98, stroke_color=color)
            a = self.text(name, 14, color, BOLD, MONO)
            b = self.text(detail, 9, MUTED, BOLD, MONO)
            VGroup(a, b).arrange(DOWN, buff=0.06).move_to(box)
            cards.add(VGroup(box, a, b))
        cards.arrange(RIGHT, buff=0.32).move_to(DOWN * 3.18)
        footer = self.text("USB HID + BLE HID  ·  USB CDC  ·  NRF52840  ·  ZMK", 12, MUTED, BOLD, MONO)
        footer.move_to(DOWN * 2.53)
        self.play(FadeIn(kicker), Write(title), FadeIn(product, shift=UP * 0.15), run_time=1.3)
        self.play(LaggedStart(*[FadeIn(card, shift=UP * 0.12) for card in cards], lag_ratio=0.18),
                  FadeIn(footer), run_time=1.0)
        self.play(product.rgb.animate.set_stroke(CYAN, opacity=0.55), Flash(product.knob, color=YELLOW, flash_radius=0.9), run_time=0.8)
        self.wait(1.4)
        self.play(FadeOut(VGroup(kicker, title, product, cards, footer)), run_time=1)
