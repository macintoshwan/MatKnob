"""Manim pseudo-3D commercial film for the MegKnob signal pipeline."""

from __future__ import annotations

import math

import numpy as np
from manim import *

from megknob_3d_common import *


class MegKnobPipeline3D(MegKnobThreeDScene):
    def construct(self):
        self.setup_world(phi=68, theta=-48, zoom=1.05)
        self.opening()
        self.mux_and_adc()
        samples = self.buffer_fill()
        packet = self.packet_assembly(samples)
        self.queue_and_usb(packet)
        self.host_decode()
        self.waveforms()
        self.final_shot()

    def opening(self):
        keyboard = keyboard3d(show_legends=False).scale(0.90)
        keyboard.rotate(-7 * DEGREES, axis=OUT)
        keyboard.shift(DOWN * 0.30)
        title = VGroup(
            txt("FROM FIELD TO FRAME", 43, INK, BOLD, SANS, 11.8),
            txt("THE JOURNEY OF ONE PRESS", 14, YELLOW, BOLD, MONO),
        ).arrange(DOWN, buff=0.14).to_edge(UP, buff=0.48)
        self.add_fixed_in_frame_mobjects(title)
        title.set_opacity(0)
        self.play(FadeIn(keyboard, shift=OUT * 0.22), title.animate.set_opacity(1), run_time=1.2)
        key = keyboard.keys[7]
        pulse = glow_core(MAGENTA, 0.11).move_to(key.get_center() + OUT * 0.35)
        self.play(key.animate.shift(IN * 0.13), FadeIn(pulse, scale=0.2), run_time=0.45)
        self.play(pulse.animate.move_to(keyboard.get_right() + RIGHT * 1.4 + OUT * 0.3), run_time=0.9,
                  rate_func=rate_functions.ease_in_cubic)
        self.play(FadeOut(keyboard), title.animate.set_opacity(0), run_time=0.5)
        self.remove(title, pulse)

    def mux_and_adc(self):
        header = hud("Analog selection", "ONE ADDRESS · THREE ANALOG PATHS",
                     "3 × 74HC4051 · GRAY-CODE ADDRESSING", 1)
        self.show_hud(header)
        muxes = VGroup()
        for row, color in enumerate(ROW_COLORS):
            body = block3d(2.4, 0.58, 1.0, "#0D1B25", color)
            rails = VGroup()
            for channel in range(8):
                z = -0.35 + channel * 0.10
                rail = Line3D([-1.35, -0.36, z], [-0.35, -0.36, z], thickness=0.009, color=EDGE)
                rails.add(rail)
            chip = VGroup(body, rails).shift(RIGHT * ((row - 1) * 2.75))
            muxes.add(chip)
        muxes.shift(DOWN * 0.25)
        address = VGroup(*[Line3D([-4.2, -0.6 + i * 0.20, 1.05], [4.2, -0.6 + i * 0.20, 1.05],
                                      thickness=0.018, color=YELLOW) for i in range(3)])
        self.play(LaggedStart(*[FadeIn(mux, shift=OUT * 0.15) for mux in muxes], lag_ratio=0.16),
                  Create(address), run_time=1.1)
        selected = VGroup()
        for row, mux in enumerate(muxes):
            path = Line3D(mux.get_left() + LEFT * 0.45, mux.get_right() + RIGHT * 0.45,
                          thickness=0.055, color=ROW_COLORS[row])
            selected.add(path)
        bits = VGroup(*[pill(v, YELLOW) for v in ("000", "001", "011", "010", "110", "111", "101", "100")])
        bits.arrange(RIGHT, buff=0.12).scale(0.72).to_edge(DOWN, buff=0.38)
        self.add_fixed_in_frame_mobjects(bits)
        self.play(FadeIn(bits), Create(selected), run_time=0.7)
        marker = SurroundingRectangle(bits[0], color=YELLOW, buff=0.06, corner_radius=0.08)
        self.add_fixed_in_frame_mobjects(marker)
        for step in range(1, len(bits)):
            self.play(Transform(marker, SurroundingRectangle(bits[step], color=YELLOW, buff=0.06,
                                                               corner_radius=0.08)), run_time=0.16)
        adc = block3d(2.0, 0.85, 1.25, "#111F2A", GREEN).move_to([0, 0.2, -1.65])
        adc_label = txt("SAADC\n12 BIT", 14, GREEN, BOLD, MONO)
        adc_label.move_to(adc.get_center())
        self.add_fixed_orientation_mobjects(adc_label)
        paths = VGroup(*[CubicBezier(mux.get_bottom(), mux.get_bottom() + IN * 0.55,
                                     adc.get_top() + LEFT * (row - 1) * 0.45 + OUT * 0.30,
                                     adc.get_top() + LEFT * (row - 1) * 0.45)
                               .set_stroke(ROW_COLORS[row], 3, opacity=0.65)
                               for row, mux in enumerate(muxes)])
        payloads = VGroup(*[glow_core(ROW_COLORS[row], 0.09).move_to(path.get_start())
                            for row, path in enumerate(paths)])
        self.play(FadeIn(adc), FadeIn(adc_label), Create(paths), run_time=0.7)
        self.add(payloads)
        self.play(*[MoveAlongPath(payloads[i], paths[i]) for i in range(3)], run_time=0.9,
                  rate_func=rate_functions.ease_in_out_cubic)
        samples = VGroup(*[block3d(0.36, 0.30, 0.36, ROW_COLORS[i], WHITE).move_to(
            adc.get_bottom() + IN * 0.45 + RIGHT * (i - 1) * 0.52) for i in range(3)])
        self.play(*[ReplacementTransform(payloads[i], samples[i]) for i in range(3)], run_time=0.45)
        self.wait(0.25)
        self.remove(marker, bits)
        self.hide_hud(header)
        self.clear_stage(muxes, address, selected, adc, adc_label, paths, samples)

    def buffer_fill(self):
        header = hud("Complete scan", "THE BUFFER FILLS IN THREES",
                     "GRAY-CODE SCAN ORDER · STABLE ROW-MAJOR STORAGE", 2)
        self.show_hud(header)
        wall = buffer_wall3d().scale(1.08).shift(DOWN * 0.12)
        self.play(FadeIn(wall, shift=OUT * 0.18), run_time=0.8)
        row_labels = VGroup(*[txt(name, 11, ROW_COLORS[i], BOLD, MONO) for i, name in enumerate(("U26", "U27", "U28"))])
        for row, label in enumerate(row_labels):
            label.move_to([-3.72, 0, (1 - row) * 0.78 - 0.12])
        self.add_fixed_orientation_mobjects(*row_labels)
        samples_by_slot = {}
        for step, col in enumerate(GRAY_ORDER):
            frames = [wall.frames[(row, col)] for row in range(3)]
            self.play(*[frame.animate.set_color(YELLOW) for frame in frames], run_time=0.10)
            triplet = []
            paths = []
            for row in range(3):
                target = wall.slots[(row, col)].get_center() + IN * 0.13
                start = target + IN * (4.0 + row * 0.18) + RIGHT * ((row - 1) * 0.16)
                sample = glow_core(ROW_COLORS[row], 0.105).move_to(start)
                path = CubicBezier(start, start + OUT * 1.6 + UP * ((1 - row) * 0.12),
                                   target + IN * 0.72, target)
                triplet.append(sample); paths.append(path)
                self.add(sample)
            duration = 0.54 if step < 6 else 0.72
            self.play(*[MoveAlongPath(triplet[i], paths[i]) for i in range(3)], run_time=duration,
                      rate_func=rate_functions.ease_out_quint)
            for row, sample in enumerate(triplet):
                sample[0].set_opacity(0)
                sample[2].set_opacity(0.82)
                samples_by_slot[(row, col)] = sample
            self.play(*[sample.animate.scale(0.82) for sample in triplet],
                      *[frame.animate.set_color(ROW_COLORS[row]) for row, frame in enumerate(frames)],
                      run_time=0.12, rate_func=there_and_back_with_pause)
        pulse = SurroundingRectangle(VGroup(*wall.frames.values()), color=GREEN, buff=0.16,
                                     corner_radius=0.16, stroke_width=3)
        pulse.rotate(PI / 2, axis=RIGHT)
        pulse.move_to(wall)
        self.play(Create(pulse), wall.animate.set_color(GREEN), run_time=0.4)
        self.play(FadeOut(pulse), run_time=0.25)
        status = pill("24 / 24 · COMPLETE SCAN", GREEN).to_edge(DOWN, buff=0.35)
        self.add_fixed_in_frame_mobjects(status)
        self.play(FadeIn(status, shift=UP * 0.1), run_time=0.35)
        self.wait(0.3)
        ordered = VGroup(*[samples_by_slot[(row, col)] for row in range(3) for col in range(8)])
        self.play(FadeOut(wall), FadeOut(VGroup(*row_labels)), FadeOut(status), run_time=0.45)
        self.hide_hud(header)
        for i, sample in enumerate(ordered):
            row, col = divmod(i, 8)
            sample.generate_target()
            sample.target.move_to([(col - 3.5) * 0.58, 0, (1 - row) * 0.48])
            sample.target.scale(0.72)
        self.play(LaggedStart(*[MoveToTarget(sample) for sample in ordered], lag_ratio=0.018), run_time=0.8)
        return ordered

    def packet_assembly(self, samples):
        header = hud("Binary protocol", "24 SAMPLES BECOME 62 BYTES",
                     "FIXED LENGTH · LITTLE ENDIAN · CRC-16", 3)
        self.show_hud(header)
        self.play(samples.animate.scale(0.72).shift(UP * 1.28), run_time=0.45)
        fields = [("MK", 2, YELLOW), ("META", 4, PURPLE), ("SEQ", 2, ORANGE),
                  ("TIME", 4, GREEN), ("24 × UINT16 mV", 48, CYAN), ("CRC", 2, MAGENTA)]
        total_width = 11.2
        scale = total_width / 62
        field_blocks = VGroup()
        cursor = -total_width / 2
        for name, count, color in fields:
            width = count * scale
            body = block3d(width, 0.58, 0.58, color,
                           ManimColor(color).interpolate(ManimColor(WHITE), 0.25), 0.78)
            body.move_to([cursor + width / 2, 0, -0.82])
            cursor += width
            field_blocks.add(body)
        labels = VGroup(*[txt(name, 10, color, BOLD, MONO) for name, _, color in fields])
        for label, body in zip(labels, field_blocks):
            label.move_to(body.get_center() + OUT * 0.38)
        self.add_fixed_orientation_mobjects(*labels)
        for i, body in enumerate(field_blocks[:-1]):
            body.shift(OUT * (1.5 + i * 0.14))
        self.play(LaggedStart(*[body.animate.shift(IN * (1.5 + i * 0.14))
                                for i, body in enumerate(field_blocks[:-1])], lag_ratio=0.12), run_time=1.1)
        sample_bytes = VGroup()
        for i in range(48):
            byte = byte_block(CYAN, width=0.075, depth=0.66, height=0.16)
            byte.move_to(field_blocks[4].get_left() + RIGHT * ((i + 0.5) * field_blocks[4].width / 48)
                         + OUT * 0.40)
            sample_bytes.add(byte)
        self.play(LaggedStart(*[FadeIn(byte, shift=OUT * 0.22) for byte in sample_bytes], lag_ratio=0.012),
                  FadeOut(samples), run_time=1.0)
        crc_body = field_blocks[-1]
        crc_body.shift(OUT * 1.7)
        beam = block3d(0.055, 0.90, 0.90, GREEN, GREEN, 0.82)
        beam.move_to(field_blocks[0].get_center() + OUT * 0.22)
        self.add(beam)
        self.play(beam.animate.move_to(field_blocks[4].get_right() + OUT * 0.22), run_time=1.15, rate_func=linear)
        self.play(crc_body.animate.shift(IN * 1.7), FadeOut(beam), run_time=0.48,
                  rate_func=rate_functions.ease_out_bounce)
        packet = VGroup(field_blocks, sample_bytes)
        shell = SurroundingRectangle(packet, color=GREEN, buff=0.12, corner_radius=0.12, stroke_width=2)
        shell.rotate(PI / 2, axis=RIGHT); shell.move_to(packet)
        self.play(Create(shell), run_time=0.35)
        packet.add(shell)
        self.play(FadeOut(VGroup(*labels)), run_time=0.2)
        self.hide_hud(header)
        return packet

    def queue_and_usb(self, packet):
        header = hud("Asynchronous transport", "REAL-TIME DATA NEVER WAITS",
                     "DEPTH 4 QUEUE · DROP OLDEST · INTERRUPT-DRIVEN USB CDC", 4)
        self.show_hud(header)
        packet.scale(0.22).move_to([-4.8, 0, 0])
        slots = VGroup(*[block3d(1.55, 0.92, 0.78, "#09151D", EDGE, 1) for _ in range(4)])
        slots.arrange(RIGHT, buff=0.22).move_to(DOWN * 0.30)
        slot_labels = VGroup(*[txt(f"Q{i}", 10, MUTED, BOLD, MONO) for i in range(4)])
        for label, slot in zip(slot_labels, slots): label.move_to(slot.get_center() + OUT * 0.45)
        self.add_fixed_orientation_mobjects(*slot_labels)
        self.play(FadeIn(slots), FadeIn(packet), run_time=0.6)
        frames = VGroup()
        for i in range(4):
            frame = packet.copy().scale(0.72)
            frame.move_to(slots[i].get_center())
            frames.add(frame)
        self.play(LaggedStart(*[ReplacementTransform(packet.copy(), frame) for frame in frames], lag_ratio=0.16),
                  FadeOut(packet), run_time=1.0)
        incoming = frames[-1].copy().move_to(slots[-1].get_right() + RIGHT * 1.4)
        oldest = frames[0]
        self.play(oldest.animate.set_color(ORANGE), FadeIn(incoming), run_time=0.25)
        self.play(oldest.animate.shift(LEFT * 1.5 + DOWN * 0.35).set_opacity(0),
                  *[frames[i].animate.move_to(slots[i - 1].get_center()) for i in range(1, 4)],
                  incoming.animate.move_to(slots[-1].get_center()), run_time=0.65)
        usb_path = CubicBezier(slots[0].get_left(), LEFT * 2.6 + DOWN * 1.2,
                               RIGHT * 2.4 + DOWN * 1.5, RIGHT * 5.7 + DOWN * 0.45)
        usb_path.set_stroke(CYAN, width=4, opacity=0.45)
        payload = glow_core(CYAN, 0.10).move_to(usb_path.get_start())
        self.play(Create(usb_path), FadeIn(payload), run_time=0.4)
        self.play(MoveAlongPath(payload, usb_path), run_time=1.1, rate_func=rate_functions.ease_in_out_cubic)
        self.play(FadeOut(payload), run_time=0.2)
        self.hide_hud(header)
        self.clear_stage(slots, frames, incoming, usb_path, VGroup(*slot_labels))

    def host_decode(self):
        header = hud("Host decoder", "FIND · FRAME · VERIFY",
                     "SEARCH MK · READ 62 BYTES · CRC CHECK", 5)
        self.show_hud(header)
        stream = VGroup()
        colors = [MUTED, MUTED, CYAN, PURPLE, ORANGE, GREEN, CYAN, CYAN, MAGENTA, MUTED, MUTED]
        for i in range(26):
            b = byte_block(colors[i % len(colors)], width=0.31, depth=0.35, height=0.35)
            b.move_to([(i - 12.5) * 0.38, 0, 0])
            stream.add(b)
        self.play(LaggedStart(*[FadeIn(b, shift=LEFT * 0.25) for b in stream], lag_ratio=0.025), run_time=0.9)
        finder = SurroundingRectangle(VGroup(stream[4], stream[5]), color=YELLOW, buff=0.07,
                                      corner_radius=0.05, stroke_width=2)
        finder.rotate(PI / 2, axis=RIGHT); finder.move_to(VGroup(stream[0], stream[1]))
        self.play(Create(finder), run_time=0.25)
        self.play(finder.animate.move_to(VGroup(stream[4], stream[5])), run_time=0.9)
        frame_window = SurroundingRectangle(VGroup(*stream[4:22]), color=CYAN, buff=0.11,
                                            corner_radius=0.08, stroke_width=2)
        frame_window.rotate(PI / 2, axis=RIGHT); frame_window.move_to(VGroup(*stream[4:22]))
        self.play(ReplacementTransform(finder, frame_window), run_time=0.35)
        beam = block3d(0.04, 0.58, 0.58, GREEN, GREEN, 0.9).move_to(stream[4])
        self.play(beam.animate.move_to(stream[21]), run_time=0.9, rate_func=linear)
        verified = pill("CRC VERIFIED", GREEN).to_edge(DOWN, buff=0.35)
        self.add_fixed_in_frame_mobjects(verified)
        self.play(FadeIn(verified), FadeOut(beam), frame_window.animate.set_color(GREEN), run_time=0.35)
        channels = VGroup(*[block3d(0.22, 0.34, 0.35 + (i % 7) * 0.055,
                                          ROW_COLORS[i // 8], WHITE) for i in range(24)])
        channels.arrange(RIGHT, buff=0.08).scale(0.86).move_to(DOWN * 0.35)
        self.play(FadeOut(stream), FadeOut(frame_window),
                  LaggedStart(*[FadeIn(ch, shift=OUT * 0.3) for ch in channels], lag_ratio=0.025), run_time=1.0)
        self.play(FadeOut(verified), run_time=0.2)
        self.hide_hud(header)
        self.clear_stage(channels)

    def waveforms(self):
        header = hud("Live visualization", "24 CHANNELS BECOME LIVE WAVEFORMS",
                     "BOUNDED QUEUE · LOW DISPLAY LAG · ONE PRESS PRESERVED", 6)
        self.show_hud(header)
        curves = VGroup()
        for i in range(12):
            points = []
            baseline = -2.35 + (i % 6) * 0.72
            depth = (i // 6) * 0.48 - 0.24
            for u in np.linspace(0, 1, 120):
                dip = -0.72 * math.exp(-((u - 0.66) / 0.07) ** 2) if i == 2 else 0
                points.append([-5.6 + 11.2 * u, depth, baseline + 0.05 * math.sin(24 * u + i) + dip])
            curve = VMobject(color=ROW_COLORS[(i // 4) % 3], stroke_width=2.0,
                              stroke_opacity=0.78).set_points_smoothly(points)
            curves.add(curve)
        self.play(LaggedStart(*[Create(curve) for curve in curves], lag_ratio=0.07), run_time=2.0)
        point = glow_core(YELLOW, 0.11).move_to(curves[2].point_from_proportion(0.66))
        self.play(FadeIn(point, scale=0.2), Circumscribe(curves[2], color=YELLOW), run_time=0.6)
        metrics = VGroup(pill("≈1216 SCANS/S · MEASURED", YELLOW),
                         pill("≈1171 RX FPS · MEASURED", CYAN),
                         pill("≈72.9 kB/S", MAGENTA))
        metrics.arrange(RIGHT, buff=0.24).to_edge(DOWN, buff=0.28)
        self.add_fixed_in_frame_mobjects(metrics)
        self.play(FadeIn(metrics, shift=UP * 0.1), run_time=0.4)
        self.wait(0.45)
        self.play(FadeOut(metrics), run_time=0.2)
        self.hide_hud(header)
        self.clear_stage(curves, point)

    def final_shot(self):
        keyboard = keyboard3d(show_legends=False).scale(0.80).shift(DOWN * 0.45)
        title = VGroup(txt("FROM FIELD TO FRAME", 43, INK, BOLD, SANS, 11.8),
                       txt("ONE PRESS · 24 CHANNELS · ONE VERIFIED DATA PATH", 13, CYAN, BOLD, MONO),
                       txt("MEGKNOB / ZMK", 12, MUTED, BOLD, MONO)).arrange(DOWN, buff=0.14).to_edge(UP, buff=0.40)
        self.add_fixed_in_frame_mobjects(title)
        title.set_opacity(0)
        path = ParametricFunction(lambda t: np.array([-4.6 + 9.2 * t, -1.5 + 0.25 * np.sin(TAU * t),
                                                       0.95 + 0.18 * np.sin(PI * t)]),
                                  t_range=[0, 1], color=CYAN, stroke_width=3)
        dot = glow_core(YELLOW, 0.10).move_to(path.get_start())
        self.play(FadeIn(keyboard), title.animate.set_opacity(1), Create(path), FadeIn(dot), run_time=1.0)
        self.play(MoveAlongPath(dot, path), run_time=1.4, rate_func=rate_functions.ease_in_out_cubic)
        self.play(keyboard.rgb.animate.set_color(CYAN), Flash(dot, color=YELLOW, flash_radius=0.7), run_time=0.5)
        self.wait(1.1)
        self.play(FadeOut(VGroup(keyboard, path, dot)), title.animate.set_opacity(0), run_time=0.8)
        self.remove(title)
