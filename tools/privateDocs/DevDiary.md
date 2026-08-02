# MegKnob 开发日志与路线图

> 排列规则：路线图置顶，按 Issue 分类、不再用"阶段"编号，每个 Issue 标注状态；开发日志按**倒序时间**排列，每天一个可折叠区块（点击标题展开），新的日期在前，旧的日期在后。

# 目标与路线图

## 状态图例

- ✅ 已完成并实机验证
- 🚧 进行中 / 部分完成
- ⏳ 未开始
- 🧊 非阻塞，降级为长期加固项，不影响当前目标推进

## 已完成的基础能力（背景信息，不作为 Issue 跟踪）

以下能力已经实机验证通过，作为后续 Issue 的前提条件记录在此，不再单独跟踪：

- ✅ **24 通道 Hall 轴 ADC 采集**：3 片 74HC4051 + Gray-code 地址 + 三通道 SAADC batch read，扫描率约 1216 Hz；
- ✅ **USB HID 键盘输出**：`CONFIG_ZMK_USB=y`，标准键盘报告可用；
- ✅ **BLE HID 键盘输出**：`CONFIG_ZMK_BLE=y`、`CONFIG_BT=y`，可配对、连接、输入（见 2026-07-23 日志）；
- ✅ **RGB underglow**：闪烁、切换效果正常；
- ✅ **单层可用 keymap**：全部字母/修饰键位 + 3 个 RGB 控制绑定，替代了早期全 `&none` 的采集专用固件；
- ✅ **Hall 按键矩阵映射修正**（`33fdd7a2`）：`MEG_MAPPING.md` 与固件 `megknob_transform` 对齐，不再串键；
- ✅ **Hall 阈值消抖 + kscan 事件队列扩容**（`c16fcc5c`）：接入 `zmk_debounce`，`physical_layouts.c` 丢事件加日志，`CONFIG_ZMK_KSCAN_EVENT_QUEUE_SIZE` 4→16；2026-07-29 刷机实测长时间使用不再出现串键/鬼键/modifier 卡键。

---

## 短期目标：逐键校准（解决手感不一致）🚧

> 本区域实时更新，只跟踪当前正在推进的工作。已收官的 Issue A（滚轮正交编码器）、Issue B（网页上位机 MVP）已移入下方"开发日志 → 已完成 Issue 归档"，此处不再展开。

**问题现象（2026-07-30 用户反馈）**：很多按键按下去手感不一样——有的轻碰就触发，有的要按很深才触发。

**根因分析**：`kscan_adc_mux.c` 目前对所有 24 通道使用**同一组全局绝对电压阈值**（`press-threshold-mv = <1000>`、`release-threshold-mv = <1300>`）。但每个磁轴键的磁铁强度、安装位置/角度、传感器个体差异都不同，导致每键的"松开静止电压（baseline）"和"按到底电压变化幅度（动态范围）"都不一样。用统一绝对阈值判定，必然使阈值相对各键 baseline 的距离远近不一——离得近的键过于灵敏，离得远的键迟钝——这就是手感不一致的直接原因，单靠调全局阈值无法根治。

**职责划分（2026-07-30 确定）：采样与计算全在网页端，固件只接收并存储最终阈值。**

- **网页端（智能侧）**：复用现有实时波形做校准向导——引导"松开所有键"对每键波形取平均得 baseline，再"按到底"取得满行程；在网页端按统一行程百分比（如按下 40%、释放 20%）并结合按下方向，算出**每键的 press/release 绝对毫伏阈值**，通过命令下发；同时对动态范围过小、传感器失效、方向接反的通道给出质量提示；
- **固件端（执行/存储侧）**：`kscan_adc_mux` 的阈值由全局标量改为**每键数组**（24× press + 24× release），判定逐键取值；支持"读取 / 写入（RAM 试用）/ 保存 NVS / 恢复默认"命令；**不需要**校准模式状态机，也不需要固件采样 baseline/满行程。

**固件端改动清单**

1. `kscan_adc_mux`：press/release 阈值从单值改为每键数组，判定逐键取值，保留全局阈值作为"恢复默认"的回落值；
2. 命令协议（Issue D 首个命令）：读取 / 写入 / 保存 NVS / 恢复默认 每键阈值；
3. NVS 持久化每键阈值，断电保留。

**网页端改动清单**

1. 校准向导 UI：松开采样 baseline → 按到底采样满行程 → 显示每键动态范围与质量提示；
2. 网页端计算每键 press/release 阈值并预览；
3. 下发阈值到固件（先 RAM 试用确认手感，再保存 NVS）；
4. 可选：把实时电压换算为 0–100% 行程显示，便于理解触发点。

**当前进度（2026-07-30）**

- ✅ 网页端校准向导已实现，交互按用户确认改为**量程检测**流程：点"按键量程检测"后随机按下所有按键，系统实时记录每键最大/最小电压（静止=max、满行程=min，因按下电压下降），点"量程标定完成"锁定量程，再设定"触发行程比例"（如 0.1）与"滞回区间"（如 0.1/0.01）即算出每键触发/释放阈值；竖条实时显示游标、静止基准线、量程填色与触发/释放线，结果表（通道/静止/量程/触发/释放）带量程质量分级，可导出校准数据；演示模式的随机按键与"按住全部"均可驱动该流程；
- ✅ 上位机 UI 重构为 VSCode 风格：左侧 Activity Bar（波形监视 / 逐键校准 / 连接 / 设置，竖排文字标签、无 emoji 的平面设计）+ Sidebar 面板（注册式结构，后续加插件面板只需加一项）+ 中央波形编辑区（含时基/量程/清屏/导出工具条）+ 底部状态栏（连接、扫描率、接收、吞吐、丢帧、校验、协议、主题快切）；提供 VSCode Dark / VSCode Light / Arduino / CubeMX / EVA 五套主题并用 localStorage 记忆选择，EVA 主题为粗衬线（宋体/明体）+ 初号机紫绿配色；界面文本已中文化（baseline→静止电压、press→触发、release→释放、RX→接收、CRC→校验）；
- ✅ 校准面板加入每通道竖直电平条可视化：灰色轨道（0–3300mV）+ 实时电压游标 + 静止电压基准线 + 满行程动态范围填色 + 触发/释放阈值线，校准过程一目了然；
- ✅ 固件端 Issue D 命令协议已实现：`hall_telemetry` 新增低优先级 RX 线程 + `MK` 命令帧解析（CRC 校验）+ 命令执行（cmd=0x01 应用每键阈值 / 0x03 保存 NVS / 0x04 恢复默认，GET 留待后续），`kscan_adc_mux` 判定改为优先用每键阈值（未校准时回退 DT 全局默认），阈值经 settings/NVS 持久化（`hall/thresholds`，上电自动加载），应答帧用独立 `AK` magic（type=0x11，避免与遥测数据帧 `MK` 混淆）并经统一 TX 线程发送；本机无 west/Zephyr SDK，完整编译与实机联调待 CI/硬件验证；
- ✅ **上位机 UI 二次重构，仔细对照 VSCode 真实结构重做**（2026-07-31）：在上一版"配色像 VSCode"的基础上，把**布局骨架**也换成 VSCode 的真实分层——新增顶部 Title Bar（菜单栏 + 窗口标题）；Activity Bar 图标从竖排文字换成真正的线性 SVG 图标，并加上"已连接"绿点徽标；Sidebar 标题栏改为 VSCode Explorer 风格（大写小字号 + 右上角操作图标），内容按`▾ 可折叠 Section`组织（点击箭头展开/收起，带旋转动画），并加了可拖拽调宽的分隔手柄；Editor 区加上 Tabs 栏（`waveform.scope`，含修改点圆点）与 Breadcrumb 面包屑（`megknob-configurator › telemetry › waveform.scope`）；新增底部 Panel（对标 VSCode 的 Terminal/Problems 面板），把校准结果表格移到这里，并新增"日志"页签做带时间戳的操作日志（命令下发/失败都会记一行），面板支持 Tab 切换与折叠；校准侧栏新增①-④步骤清单（当前步骤高亮、已完成步骤打勾划线），随校准流程实时联动；主题面板新增可点击的调色板缩略图（thumbnail swatch），点击即切换，与原有下拉框互相同步；同时补上网页端"保存到 NVS"（cmd=0x03）与"恢复默认"（cmd=0x04）两个按钮，复用固件已实现的命令协议，命令帧构建从"只会拼 SET_THRESHOLDS"泛化成通用的`buildCommandFrame(cmd, payload)`；全部 CSS 变量按官方 Theme Color 命名习惯重新梳理（`--titlebar-*`、`--tab-*`、`--panel-*`、`--list-active-*`等），五套主题（VSCode Dark/Light、Arduino、CubeMX、EVA）逐一配齐新增的每一个变量；用 Chrome headless + CDP 脚本跑了一遍面板切换/主题切换/Section 折叠/底部面板折叠/演示模式全流程校准（含 NVS 命令）的端到端验证，全程 0 条 console 报错、0 个异常。

