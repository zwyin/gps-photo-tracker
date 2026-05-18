# GPS Photo Tracker

[English](../README.md)

批量处理照片，根据 GPS 轨迹（GPX/KML/TCX）自动写入 EXIF GPS 标签。为没有内置 GPS 的相机拍摄的照片添加地理信息，使照片管理软件（Photos、Lightroom 等）能按地点整理照片。

## 功能特点

- **多格式 GPS 轨迹支持** — GPX、KML（Google Earth）、TCX（Garmin），自动识别格式
- **线性插值匹配** — 在相邻 GPS 轨迹点之间按时间比例插值计算照片位置，精度更高
- **安全复制模式** — 复制照片后写入 GPS，不修改原始文件
- **GPS 覆盖保护** — 默认跳过已有 GPS 信息的照片，防止数据丢失
- **批量处理** — 支持数千张照片，带进度显示和取消操作
- **智能参数推荐** — 根据轨迹密度自动推荐最佳匹配参数
- **HTML 报告** — 自包含的 HTML 报告，内联 SVG 图表展示匹配结果
- **断点续传** — 复制模式支持断点续传，中断后可恢复处理
- **并行写入** — 多线程 EXIF 写入，提升处理速度
- **EXIF 方向** — 正确显示缩略图，自动处理 EXIF Orientation 标签
- **交互式复查** — 预览后复查未匹配照片，手动指定坐标或选择附近轨迹点
- **所见即所得流程** — 三步引导：预览 → 复查 → 执行，表格编辑实时同步到写入
- **方向键跟随** — 使用 ← → 键快速从相邻已匹配照片获取 GPS
- **二轮自动跟随** — 未匹配照片自动跟随最近的成功邻居；已跳过照片（已有 GPS）排除传播
- **结果导出** — 导出为 CSV 或 Markdown，自动生成文件名（开发模式含 commit hash）
- **Esc 撤销** — 按 Esc 恢复照片到原始匹配状态，撤销所有跟随/保护/编辑操作
- **来源列右键菜单** — 双击来源列，快速访问跟随/保护/撤销操作
- **写入状态追踪** — 每张照片的写入状态列（已复制 / 已覆盖 / 跳过 / 失败 / 已取消）

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
