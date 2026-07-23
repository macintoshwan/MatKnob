# MegKnob bring-up notes

## Current goal

`megknob` is currently being validated as the smallest possible ZMK shield on `nice_nano`.
At this stage the goal is not to finish the full product feature set, but to confirm that the basic input path works reliably over both USB and BLE.

The current validation target is:
- one normal matrix key
- `P1.11` as row
- `P1.13` as column
- closing the switch should send `Q`

## What I changed after taking over

### 1. First pass: reduced the shield to a minimal bootable configuration

When I first took over, the requirement sounded like:
- BLE should work
- a wheel / rotary input should work
- `P1.11` and `P1.13` were associated with scroll-down validation

Based on that interpretation, I changed `megknob` into a minimal test shield that:
- kept BLE and USB enabled
- used a single placeholder key so the firmware could build cleanly
- used `P1.11` and `P1.13` as an EC11 encoder input
- mapped rotation to scroll events

That version was useful only for validating:
- whether the board could boot
- whether the shield could build
- whether BLE/USB enumeration still worked
- whether the encoder path was wired correctly

### 2. Second pass: corrected the validation target

After your clarification, it became clear that `P1.11` and `P1.13` were not meant to be a temporary encoder for this test.
They were meant to form a normal row/column crossing, so shorting them should behave like pressing one matrix key.

Because of that, I changed the shield again to match the actual hardware validation goal:
- removed the temporary encoder path
- removed pointing / scroll behavior
- changed the shield to a 1x1 matrix keyboard
- mapped the only key to `Q`

This is the current correct bring-up direction.

## Why I changed it this way

The main reason is that ZMK validation is much easier when the firmware model matches the actual electrical intention.

If the hardware being tested is a normal row/column key, then the firmware should also model it as:
- a matrix kscan
- a normal key binding

That gives a much cleaner result than mixing in unrelated features like:
- encoder sensors
- scroll behaviors
- pointing HID paths

By reducing the design to one matrix key, we minimize variables and make debugging easier.
If `Q` works reliably, the next feature can be added with confidence.

## What was lacking in the earlier state

There were several gaps in the earlier direction.

### 1. The validation target was not precise enough

The initial requirement mixed together:
- BLE bring-up
- wheel / encoder behavior
- `P1.11` and `P1.13` pin verification

Those are not the same test.
Without clearly separating them, it is easy to validate the wrong firmware path.

### 2. Pin roles were inconsistent across iterations

At different points, `P1.11` and `P1.13` were treated as:
- matrix pins
- encoder A/B pins
- temporary validation pins

That made it hard to know what a successful test actually meant.

### 3. Firmware layers were temporarily out of sync

During bring-up, the following pieces should describe the same hardware intent:
- overlay
- keymap
- config
- shield metadata

In the temporary encoder version, those layers were internally consistent for an encoder test, but they no longer matched the real goal once you clarified that the two pins should act as one normal key.

### 4. The old test path could prove the wrong thing

A board can:
- enumerate over USB
- pair over BLE
- build successfully

and still fail to validate the intended key wiring.

That is what happened here: connectivity worked, but the input path being tested was not the one you actually cared about.

## Why the current version is better

The current version is better for bring-up because it is focused.

It now tests exactly one thing:
- whether `P1.11` and `P1.13` work as a row/column key crossing in ZMK

That means:
- fewer moving parts
- easier debugging
- a direct match between hardware action and firmware behavior

If this version sends `Q` correctly over USB and BLE, then the basic matrix path is confirmed.
After that, encoder support can be added back as a separate task instead of being mixed into first-stage validation.

## Recommended next step after Q works

Once the `Q` key works correctly, the next step should be a separate change that reintroduces the intended final feature set, for example:
- add the real encoder back
- assign dedicated encoder pins
- bind rotation to scroll or another action
- update shield metadata and config accordingly

That will keep the project easy to reason about and prevent future bring-up confusion.
