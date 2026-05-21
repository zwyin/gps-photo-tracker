# GPS Photo Tracker

[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-859%20passing-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-99.80%25-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/platform-Win%20%7C%20Mac%20%7C%20Linux-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()

[English](../README.md)

批量给照片打 GPS 地理标签——根据 GPS 轨迹（GPX/KML/TCX），自动为没有内置 GPS 的相机照片写入 EXIF 坐标。

<!-- TODO: 添加截图或演示 GIF
![截图](images/screenshot_zh.png)
-->

## 为什么需要这个工具

大多数相机（不像手机和无人机）不记录 GPS。没有地理标签，相册应用无法按地点整理或推荐照片。手动逐张添加不现实。

**典型场景**：相机拍照 + 手机/智能手表（Apple Watch、Garmin 等）记录轨迹，回家后用本软件批量匹配。

现有工具用线性插值匹配，覆盖率 **30-50%**，大量照片无法覆盖。GPS Photo Tracker 独有的**二轮邻居跟随**算法将覆盖率提升至 **~90%**，参数可调，平衡准确性和覆盖率。

**目标用户**：用手机/智能手表记录轨迹但用相机拍照的旅行者。需要按地点管理照片的摄影师。需要给考察照片打地理标签的野外工作者。

## 竞品对比

| 特性 | GPS Photo Tracker | GeoSetter | HoudahGeo | Lightroom Classic | ExifTool | PicMeta PhotoTracker |
|------|:-:|:-:|:-:|:-:|:-:|:-:|
| 价格 | **免费 / 开源** | 免费 | $39 | $20/月 | 免费 | 免费 |
| 平台 | Win/Mac/Linux | 仅 Windows | 仅 Mac | Win/Mac | 命令行 | 仅 Windows |
| 开源 | **是 (GPLv3)** | 否 | 否 | 否 | 是 | 否 |
| 中文界面 | **支持** | 支持 | 不支持 | 支持 | 部分 | 不支持 |
| 轨迹格式 | GPX<br>KML<br>TCX | GPX<br>NMEA<br>KML<br>+3 | GPX<br>NMEA<br>FIT<br>+1 | GPX | GPX<br>NMEA<br>KML<br>+3 | GPX |
| 线性插值 | **支持** | 支持 | 支持 | 支持 | 支持 | 不支持 |
| 二轮邻居跟随 | **支持** | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| GPS 覆盖率（典型） | **~90%** | ~50-70% | ~60-80% | ~50-70% | ~50-70% | ~30-40% |
| 交互式复查 | **支持** | 有限 | 支持 | 有限 | 无（命令行） | 不支持 |
| 参数可调 | **支持** | 支持 | 支持 | 仅时间偏移 | 支持 | 有限 |
| 所见即所得流程 | **支持** | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| 方向键快速跟随 | **支持** | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| 批量处理 | **支持** | 支持 | 支持 | 支持 | 支持 | 支持 |
| 写入状态追踪 | **支持** | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| 最近更新 | 2026 | 2019 | 2025 | 2026 | 2026 | 2022 |

> **覆盖率**：轨迹点密集时所有工具表现接近。差异体现在轨迹稀疏或 GPS 信号中断场景——二轮邻居跟随可恢复其他工具无法匹配的照片。

## 功能特点

### 核心匹配

- **多格式 GPS 轨迹支持** — GPX、KML（Google Earth）、TCX（Garmin），自动识别格式
- **线性插值匹配** — 在相邻 GPS 轨迹点之间按时间比例插值计算照片位置，精度更高
- **二轮邻居跟随** — 未匹配照片自动跟随最近的成功邻居；已有 GPS 的照片排除传播
- **智能参数推荐** — 根据轨迹密度自动推荐参数；所有阈值均可手动调整

### 交互操作

- **所见即所得流程** — 三步引导：预览 → 复查 → 执行，表格编辑实时同步到写入
- **交互式复查** — 预览后复查未匹配照片，手动指定坐标或选择附近轨迹点
- **方向键跟随** — 使用 ← → 键快速从相邻已匹配照片获取 GPS
- **Esc 撤销** — 按 Esc 恢复照片到原始匹配状态，撤销所有操作
- **来源列右键菜单** — 双击来源列，快速访问跟随/保护/撤销操作
- **GPS 覆盖保护** — 默认跳过已有 GPS 信息的照片，防止数据丢失
- **GPS 覆盖率统计** — 实时显示处理前后覆盖率和成功率

### 安全与性能

- **安全复制模式** — 复制照片后写入 GPS，不修改原始文件
- **批量处理** — 支持数千张照片，带进度显示和取消操作
- **并行写入** — 多线程 EXIF 写入，提升处理速度
- **断点续传** — 复制模式支持断点续传，中断后可恢复处理
- **EXIF 方向** — 正确显示缩略图，自动处理 EXIF Orientation 标签
- **写入状态追踪** — 每张照片的写入状态列（已复制 / 已覆盖 / 跳过 / 失败 / 已取消）

### 导出与报告

- **结果导出** — 导出为 CSV 或 Markdown，自动生成文件名
- **HTML 报告** — 自包含的 HTML 报告，内联 SVG 图表展示匹配结果

## 未来规划

- **移动端支持（iOS/Android）** — 手机上直接处理，记录轨迹 + 打 GPS 一步到位，无需电脑。

## 快速开始

### 方式一：下载安装包（推荐）

从 [GitHub Actions](../../actions/workflows/build.yml) 下载 → 点击最近一次成功的运行 → 页面底部 **Artifacts** 区域：

| 平台 | 文件 |
|------|------|
| macOS | `GPS-Photo-Tracker-v0.19.0-macos.zip` |
| Windows | `GPS-Photo-Tracker-v0.19.0-windows.zip` |
| Linux | `GPS-Photo-Tracker-v0.19.0-linux.tar.gz` |

下载后解压，双击即可运行，无需安装 Python 或任何其他软件。

### 方式二：从源码运行

**第 1 步 — 检查 Python 版本**

```bash
python --version
```

需要 **Python 3.11 或更高版本**。如果版本低于 3.11，请到 [python.org](https://www.python.org/downloads/) 下载安装。

**第 2 步 — 下载源码**

```bash
git clone https://github.com/zwyin/gps-photo-tracker.git
cd gps-photo-tracker
```

**第 3 步 — 安装依赖**

```bash
pip install -e .
```

这条命令会自动安装所有需要的包：PySide6、piexif、gpxpy、Pillow、geopy、tenacity。

**第 4 步 — 启动**

```bash
python -m gps_photo_tracker
```

启动时程序会自动检查依赖。如果缺少某个包，会显示明确的提示，告诉你需要安装什么。

### 使用流程

程序采用三步引导流程：

1. **① 预览** — 选择 GPS 轨迹和照片目录，自动匹配照片到 GPS 位置
2. **② 复查** — 对未匹配的照片，手动指定坐标或选择附近轨迹点
3. **③ 执行** — 写入 GPS 数据（复制到输出目录或原地覆盖）

预览表格中显示的内容即为最终写入结果 — 所有手动修正（方向键跟随、复查编辑、重置）都会同步到执行阶段。

### 数据安全

- 写入 GPS 元数据会改变文件的修改时间。如需保留原始时间戳，请使用**复制模式**。
- **覆盖模式**会直接修改原文件中的 GPS 元数据。已有 GPS 的照片默认跳过，但如果开启了"覆盖已有 GPS"，写入后无法恢复。图片文件本身不受影响，变化的仅是元数据。
- **推荐使用复制模式**：将照片复制到独立输出目录后再写入 GPS，原文件不受影响。支持断点续传。

## 开发

### 开发环境

```bash
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest                          # 运行所有测试
pytest --cov                    # 带覆盖率报告
pytest tests/unit/test_gps_matcher.py  # 单个模块
```

### 覆盖率

| 层级 | 目标 | 当前 |
|------|------|------|
| Core（算法/IO） | >= 85% | ~95% |
| Service | >= 80% | 86% |
| 整体 | >= 75% | ~80% |

### 项目结构

```
src/gps_photo_tracker/
├── core/           # 核心算法：GPS 匹配、解析器、EXIF 读写、断点续传
├── service/        # 业务编排：处理管线、取消控制
├── gui/            # PySide6 图形界面：主窗口、面板、对话框
└── logging_/       # 结构化日志
tests/
├── unit/           # 565+ 单元测试
├── integration/    # 端到端测试
└── batch/          # 大批量测试
```

## 参数说明

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `isolated_window` | 300 秒 | 60-3600 | 孤立照片的最大时间差 |
| `middle_time_window` | 3600 秒 | 600-7200 | 插值照片的最大时间差 |
| `context_window` | 300 秒 | 60-1800 | 判断照片是否适合插值的时间窗口 |
| `max_gps_distance` | 200 米 | 50-1000 | 前后 GPS 点最大距离（防止跳变） |
| `match_tail` | 开启 | — | 是否匹配轨迹首尾的孤立照片 |
| `time_offset` | 0 秒 | -3600~3600 | 照片时间修正值（相机时钟偏差） |

### 参数详解

**`time_offset` — 相机时钟修正**

匹配失败最常见的原因。相机时钟可能与 GPS 时间不一致（时区错误、夏令时、或单纯走时不准），调整此值补偿偏差。

- 相机快 5 分钟 → 设为 `-300`（减去 5 分钟）
- 相机时区错误（如日本 UTC+9，GPS 在 UTC+8）→ 设为 `3600`（加 1 小时）
- 不确定 → 保持 0，先看预览结果；如果全部未匹配，以 ±300 秒步长尝试

**`isolated_window` — 孤立照片搜索范围**

当照片前后没有 GPS 点（GPS 信号丢失、轨迹开头/结尾），此参数控制向前后搜索最近 GPS 点的最大时间跨度。

- 密集轨迹（手机每秒记录）→ 默认 300 秒即可
- 稀疏轨迹（智能手表每 5-10 分钟记录）→ 增大至 600-900 秒
- 户外徒步 GPS 信号间断 → 增大至 1800-3600 秒（牺牲精度换覆盖率）

**`middle_time_window` — 插值的最大时间跨度**

当照片落在两个 GPS 点之间时，工具会插值计算位置。此参数限制这两个 GPS 点的最大时间间隔。值越大，匹配越多但精度越低。

- 城市行走、GPS 频繁刷新 → 默认 3600 秒（1 小时）即可
- 长途自驾、GPS 有间断 → 增大至 7200 秒
- 只想要高精度匹配 → 减小至 600-1200 秒

**`context_window` — 邻居照片的判定窗口**

判断一张照片是"中间照片"（可插值）还是"孤立照片"（用最近点）。只有前后两张照片都在此时间窗口内，才被视为"中间"。

- 连续拍摄（连拍模式）→ 默认 300 秒即可
- 间隔拍摄（风景照、每隔几分钟）→ 增大至 600 秒
- 拍摄间隔不规律 → 保持默认，孤立匹配会处理边缘情况

**`max_gps_distance` — 防止 GPS 跳变**

插值时，如果前后两个 GPS 点距离过远（如城市间飞行），插值位置不可靠。此参数在 GPS 点距离过大时拒绝插值。

- 步行/徒步（低速移动）→ 默认 200 米即可
- 驾车或骑行 → 增大至 500 米
- 希望保守匹配 → 减小至 100 米

**`match_tail` — 轨迹首尾匹配**

是否将轨迹开始前或结束后拍摄的照片，匹配到最近的轨迹端点。

- 开启（默认）— 旅途开头/结尾的照片会被匹配到第一个/最后一个 GPS 点
- 关闭 — 只匹配轨迹覆盖时间范围内的照片；适合轨迹起点不可靠的场景（如 GPS 开晚了）

## 构建

```bash
python scripts/build.py          # 构建当前平台安装包
python scripts/build.py --clean  # 清理构建
```

需要安装 [PyInstaller](https://pyinstaller.org/)。macOS 生成 `.app`，Windows 生成 `.exe`，Linux 生成二进制文件。

## 许可证

本项目基于 [GNU General Public License v3.0](../LICENSE) 开源。

## 致谢

- GPS 匹配算法经过 1,832 张真实照片验证，成功率 83%+
- 使用 [PySide6](https://doc.qt.io/qtforpython-6/)、[piexif](https://github.com/hMatoba/Piexif)、[gpxpy](https://github.com/tkrajina/gpxpy)、[Pillow](https://python-pillow.org/)、[geopy](https://github.com/geopy/geopy) 构建
