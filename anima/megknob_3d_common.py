"""Shared pseudo-3D assets for the MegKnob Manim films."""

from __future__ import annotations

import numpy as np
from manim import *

BG = "#050B12"
PANEL = "#0B1721"
PANEL_2 = "#122532"
EDGE = "#274554"
INK = "#E5F2F7"
MUTED = "#718A96"
CYAN = "#22D3EE"
YELLOW = "#F8C537"
MAGENTA = "#F05BC8"
GREEN = "#53E6A1"
ORANGE = "#FF8A4C"
PURPLE = "#9D8CFF"
RED = "#FF5D73"
MONO = "Menlo"
SANS = "Arial"
ROW_COLORS = (CYAN, MAGENTA, GREEN)
GRAY_ORDER = (0, 1, 3, 2, 6, 7, 5, 4)


def txt(value, size=28, color=INK, weight=NORMAL, font=SANS, max_width=None):
    mob = Text(value, font=font, font_size=size, color=color, weight=weight)
    if max_width is not None and mob.width > max_width:
        mob.scale_to_fit_width(max_width)
    return mob


def block3d(width, depth, height, color=PANEL_2, edge=EDGE, opacity=1.0):
    block = Cube(side_length=1, fill_color=color, fill_opacity=opacity,
                 stroke_color=edge, stroke_width=0.8, stroke_opacity=0.82)
    block.stretch_to_fit_width(width)
    block.stretch_to_fit_depth(depth)
    block.stretch_to_fit_height(height)
    block.set_shade_in_3d(True)
    return block


def glow_core(color=CYAN, radius=0.11):
    halo = Sphere(radius=radius * 2.0, resolution=(8, 8), fill_color=color,
                  fill_opacity=0.10, stroke_opacity=0)
    core = Sphere(radius=radius, resolution=(10, 10), fill_color=color,
                  fill_opacity=0.92, stroke_color=WHITE, stroke_width=0.5)
    hot = Sphere(radius=radius * 0.35, resolution=(6, 6), fill_color=WHITE,
                 fill_opacity=0.95, stroke_opacity=0)
    return VGroup(halo, core, hot)


def hud(kicker, heading, detail, index=None):
    top = txt(kicker.upper(), 13, YELLOW, BOLD, MONO)
    title = txt(heading, 31, INK, BOLD, SANS, 11.6)
    sub = txt(detail.upper(), 12, MUTED, BOLD, MONO, 11.8)
    if index is not None:
        number = txt(f"{index:02d}", 15, CYAN, BOLD, MONO)
        first = VGroup(number, top).arrange(RIGHT, buff=0.22, aligned_edge=DOWN)
    else:
        first = top
    group = VGroup(first, title, sub).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
    group.to_corner(UL, buff=0.32)
    rule = Line(LEFT * 6.7, RIGHT * 6.7, color=EDGE, stroke_width=1)
    rule.next_to(group, DOWN, buff=0.14)
    return VGroup(group, rule)


def pill(value, color=CYAN):
    label = txt(value, 11, color, BOLD, MONO)
    box = RoundedRectangle(width=label.width + 0.38, height=0.34, corner_radius=0.14,
                           fill_color=color, fill_opacity=0.08, stroke_color=color, stroke_width=1)
    label.move_to(box)
    return VGroup(box, label)


