# SerialKM - 串口控制键盘鼠标设备

基于 ZMK 固件的可编程键盘鼠标输入注入设备，通过 UART 串口接收指令并模拟键盘和鼠标操作。

## 项目简介

这是一个**自动化输入设备**。它可以：

- 接收来自上位机（PC/树莓派等）的串口指令
- 模拟键盘按键的按下和释放
- 模拟鼠标的移动和点击
- 用于游戏自动化、辅助工具、远程控制等场景

## 核心特性

### 🎮 键盘注入

- 支持所有标准 HID 键盘按键（通过 HID Usage ID）
- 按键按下/释放/全部释放指令
- 精确的按键时序控制

### 🖱️ 鼠标注入

- 相对坐标移动（支持负值）
- 左键/右键/中键的点击、按下、释放
- 可配置的点击延迟时间

### 🛡️ 安全机制

- **防抱死保护**：500ms 内未收到指令自动释放所有按键
- 心跳保活机制（`S:P` 指令）
- 指令队列防止丢失

### 🔌 通信方式

- USB CDC ACM 虚拟串口
- 中断驱动的高效接收
- 文本协议，易于调试

## 指令协议

采用 `模块:指令:参数` 的三段式文本协议，以 `\n` 结尾。

### 键盘指令 (K)

| 指令   | 格式          | 示例     | 说明             |
| ------ | ------------- | -------- | ---------------- |
| 按下   | `K:D:<HID码>` | `K:D:04` | 按下 A 键 (0x04) |
| 释放   | `K:U:<HID码>` | `K:U:04` | 释放 A 键        |
| 全释放 | `K:A`         | `K:A`    | 释放所有按键     |

### 鼠标指令 (M)

| 指令 | 格式          | 示例        | 说明            |
| ---- | ------------- | ----------- | --------------- |
| 移动 | `M:R:<X>:<Y>` | `M:R:15:-5` | 向右 15，向上 5 |
| 点击 | `M:C:<按键>`  | `M:C:L`     | 左键单击        |
| 按下 | `M:D:<按键>`  | `M:D:R`     | 按下右键        |
| 释放 | `M:U:<按键>`  | `M:U:M`     | 释放中键        |

按键代码：`L`=左键，`R`=右键，`M`=中键

### 系统指令 (S)

| 指令 | 格式  | 示例  | 说明                 |
| ---- | ----- | ----- | -------------------- |
| 心跳 | `S:P` | `S:P` | 保活，防止防抱死触发 |

### 响应消息

设备会返回 ACK 消息：

- `OK K` / `OK M` - 指令执行成功
- `PONG` - 心跳响应
- `ERR FORMAT` / `ERR K` / `ERR M` - 指令格式错误
- `ERR QUEUE` - 指令队列满
- `HOSTCMD READY` - 设备启动完成

## 硬件要求

- **MCU**: nRF52840 或其他支持 USB 的 Zephyr 平台
- **连接**: USB 数据线（提供电源和虚拟串口）
- **可选**: 外部 UART（如需独立串口通信）

## 编译和烧录

### 1. 安装 ZMK 开发环境

参考 [ZMK 官方文档](https://zmk.dev/docs/development/setup)

### 2. 编译固件

```bash
west build -b nice_nano_v2 -S host-cmd-usb-uart
```

### 3. 烧录固件

```bash
west flash
```

## 配置选项

在 `app/src/host_cmd/Kconfig` 中可配置：

| 选项                               | 默认值 | 说明           |
| ---------------------------------- | ------ | -------------- |
| `ZMK_HOST_CMD_LINE_MAX_LEN`        | 64     | 最大指令长度   |
| `ZMK_HOST_CMD_QUEUE_DEPTH`         | 8      | 指令队列深度   |
| `ZMK_HOST_CMD_CLICK_DELAY_MS`      | 8      | 鼠标点击延迟   |
| `ZMK_HOST_CMD_FAILSAFE_TIMEOUT_MS` | 500    | 防抱死超时时间 |

## 使用示例

### Python 示例

```python
import serial

ser = serial.Serial('/dev/ttyACM0', 115200)

# 按下并释放 A 键
ser.write(b'K:D:04\n')
ser.write(b'K:U:04\n')

# 鼠标移动并点击
ser.write(b'M:R:100:50\n')
ser.write(b'M:C:L\n')

# 心跳保活
ser.write(b'S:P\n')
print(ser.readline())  # 读取 "PONG"

ser.close()
```

### 游戏自动化示例

```python
import serial
import time

ser = serial.Serial('COM3', 115200)

def press_key(hid_code):
    ser.write(f'K:D:{hid_code:02X}\n'.encode())
    time.sleep(0.05)
    ser.write(f'K:U:{hid_code:02X}\n'.encode())

# 自动按 W 键前进
for _ in range(10):
    press_key(0x1A)  # W 键
    time.sleep(0.1)
    ser.write(b'S:P\n')  # 心跳

ser.close()
```

## 常见 HID 键码

| 按键 | HID 码 | 按键  | HID 码 |
| ---- | ------ | ----- | ------ |
| A    | 0x04   | 1     | 0x1E   |
| W    | 0x1A   | Space | 0x2C   |
| S    | 0x16   | Enter | 0x28   |
| D    | 0x07   | Esc   | 0x29   |

完整列表参考 [USB HID Usage Tables](https://www.usb.org/sites/default/files/documents/hut1_12v2.pdf)

## 应用场景

- 游戏脚本自动化（自动打怪、自动采集）
- RPA 流程自动化
- 辅助功能设备
- 自动化测试（UI 测试、压力测试）
- 创意控制器（配合传感器、按钮等）

## 安全提示

⚠️ **重要**：此设备可以完全控制键盘和鼠标输入，请：

- 仅在受控环境中使用
- 不要在不信任的计算机上使用
- 注意防抱死机制可能在网络延迟时触发
- 游戏使用可能违反服务条款，后果自负

## 技术架构

基于 [ZMK Firmware](https://zmk.dev/)（MIT 许可证），运行在 [Zephyr RTOS](https://www.zephyrproject.org/) 上。

核心实现：

- [app/src/host_cmd/uart.c](app/src/host_cmd/uart.c) - 串口协议解析和事件注入
- [app/src/host_cmd/Kconfig](app/src/host_cmd/Kconfig) - 配置选项
- [app/snippets/host-cmd-usb-uart/](app/snippets/host-cmd-usb-uart/) - USB CDC ACM 配置

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 致谢

本项目基于 [ZMK Firmware](https://github.com/zmkfirmware/zmk) 开发。