**验收标准**

- 校准后所有键在相同物理行程（如同一把直尺压到同一深度）触发，主观手感一致；
- 校准数据断电保留，重新上电无需重新校准；
- 恢复默认值后回到全局阈值行为；
- 校准过程不丢波形帧、不影响 HID/BLE 输入。

---

## 中期目标：参数化配置与产品化外设

上一阶段（正交编码器 + 网页上位机基础链路）已完成，当前短期目标聚焦"逐键校准"（见上），其依赖的双向协议即 Issue D。这里的条目在完整可用之前不阻塞当前短期目标，可以按硬件到货和验证进度并行推进。

### Issue C：恢复完整键位与蓝牙/输出功能层 🚧

- 按 `MEG_MAPPING.md` 恢复全部确认存在的磁轴键（当前只有 MEG0–MEG18，不要把 24 采样槽位误当成 24 个已装按键）；
- 恢复滚轮按下与（Issue A 完成后的）旋转绑定；
- 设计至少一个功能层：蓝牙 profile 选择/清除配对、USB/BLE 输出切换、RGB、调试功能；
- 做逐键 pressed/released 日志，核对矩阵位置、键帽标识和发送键码；
- 处理滚轮按下位置 19 与 Hall viewer 模式切换的功能冲突：调试固件保留切换，日用固件关闭切换、交给 keymap；
- 验证 USB/BLE 输出切换前后不残留 modifier 或卡住普通键。
- 🧊 **非阻塞项**：评估在连接状态变化（USB 拔出、BLE 断开）时主动触发一次全键释放，覆盖"设备未被显式 disable，但连接已断开"的场景；目前 `kscan_adc_mux_disable()` 路径已覆盖断连/disable 场景，且 2026-07-29 实测未复现卡键，此项优先级下调。

### Issue D：网页上位机参数读写协议（首个落地命令 = 每键阈值下发）

- 在 Issue B 只读实时波形的基础上，新增主机到设备命令：读取配置、写入配置、保存 NVS、恢复默认值、开始/停止遥测；
- 命令帧格式（2026-07-30 网页端已定稿组装）：`'M' 'K'` + version(3) + type(0x10=命令) + command + payload length + payload + CRC-16/CCITT-FALSE；首个命令 cmd=0x01"设置每键阈值"payload=24×(press:u16le, release:u16le)=96 字节，整帧 104 字节；设备→主机 ACK 帧格式与错误码待固件实现时一并定义；
- **首个落地命令是每键 press/release 阈值的读取 / 写入 / 保存 / 恢复默认**：baseline 采样与阈值计算都在网页端完成（见"短期目标"），固件只接收最终阈值，不实现校准模式或采样状态机；随后再扩展 debounce 时间、扫描率等参数；
- Rapid Trigger 仍留到长期目标；
- RAM 试用与 NVS 持久化分开，避免拖动滑块/校准时频繁写 Flash；
- 固件端做最终范围校验，网页端校验不能替代固件校验。

**Issue D 进度（2026-07-30）**

- ✅ 命令帧格式定稿（见上），网页端已能组装并发送 SET_THRESHOLDS；
- ✅ 固件端命令链路已实现：RX 线程 + 帧解析 + SET_THRESHOLDS（应用每键阈值到 RAM）/ SAVE_NVS（写 `hall/thresholds`）/ RESET_DEFAULTS（回退 DT 默认）+ `AK` 应答帧 + NVS 上电加载；`kscan_adc_mux` 已改用每键阈值；
- ⏳ GET_THRESHOLDS 回读、ACK 错误码细化、阈值范围校验、网页端 ACK 解析与"已应用"反馈：留待联调；
- ⏳ 完整编译与 USB/BLE 并发实机验证：本机无 Zephyr SDK，待 CI/硬件。

### Issue E：与 ZMK Studio 集成评估

- USB HID 与 BLE 稳定后，单独构建 ZMK Studio 实验固件（`studio-rpc-usb-uart` snippet + `CONFIG_ZMK_STUDIO=y`）；
- 验证 MegKnob 现有 physical layout 能被 Studio 正确识别；
- 评估 Studio 新增的 Flash/RAM 开销、CDC endpoint 和 Hall 遥测流的冲突，冲突时选择独立接口或明确的多路复用协议，不裸接在同一字节流上；
- `&studio_unlock` 只放在功能层，避免设备长期可写。

### Issue F：点亮并集成 0.91 寸 128×32 OLED

- 仓库目前没有 OLED/SSD1306/I2C 屏幕节点；nice_nano 标准 `pro_micro_i2c`（P0.17/SDA、P0.20/SCL）当前未被 MegKnob 占用；`knob_goblin` 是最接近的成熟范例；
- 写设备树前先人工核对：控制器确为 SSD1306、I2C 地址 0x3C/0x3D、供电电压、是否有 Reset 引脚、PCB 预留是否真的接到 P0.17/P0.20；
- 实施顺序：核对丝印/手册 → 断电测通断 → I2C 扫描定地址 → overlay 加 `solomon,ssd1306fb` 节点 → 先做清屏/像素测试 → 接入 ZMK 内置 status screen（先 layer/output）→ 加电量/profile → 需要时做 MegKnob 专用状态页 → 加 blank-on-idle；
- 128×32 布局建议：左侧层/模式、中间 USB/BLE 图标+profile、右侧电量；不在小屏上画 24 路波形，交给网页上位机；
- 验收：冷启动/USB/电池启动均可靠初始化；显示不错位不花屏；屏幕更新不拖慢 Hall scan 或导致 BLE 掉线；idle 后按预期熄屏；连续运行 8 小时无 I2C 错误。

### Issue G：恢复电池、功耗与无线稳定性

- 核对硬件是否有可用电池电压采样节点，再决定是否开 `CONFIG_ZMK_BATTERY_REPORTING`；
- 测量 BLE 广播/已连接静置/持续输入三种状态功耗；
- 评估 RGB、连续 ADC 扫描、CDC 遥测对续航的影响；
- 设计空闲分级：活跃高扫描率、短空闲降频、长空闲进入 ZMK sleep；
- 恢复睡眠前验证 ADC mux 驱动 enable/disable、唤醒源和首次采样可靠；
- BLE 压力测试至少 8 小时，含多次超距断开/回范围自动重连；
- 验收：无线长测不崩溃不持续掉线；睡眠唤醒无首键丢失/卡键；电量报告与万用表实测趋势一致。

### 中期目标完成判定

- USB HID 与 BLE HID 均可独立使用，CDC 遥测不影响键盘输入；
- 全部实际键位、滚轮按下、正交旋转、modifier 和多键组合通过测试；
- 配对、重连、profile、输出切换、清除配对均可恢复；
- 网页上位机能稳定显示实时波形，完成基础参数读取/临时应用/持久化/恢复默认值；
- OLED 可靠显示层/输出/profile 状态，idle blank、功耗、长时间稳定性通过；
- 至少一次 8 小时 BLE/OLED 稳定性测试、一次 10 分钟全通道波形对照通过；
- 有日用固件与诊断固件的明确构建方式，有可回退的稳定 UF2 和对应 Git 版本。

---

## 长期目标：从"能输入"发展为完整的无线磁轴键盘平台

### 1. 逐键校准与统一行程模型（基础版已提前为当前短期目标）

> 基础逐键校准（每键阈值下发）已提前为当前"短期目标"；以下为固件端归一化行程等长期增强项。

- 为每个实际磁轴键保存释放电压、按到底电压、方向、死区和噪声；
- 将不同传感器的毫伏值归一化为 0–100% 行程；
- 校准数据写入 settings/NVS，提供恢复默认值和重新校准流程；
- 检测磁铁方向错误、传感器失效、动态范围过小和相邻通道串扰。

### 2. 可配置触发点与 Rapid Trigger