def keyboard3d(show_legends=True):
    base = block3d(7.4, 4.05, 0.26, "#09151D", CYAN)
    base.shift(IN * 0.18)
    top = block3d(7.12, 3.78, 0.10, PANEL, EDGE)
    top.shift(OUT * 0.02)
    keys = VGroup()
    legends = VGroup()
    labels = ["TAB", "Q", "W", "E", "R", "FN", "A", "S", "D", "F",
              "SHIFT", "Z", "X", "C", "BSP", "CTRL", "WIN", "ALT", "SPACE"]
    positions = []
    for row, count in enumerate((5, 5, 4, 5)):
        offset = -0.36 if row == 2 else 0.0
        for col in range(count):
            positions.append((-2.35 + col * 1.02 + offset, 1.18 - row * 0.88))
    for i, ((x, y), label) in enumerate(zip(positions, labels)):
        width = 1.28 if i == 18 else 0.86
        key = block3d(width, 0.70, 0.34, "#142631", "#3B5967")
        key.move_to([x, y, 0.30])
        keys.add(key)
        if show_legends:
            legend = txt(label, 8 if len(label) > 4 else 10, INK, BOLD, MONO)
            legend.move_to([x, y, 0.49])
            legends.add(legend)
    knob_outer = Cylinder(radius=0.70, height=0.38, direction=OUT, resolution=(24, 8),
                          fill_color="#172934", fill_opacity=1, stroke_color=PURPLE, stroke_width=1.6)
    knob_outer.move_to([2.65, 0.74, 0.38])
    knob_inner = Cylinder(radius=0.50, height=0.40, direction=OUT, resolution=(24, 8),
                          fill_color="#0A151D", fill_opacity=1, stroke_color=EDGE, stroke_width=1)
    knob_inner.move_to(knob_outer)
    marker = Line3D([2.65, 0.94, 0.60], [2.65, 1.19, 0.60], thickness=0.025, color=YELLOW)
    knob = VGroup(knob_outer, knob_inner, marker)
    usb = block3d(0.78, 0.32, 0.24, BG, MUTED)
    usb.move_to([1.35, 1.98, 0.02])
    rgb = VGroup()
    for x, y in positions:
        light = Cylinder(radius=0.11, height=0.025, direction=OUT, resolution=(10, 4),
                         fill_color=MAGENTA, fill_opacity=0.65, stroke_opacity=0)
        light.move_to([x, y, 0.05])
        rgb.add(light)
    result = VGroup(base, top, rgb, keys, legends, knob, usb)
    result.base = base
    result.top = top
    result.rgb = rgb
    result.keys = keys
    result.legends = legends
    result.knob = knob
    result.usb = usb
    return result


def buffer_wall3d():
    wall = VGroup()
    slots = {}
    frames = {}
    for row in range(3):
        for col in range(8):
            x = (col - 3.5) * 0.76
            z = (1 - row) * 0.72
            back = block3d(0.62, 0.16, 0.52, "#0A141C", EDGE)
            back.move_to([x, 0, z])
            frame = VGroup(
                Line3D([x - 0.31, -0.10, z - 0.26], [x + 0.31, -0.10, z - 0.26], thickness=0.012, color=EDGE),
                Line3D([x - 0.31, -0.10, z + 0.26], [x + 0.31, -0.10, z + 0.26], thickness=0.012, color=EDGE),
                Line3D([x - 0.31, -0.10, z - 0.26], [x - 0.31, -0.10, z + 0.26], thickness=0.012, color=EDGE),
                Line3D([x + 0.31, -0.10, z - 0.26], [x + 0.31, -0.10, z + 0.26], thickness=0.012, color=EDGE),
            )
            slot = VGroup(back, frame)
            slots[(row, col)] = slot
            frames[(row, col)] = frame
            wall.add(slot)
    wall.slots = slots
    wall.frames = frames
    return wall


def byte_block(color, width=0.13, depth=0.34, height=0.34):
    return block3d(width, depth, height, color, ManimColor(color).interpolate(ManimColor(WHITE), 0.25), 0.90)


class MegKnobThreeDScene(ThreeDScene):
    def setup_world(self, phi=68, theta=-48, zoom=1.05, center=ORIGIN):
        self.camera.background_color = BG
        self.set_camera_orientation(phi=phi * DEGREES, theta=theta * DEGREES,
                                    zoom=zoom, frame_center=center)

    def show_hud(self, group):
        self.add_fixed_in_frame_mobjects(group)
        group.set_opacity(0)
        self.play(group.animate.set_opacity(1), run_time=0.55)

    def hide_hud(self, group):
        self.play(group.animate.set_opacity(0), run_time=0.35)
        self.remove(group)

    def clear_stage(self, *mobjects, run_time=0.45):
        present = [mob for mob in mobjects if mob is not None]
        if present:
            self.play(*[FadeOut(mob, shift=IN * 0.15) for mob in present], run_time=run_time)
