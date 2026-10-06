# Immich 本地 NSFW 分类服务

## Goal
为现有 Windows Docker Immich 部署独立的本地 NSFW 分类服务。保留原图，通过用户 API 识别、审核、锁定，并提供恢复记录。用户明确要求先计划再执行。

## Current Phase
Phase 12 — 跨页预览与分页控制（complete）。

## Next Step
新版本已健康上线2983。用户刷新浏览器使用跨页清晰、页码跳转及每页数量；NSFW模型说明已更新。

### Phase 1: 环境与接口 — complete
- 核对 Docker、硬件、Immich 版本与版本对应 API。
- API Key 通过仅本机可访问页面配置，不使用数据库获取用户凭据。
- 确认资产分页、预览、锁定、PIN 验证、相册恢复。

### Phase 2: 实现 — complete
- 本地模型、扫描任务、SQLite 状态与操作记录。
- 管理页面、连接配置、审核列表、单个/批量锁定和恢复。
- 增量定时扫描、模式与阈值配置、取消任务与处理失败状态。

### Phase 3: 验证 — complete
- 有意义的 API 合约模拟测试与状态恢复测试。
- 构建容器，实际下载模型并完成合成图片推理。
- 检查密码/API Key 不泄漏、只绑定本机、只修改授权用户资产。

### Phase 4: 部署和交付 — complete
- Docker Compose 独立项目，持久模型缓存与状态。
- 默认审核模式，提供使用文档、模型限制和撤销方式。
- 用户配置 Key 后，进行只读的真实 API 验证；必要时等待本机登录配置。

用户已连接 API Key 并扫描 100 项：review 1、scored 96、unsupported 3；没有锁定操作。真实恢复没有在用户照片上运行。

### Phase 5: 目录、名称和端口迁移 — complete
- 目标 D:/Program/Docker/wsl/immich/immich-nsfw-identify。
- 备份状态卷、保存匿名汇总基线，验证无扫描任务。
- 原数据卷通过本机 compose.override.yaml 继续引用。
- 统一项目/镜像/容器名、2983 监听和健康检查；主机端口及 Immich 地址用 .env 配置。

### Phase 6: GitHub 项目文档 — complete
- 中文 README：适量 emoji、静态徽章、目录、通用 Docker 命令、API 权限、操作和 Immich 效果映射、限制及运维。
- MIT LICENSE（2026 immich-nsfw-identify contributors），模型 Apache-2.0 THIRD_PARTY_NOTICES。
- 忽略本机覆盖、.env、备份和研究/规划文件；不创建或发布远程 GitHub 仓库。

### Phase 7: 迁移验证与交付 — complete
- 构建、现有 22 项测试、JS 语法和 Compose 配置。
- 2983 健康，8090 不再由插件监听；核对 credentials 哈希、设置、扫描结果和模型缓存保留。
- 原 Immich 正常；审核模式、定时关闭；本轮不扫描/锁定照片。

### Phase 8: 运行日志和交互 — complete
- 用户选择 Docker Desktop/Compose 为日志入口，网页继续显示进度摘要。
- 业务日志标准输出 JSON，记录生命周期、任务开始/节流进度/完成/失败、锁定/恢复结果；不输出凭据、原始响应、文件名、图片路径和图片内容。
- Compose 配置本服务的 Docker local 日志轮转；不修改全局 Docker，不安装额外日志平台。
- 增加显示/模糊本页按钮；翻页、切换筛选、刷新结果重置模糊。
- 鼠标左键拖框替换选择，Ctrl/Command 拖框追加；仅可操作状态的照片可选，Escape 取消，触摸保持滚动。

### Phase 9: 架构 README 与 TODO — complete
- Mermaid 架构图、模块职责、数据流、FastAPI/PyTorch/Transformers/SQLite/HTTPX/Docker 选型说明。
- 模型选择：专用二分类、CPU可用、本地隐私、Apache2许可、固定revision+安全权重；无横向评测，不宣称最准。
- Docker日志入口、CLI与kubectl logs类比、INFO/WARN/ERROR、轮转与日志非审计账本。
- GPU镜像和设备选择、FFmpeg视频抽帧/多帧聚合/短片段漏检/恢复测试列为未实现TODO。
- 指明有GPU不等于当前版本支持视频，CPU视频也可实现但慢。

### Phase 10: 验证与发布本机版本 — complete
- 现有及日志隐私测试；前端批量预览/框选交互用合成测试数据验证。
- 等现有扫描结束后更新容器，核对数据保留、日志输出及2983健康。
- 不启动用户照片新扫描或锁定；更新干净源码包和文档。

### Phase 11: 候选刷新、重新识别和favicon — complete
- 后台已存在1037候选，页面扫描中只刷新job而不刷新结果，是旧结果显示问题；模型分布正常，不修改阈值。
- 扫描中定期更新结果和总数；用户选中/拖拽/取消模糊时延迟重排，显示新结果提醒和手动刷新。
- 明确“重新识别整个照片库”入口，强制重跑review/scored；保留人工保留、锁定和未知状态，拒绝incremental+force。
- 审核模式仍不修改Immich资产；用户之后自己点击全库重新识别，本轮不启动。
- 添加与配色一致的代码原生SVG favicon，并提供PNG/ICO兼容资源。
- 测试候选实时刷新、审核交互不被自动刷新打断、强制识别保护状态、favicon及升级数据保留。

## Decisions
- 不删除/移动原图，不直接修改 Immich 数据库。
- 不调用外部图像识别 API；模型仅首次下载，推理在本机。
- 未验证阈值前默认审核，不自动锁定现有库。
- 真正的恢复需要用户授权解锁/PIN；API Key 不应绕过锁定权限。
- 视频首版明确跳过，不用封面冒充视频完整检测。
- 用户未要求并行 agent，不委派。

### Phase 12: 全局预览和分页 — complete
- 用户确认“显示所有预览”为当前浏览器会话跨页清晰模式，重新加载页面后恢复默认模糊。
- 页大小提供24/48/96/192，默认48；后端limit范围1–192；页码跳转1到当前总页数，空结果仍显示1/1。
- 每页数量与页码变更重置当前页选择，保留跨页预览模式；受保护照片仍不读取。
- 页大小仅保存在当前页面内，不改Immich/扫描设置；后台结果缩减时钳制到最后一页。
- 增加API分页和前端边界测试，用合成数据验证跨页清晰/恢复模糊/跳页/大小切换。
- 当前插件闲置，确认无任务后升级；不启动扫描或修改照片。

## Errors Encountered
| Error | Attempt | Resolution |
| Docker build context lacks tests directory | 1 | 添加有意义的测试文件后重新构建 |
| Windows Move-Item reports source in use | 1 | 首次命令在源目录中运行；切到工作区父目录后 Move-Item -ErrorAction Stop 成功 |
| apply_patch rejects delete/add for same path in one patch | 1 | 将 README 替换拆为两个顺序操作后成功 |
| Verification helper's localhost points to itself | 1 | 使用新服务的 container 网络命名空间后一致性检查通过 |
| Git ignore verification fails under Windows text stdin | 1 | 诊断出 CRLF 路径尾部 CR，改用 NUL 分隔的二进制 stdin，正确处理否定模式后通过 |
| apply_patch out-of-order hunks did not match app.py | 1 | 检查确认未改动文件，按源码行顺序重排补丁后成功 |