- 第一阶段实现固定行程触发点和独立释放点；
- 第二阶段实现 Rapid Trigger：根据局部极值和反向移动量动态触发/释放；
- 支持每键参数、最小变化量、噪声门限和安全滞回；
- 使用已录制波形做离线回归，再进入 HID 实机测试；
- 对慢按、快速连击、半程抖动、压住微动、多键同时动作建立自动测试集。

### 3. 网页配置器、运行时配置与诊断产品化

- 形成正式的 MegKnob Web Configurator，响应式键盘布局、逐键选择、实时状态反馈；
- 触发点、RT 灵敏度、校准、扫描率、RGB、OLED、调试流开关做成可持久化配置；
- 通用 keymap/层/behavior 用 ZMK Studio，磁轴参数与实时波形用 MegKnob 专用页面；
- 参考 VIA/Vial 的设备连接和键位编辑流程，参考 Wootility/Keychron Launcher 的触发点/RT/校准 UX，不复制闭源实现；
- 为协议建立版本协商、能力发现、配置 schema 版本和迁移机制；
- 保留协议 v3 诊断能力，支持按需启动/通道选择/降采样，避免无线日用模式持续输出高频帧；
- 增加逐键校准向导、质量评分、波形回放、配置导入导出和一键恢复；
- 长期评估 PWA 与原生壳，覆盖不支持 Web Serial/Web Bluetooth 的平台。

### 4. OLED 产品化

- 为 128×32 单色屏设计 MegKnob 专用紧凑状态页；
- 支持层、USB/BLE 输出、profile、电量、Caps Lock、校准和错误提示；
- 采用事件驱动刷新和脏区域更新，避免无变化时持续渲染；
- 提供屏幕亮度、超时、翻转方向和关闭选项；
- 对烧屏、I2C 恢复、睡眠唤醒和固件升级状态建立测试。

### 5. 功耗自适应扫描

- 输入活跃时保持约 1000 Hz；
- 短时间静止后降低扫描频率；
- 更长空闲后关闭不必要外设并进入 ZMK sleep；
- 用唤醒后的快速预扫描避免第一键丢失；
- 在延迟、噪声、BLE 射频调度和续航之间形成量化策略。

### 6. 可靠性与可制造性

- 建立 24 通道开机自检：断路、短路、饱和、固定 0 V、动态范围异常；
- 针对 U28 这类焊接故障设计生产测试点和自动测试流程；
- 固化 PCB 版本、元件型号、传感器方向、4051 Enable 连接和 ADC 映射；
- 建立版本化固件、配置迁移和恢复机制；
- 最终形成可重复制造、校准、刷写和验收的完整流程。

---

# 开发日志（倒序，按天折叠）

> 下方"已完成 Issue 归档"保存从顶部 roadmap 移入的已收官 Issue 完整记录，仅作存档，不代表当前工作；当前推进见上方"短期目标"。按天的开发日志在归档之后。

## 已完成 Issue 归档

<details>
<summary><strong>Issue A</strong>：滚轮 A/B 相迁移为正交编码器 ✅（2026-07-29 实现 / 2026-07-30 实机验收）</summary>

**问题结论**

原 `kscan_wheel` 是 1×3 GPIO 矩阵：`ROW1=P1.11`（公共），`COL0=P1.00`（按下）、`COL1=P0.11`（A 相）、`COL2=P0.24`（B 相）。A/B 两相曾被当成两个独立矩阵键（`RC(3,1)`/`RC(3,2)`，绑定 `RGB_EFF`/`RGB_BRI`），机械编码器每次转动 A、B 两相都会依次翻转，当成普通键处理时一次旋转必然同时触发两个方向的事件。正确方向只能由 `00 → 01 → 11 → 10` 或反向序列判断，需要 ZMK 的 `alps,ec11` 正交解码器，不是换键码能解决的问题。

**实现结果（2026-07-29）**

- `P0.11`/`P0.24` 已从 `kscan_wheel` 移出，新增 `wheel_encoder`（`alps,ec11`）和 `zmk,keymap-sensors`；
- `kscan_wheel` 已缩为仅保留 `P1.00`/`P1.11` 的 1×1 按下矩阵；
- 已启用 `CONFIG_EC11` 与全局触发线程；滚轮旋转默认绑定音量增减；
- `megknob_transform`、keymap 和 `MEG_MAPPING.md` 已同步移除 A/B 两个伪矩阵键位。

**实机修复与验收（2026-07-30）**

- 首版正交固件中，滚轮按下可以切换 RGB，但旋转完全没有响应。根因是 EC11 的 A/B 相由驱动异步采样，而公共端 `P1.11` 仍由 1×1 矩阵扫描短暂驱动，无法为 A/B 提供稳定参考；A/B 也没有上下拉；
- 将 `P1.11` 改为 GPIO hog 持续输出高电平，`P0.11`/`P0.24` 改为带下拉的 active-high EC11 输入；
- 滚轮按下 `P1.00` 从矩阵扫描改为 `zmk,kscan-gpio-direct` active-high 下拉输入，按下仍绑定 `RGB_TOG`；
- 修复后旋转方向与音量加减均可识别，但初始 `triggers-per-rotation = <20>` 需要旋转约 2～3 个机械刻度才触发一次；
- 将 `triggers-per-rotation` 提高到 `<40>` 后，每个最小机械刻度均能正常响应，编码器实机验收通过；
- 最终保留 `steps = <80>`、`triggers-per-rotation = <40>`。若未来更换不同规格编码器，需要按其每圈机械刻度和正交边沿数重新校准。

</details>

<details>
<summary><strong>Issue B</strong>：网页上位机 MVP（Web Serial + CDC ACM 数据回传）✅（2026-07-29 实现 / 2026-07-30 实机在用）</summary>

**实现结果（2026-07-29）**

- overlay 已加入独立 `zephyr,cdc-acm-uart` 节点，并通过 `zmk,hall-telemetry-uart` chosen 节点连接遥测模块；`megknob.conf` 已启用 `CONFIG_HALL_TELEMETRY`；
- 新增 `hall_telemetry` 模块：在独立的 `K_LOWEST_APPLICATION_THREAD_PRIO` 线程中发送 62-byte 协议 v3 帧；扫描侧只做 `K_NO_WAIT` 有界队列入队，队列满时丢弃最旧样本，避免 CDC 反压影响 Hall 扫描、HID 或 BLE；
- `kscan_adc_mux_read()` 在完成整轮 24 通道采样后提交 mV 数据，不新增采样线程或 mutex；CRC-16/CCITT-FALSE 查表实现已与网页端逐位算法随机数据交叉验证一致；
- 新增 `tools/megknob_web_configurator/`：提供 Web Serial 连接/断开、Web Worker 帧解析、24 路 Canvas 波形、通道开关与统计、扫描率/RX 帧率/CRC/序号丢帧指标及 CSV 导出。

**GitHub 方案调研结论**

成熟键盘网页工具大致分两类，但没有项目能直接满足"ZMK + 磁轴逐键参数 + 实时波形"：

| 方案 | 地址 | 可借鉴内容 | 对 MegKnob 的限制 |
|---|---|---|---|
| ZMK Studio | <https://github.com/zmkfirmware/zmk-studio> / <https://zmk.studio/> | 官方运行时 keymap 编辑、USB 串口与 BLE 配置入口 | 不支持磁轴校准、触发点、实时波形，不能注入自定义页面 |
| ZMK custom Studio RPC 模板 | <https://github.com/cormoran/zmk-module-template-with-custom-studio-rpc> | 自定义固件 RPC 与 Web 客户端范式 | 需要自己设计 RPC 与 UI |
| VIA | <https://github.com/the-via/app> | 成熟 WebHID 配置器架构 | 面向 QMK/VIA，不兼容 ZMK |
| Vial | <https://github.com/vial-kb/vial-gui> | 动态 keymap、宏和参数编辑 UX | 面向 QMK/Vial，不兼容 ZMK |
| ZMK keymap-editor | <https://github.com/nickcoutsos/keymap-editor> | ZMK keymap 网页编辑体验 | 编辑配置文件，非实时磁轴工具 |
| Wootility / Keychron Launcher | 厂商工具 | 触发点/RT/校准 UX 参考 | 闭源，只能参考交互，不能复制实现 |

采用**双轨架构**：通用键位/层/behavior 走官方 ZMK Studio；磁轴专用功能（实时波形、触发点参数）走 MegKnob 专用 Web Configurator，第一版通过 Chromium Web Serial 直接复用 v3 数据流。

**协议设计原则**

