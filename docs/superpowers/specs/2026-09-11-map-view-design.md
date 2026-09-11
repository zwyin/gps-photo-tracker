# Map View 地图预览面板设计（任务 #7，P4.0）

- 日期：2026-09-11
- 分支：`feat/map-view`（基于 develop @ fcc4f60）
- 状态：已实现（TDD）
- 范围：GUI 增加地图预览面板——显示当前加载的 GPS 轨迹折线 + 照片打点 + 选中照片高亮

## 1. 背景与目标

用户加载 GPX/KML/TCX/FIT 轨迹并匹配照片后，纯表格/文本方式无法直观确认
"轨迹长什么样、照片落在轨迹哪个位置"。目标：在主窗口右侧增加一个地图面板，

1. 画出当前扫描到的全部轨迹段（折线）；
2. 为已匹配/已有 GPS 的照片打点；
3. 列表选中照片时高亮对应 marker；
4. 无网络/无 key/无数据时优雅降级为占位提示，不影响主流程。

非目标（v1 明确不做）：地图交互缩放拖动、点击地图反查照片、离线瓦片渲染、
review 对话框内嵌地图。

## 2. 方案对比与选型

| 维度 | A. 高德 REST 静态图（选定） | B. QtWebEngine 内嵌 JS API | C. 生成 HTML 外开浏览器 |
|------|--------------------------|---------------------------|------------------------|
| 新增依赖 | **零**（Qt 自带 QNetworkAccessManager / urllib） | PySide6-Addons QtWebEngine（~150MB 打包增量，PyInstaller spec 大改） | 零 |
| 渲染质量 | 服务端出图 PNG，固定视野 | 矢量/瓦片完整交互 | 完整交互 |
| 交互能力 | 无原生交互（刷新换图模拟高亮） | 平移/缩放/点击 marker | 平移/缩放/点击 |
| 无头/CI 可测性 | URL 构建 + 拉取全部可 mock，纯逻辑占大头 | 需要 WebView 进程，CI 不稳定 | 进程外，无法断言 |
| 首版工作量 | 小 | 大（QWebChannel 桥、生命周期） | 小但脱离应用 |

选 A 的理由：

- 项目红线是"零新增 pip 依赖、打包体积不变"（当前 PyInstaller spec 不含 WebEngine）。
- 本需求是**预览**（看轨迹和点位），不是地图操作工具；静态图足够。
- 静态图 URL 的构建、视野计算、坐标转换全部是纯函数，TDD 友好，符合项目
  99.8% 覆盖率的门禁文化。
- 演进路径开放：`core/geo.py`（坐标转换）与 `service/map_service.py`
  （视图计算/URL/凭证）与渲染层解耦，日后换 QtWebEngine 只需替换 `gui/map_panel.py`。

## 3. 坐标系转换（core/geo.py）

- GPS 轨迹与照片 EXIF 均为 WGS-84；高德底图为 GCJ-02。**必须转换**，
  否则整体偏移约 300–600 m。
- 采用社区标准算法（与 googollee/eviltransform 逐式一致，非自造公式）：
  - `out_of_china(lat, lng)`：lng∈[72.004, 137.8347] 且 lat∈[0.8293, 55.8271]
    之外不偏移；
  - `wgs84_to_gcj02(lat, lon)`：transform 偏移量 × GCJ 扁率修正；
  - `haversine_m(lat1, lon1, lat2, lon2)`：验证用测距。
- 参考向量（eviltransform 官方测试集，测试断言 abs≤1e-6）：
  - 上海 (31.1774276, 121.5272106) → (31.17530398364597, 121.531541859215)
  - 深圳 (22.543847, 113.912316) → (22.540796131694766, 113.9171764808363)
  - 北京 (39.911954, 116.377817) → (39.91334545536069, 116.38404722455657)
- 实测偏移量（haversine，测试内固化）：上海 ≈ 475 m、深圳 ≈ 604 m、
  北京 ≈ 554 m，均在 300–700 m 预期区间（任务书预估 300–500 m 略保守，
  以参考向量实测为准）。

## 4. 服务层（service/map_service.py）

全部纯函数 + 薄封装，无状态：

- `load_amap_credentials(env=None, dotenv_path=None) -> (key|None, secret|None)`
  - 优先环境变量 `AMAP_KEY`/`AMAP_SECRET`，其次解析 `.env`（KEY=VALUE，
    容忍引号/行内注释/空行/`#` 注释；缺文件返回 (None, None) 不抛错）。
  - 项目此前无 dotenv 加载链路（src/ 无任何 environ 读取），此处即该链路的
    最小实现；**key/secret 永不打日志、永不出现在 URL 断言之外**。
