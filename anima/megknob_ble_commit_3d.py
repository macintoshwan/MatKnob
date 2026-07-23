"""Manim pseudo-3D explainer for the MegKnob Bluetooth controller commit."""

from __future__ import annotations

from manim import *

from megknob_3d_common import *


class MegKnobBLECommit3D(MegKnobThreeDScene):
    """Explain what CONFIG_BT_CTLR does, why it was added, and its portability caveat."""

    def construct(self):
        self.setup_world(phi=67, theta=-50, zoom=1.08)
        self.commit_reveal()
        self.stack_gap()
        self.packet_journey()
        self.target_scope()
        self.engineering_takeaway()

    def fixed_title(self, kicker, title, detail, index):
        header = hud(kicker, title, detail, index)
        self.show_hud(header)
        return header

    def fixed_label(self, value, position, color=INK, size=13):
        label = txt(value, size, color, BOLD, MONO)
        label.move_to(position)
        self.add_fixed_orientation_mobjects(label)
        return label

    def commit_reveal(self):
        header = self.fixed_title(
            "Commit df656f66",
            "ONE LINE · ONE MISSING LAYER",
            "FIX(MEGKNOB): ENABLE NRF BLUETOOTH CONTROLLER",
            1,
        )
        panel = block3d(8.4, 0.28, 3.5, "#09141D", EDGE).shift(DOWN * 0.30)
        lines = VGroup(
            txt("CONFIG_ZMK_BLE=y", 22, CYAN, BOLD, MONO),
            txt("CONFIG_BT=y", 22, PURPLE, BOLD, MONO),
            txt("+ CONFIG_BT_CTLR=y", 25, GREEN, BOLD, MONO),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.34)
        lines.move_to(panel.get_center() + OUT * 0.25)
        self.add_fixed_orientation_mobjects(lines)
        lines.set_opacity(0)
        self.play(FadeIn(panel, shift=OUT * 0.12), run_time=0.65)
        self.play(LaggedStart(*[line.animate.set_opacity(1) for line in lines], lag_ratio=0.24), run_time=1.15)
        beam = SurroundingRectangle(lines[2], color=GREEN, buff=0.16, stroke_width=2)
        self.add_fixed_orientation_mobjects(beam)
        self.play(Create(beam), Flash(lines[2], color=GREEN, flash_radius=0.8), run_time=0.65)
        intent = pill("INTENT: COMPLETE THE BLE STACK", YELLOW).to_edge(DOWN, buff=0.42)
        self.add_fixed_in_frame_mobjects(intent)
        self.play(FadeIn(intent), run_time=0.45)
        self.wait(0.35)
        self.play(FadeOut(intent), run_time=0.2)
        self.remove(intent)
        self.hide_hud(header)
        self.clear_stage(panel, lines, beam)

    def stack_block(self, name, detail, color, z):
        body = block3d(5.6, 1.55, 0.62, "#0C1922", color).move_to([0, 0, z])
        title = self.fixed_label(name, body.get_center() + OUT * 0.34, color, 15)
        sub = self.fixed_label(detail, body.get_center() + OUT * 0.34 + DOWN * 0.30, MUTED, 9)
        return VGroup(body, title, sub)

    def stack_gap(self):
        header = self.fixed_title(
            "Know-how · BLE anatomy",
            "HOST IS NOT THE CONTROLLER",
            "APPLICATION → HOST → HCI → CONTROLLER → 2.4 GHZ RADIO",
            2,
        )
        app = self.stack_block("ZMK BLE HID", "KEYBOARD SERVICE + REPORTS", CYAN, 1.55)
        host = self.stack_block("ZEHPYR BT HOST", "GATT · L2CAP · SMP", PURPLE, 0.62)
        controller = self.stack_block("BT CONTROLLER", "LINK LAYER · SCHEDULER · PHY", GREEN, -0.62)
        radio = self.stack_block("nRF52840 RADIO", "2.4 GHZ HARDWARE", YELLOW, -1.55)
        controller.set_opacity(0.12)
        gap = self.fixed_label("MISSING", controller.get_center() + RIGHT * 4.05, RED, 16)
        cross = Cross(controller, stroke_color=RED, stroke_width=5)
        self.play(LaggedStart(FadeIn(app), FadeIn(host), FadeIn(controller), FadeIn(radio), lag_ratio=0.14), run_time=1.1)
        self.play(Create(cross), FadeIn(gap), run_time=0.45)
        stalled = glow_core(RED, 0.10).move_to(host.get_bottom())
        self.play(FadeIn(stalled), stalled.animate.shift(IN * 0.35), run_time=0.45)
        config = pill("CONFIG_BT_CTLR=y", GREEN).to_edge(RIGHT, buff=0.45)
        self.add_fixed_in_frame_mobjects(config)
        self.play(FadeOut(cross), FadeOut(gap), controller.animate.set_opacity(1), FadeIn(config), run_time=0.65)
        self.play(stalled.animate.set_color(GREEN).move_to(radio.get_top()), run_time=0.85)
        self.play(Flash(radio, color=YELLOW, flash_radius=1.0), run_time=0.45)
        self.play(FadeOut(config), FadeOut(stalled), run_time=0.25)
        self.remove(config)
        self.hide_hud(header)
        self.clear_stage(app, host, controller, radio)

    def packet_journey(self):
        header = self.fixed_title(
            "What it unlocks",
            "A KEY EVENT CAN REACH THE AIR",
            "HID REPORT → GATT → HCI → LINK LAYER → RADIO PACKET",
            3,
        )
        names = (
            ("HID", CYAN),
            ("GATT", PURPLE),
            ("HCI", ORANGE),
            ("LL", GREEN),
            ("RF", YELLOW),
        )
        modules = VGroup()
        labels = VGroup()
        for index, (name, color) in enumerate(names):
            module = block3d(1.55, 1.15, 1.05, "#0C1922", color).move_to([(index - 2) * 2.35, 0, 0])
            label = self.fixed_label(name, module.get_center() + OUT * 0.58, color, 16)
            modules.add(module)
            labels.add(label)
        rails = VGroup(*[
            Line3D(modules[i].get_right(), modules[i + 1].get_left(), thickness=0.025, color=EDGE)
            for i in range(len(modules) - 1)
        ])
        self.play(LaggedStart(*[FadeIn(module, shift=OUT * 0.08) for module in modules], lag_ratio=0.12),
                  FadeIn(labels), Create(rails), run_time=1.05)
        packet = glow_core(CYAN, 0.13).move_to(modules[0].get_center() + OUT * 0.72)
        self.play(FadeIn(packet), run_time=0.2)
        colors = (PURPLE, ORANGE, GREEN, YELLOW)
        for index, color in enumerate(colors, start=1):
            self.play(packet.animate.move_to(modules[index].get_center() + OUT * 0.72).set_color(color),
                      modules[index].animate.set_fill(color, opacity=0.26), run_time=0.52)
        waves = VGroup(*[
            Arc(radius=r, start_angle=-PI / 3, angle=2 * PI / 3, color=YELLOW, stroke_width=2.5)
            for r in (0.45, 0.75, 1.05)
        ]).rotate(PI / 2).next_to(modules[-1], RIGHT, buff=0.25)
        self.play(Create(waves), Flash(packet, color=YELLOW, flash_radius=0.9), run_time=0.65)
        benefit = VGroup(pill("WIRELESS HID", GREEN), pill("PAIRING", PURPLE), pill("BATTERY REPORT", YELLOW))
        benefit.arrange(RIGHT, buff=0.45).to_edge(DOWN, buff=0.30)
        self.add_fixed_in_frame_mobjects(benefit)
        self.play(FadeIn(benefit), run_time=0.45)
        self.wait(0.3)
        self.play(FadeOut(benefit), run_time=0.2)
        self.remove(benefit)
        self.hide_hud(header)
        self.clear_stage(modules, labels, rails, packet, waves)

    def target_scope(self):
        header = self.fixed_title(
            "Hardware scope",
            "MEGKNOB HAS ONE TARGET",
            "NICE!NANO V2 · NRF52840 · USB + BLE",
            4,
        )
        shield = block3d(5.2, 2.8, 0.34, "#0A2B24", GREEN).move_to([0, 0, 1.05])
        controller = block3d(2.5, 1.45, 0.72, "#0D1B25", CYAN).move_to([0, 0, -0.72])
        chip = block3d(1.12, 0.82, 0.22, "#101820", PURPLE).move_to(controller.get_center() + OUT * 0.48)
        shield_label = self.fixed_label("MEGKNOB PCB", shield.get_center() + OUT * 0.22, GREEN, 16)
        board_label = self.fixed_label("NICE!NANO V2", controller.get_center() + OUT * 0.42, CYAN, 15)
        chip_label = self.fixed_label("nRF52840", chip.get_center() + OUT * 0.15, PURPLE, 11)
        pins = VGroup(*[
            Line3D([x, -0.72, 0.55], [x, -0.72, -0.28], thickness=0.025, color=YELLOW)
            for x in (-1.75, -1.25, -0.75, -0.25, 0.25, 0.75, 1.25, 1.75)
        ])
        self.play(FadeIn(shield), FadeIn(shield_label), run_time=0.6)
        self.play(FadeIn(VGroup(controller, chip, board_label, chip_label), shift=OUT * 0.10),
                  Create(pins), run_time=0.85)
        lock = VGroup(pill("TARGET LOCKED", GREEN), pill("NORDIC RADIO", PURPLE))
        lock.arrange(RIGHT, buff=0.45).to_edge(DOWN, buff=0.42)
        self.add_fixed_in_frame_mobjects(lock)
        self.play(FadeIn(lock), Flash(chip, color=PURPLE, flash_radius=0.9), run_time=0.6)
        note = txt("PRO MICRO DESCRIBES THE CONNECTOR · NOT A SECOND MCU REQUIREMENT", 13, YELLOW, BOLD, MONO)
        note.to_edge(DOWN, buff=0.95)
        self.add_fixed_in_frame_mobjects(note)
        self.play(FadeIn(note), run_time=0.5)
        self.wait(0.45)
        self.play(FadeOut(VGroup(lock, note)), run_time=0.25)
        self.remove(lock, note)
        self.hide_hud(header)
        self.clear_stage(shield, shield_label, controller, chip, board_label, chip_label, pins)

    def engineering_takeaway(self):
        header = self.fixed_title(
            "Engineering takeaway",
            "INTENT ≠ VERIFIED OUTCOME",
            "SCOPE HARDWARE CONFIG · TEST THE MATRIX · READ THE FIRST REAL ERROR",
            5,
        )
        cards = VGroup()
        content = (
            ("01", "DECLARE THE TARGET", "NICE!NANO V2 · NRF52840", CYAN),
            ("02", "COMPLETE THE STACK", "HOST + CONTROLLER + RADIO", PURPLE),
            ("03", "TEST REAL HARDWARE", "USB HID · BLE HID · CDC", YELLOW),
        )
        fixed_text = VGroup()
        for i, (num, title, detail, color) in enumerate(content):
            card = block3d(3.65, 0.45, 2.35, "#0B1721", color).move_to([(i - 1) * 4.0, 0, -0.1])
            number = self.fixed_label(num, card.get_center() + UP * 0.62 + OUT * 1.20, color, 15)
            heading = self.fixed_label(title, card.get_center() + UP * 0.12 + OUT * 1.20, INK, 12)
            detail_label = self.fixed_label(detail, card.get_center() + DOWN * 0.45 + OUT * 1.20, MUTED, 8)
            cards.add(card)
            fixed_text.add(number, heading, detail_label)
        self.play(LaggedStart(*[FadeIn(card, shift=OUT * 0.10) for card in cards], lag_ratio=0.16),
                  FadeIn(fixed_text), run_time=1.1)
        verdict = VGroup(
            txt("THE COMMIT ADDS THE MISSING CONTROLLER SWITCH", 16, GREEN, BOLD, MONO),
            txt("THE BUILD NOW FOLLOWS THE ACTUAL NICE!NANO V2 TARGET", 14, YELLOW, BOLD, MONO),
        ).arrange(DOWN, buff=0.12).to_edge(DOWN, buff=0.32)
        self.add_fixed_in_frame_mobjects(verdict)
        self.play(FadeIn(verdict), run_time=0.65)
        self.wait(0.75)
        self.play(FadeOut(verdict), run_time=0.25)
        self.remove(verdict)
        self.hide_hud(header)
        self.clear_stage(cards, fixed_text, run_time=0.65)