- 保留现有 v3 DATA/MODE/PERF 帧定义，不破坏 `tools/megknob_hall_viewer.py` 的解析逻辑；
- 遥测使用有界缓存和丢旧策略；实时数据不追求可靠传输，UI 展示为主。

**连接架构（2026-07-30 实机确认）**

- HID 走 BLE（无线）或 USB HID，遥测走 USB CDC ACM；网页上位机基于 Web Serial，**只能访问本机 USB 串口，无法通过 BLE 连接**——因此"无线打字 + 插线看波形"是当前标准用法，看波形必须插 USB 线；
- 若未来要不插线看波形，需改用 Web Bluetooth：固件把遥测经自定义 BLE GATT characteristic 以 notify 推送并做降采样（见长期目标 3）；BLE 带宽有限，不适合日常持续输出高频波形，只做按需诊断；
- 实机已验证 HID(BLE) + CDC(USB) 共存、24 路波形实时刷新正常。

**实机验收结果**

- ✅ USB 同时识别键盘 HID 与 CDC 串口，两者互不干扰；
- ✅ HID 经 BLE 输入、CDC 经 USB 输出波形可同时工作，未见 BLE 掉线或输入延迟劣化；
- ✅ Chrome/Edge 能稳定连接、断开、重新连接网页；
- ✅ 24 路波形实时刷新正常；
- 🧊 30 分钟内存长测、与 Python 上位机数值逐帧对照：降级为长期加固项。

</details>

---

<details>
<summary><strong>2026-07-30</strong>：短期目标收尾——网页上位机连接架构确认与逐键校准立项</summary>

## 短期目标完成确认

- Issue A（滚轮正交编码器）：实机验收通过（见下一条 07-30 日志）；
- Issue B（网页上位机 MVP）：网页端已能实时看到 24 路波形，HID 与遥测共存正常，短期目标整体完成。

## 网页上位机连接架构（回答"是否必须插 USB"）

当前遥测链路是：固件 `hall_telemetry` → USB CDC ACM 虚拟串口 → 浏览器 Web Serial。Web Serial 只能访问本机 USB/串口设备，**无法通过 BLE 连接**，所以：

- HID：走 BLE（无线）或 USB HID，可纯无线打字；
- 波形/遥测：必须插 USB 线才能看；
- 即"无线打字 + 插线看波形"是当前标准用法，两者互不干扰。

若要不插线看波形，需改用 Web Bluetooth：固件把遥测经自定义 BLE GATT characteristic 以 notify 推送并降采样。但 BLE 带宽有限，持续高频波形会挤占 HID 与续航，只适合按需诊断，列为长期目标 3，不在当前做。

## 手感不一致根因与逐键校准立项

用户反馈多键手感不一致。定位为 `kscan_adc_mux.c` 用全局统一绝对阈值（press 1000mV / release 1300mV）判定所有通道，而各磁轴键 baseline 与动态范围天然不同，统一阈值相对各键的距离不一，导致灵敏度参差。根治需逐键校准 + 归一化行程（0–100%），已从长期目标 1 提前为"当前焦点"，其双向命令通道复用 Issue D 协议，校准作为该协议首个落地命令。

</details>

<details>
<summary><strong>2026-07-30</strong>：EC11 公共端修复与滚轮分辨率实机校准完成</summary>

## 现象

首版 `alps,ec11` 正交编码固件中，按下滚轮可以正常切换 RGB，但旋转没有音量事件。调整电气模型后旋转恢复，但最初需要转动约 2～3 个机械刻度才触发一次音量变化。

## 根因与修复

编码器的 A 相 `P0.11`、B 相 `P0.24` 和按下 `P1.00` 共用 `P1.11`。旧配置仍把 `P1.11` 当作按键矩阵行，只在矩阵扫描期间短暂驱动；EC11 驱动却会异步采样 A/B，因此公共端电平不稳定，A/B 也缺少确定的默认电平。

最终配置：

- `P1.11`：GPIO hog，持续输出高电平；
- `P0.11` / `P0.24`：active-high + pull-down，由 `alps,ec11` 解码；
- `P1.00`：active-high + pull-down，由 `zmk,kscan-gpio-direct` 扫描按压；
- 旋转绑定 `C_VOL_UP` / `C_VOL_DN`，按下保留 `RGB_TOG`；
- `steps = <80>`，`triggers-per-rotation = <40>`。

## 实机结果

- 正反方向和音量功能正常；
- 最小机械刻度可以产生一次响应，不再需要连续转动 2～3 格；
- 滚轮按下仍可切换 RGB；
- EC11 正交编码器 Issue 完成。

</details>

<details>
<summary><strong>2026-07-29</strong>：刷入消抖修复固件实测通过，串键/鬼键/modifier 卡键三类问题清零</summary>

## 刷入消抖修复固件实测通过，串键/鬼键/modifier 卡键三类问题清零

### 验证方式

按 `c16fcc5c`（`kscan_adc_mux` 接入 `zmk_debounce` + `physical_layouts.c` 丢事件日志 + 事件队列扩容到 16）与后续 `495dbb36`（clang-format 修正）重新本地编译 `nice_nano_v2` 固件，通过 UF2 方式刷入实机，替换此前的稳定基线固件，进行日常正常使用（非受控实验室条件，覆盖打字、组合键、长时间连续使用）。

### 结果

- **未再出现串键**：延续 2026-07-27 `33fdd7a2` 的映射修正结果，本次固件同样没有复现按键映射错位的问题；
- **未再出现鬼键**（非预期的额外按键事件）：此前怀疑的 Hall 轴阈值附近抖动触发的多余 press/release 事件，在消抖生效后没有再观察到；
- **未再出现 modifier 卡键**：这是本次验证的重点——2026-07-28 定位的根因（`kscan_adc_mux_pressed()` 无消抖 + `physical_layouts.c` 事件队列静默丢包 → modifier 引用计数失衡）在实测中得到正面验证，长时间正常使用、不刻意断电断连的情况下 Ctrl/Alt/Win 均未再出现卡在"按下"状态的现象。

### 结论

至此，路线图里三类已知的 Hall 轴输入正确性问题——**映射错位串键**（`33fdd7a2` 修复）、**阈值抖动引发的鬼键/误触发**、**事件队列丢包引发的 modifier 卡键**（`c16fcc5c` 修复）——均已完成实机验证，相关能力移入路线图"已完成的基础能力"，不再作为独立 Issue 跟踪。

评估在连接状态变化时主动触发全键释放这一项，目前没有实测证据表明是当前卡键问题的必要修复项，作为非阻塞的长期稳定性加固项保留（Issue C 中标注 🧊）。

`CONFIG_ZMK_LOG_LEVEL=DBG` 下核对"kscan 事件队列丢弃 `LOG_ERR` 是否完全消失"尚未专门测过，后续如果想进一步确认消抖参数（15 ms）和队列容量（16）是否有足够裕量，可以补一次 DBG 日志观察，但不阻塞当前推进节奏。

### 路线图影响：短期目标工作重心前移

三类输入正确性问题清零后，短期目标的工作重心正式前移到：

1. **Issue A：滚轮正交编码器**——当前唯一还未开工、且会阻塞"全键位日用固件"定稿的输入模型缺陷；
2. **Issue B：网页上位机 MVP**——用户明确要求这次一并推进，需要重新给固件接入 CDC ACM + 协议 v3 数据回传；
3. Issue C（完整键位/输出切换）、Issue F（OLED）、Issue G（功耗）移入中期目标，可与短期目标并行或其后推进。

</details>

<details>
<summary><strong>2026-07-28</strong>：modifier 卡键真正根因是抖动误触发 + 事件队列丢包，与断连无关（Know-How）</summary>

## modifier 卡键真正根因是抖动误触发 + 事件队列丢包，与断连无关（Know-How）

### 用户反馈纠正了之前的假设

2026-07-27 的分析把 modifier 卡键完全归因于"断电/断连时 `kscan_adc_mux_disable()` 不清空按键状态"。修复合入后，用户反馈：**不拔 USB 电源、设备全程保持连接的情况下，同样会出现卡键**。这说明断连只是可能触发卡键的场景之一，而不是根因——真正的问题一定出在"扫描仍在正常运行"这条主路径上。

### 根因定位

问题出在两处叠加：`kscan_adc_mux` 驱动没有消抖，加上 `physical_layouts.c` 的事件队列会静默丢事件。

**1. `kscan_adc_mux_pressed()` 的阈值判断完全没有消抖**