- `fit_view(points, width, height, padding=1.25) -> ((lat, lon), zoom) | None`
  - Web Mercator 像素数学：`world_px = 256·2^z`，取经/纬向所需缩放的较小值，
    clamp 到 [3, 17]；空点集返回 None。
- `build_paths_param(segments) -> str | None`
  - 每段降采样至 ≤128 点（保留首末点），格式
    `weight,color,alpha,,:lon,lat;...`（高德文档原样，fillcolor 留空不填充）；
    段间 `|` 连接，高德上限 4 组，超出丢弃（记录于 docstring）。
- `build_markers_param(points, selected=None) -> str | None`
  - 照片点 blue small 组 + 选中点 red large 组；>96 点均匀降采样。
- `sign_params(params, secret) -> str`：高德数字签名 = md5(按 key 排序的
  urlencode 串 + secret)。secret 存在时自动附加 `sig`。
- `build_static_map_url(...) -> str`：端点
  `https://restapi.amap.com/v3/staticmap`，参数 zoom/size(`W*H`)/scale=2/
  location(`lon,lat` 6 位小数)/paths/markers。
- `MapService.fetch_png(url, timeout=10) -> bytes`：urllib 同步拉取；
  高德出错时返回 JSON（status=0）而非图——按 content-type/`{` 开头识别并抛
  `MapFetchError`（含 infocode），网络异常同样包装。

## 5. GUI（gui/map_panel.py）

`MapPanel(QWidget)`：

- 布局：状态行 QLabel + 图片 QLabel（QPixmap，KeepAspectRatio 缩放）。
- 数据入口：`set_track(segments)`（worker 扫描段，含 points；入面板时即做
  WGS→GCJ）、`set_results(details)`（表格行 detail，取 lat/lon），
  `set_selected(lat, lon)` / `clear_selected()`。
- 刷新：300 ms QTimer 防抖 → 组装点集 → `fit_view` → 构 URL →
  内存缓存（URL→QPixmap，上限 16 张 FIFO）命中直接显示；未命中
  QNetworkAccessManager 异步拉取，完成后显示或报错。选中照片以独立
  red large marker 组呈现（静态图无原生交互，刷新即"高亮"）。
- 降级：无 key → "未配置 AMAP_KEY（.env）"；无数据 → "暂无轨迹"；
  网络失败 → 错误信息。主流程零依赖（地图失败不影响打标）。
- 集成点（main_window）：
  - `_build_right_panel`：右侧垂直 splitter 顶部加 MapPanel，"视图"菜单
    增加"地图面板"开关（checkable，镜像"配置面板"模式）；
  - worker `scan_done_signal` 段字典补充 `points`（复用 review 信号的同构
    dict，GPXBrowserDialog 对多出的 key 向后兼容）；
  - `_on_scan_done` → `set_track`；`_on_done` 与 `_apply_review_to_table`
    → `set_results`；`_on_selection_changed` → `set_selected/clear_selected`。
  - v1 已知取舍：行内 GPS 快捷修改（跟随/撤销/保护）不即时刷新地图，
    待下次选中或预览完成刷新。

## 6. 测试策略（TDD）与覆盖率

- 新增 `tests/unit/test_geo.py`：参考向量、境外不偏移、out_of_china 边界、
  偏移量 300–600 m 固化、haversine 上海↔北京 ≈ 1,078 km（±1 m）。
- 新增 `tests/unit/test_map_service.py`：凭证加载（env 优先/引号注释/缺文件）、
  fit_view（空/单点/远距/近距/尺寸影响）、paths/markers（格式、降采样、上限、
  选中分组）、签名 md5 定值、URL 精确串、fetch 三态（图/JSON 错/网络错，mock
  urlopen）。
- 新增 `tests/unit/test_map_panel.py`：状态降级、数据入口转换与计数、防抖单次、
  缓存命中显示、PNG bytes 显示/坏 bytes 报错（PIL 生成 fixture），
  MainWindow 集成（scan_done→track、selection→selected）。
- 覆盖率门禁（沿用项目分层）：core/geo 100%，service/map_service ≥90%，
  gui/map_panel ≥80%；整体维持 ≥95%。
- 回归：`pytest tests/unit/ -q` 基线 984 passed / 3 failed（test_main 的
  tkinter deselect 已知问题，与本功能无关）。

## 7. 红线确认

- AMAP_KEY/AMAP_SECRET 不入库（.env 已在 .gitignore？——已确认 .env 未被
  跟踪）、不打印、不写入测试断言字面量。
- 不合并 master、不发版、不动全局配置；零新增 pip 依赖。
