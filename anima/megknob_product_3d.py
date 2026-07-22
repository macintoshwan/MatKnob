"""Manim pseudo-3D commercial product film for MegKnob."""

from __future__ import annotations

import math

import numpy as np
from manim import *

from megknob_3d_common import *


class MegKnobProduct3D(MegKnobThreeDScene):
    def construct(self):
        self.setup_world(phi=66, theta=-52, zoom=1.08)
        self.hero()
        self.hall_cutaway()
        self.rotary_control()
        self.exploded_core()
        self.transports()
        self.telemetry_and_tuning()
        self.final_hero()

    def hero(self):
        product = keyboard3d(show_legends=True).scale(0.88).shift(DOWN * 0.42)
        title = VGroup(txt("MEGKNOB", 50, INK, BOLD, SANS),
                       txt("MAGNETIC CONTROL, ENGINEERED TO BE SEEN.", 14, YELLOW, BOLD, MONO))
        title.arrange(DOWN, buff=0.12).to_edge(UP, buff=0.42)
        self.add_fixed_in_frame_mobjects(title)
        title.set_opacity(0)
        for light in product.rgb: light.set_opacity(0)
        self.play(FadeIn(product.base, shift=OUT * 0.12), FadeIn(product.top), title.animate.set_opacity(1), run_time=0.9)
        self.play(LaggedStart(*[FadeIn(key, shift=OUT * 0.10) for key in product.keys], lag_ratio=0.035),
                  FadeIn(product.knob), FadeIn(product.usb), run_time=1.2)
        if len(product.legends): self.play(FadeIn(product.legends), run_time=0.35)
        self.play(LaggedStart(*[light.animate.set_opacity(0.72) for light in product.rgb], lag_ratio=0.035), run_time=1.0)
        self.play(Rotate(product.knob, angle=0.48, axis=OUT), run_time=0.55)
        self.wait(0.4)
        self.play(FadeOut(product), title.animate.set_opacity(0), run_time=0.55)
        self.remove(title)

    def hall_cutaway(self):
        header = hud("Magnetic input", "19 HALL KEYS · ANALOG AT THE CORE",
                     "CONTINUOUS VOLTAGE BECOMES A PRECISE HID EVENT", 1)
        self.show_hud(header)
        cap = block3d(3.0, 2.0, 0.48, "#172A36", CYAN).move_to([0, 0, 1.35])
        stem = block3d(0.78, 0.72, 1.15, "#122532", CYAN).move_to([0, 0, 0.56])
        magnet = block3d(0.58, 0.54, 0.34, MAGENTA, WHITE).move_to([0, 0, -0.22])
        pcb = block3d(4.2, 2.4, 0.16, "#0B2A24", GREEN).move_to([0, 0, -1.18])
        hall = block3d(1.38, 0.72, 0.28, "#102733", CYAN).move_to([0, 0, -0.90])
        hall_label = txt("LINEAR HALL", 12, CYAN, BOLD, MONO).move_to(hall.get_center() + OUT * 0.19)
        self.add_fixed_orientation_mobjects(hall_label)
        field_lines = VGroup()
        for offset in np.linspace(-0.70, 0.70, 7):
            line = ParametricFunction(lambda t, o=offset: np.array([o * (1 - 0.35 * math.sin(PI * t)),
                                                                       0.25 * math.sin(TAU * t + o),
                                                                       -0.18 - 0.68 * t]),
                                      t_range=[0, 1], color=MAGENTA, stroke_width=2,
                                      stroke_opacity=0.58)
            field_lines.add(line)
        voltage = VGroup(txt("1880 mV", 25, YELLOW, BOLD, MONO), pill("RELEASED", MUTED))
        voltage.arrange(DOWN, buff=0.15).to_edge(RIGHT, buff=0.55)
        self.add_fixed_in_frame_mobjects(voltage)
        self.play(FadeIn(VGroup(cap, stem, magnet, pcb, hall)), FadeIn(hall_label), Create(field_lines),
                  FadeIn(voltage), run_time=1.0)
        moving = VGroup(cap, stem, magnet)
        pressed_voltage = VGroup(txt("720 mV", 25, GREEN, BOLD, MONO), pill("PRESSED", GREEN))
        pressed_voltage.arrange(DOWN, buff=0.15).move_to(voltage)
        self.play(moving.animate.shift(IN * 0.58),
                  Transform(voltage, pressed_voltage),
                  field_lines.animate.scale(0.76).set_color(MAGENTA), run_time=1.1,
                  rate_func=rate_functions.ease_in_out_cubic)
        pulse = glow_core(CYAN, 0.11).move_to(hall.get_center() + RIGHT * 0.8)
        wire = CubicBezier(hall.get_right(), hall.get_right() + RIGHT * 1.3,
                           RIGHT * 3.1 + DOWN * 0.8, RIGHT * 4.5 + DOWN * 0.4).set_stroke(CYAN, 3, opacity=0.6)
        self.play(Create(wire), FadeIn(pulse), run_time=0.35)
        self.play(MoveAlongPath(pulse, wire), run_time=0.8)
        self.play(FadeOut(pulse), run_time=0.15)
        self.remove(voltage)
        self.hide_hud(header)
        self.clear_stage(cap, stem, magnet, pcb, hall, hall_label, field_lines, wire)

    def rotary_control(self):
        header = hud("Tactile control", "TURN · PRESS · CHANGE LAYER",
                     "TRUE QUADRATURE ROTARY INPUT", 2)
        self.show_hud(header)
        product = keyboard3d(show_legends=True).scale(0.73).shift(LEFT * 1.05 + DOWN * 0.30)
        self.play(FadeIn(product), run_time=0.75)
        labels = VGroup(pill("VOLUME ±", CYAN), pill("PRESS · MUTE", YELLOW))
        labels.arrange(DOWN, aligned_edge=LEFT, buff=0.20).to_edge(RIGHT, buff=0.70)
        self.add_fixed_in_frame_mobjects(labels)
        self.play(FadeIn(labels), Rotate(product.knob, angle=1.3, axis=OUT), run_time=1.0)
        self.play(product.knob.animate.shift(IN * 0.09), run_time=0.18)
        self.play(product.knob.animate.shift(OUT * 0.09), Circumscribe(labels[1], color=YELLOW), run_time=0.25)
        fn = product.keys[5]
        layer_labels = VGroup(pill("NEXT / PREVIOUS", PURPLE), pill("PRESS · PLAY / PAUSE", PURPLE))
        layer_labels.arrange(DOWN, aligned_edge=LEFT, buff=0.20).move_to(labels)
        self.play(fn.animate.shift(IN * 0.10), Transform(labels, layer_labels),
                  product.rgb.animate.set_color(PURPLE), run_time=0.55)
        self.play(Rotate(product.knob, angle=-1.0, axis=OUT), run_time=0.75)
        self.play(fn.animate.shift(OUT * 0.10), run_time=0.22)
        self.remove(labels)
        self.hide_hud(header)
        self.clear_stage(product)

    def exploded_core(self):
        header = hud("Inside MegKnob", "ONE CONTROLLER · EVERY PATH",
                     "SCAN · FILTER · HID · BLE · RGB · CONFIG", 3)
        self.show_hud(header)
        product = keyboard3d(show_legends=False).scale(0.80).shift(DOWN * 0.20)
        pcb = block3d(6.8, 3.45, 0.10, "#0A2B24", GREEN).move_to(product.top.get_center() + IN * 0.10)
        chip = block3d(1.28, 1.0, 0.18, "#101820", CYAN).move_to(pcb.get_center() + OUT * 0.18)
        chip_label = txt("nRF52840", 12, CYAN, BOLD, MONO).move_to(chip.get_center() + OUT * 0.13)
        muxes = VGroup(*[block3d(0.84, 0.42, 0.15, "#111820", ROW_COLORS[i], 1)
                         .move_to(pcb.get_center() + LEFT * 2.15 + RIGHT * i * 0.98 + OUT * 0.17)
                         for i in range(3)])
        self.add_fixed_orientation_mobjects(chip_label)
        self.play(FadeIn(product), run_time=0.7)
        self.play(product.keys.animate.shift(OUT * 1.15), product.legends.animate.shift(OUT * 1.15),
                  product.top.animate.shift(OUT * 0.62), product.base.animate.shift(IN * 0.55),
                  FadeIn(pcb), FadeIn(chip), FadeIn(chip_label), FadeIn(muxes), run_time=1.35,
                  rate_func=rate_functions.ease_in_out_cubic)
        paths = VGroup()
        for i, color in enumerate((MAGENTA, YELLOW, CYAN, PURPLE, GREEN)):
            start = pcb.get_left() + RIGHT * (0.7 + i * 1.2) + OUT * 0.24
            path = CubicBezier(start, start + OUT * 0.45, chip.get_center() + LEFT * (i - 2) * 0.18 + OUT * 0.35,
                               chip.get_center() + OUT * 0.25).set_stroke(color, 3, opacity=0.62)
            paths.add(path)
        self.play(LaggedStart(*[Create(path) for path in paths], lag_ratio=0.10), run_time=0.9)
        self.play(Flash(chip, color=CYAN, flash_radius=1.0), run_time=0.55)
        self.hide_hud(header)
        self.clear_stage(product, pcb, chip, chip_label, muxes, paths)

    def host_icon(self, name, color):
        body = block3d(2.20, 0.34, 1.42, "#0C1821", color)
        stand = VGroup(block3d(0.18, 0.34, 0.55, "#0C1821", color),
                       block3d(1.15, 0.42, 0.12, "#0C1821", color)).arrange(DOWN, buff=0)
        stand.next_to(body, DOWN, buff=0)
        label = txt(name, 13, color, BOLD, MONO).move_to(body.get_center() + IN * 0.19)
        return VGroup(body, stand, label)

    def transports(self):
        header = hud("Dual transport", "USB HID + BLE HID",
                     "BOTH ENABLED · USB ALSO CARRIES CDC", 4)
        self.show_hud(header)
        product = keyboard3d(show_legends=False).scale(0.48).move_to(DOWN * 0.25)
        usb_host = self.host_icon("USB HOST", CYAN).move_to(LEFT * 4.7 + DOWN * 0.25)
        ble_host = self.host_icon("BLE HOST", PURPLE).move_to(RIGHT * 4.7 + DOWN * 0.25)
        cable_hid = CubicBezier(product.get_left(), LEFT * 2.0 + UP * 0.32,
                                usb_host.get_right() + RIGHT * 0.7 + UP * 0.30,
                                usb_host.get_right() + UP * 0.25).set_stroke(YELLOW, 3, opacity=0.62)
        cable_cdc = CubicBezier(product.get_left(), LEFT * 2.0 + DOWN * 0.32,
                                usb_host.get_right() + RIGHT * 0.7 + DOWN * 0.30,
                                usb_host.get_right() + DOWN * 0.25).set_stroke(CYAN, 3, opacity=0.72)
        wireless = VGroup(*[Arc(radius=r, start_angle=-PI / 3, angle=2 * PI / 3,
                                color=PURPLE, stroke_width=2.5) for r in (0.46, 0.72, 0.98)])
        wireless.rotate(PI / 2).move_to(RIGHT * 2.45 + DOWN * 0.18)
        labels = VGroup(pill("HID", YELLOW), pill("CDC", CYAN), pill("HID", PURPLE))
        labels[0].move_to(LEFT * 2.55 + UP * 0.55); labels[1].move_to(LEFT * 2.55 + DOWN * 0.58)
        labels[2].move_to(RIGHT * 2.55 + UP * 0.72)
        self.add_fixed_in_frame_mobjects(labels)
        self.play(FadeIn(product), FadeIn(usb_host), FadeIn(ble_host), Create(cable_hid), Create(cable_cdc),
                  Create(wireless), FadeIn(labels), run_time=1.0)
        p1 = glow_core(YELLOW, 0.08).move_to(cable_hid.get_start())
        p2 = glow_core(CYAN, 0.08).move_to(cable_cdc.get_start())
        p3 = glow_core(PURPLE, 0.08).move_to(product.get_right())
        self.add(p1, p2, p3)
        self.play(MoveAlongPath(p1, cable_hid), MoveAlongPath(p2, cable_cdc),
                  p3.animate.move_to(ble_host.get_left()), run_time=1.1)
        ready = VGroup(pill("WIRED READY", GREEN), pill("WIRELESS READY", GREEN))
        ready.arrange(RIGHT, buff=5.0).to_edge(DOWN, buff=0.30)
        self.add_fixed_in_frame_mobjects(ready)
        self.play(FadeIn(ready), Flash(p1, color=GREEN), Flash(p3, color=GREEN), run_time=0.55)
        self.wait(0.25)
        self.play(FadeOut(VGroup(labels, ready)), run_time=0.2)
        self.remove(labels, ready)
        self.hide_hud(header)
        self.clear_stage(product, usb_host, ble_host, cable_hid, cable_cdc, wireless, p1, p2, p3)

    def telemetry_and_tuning(self):
        header = hud("Observe and tune", "24 CHANNELS · LIVE CONFIGURATION",
                     "USB CDC TELEMETRY AND BIDIRECTIONAL COMMANDS", 5)
        self.show_hud(header)
        wall = buffer_wall3d().scale(0.68).move_to(LEFT * 3.4 + UP * 0.10)
        self.play(FadeIn(wall), run_time=0.6)
        values = VGroup()
        for row in range(3):
            for col in range(8):
                sample = glow_core(ROW_COLORS[row], 0.055)
                sample.move_to(wall.slots[(row, col)].get_center() + IN * 0.10)
                values.add(sample)
        self.play(LaggedStart(*[FadeIn(value, scale=0.25) for value in values], lag_ratio=0.018), run_time=0.8)
        panel = block3d(4.65, 0.22, 3.65, "#0A151D", EDGE).move_to(RIGHT * 3.3)
        rows = VGroup()
        for i, (name, value, color) in enumerate((("PRESS", "900 mV", YELLOW),
                                                  ("RELEASE", "1400 mV", ORANGE),
                                                  ("STABLE", "3 SCANS", CYAN))):
            row = VGroup(txt(name, 12, MUTED, BOLD, MONO), txt(value, 15, color, BOLD, MONO))
            row.arrange(RIGHT, buff=1.3).move_to([3.3, 0, 0.78 - i * 0.72])
            rows.add(row)
        self.add_fixed_orientation_mobjects(*rows)
        self.play(FadeIn(panel), FadeIn(rows), run_time=0.6)
        command_path = CubicBezier(panel.get_left(), RIGHT * 0.4 + DOWN * 1.5,
                                   LEFT * 1.2 + DOWN * 1.5, wall.get_right()).set_stroke(GREEN, 3, opacity=0.65)
        command = glow_core(GREEN, 0.09).move_to(command_path.get_start())
        self.play(Create(command_path), FadeIn(command), rows[0][1].animate.set_color(GREEN), run_time=0.45)
        self.play(MoveAlongPath(command, command_path), run_time=0.9)
        saved = pill("APPLIED · SAVED TO FLASH", GREEN).to_edge(DOWN, buff=0.30)
        self.add_fixed_in_frame_mobjects(saved)
        self.play(FadeIn(saved), Flash(command, color=GREEN), run_time=0.45)
        self.wait(0.3)
        self.play(FadeOut(saved), run_time=0.18); self.remove(saved)
        self.hide_hud(header)
        self.clear_stage(wall, values, panel, rows, command_path, command)

    def final_hero(self):
        product = keyboard3d(show_legends=True).scale(0.84).shift(DOWN * 0.35)
        title = VGroup(txt("MEGKNOB", 48, INK, BOLD, SANS),
                       txt("CONTROL · OBSERVE · TUNE", 20, CYAN, BOLD, MONO),
                       txt("19 HALL KEYS · USB HID / BLE HID · USB CDC TELEMETRY", 11, MUTED, BOLD, MONO))
        title.arrange(DOWN, buff=0.13).to_edge(UP, buff=0.35)
        cards = VGroup(pill("CONTROL", CYAN), pill("OBSERVE", MAGENTA), pill("TUNE", GREEN))
        cards.arrange(RIGHT, buff=0.36).to_edge(DOWN, buff=0.28)
        self.add_fixed_in_frame_mobjects(title, cards)
        title.set_opacity(0); cards.set_opacity(0)
        self.play(FadeIn(product, shift=OUT * 0.18), title.animate.set_opacity(1), run_time=1.0)
        self.play(cards.animate.set_opacity(1), LaggedStart(*[light.animate.set_color(CYAN)
                                                             for light in product.rgb], lag_ratio=0.035), run_time=0.9)
        self.play(Rotate(product.knob, angle=0.45, axis=OUT), Flash(product.knob, color=YELLOW,
                                                                   flash_radius=0.85), run_time=0.55)
        self.wait(1.2)
        self.play(FadeOut(product), title.animate.set_opacity(0), cards.animate.set_opacity(0), run_time=0.8)
        self.remove(title, cards)