```48:57:app/module/drivers/kscan/kscan_adc_mux.c
static bool kscan_adc_mux_pressed(const struct kscan_adc_mux_config *config, bool was_pressed,
                                  int32_t sample_mv) {
    if (config->press_is_greater) {
        return was_pressed ? sample_mv > config->release_threshold_mv
                           : sample_mv > config->press_threshold_mv;
    }

    return was_pressed ? sample_mv < config->release_threshold_mv
                       : sample_mv < config->press_threshold_mv;
}
```

`megknob.overlay` 配置 `press-threshold-mv = 1000`、`release-threshold-mv = 1300`，`polling-interval-ms = 5`，即每 5 ms 完整扫描一次全部 24 个通道，采样值一旦跨过阈值就立刻触发回调，**没有连续 N 次确认**的消抖逻辑。值得注意的是，路线图历史记录的阈值是"连续 3 次扫描确认"，说明这个消抖机制在某次重写/回退中被丢失了，而不是从来没有过。

Hall 轴电压在按下/释放阈值附近，哪怕手指静止不动，也会因为机械微振动、磁体轻微晃动、ADC 量化噪声等原因在阈值两侧反复穿越。一旦发生，驱动会以 5 ms 扫描速率连续产生 press/release 交替事件，而不是一次干净的按下。

**2. `physical_layouts.c` 的 kscan 事件队列会静默丢事件**

```266:279:app/src/physical_layouts.c（修复前）
static void zmk_physical_layout_kscan_callback(const struct device *dev, uint32_t row,
                                               uint32_t column, bool pressed) {
    if (dev != active->kscan) {
        return;
    }

    struct zmk_kscan_event ev = { ... };

    k_msgq_put(&physical_layouts_kscan_msgq, &ev, K_NO_WAIT);
    k_work_submit(&msg_processor.work);
}
```

`physical_layouts_kscan_msgq` 容量由 `CONFIG_ZMK_KSCAN_EVENT_QUEUE_SIZE` 决定，默认只有 **4**。`k_msgq_put(..., K_NO_WAIT)` 在队列满时会直接返回错误、事件被丢弃，且原代码完全不检查返回值，没有任何日志。

**3. 两者叠加导致 modifier 引用计数永久失衡**

`app/src/hid.c` 里 modifier 的按下/释放是带引用计数的（`explicit_modifier_counts[8]`）：

```53:76:app/src/hid.c
int zmk_hid_register_mod(zmk_mod_t modifier) {
    explicit_modifier_counts[modifier]++;
    ...
}

int zmk_hid_unregister_mod(zmk_mod_t modifier) {
    if (explicit_modifier_counts[modifier] <= 0) {
        LOG_ERR("Tried to unregister modifier %d too often", modifier);
        return -EINVAL;
    }
    explicit_modifier_counts[modifier]--;
    ...
}
```

如果某个 modifier（如 Ctrl）对应的 Hall 通道在阈值附近抖动，短时间内产生的 press/release 事件数超过队列的 4 个槽位，一旦某次 **release 事件被挤掉、而对应的 press 事件被处理**，计数就会多加 1 且没有人再减它，`explicit_modifiers` 对应 bit 永远不会被清零——表现为 Ctrl/Alt/Win 卡在"按下"状态，且与 USB/BLE 是否断开完全无关，这与用户的实际观察完全吻合。

### 修复

1. **`kscan_adc_mux.c` 接入 ZMK 官方 `zmk_debounce` 库**（`app/module/lib/zmk_debounce`，与 `kscan_gpio_matrix`/`kscan_gpio_direct` 等驱动使用同一套"连续确认"消抖算法），把瞬时阈值判断结果喂给 `zmk_debounce_update()`，只有确认状态真的翻转（`zmk_debounce_get_changed()`）才触发回调，从源头抑制阈值附近的高频抖动误触发；
2. 新增 devicetree 属性 `debounce-press-ms`/`debounce-release-ms`（默认 5ms，`megknob.overlay` 显式设为 **15ms** ≈ 3 次扫描确认），Kconfig 里 `ZMK_KSCAN_ADC_MUX` 增加 `select ZMK_DEBOUNCE`；
3. `kscan_adc_mux_release_all()`（断连/disable 时补发释放事件）同步清空消抖状态，避免 disable/enable 循环后残留半确认的过渡状态；
4. `physical_layouts.c` 里两处 `k_msgq_put(..., K_NO_WAIT)` 改为检查返回值并在丢事件时打印 `LOG_ERR`，把原本的静默失败变成可诊断的日志；`K_NO_WAIT` 本身保留不改，因为这个回调在某些 kscan 驱动下可能来自中断上下文，不能阻塞；
5. `megknob.conf` 把 `CONFIG_ZMK_KSCAN_EVENT_QUEUE_SIZE` 从默认 4 调到 **16**，作为消抖之外的第二道安全边际，应对滚轮+按键同时动作等突发多事件场景。

### 影响范围与验证方式

- 修复只影响 `kscan_adc_mux` 驱动本身和 `megknob` shield 的配置，`zmk,kscan-adc-mux` 目前只有 `megknob` 一个使用方，不影响其它 board/shield；
- 本地没有 west/Zephyr SDK/Docker 工具链，无法本地交叉编译验证，已完成的静态验证包括：clang-format 格式检查（`.clang-format` 规则）、`zmk/debounce.h` 的 include 路径与 `CONFIG_ZMK_DEBOUNCE` 的 CMake/Kconfig 链接路径逐项对照官方 `kscan_gpio_matrix.c`/`kscan_gpio_direct.c` 的用法确认一致；实际编译结果依赖 push 后的 GitHub Actions CI（`zmkfirmware/zmk-build-arm:4.1` 容器）；
- 验收时建议开 `CONFIG_ZMK_LOG_LEVEL=DBG`，重点关注：（1）新增的 kscan 事件队列丢弃 `LOG_ERR` 是否还会出现；（2）手指停在按键临界行程附近时是否还会看到连续的 press/release 抖动日志；（3）长时间正常使用（不断电不断连）是否还会复现 modifier 卡键。

</details>

<details>
<summary><strong>2026-07-27</strong>：断连/断电卡键分析 + Hall 按键矩阵映射修正</summary>

## 断连/断电后 Ctrl、Alt、Win 卡键问题分析（Know-How）

### 现象

按键映射修正后（见下一条日志），键盘功能验证正常。但接上电脑使用一段时间后，如果直接给键盘断电（拔 USB 或电池耗尽/移除），电脑上的一些操作会被"卡住"，表现类似 `Ctrl`、`Alt`、`Win` 一直处于按下状态；断电后必须在物理上把这几个键各按一下并保持一会儿，系统才会恢复正常。

### 根因定位

`LEFT_CTRL`、`LGUI`（Win）、`LALT` 在 MegKnob 上都不是普通机械矩阵键，而是走 `kscan_adc_mux` 的 Hall/磁轴 ADC 阈值判断（见 `MEG_MAPPING.md`：`MEG16/LEFT_CTRL`、`MEG17/WIN`、`MEG18/ALT`）。问题出在驱动和主机 HID 状态机的交互上：

1. **驱动没有"断连时清空按键状态"的机制。**

```160:163:app/module/drivers/kscan/kscan_adc_mux.c
static int kscan_adc_mux_disable(const struct device *dev) {
    struct kscan_adc_mux_data *data = dev->data;

    return k_work_cancel_delayable(&data->work) < 0 ? -EIO : 0;
}
```

`disable_callback` 只是取消了周期扫描的 `k_work_delayable`，`matrix_state[]` 里记录的"当前哪些位置处于按下状态"完全没有清零，也没有在关闭前补发一次"全部释放"的回调。如果 USB/电源被拔掉的瞬间，`matrix_state[]` 里恰好有 Ctrl/Alt/Win 对应的位置是 `true`（按下），设备发给主机的最后一份 HID 报告里这几个 modifier bit 就是 1。

