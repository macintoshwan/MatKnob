# MegKnob MEG / 4051 映射核对表

这份表记录当前固件里的假设映射，用来手动核对和更正。

当前硬件假设：

- `ADR0 = P1.06`
- `ADR1 = P0.09`
- `ADR2 = P0.10`
- `U26` 公共端接 `ADC3 / P0.31 / AIN7`，在固件里是 ADC row 0
- `U27` 公共端接 `ADC2 / P0.29 / AIN5`，在固件里是 ADC row 1
- `U28` 公共端接 `ADC1 / P0.02 / AIN0`，在固件里是 ADC row 2
- 4051 的 `Y0..Y7` 对应固件里的 column `0..7`
- 滚轮不属于 MEG，单独走 GPIO matrix，目前映射为 RGB 控制

## 当前按键到 MEG / 4051 映射

| 当前按键 | MEG编号 | 4051芯片 | 4051通道 | ADC输入 | 固件RC | 手动更正 |
|---|---:|---|---|---|---|---|
| TAB | MEG0 | U28 | Y2 | ADC1 / P0.02 | RC(2,2) | |
| Q | MEG1 | U28 | Y4 | ADC1 / P0.02 | RC(2,4) | |
| W | MEG2 | U27 | Y2 | ADC2 / P0.29 | RC(1,2) | |
| E | MEG3 | U27 | Y4 | ADC2 / P0.29 | RC(1,4) | |
| R | MEG4 | U26 | Y4 | ADC3 / P0.31 | RC(0,4) | |
| CAPS | MEG5 | U28 | Y1 | ADC1 / P0.02 | RC(2,1) | |
| A | MEG6 | U28 | Y6 | ADC1 / P0.02 | RC(2,6) | |
| S | MEG7 | U27 | Y1 | ADC2 / P0.29 | RC(1,1) | |
| D | MEG8 | U27 | Y6 | ADC2 / P0.29 | RC(1,6) | |
| F | MEG9 | U26 | Y6 | ADC3 / P0.31 | RC(0,6) | |
| LEFT_SHIFT | MEG10 | U28 | Y0 | ADC1 / P0.02 | RC(2,0) | |
| Z | MEG11 | U28 | Y7 | ADC1 / P0.02 | RC(2,7) | |
| X | MEG12 | U27 | Y0 | ADC2 / P0.29 | RC(1,0) | |
| C | MEG13 | U27 | Y7 | ADC2 / P0.29 | RC(1,7) | |
| BACKSPACE | MEG15 | U28 | Y3 | ADC1 / P0.02 | RC(2,3) | |
| LEFT_CTRL | MEG16 | U28 | Y5 | ADC1 / P0.02 | RC(2,5) | |
| WIN | MEG17 | U27 | Y3 | ADC2 / P0.29 | RC(1,3) | |
| ALT | MEG18 | U27 | Y5 | ADC2 / P0.29 | RC(1,5) | |
| SPACE | MEG14 | U26 | Y7 | ADC3 / P0.31 | RC(0,7) | |

## 当前滚轮映射（2026-07-29 起：旋转已迁移为正交编码器）

滚轮按下仍然是矩阵按键；旋转不再是两个矩阵按键，而是由 `wheel_encoder`（`compatible = "alps,ec11"`）解码为一个带方向的 sensor，通过 keymap 的 `sensor-bindings` 绑定行为。旧的"两个独立按键"模型是错误的：机械编码器每次转动 A/B 两相都会先后翻转，当成两个按键处理时一次旋转必然同时触发两个方向的事件。

| 功能 | 矩阵/传感器位置 | 物理连接 | 当前绑定 | 手动更正 |
|---|---|---|---|---|
| 滚轮按下 | RC(3,0) | COL0 P1.00 -- ROW1 P1.11 | RGB_TOG | |
| 滚轮旋转（A 相） | `wheel_encoder` a-gpios | P0.11 | `sensor-bindings`：`&inc_dec_kp C_VOL_UP C_VOL_DN` | 方向未经实测确认，如反向请交换 `inc_dec_kp` 的两个参数 |
| 滚轮旋转（B 相） | `wheel_encoder` b-gpios | P0.24 | 同上（A/B 两相共同解码为一个方向性 delta，不再单独绑定） | |

`steps = <80>`、`triggers-per-rotation = <20>` 沿用之前 GPIO 矩阵阶段的经验值，尚未用逻辑分析仪对实际编码器的每圈脉冲数做过验证，后续如发现步进变慢/变快或漏步，需要现场测量后调整这两个参数。

## 按 MEG 编号排序的 4051 通道表

| MEG编号 | 4051芯片 | 4051通道 | ADC输入 | 固件RC | 当前按键 | 手动更正 |
|---:|---|---|---|---|---|---|
| MEG0 | U28 | Y2 | ADC1 / P0.02 | RC(2,2) | TAB | |
| MEG1 | U28 | Y4 | ADC1 / P0.02 | RC(2,4) | Q | |
| MEG2 | U27 | Y2 | ADC2 / P0.29 | RC(1,2) | W | |
| MEG3 | U27 | Y4 | ADC2 / P0.29 | RC(1,4) | E | |
| MEG4 | U26 | Y4 | ADC3 / P0.31 | RC(0,4) | R | |
| MEG5 | U28 | Y1 | ADC1 / P0.02 | RC(2,1) | CAPS | |
| MEG6 | U28 | Y6 | ADC1 / P0.02 | RC(2,6) | A | |
| MEG7 | U27 | Y1 | ADC2 / P0.29 | RC(1,1) | S | |
| MEG8 | U27 | Y6 | ADC2 / P0.29 | RC(1,6) | D | |
| MEG9 | U26 | Y6 | ADC3 / P0.31 | RC(0,6) | F | |
| MEG10 | U28 | Y0 | ADC1 / P0.02 | RC(2,0) | LEFT_SHIFT | |
| MEG11 | U28 | Y7 | ADC1 / P0.02 | RC(2,7) | Z | |
| MEG12 | U27 | Y0 | ADC2 / P0.29 | RC(1,0) | X | |
| MEG13 | U27 | Y7 | ADC2 / P0.29 | RC(1,7) | C | |
| MEG14 | U26 | Y7 | ADC3 / P0.31 | RC(0,7) | SPACE | |
| MEG15 | U28 | Y3 | ADC1 / P0.02 | RC(2,3) | BACKSPACE | |
| MEG16 | U28 | Y5 | ADC1 / P0.02 | RC(2,5) | LEFT_CTRL | |
| MEG17 | U27 | Y3 | ADC2 / P0.29 | RC(1,3) | WIN | |
| MEG18 | U27 | Y5 | ADC2 / P0.29 | RC(1,5) | ALT | |

## 当前 transform 顺序

当前 `megknob_transform` 的顺序等同于下面这个序列，keymap 的 `bindings` 会按这个顺序一一对应（20 项，`WHEEL_A`/`WHEEL_B` 不再是矩阵位置，见上一节）：

```text
MEG0, MEG1, MEG2, MEG3, MEG4,
MEG5, MEG6, MEG7, MEG8, MEG9,
MEG10, MEG11, MEG12, MEG13,
MEG15, MEG16, MEG17, MEG18, MEG14,
WHEEL_PRESS
```

注意：这里 `MEG14` 当前放在 SPACE 位置，所以顺序上在 `MEG18` 后面。滚轮旋转单独走 `sensor-bindings`，不占用这个矩阵序列。
