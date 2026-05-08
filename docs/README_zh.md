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

## 快速开始

### 环境要求

- Python 3.11+
- PySide6（GUI 界面）

### 安装

```bash
git clone https://github.com/zwyin/gps-photo-tracker-claude.git
cd gps-photo-tracker-claude
pip install -e .
```

### 运行

```bash
python -m gps_photo_tracker
```

### 使用流程

1. 选择包含 GPS 轨迹文件（GPX/KML/TCX）的目录
2. 选择包含照片（JPEG/PNG）的目录
3. 调整匹配参数，或点击"智能推荐"
4. 预览匹配结果，确认后选择复制模式或覆盖模式执行

### 输出模式说明

| 模式 | 说明 |
|------|------|
| **预览** | 只显示匹配结果，不修改任何文件 |
| **复制**（推荐） | 复制照片到输出目录并写入 GPS，不改动原文件 |
| **覆盖** | 直接修改原文件，需确认 |

## 使用场景

- 旅行拍摄大量照片，但手机 GPS 关闭或信号差，照片没有位置信息
- 有 GPS 记录仪或运动手表导出的 GPX 轨迹文件
- 需要把 GPS 坐标和照片按时间对齐，写入照片 EXIF
- 数据规模：一次处理 100-5000 张照片，10-100 个轨迹文件

## 参数说明

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| 孤立照片时间窗口 | 300 秒（5分钟） | 60-3600 | 孤立照片的最大时间差 |
| 中间照片时间窗口 | 3600 秒（1小时） | 600-7200 | 插值照片的最大时间差 |
| 上下文窗口 | 300 秒（5分钟） | 60-1800 | 判断照片是否适合插值的时间窗口 |
| GPS 距离阈值 | 200 米 | 50-1000 | 前后 GPS 点最大距离（防止跳变） |
| 匹配首尾 | 开启 | — | 是否匹配轨迹首尾的孤立照片 |
| 时间偏移 | 0 秒 | -3600~3600 | 照片时间修正值（相机时钟偏差） |

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
| Core（算法/IO） | >= 85% | ~90% |
| Service | >= 80% | ~81% |
| 整体 | >= 75% | ~86% |

### 项目结构

```
src/gps_photo_tracker/
├── core/           # 核心算法：GPS 匹配、解析器、EXIF 读写、断点续传
├── service/        # 业务编排：处理管线、取消控制
├── gui/            # PySide6 图形界面：主窗口、面板、对话框
└── logging_/       # 结构化日志
tests/
├── unit/           # 334 个单元测试
├── integration/    # 端到端测试
└── batch/          # 大批量测试
```

## 构建

```bash
python scripts/build.py          # 构建当前平台安装包
python scripts/build.py --clean  # 清理构建
```

需要安装 [PyInstaller](https://pyinstaller.org/)。macOS 生成 `.app`，Windows 生成 `.exe`。

## 许可证

本项目基于 [GNU General Public License v3.0](LICENSE) 开源。

## 致谢

- GPS 匹配算法经过 1,832 张真实照片验证，成功率 83%+
- 使用 [PySide6](https://doc.qt.io/qtforpython-6/)、[piexif](https://github.com/hMatoba/Piexif)、[gpxpy](https://github.com/tkrajina/gpxpy)、[Pillow](https://python-pillow.org/)、[geopy](https://github.com/geopy/geopy) 构建