2. **主机没有后续报文可以清除这个状态。** 键盘一旦掉电/断连，不会再发送任何 HID 报告。标准 USB HID 协议下，主机只能依赖设备主动上报的"释放"事件来清除按键状态；设备既没有正常发送 release 报告，也没有一个"设备已断开，清空所有按键"的兜底机制，所以操作系统会一直认为这几个 modifier 是被摁着的，直到用户重新按一次对应的物理键，产生新的按下/释放沿，才能把状态"掰回来"。
3. **Hall 轴在掉电边沿容易产生瞬态误判，放大了这个问题。** 当前配置 `press-threshold-mv = 1000`、`release-threshold-mv = 1300`、`press_is_greater = false`（电压走低代表按下）。断电/拔线瞬间，ADC 参考电压、供电轨或悬空输入的电位变化速度往往快于扫描任务的正常退出，容易让某一次采样"看起来"低于按下阈值，被误判为按下，而这次误判恰好没有机会被后续扫描纠正（因为设备本身正在关闭）。
4. **ZMK 上游的通用 kscan 矩阵驱动也没有强制的"断连清空"语义**，这不是 MegKnob 独有的缺陷。对普通机械轴矩阵而言，物理开关断电后立刻恢复"断路"状态，被下一次上电扫描直接读到，不会有历史遗留状态；但 Hall 轴由电压阈值决定状态，断电前的最后一帧状态可能残留在主机侧。

### 尚未落地的修复方向（记录以便下一步实施）

1. 在 `kscan_adc_mux_disable()` 里，对所有 `matrix_state[idx] == true` 的位置主动回调一次 `pressed = false`；
2. 评估在 USB/BLE 连接状态变化时主动触发一次"全键释放"广播，覆盖"设备没有被禁用、但连接已经断开"的场景；
3. 评估给 Hall 轴增加断电检测防护；
4. 补充一个专门的"拔电/拔线卡键回归测试"。

### 影响范围

这次问题因为按键映射刚刚修好、Ctrl/Alt/Win 才第一次被实际使用到，才被观察到；但根因在最早的驱动实现里就已经存在，属于一直潜伏、之前没有测试到的缺陷。

---

## 修正 Hall 按键矩阵映射，串键问题解决

`33fdd7a2 fix(megknob): correct Hall key matrix mapping` 修正了 `megknob.overlay` 中 `megknob_transform` 的 `RC(row,col)` 映射关系，并同步更新了 `MEG_MAPPING.md` 里 MEG 编号与 4051/ADC 通道的对照表。

修正前记录在案的现象（见更早的 `ADC_ISSUE_ANALYSIS.md` 分析）：`Shift → R`、`Z → Space`、`A → F`、`F → TAB + A` 等串键/错键。修正后实测按键映射已经正确，不再出现串键。

结合此前的分析，这类问题的本质是固件里 RC 位置与实际 4051 通道/ADC 输入的对应关系搭错了，而不是采样阈值或扫描时序问题——`press-threshold-mv`/`release-threshold-mv`/`settle-time-us` 等模拟参数在此次修复前后没有变化，纯粹是 `megknob_transform` 的 `map` 顺序和 `MEG_MAPPING.md` 中记录的 MEG↔RC 对应关系被订正。

**Know-How**：涉及多路模拟开关（4051）+ ADC 复用的按键矩阵，`RC(row,col)` 顺序、4051 的 `Y0..Y7` 通道顺序、以及固件里 ADC row 编号三者必须逐一对齐并留档（`MEG_MAPPING.md` 的价值即在于此）；串键现象优先怀疑映射表顺序错位，而不是急于调整模拟采样参数。

</details>

<details>
<summary><strong>2026-07-23</strong>：BLE Controller 构建目标收敛 + RGB/BLE 成功连接 Know-How</summary>

## BLE Controller 与构建目标收敛

MegKnob 的实际 MCU 目标一直是 `nice!nano v2`，核心芯片为 nRF52840。为补齐 BLE 协议栈，`megknob.conf` 显式启用了 `CONFIG_BT_CTLR=y`：`CONFIG_ZMK_BLE` 负责 ZMK BLE HID，`CONFIG_BT` 负责 Zephyr Host，`CONFIG_BT_CTLR` 负责 Link Layer、PHY 与 nRF 无线电控制。

后续 Build workflow 曾自动生成 `MegKnob + RP2040` 等无关组合。根因不是产品使用了 RP2040，而是硬件元数据中的 `requires: [pro_micro]` 只表达插针互连兼容；CI 将它解释为应与所有暴露 `pro_micro` 互连的控制器进行笛卡尔积构建。MegKnob overlay 使用 Nordic 专用 `NRF_PSEL`、SAADC 与 nRF pinctrl，因而这些组合没有产品意义。

本次修正：

1. 保留 `requires: [pro_micro]` 表达物理接口，但在元数据描述中明确目标为 `nice!nano v2 (nRF52840)`；
2. Build matrix 对 MegKnob 仅生成 `nice_nano//zmk` 组合；
3. BLE Know-How 视频改为解释真实硬件栈，不再把 CI 误生成的 MCU 当成产品设计的一部分；
4. Windows 本地构建默认目标仍为 `nice_nano_v2`。

工程结论：连接器兼容不等于 MCU 兼容。对使用 SoC 专有 DeviceTree 宏和外设的 shield，CI 构建目标必须显式收敛到实际支持的控制器。

---

## RGB 闪烁与 BLE 成功连接 Know-How（含失败方案复盘）

### 背景

`3699221f → df656f66 → a7123a1d` 三个提交陆续为 MegKnob 打开 BLE、补齐 Controller、收敛构建目标，但实测下来蓝牙连接和 RGB underglow 表现都不稳定。最终在 `4113e8ba`（`revert(megknob): restore stable BLE keyboard firmware`）上验证通过：**RGB 能正常闪烁、主机能稳定配对并保持连接**。本章记录这次收敛过程中，成功方案具体做对了什么，以及之前几版为什么会失败。

### 最终成功方案（4113e8ba）

**1. Bluetooth Controller 交给 Kconfig 默认依赖链自动 select，不手动显式声明**

```text
CONFIG_ZMK_BLE=y
CONFIG_BT=y
CONFIG_BT_CTLR_PHY_2M=n
```

没有出现 `CONFIG_BT_CTLR=y`。nRF52840 在 Zephyr 里的 BT Controller 是否启用、启用哪一种本身是由 `CONFIG_BT=y` 结合 board 的 defconfig、`CONFIG_BT_LL_SW_SPLIT` 等选项通过 `select`/`depends on` 自动推导出来的。手动显式写 `CONFIG_BT_CTLR=y` 并不会让协议栈更完整，反而可能和自动推导出的组合产生冲突。

真正对连接稳定性起作用的是新加的一行 `CONFIG_BT_CTLR_PHY_2M=n`：显式关闭 2M PHY，只保留 1M PHY 广播/连接。2M PHY 虽然吞吐更高，但对天线布局、主机适配器兼容性要求更高，在早期打样阶段容易表现为"能扫描到设备，但连接后很快断开"或"配对成功但输入不稳定"。

**2. keymap 从两层裁剪回一层，去掉尚未验证稳定的外围绑定**

成功版本的 `megknob.keymap` 只有一个 `default_layer`，且只保留三个最基础的 RGB 绑定：

```dts
&rgb_ug RGB_TOG  &rgb_ug RGB_EFF  &rgb_ug RGB_BRI
```

之前 `3699221f` 引入的 `function_layer` 里塞了 `sensor-bindings`、`&bt BT_SEL 0..4`、`&bt BT_CLR`、`&out OUT_TOG/OUT_USB/OUT_BLE`、5 个 RGB 子命令、`&bootloader` 等十几个绑定，还依赖一个 `sensors` 节点和 `&encoder` 设备树节点。任何一个环节出问题都会表现为"键盘整体不工作"，无法定位具体故障点。回退版本把验证面收窄到"矩阵按键 + 三个 RGB 命令"，才第一次能明确看到 RGB 灯效正常切换。

**3. `kscan_adc_mux.c` 驱动回退到同步阻塞的最简实现**

去掉了此前为 Hall 数据回传新增的：CDC ACM 命令协议（`hall_command_frame`/`hall_stream_frame`）、独立 `k_work_q` 扫描线程、`k_mutex` 保护的运行时配置、settings 持久化、批量 ADC + Gray-code 寻址优化、`timing_*` 性能统计等一整套机制，恢复成"每列依次读取三路 ADC、`k_work_schedule` 周期重触发"的最初版本。这部分代码本身跟 BLE/RGB 没有直接关系，但它引入了额外的线程调度、mutex 竞争和中断驱动的 UART 收发，会挤占 BLE 协议栈需要的 CPU 时间片和优先级窗口。回退后 BLE 和 RGB 才有了一个"干净"的验证环境。

**4. Build workflow 目标同时收敛到 `nice_nano`（非 `nice_nano//zmk`）**

```diff
- if (s.id === "megknob" && b.id !== "nice_nano//zmk") {
+ if (s.id === "megknob" && b.id !== "nice_nano") {
```

避免 CI 矩阵里出现和实际打样硬件不一致的构建目标，保证"验证通过的固件"和"实际刷入板子的固件"是同一份产物。

### 失败方案对比

| 方案 | 关键改动 | 结果 | 失败原因分析 |
|---|---|---|---|
| ① `2d5021a9` 阶段（仅 CDC） | `CONFIG_ZMK_BLE=n`、`CONFIG_BT=n`，keymap 全 `&none` | 不适用（本就未开 BLE） | 作为纯 Hall 采集基线，未涉及无线，仅作为对照 |
| ② `3699221f` 首次开 BLE | 打开 `CONFIG_ZMK_BLE=y`/`CONFIG_BT=y`，未显式处理 Controller/PHY；keymap 一次性加入双层 19+ 个绑定、`sensors` 节点、`encoder` 设备树节点 | 蓝牙连接不稳定，RGB 表现异常 | 变量一次性引入过多，且未处理 PHY 兼容性，无法定位具体故障点 |
| ③ `df656f66` 显式加 Controller | 新增 `CONFIG_BT_CTLR=y`，同时 `a7123a1d` 收紧构建目标，`kscan_adc_mux.c` 又叠加了 CDC 协议栈、独立线程、mutex 等大改 | 仍不稳定 | 显式 `BT_CTLR=y` 未解决根本问题，同时 Hall 驱动的线程/中断改造与 BLE 协议栈抢占 CPU 调度窗口，问题面进一步扩大 |
| ④ `4113e8ba` revert（成功） | 交还 Controller 给 Kconfig 自动 select；显式关闭 `BT_CTLR_PHY_2M`；keymap 收窄到 1 层 3 个 RGB 绑定；`kscan_adc_mux.c` 回退为同步阻塞最简实现；构建目标精确到 `nice_nano` | **RGB 正常闪烁，BLE 稳定配对连接**，CI 均 success | 同一时间只保留"能验证 BLE + RGB"所必需的最小变更集 |

### Know-How 总结

1. **Kconfig 层面，"显式声明"不等于"更正确"。** Zephyr 的 Bluetooth Controller 选择本身有一套通过 SoC/board defconfig 驱动的默认推导逻辑；手动 `select` 一个本该被自动选中的符号，只在明确知道要覆盖默认行为时才有意义。遇到"编译通过但功能不工作"时，优先怀疑更细粒度的行为开关（如 PHY、连接参数）。
2. **PHY 兼容性是 BLE 连接稳定性里容易被忽视的一环。** `CONFIG_BT_CTLR_PHY_2M=n` 这种"退一步换稳定性"的配置，在打样阶段、天线/PCB 尚未做过射频验证时，往往比追求更高吞吐更重要。
3. **调试无线功能时必须控制变量数量。** 一次提交里同时改协议栈配置、keymap 绑定数量、驱动线程模型、CI 构建矩阵，一旦出问题就无法判断是哪一层导致的。
4. **验证用的 keymap 应该比目标 keymap 更简单。** 先验证最小闭环，再逐步加回外围功能，每加一层都单独验证。
5. **外围驱动改造（Hall 数据回传协议、独立线程）应该和无线协议栈验证分开进行。** 两者都会消耗 CPU 调度窗口和中断优先级，应该先确认 BLE/RGB 基线稳定后，再单独引入驱动层的性能优化。**这一条对当前的 Issue B（网页上位机 CDC 回传）直接适用：必须先确认 Issue A/现有 BLE 基线不受影响，再叠加遥测。**

</details>

<details>
<summary><strong>2026-07-20</strong>：1000 Hz 冲刺全过程（协议 v3、CDC 优化、时基修复）</summary>

## 1000 Hz 目标达成

CDC 中断批量发送版本实测结果：

| 指标 | 实测值 |
|---|---:|
| Scan rate | **1216 Hz** |
| 平均完整周期 | **0.822 ms** |
| 周期抖动标准差 | **0.040 ms** |
| RX data frame rate | **1171 fps** |
| USB CDC 吞吐量 | **72907 B/s** |
| 设备扫描主体 `PERF scan_us` | **610 µs** |

吞吐量换算为 `72907 / 62 ≈ 1175.9` 个总帧/秒。固件每 256 次扫描额外发送一个 62-byte performance frame，扣除这部分后与上位机显示的 1171 个数据帧/秒基本一致，证明传输统计自洽。

CDC 从逐字节 `uart_poll_out()` 改为 TX 中断下整帧 `uart_fifo_fill()` 后，完整数据输出稳定跨过 1000 fps，主要传输瓶颈得到解决。Scan rate 1216 Hz 比目标高约 21.6%，0.822 ms 周期比 1.000 ms 预算保留约 178 µs，0.040 ms 抖动约占平均周期 4.9%。

`PERF` 从此前 562 µs 变为 610 µs 不代表 ADC 退化。批量 CDC 改变了扫描线程、USB workqueue 和中断之间的 CPU 竞争关系，测量期间可能被 USB 中断或更高优先级任务抢占。即使按 610 µs 计算，扫描主体理论上限仍约为 1639 Hz，无需继续绕过 Zephyr `adc_read()`。

下一阶段不再追求更高空载频率，优先验证模拟精度、限制目标运行频率、恢复 HID 与 BLE。

---

## CDC 批量发送优化

第二阶段初次实测：scan rate 约 888 Hz，RX 约 862 fps，吞吐量约 53710 B/s，设备端 `PERF scan_us` 约 562 µs。

`1,000,000 / 562 ≈ 1779 Hz`，说明地址切换、settle、八次 ADC batch read 和矩阵处理已经明显超过 1000 Hz。限制位于 CRC、封包、线程调度和 CDC 发送，而不是 4051 或 SAADC。

本地驱动检查确认：

- nRF SAADC 已通过 EasyDMA 将每个地址的三个通道搬运到 RAM；
- CDC ACM 内部已有 1024-byte TX ring buffer 和 USB bulk endpoint；
- 原发送线程对每个 62-byte 帧调用 62 次 `uart_poll_out()`，862 fps 时约为每秒 53444 次逐字节 API 调用。

优化后的发送路径：

1. 发送线程从消息队列取得一帧；
2. 将完整 62-byte 帧放入共享 TX frame 并启用 TX IRQ；
3. TX-ready 回调调用 `uart_fifo_fill()`，通常一次放入完整帧；
4. ring buffer 只能接受部分数据时保留 offset，下一次继续；
5. 完整帧入队后关闭 TX IRQ，并用 semaphore 唤醒发送线程。

该修改保持协议 v3、CRC、ADC 配置和上位机协议不变。构建成功，UF2 大小为 136192 bytes。

---

## 冲击 1000 Hz，第二阶段候选固件

在保留协议 v3、12-bit、无过采样、三通道 ADC batch read 和 Gray-code 扫描的基础上继续压缩开销：

1. SAADC acquisition time 从 5 µs 降至 3 µs；
2. 4051 settle time 从 20 µs 降至 10 µs；
3. work handler 启动后连续扫描，不再每帧重新 reschedule；
4. 每轮完整扫描后执行一次 `k_yield()`，让同优先级 CDC 线程运行；
5. CRC 从逐 bit 算法改为 16 项 nibble 查表；
6. enable/disable 改用原子状态控制。

固件编译成功，UF2 大小为 135680 bytes。验收重点是扫描率、RX fps、`LOSS DEV/UI`、静止噪声、完全按下幅值和相邻通道串扰。3 µs acquisition 与 10 µs settle 均属激进配置，不能以错误采样换取频率数字。

---

## 停止兼容 v2，升级协议 v3

旧版和新版固件曾共同使用协议 v2，但时间戳语义不同：第一版直接换算 32-bit、64 MHz DWT 值，约每 67.1 秒回绕；修复版发送 32-bit 微秒累计值，约每 71.6 分钟回绕。上位机只能猜测固件类型，存在误判风险，因此固件和上位机统一只支持 v3。

v3 时间处理：

1. 固件只换算相邻 DWT 读数之间的短周期差值；
2. 差值先转为纳秒，再累计进 64-bit `timestamp_ns`；
3. 线上发送 `timestamp_ns / 1000` 的低 32 bit，约 71.6 分钟自然回绕；
4. 上位机检测标准 uint32 回绕并精确增加 `2^32 µs`；
5. 删除旧版 67.1 秒启发式兼容逻辑，拒绝非 v3 帧。

升级后必须同时使用 v3 固件和新版上位机。

---

## 长时间运行后时基缩短

### 现象

长时间传输后，可见波形范围明显缩短，甚至不足 100 ms；点击"清屏"后恢复。

### 根因

协议时间戳约每 71.6 分钟正常回绕，但旧版 67.1 秒 DWT 回绕兼容判断位于标准 uint32 判断之前。标准回绕被误判后，上位机只增加 `67,108,864 µs`，而不是 `4,294,967,296 µs`，导致展开时间倒退约 70 分钟，历史缓存残留"未来样本"。

### 修复

1. 优先检查向后跳变量是否大于 `0x80000000`，满足时按标准 uint32 回绕增加 `2^32`；
2. 只有不满足标准回绕时，才进入旧版兼容分支；
3. 随后通过协议 v3 完全删除歧义。

---

## 第一阶段实测与上位机性能修复

第一阶段刷入后，完整 24 通道 scan rate 从约 695 Hz 提升至约 **800 Hz**。

发现的问题：

1. 运行一段时间后曲线逐渐稀疏，清屏后暂时恢复；
2. ALL 24 CH 模式 GUI 负载较高；
3. 原 `DISPLAY LAG` 混入 MCU/PC 时钟漂移，不具有可靠含义。

修复内容：

- 固件累计相邻 DWT 短差值，避免 DWT 自身约 67.1 秒回绕破坏时间轴；
- 历史缓存只保留当前时基约 110%；
- NumPy 转换前将绘图数据限制到约 1000 点，并保留最新点；
- 关闭全局抗锯齿，启用 `clipToView` 与 peak downsampling；
- 通道标签改为每 200 ms 更新，波形仍保持 25 FPS；
- 串口线程记录解码到达时间，`DISPLAY LAG` 改为 GUI 队列等待时间；
- `FRAME LOSS` 改为 `LOSS DEV/UI`，区分协议序号丢帧与 GUI 主动丢旧帧。

上位机语法、PyQt5 离屏窗口和固件构建均通过。

---

## 冲击 1000 Hz，第一阶段

上一版本为 695 Hz，完整扫描周期约 1.44 ms。1000 Hz 要求周期不超过 1.00 ms，需要减少约 0.44 ms。

已完成修改：

1. 协议升级到微秒时间戳，并使用 Cortex-M4 DWT 计时；
2. 每 256 次扫描发送 performance frame，记录 `scan/address/adc/process`；
3. acquisition time 从默认 10 µs 改为 5 µs；
4. settle time 从 30 µs 改为 20 µs；
5. 地址顺序改为 `0 → 1 → 3 → 2 → 6 → 7 → 5 → 4`，相邻地址只翻转一个 GPIO；
6. 上位机增加设备端分段性能显示。

固件构建成功，最终设备树确认 settle 为 20 µs、acquisition 为 5 µs，UF2 大小 135168 bytes。

</details>

<details>
<summary><strong>2026-07-19</strong>：500 Hz 目标完成、24 路性能基线、U28 硬件故障定位</summary>

## 500 Hz 目标完成

最终实测完整 24 通道扫描率达到 **695 Hz**，平均扫描周期约：

```text
1000 / 695 ≈ 1.44 ms
```

已经超过原定 500 Hz 目标约 39%。后续不再单纯追求空载扫描率，优先验证模拟质量、端到端延迟和磁轴算法稳定性。

本轮优化过程：

1. 初始基线 83.170 Hz：settle 500 µs、polling 5 ms，每通道一次 dummy read 加一次正式 read；
2. 重新焊接 U28，解决其公共端 Z 始终为 0 V 的硬件故障；
3. 逐步缩短轮询与 settle，并取消 dummy read；
4. 扫描任务移至独立工作队列；
5. 从每帧 24 次独立 `adc_read()` 优化为 8 次三通道 batch read；
6. 上位机从逐帧 Qt signal 改为有界共享队列、批量取帧、积压丢旧帧并限制绘图点数；
7. 将几十微秒延时从 `k_usleep()` 改为 `k_busy_wait()`，最终达到 695 Hz。

### UF2 刷写现象

复制完成后 bootloader 会立即重启，虚拟 U 盘消失。Windows 有时提示"无法复制"，有时不提示，两种情况都可能已成功刷写。应以 bootloader 盘消失、COM 端口重新出现、上位机恢复接收和新行为生效为判断标准。

---

## 24 路采集性能基线

测试条件：COM12、USB CDC ACM、统计 30.059 s、settle 500 µs、polling 5 ms、每路一次 dummy read 与一次正式 read、每帧 62 bytes、CRC-16/CCITT-FALSE。

| 指标 | 实测结果 |
|---|---:|
| 有效数据帧 | 2499 |
| 下位机扫描频率 | 83.170 Hz |
| 上位机接收帧率 | 83.137 fps |
| 平均完整扫描周期 | 12.0235 ms |
| 最短周期 | 11 ms |
| 最长周期 | 13 ms |
| 周期抖动标准差 | 0.158 ms |
| 协议序号检测丢帧 | 0 |
| CRC 错误 | 0 |
| 平均串口吞吐量 | 5156 B/s |

该组数据作为后续 settle time 修改的 baseline。软件统计证明传输链路稳定，但当时尚未统计模拟离群点。

---

## U28 故障定位与返修

### 现象

- U26 Y6、Y7 曾在真实电压与 0 V 之间频繁跳变；
- ADC3 一组的 MEG4、MEG9、MEG14 靠近磁铁时没有波形变化；
- U28 各 Y 输入约 1.6 V，但公共输出 Z 为 0 V。

### 结论

重新焊接 U28 后问题解决，根因在 U28 芯片或焊接连接，不是 ADC 阈值、扫描映射或地址建立时间。

按现象推断，可疑焊点优先级为：

1. `Z/COM` 引脚虚焊或走线接触不良；
2. `VCC` 虚焊；
3. `E` 未可靠保持低电平，使 Z 进入高阻；
4. `GND/VEE` 公共焊点虚焊。

地址 A/B/C 单点虚焊通常造成选错或随机选通，不太容易在所有 Y 输入相近时稳定产生"Z 始终为 0 V"。

</details>

---

## 2026-08-03：MegKnob OLED 初始化故障修复与状态页验证

### 故障现象与根因

启用 OLED 后，设备曾出现全屏黄色、Windows 将 USB HID 识别为不受支持设备、BLE 断连且按键无响应的连锁故障。根因是屏幕设备树节点虽然存在，但配置未启用 I2C 和 SSD1306 驱动；显示子系统处于未完成初始化的状态，并在系统共享工作队列中阻塞，进而饿死 USB、BLE 和键盘扫描任务。

### 已完成的修复

- 在 `megknob.conf` 显式启用 `CONFIG_I2C`、`CONFIG_SSD1306` 与 128×32 单色 OLED 所需的 LVGL 1-bit 配置（`LV_Z_BITS_PER_PIXEL=1`、`LV_Z_VDB_SIZE=64`）；
- 在 `Kconfig.defconfig` 中为 `ZMK_DISPLAY` 提供相同的 I2C、SSD1306 和 LVGL 默认值，避免构建配置遗漏；
- 启用 `CONFIG_ZMK_DISPLAY_WORK_QUEUE_DEDICATED`，将显示刷新移到独立工作队列。即使 I2C 传输缓慢或异常，也不会再阻塞 USB HID、BLE 和 kscan；
- 修正 GitHub Actions 对 `nice_nano//zmk` 的矩阵过滤条件，确保 MegKnob 固件会进入 CI 编译；
- CI 运行 `30756387942` 已成功生成 `nice_nano__zmk-megknob-zmk.zip`，RAM 使用约 25.35%（66 KB），有充足余量。

### 实机结果

刷入最新构建产物后，USB、BLE、按键和 OLED 均已恢复正常，确认上述修复有效。

### 后续显示方向

128×32 OLED 的默认状态页将继续保持高信息密度：顶部展示 USB/BLE 输出状态与当前 BLE profile、电池/充电状态；底部展示活动层与 WPM。为让电量信息可用，MegKnob 后续固件开启电池采样并显示百分比；这不会影响 Hall 遥测，显示更新仍在独立工作队列内执行。Caps Lock、校准进度、Hall 异常等诊断型信息适合在后续作为短时提示页加入，而不是常驻挤占主状态页。
