# CHANGELOG

## 2026-09-12 v2.4.1-beta2

> **内部测试版**：角色库改为**配置 JSON 权威**（与「风格示例池」同构）；去掉 `/char reload`。

### 变更

- **权威数据源**：配置项 `director_characters`（Dashboard JSON 编辑器，`editor_mode`）。
- **保存即生效**：改配置并保存后，下次 `/direct`/`/char`/合成自动刷新（原 reload 语义内建）。
- **`/char reload` 移除**：命令提示改为「配置面板保存即生效」；`/char` 仍可 list/show。
- **plugin_data 文件**：`director/characters.json` 仅作 **beta1 兼容/迁移兜底**（配置为空时读取并打迁移日志）；配置有内容则以配置为准，不再写文件。
- **默认示例**：schema 内置「小茵」JSON 预设（与风格示例池同款）。

### 验证

- 单测 **145/145**。
- **安装（2026-09-12）**：`force_refresh` 成功；failed **空**；**activated**；版本 **v2.4.1-beta2**；组件 **35**

## 2026-09-12 v2.4.1-beta1

> **内部测试版**：导演角色库 P5-M1 首切片（文件存储 + 查询 + `/direct <角色名>` + 合成展开）。

### 新增

- **角色库文件**：`plugin_data/astrbot_plugin_mimo_tts/director/characters.json`（权威资产，可手改；首次自动写入示例角色「小茵」）。
- **配置**：`director_characters_enabled`（默认关）、`character_require_voice`（默认开）。
- **命令**：`/char` 列表、`/char show <名>`、`/char reload`（管理员重读 JSON）。
- **应用**：`/direct 小茵` / `/direct once 小茵`（**不要求** `@角色`；`@小茵` 为可选别名）。
- **匹配流水线**：内置场景 → 角色短名精确匹配 → 三维稿 → LLM；长文/含三维标签不查角色库。
- **合成展开**：payload 含 `character_id` 时从库刷新 character/guidance（改库立即生效）。
- **音色**：应用角色时若会话音色仍为默认 → 自动绑定角色 `voice`；已自定义则不覆盖。

### 边界（beta1）

- 未做 `/char add/set/del` 与 WebUI 管理（手改 JSON + reload）。
- 未做 `asset_ref` 长文档读取。
- design 通道仍不注入导演。

### 验证

- 单测 **144/144**；ruff F/E9 通过。
- **安装（2026-09-12）**：`force_refresh` 成功；failed **空**；**activated**；版本 **v2.4.1-beta1**；组件 **35**（新增 `/char`）
- **日志闭环**：`characters loaded n=1` + `character apply id=xiaoyin layer=sticky voice=茉莉`（用户实测）

## 2026-09-12 v2.4.0

> **导演模式 P3 正式版**（内部 test1–test7 收口）。默认关闭；关闭时全链路与 v2.3.2 等价。

### 新增：导演模式

- **`/direct` 命令（公开）**
  - `/direct <内置场景名|三维稿|自然语言>` → 会话常驻（sticky）
  - `/direct once <…>` → 仅下一次合成（pending，优先于常驻，用尽自动回落）
  - `/direct` 查看两层状态；`/direct off` 双层全清
  - 三维稿：中文「角色/场景/指导」或英文 Role/Scene/Guidance
- **双层状态（P3 增强）**
  - `director_sticky` + `director_pending`；once **不**再覆盖会话常驻
  - 旧单槽 `director_mode`/`director_payload` 自动迁移（已有新字段不覆盖）
  - pending 成功消费后只清 pending，回落 sticky
- **内置场景 ×6**：深夜电台 / 哄睡 / 元气早安 / 古风叙事 / 新闻播报 / emo 独白
- **可选 LLM 自由解析**：`director_parse_llm` + `director_parse_prompt` + 超时/缓存 + 专用 Provider（回退：专用 → 润色 → 当前对话）；失败不中断其它功能
- **注入范围**：default / 克隆 / 唱歌；**design 不注入**（user=音色身份）
- **配置分组「导演模式」**：`director_enabled` 等，默认全关
- **模块**：`core/director_*` + `handlers/director.py`；`main.py` 仅注册

### 新增：Voice Studio 导演控制台

- REST：`director/scenes|state|parse|apply|clear`；`/tts` 临时覆盖 `director_sticky`/`director_pending`
- 合成页控制台卡片：UID / 内置场景 / 自定义描述 / 应用（session|once）/ 清除 / 分层状态
- 与 `/direct` 同一 `user_state` 状态源；合成默认吃已应用状态

### 日志与可观测

- `synthesize text … director=pending|sticky|pending+sticky|-`（`text=` = 实际朗读正文）
- `director set … layer=sticky|pending`；`director prompt applied mode=default|clone|…`
- 不做 ASR 回环：正文以 API assistant 字段为准

### 使用示例

```
/direct 哄睡
/direct once 元气早安
/mimo_say …          # director=pending+sticky，元气
/mimo_say …          # director=sticky，回落哄睡
/direct off          # 双层全清
```

### 边界

1. 场景包级双层；**不做**逐维粘性（P5）
2. 自动 TTS 会消费 pending
3. design 不注入；`mimo_direct` / `director_for_design` 未实现
4. clone + 哄睡等慢速场景叠层过重时，起音可能有轻微杂音（观察项，频繁再收窄）

### 验证（2026-09-12）

| 项 | 结果 |
|----|------|
| 单测 | **136/136** |
| review | **0 error** |
| 安装 | force_refresh → activated，failed 空，组件 34 |
| 双层闭环日志 | set sticky → set pending → `pending+sticky` → `sticky` 回落 → off 双清 |
| 听感 | 用户确认闭环；clone 起音杂音见边界 4 |

## 2026-09-04 v2.3.2

### 修复（缓存清理机制加固，补齐跨进程生命周期缺口）

- **temp 音频孤儿文件回收**：`_recent_files` 仅存内存，进程崩溃/重启后 `data/temp/` 下已生成的音频文件无人认领，100MB 总量上限约束不到这些孤儿——新增 `UserStateManager.cleanup_temp_dir()` 目录级扫描，插件加载时执行；mtime 存活期不足 1 小时的文件保留（防插件热重载瞬间误删旧实例仍在写入的在途文件），其余孤儿删除并记日志；
- **`_user_umo` / `_nl_sing_last` 无界增长修复**：两个派生映射（会话标识、自然语唱歌冷却）此前只增不减，长期运行的公群机器人慢性内存泄漏；现随 `_evict_stale_users` 与主设置同步淘汰（键不在 settings 存活集即清除），`restore()`/`reset_all()` 一并清理；`_nl_sing_last` 存储从 main.py 迁入 `UserStateManager`（main 经属性委托访问，handlers/nl_sing.py 零改动）；
- **日志滚动窗口改为时间驱动**：`cleanup_old_logs()` 此前仅在插件加载时执行一次，AstrBot 长驻不重载时日志可远超 7 天窗口持续累积；现 `write()` 按天惰性触发（当日首次写日志时清理，`_last_cleanup_date` 守卫防重复），启动清理保留且共用同一守卫；
- 移除死常量 `_MAX_LOG_LINES = 2000`（定义后从未引用）。

### 测试

- 新增 `tests/test_cache_cleanup.py`（11 项：孤儿扫描删除/近期保留/在途保护/缺目录回退/默认路径、派生映射淘汰/超限联动/restore/reset_all 清理、日志按天守卫/7 天窗口删除），新增 `tests/conftest.py` 为无 AstrBot 运行时提供 `astrbot.api` 最小桩；全套 35/35。

### 清理

- 移除 `tts/prompt_builder.py` 中已无消费方的 `detect_emotion` 兼容 re-export（handlers 已直连 `emotion.emotion_detector`）；同步修正 `emotion_detector` 过时注释。`astrbot_review_path` **0 error / 0 warning / 0 info**。

## 2026-08-30 v2.3.0

### 修复（分段模式行为重构，issue #9 问题一 + 用户实测反馈链）

- **分段「只剩纯语音」根因修复**：`/text off`（或 `send_text_with_tts=false`）时命中段跳过文字且 `result.chain=[]` 无兜底，配合默认 `segment_voice_probability=1.0`（每段必中）导致整条回复退化为纯语音流；按新决策矩阵补全所有开关组合行为，未命中/合成失败段有明确文字兜底出口；合成失败不再向聊天裸发 `[TTS 合成失败: ...]`，错误只写插件日志；
- **删除死代码**：`on_decorating_result` 中 `if i == 0 and len(seg) <= min_text_length` 分支（仅当首段长度恰好等于 min_text_length 时可达）；
- **分段模式接入 `text_async`**：文字异步发送此前仅在全文路径生效；现命中段支持「文字先发 + 语音后台串行补发」（单个后台任务按原顺序消费语音队列，不并行，避免顺序错乱与并发打满 TTS 服务端）；
- **命中段「文字先于语音」次序保证**：捆绑链 `[文字, 语音]` 在部分平台适配器（QQ/NapCat 实测）被渲染成语音在前，拆为两次顺序 `event.send`（先文字、合成完紧接语音），次序不依赖平台渲染行为；
- **`_polish` 函数 `uid` 未定义修复**（日志定位：`segment N delivery failed: name 'uid' is not defined`）：开启润色后每个命中段进入润色即抛 NameError、被兜底转纯文字，表现为命中段只有文字没有语音；
- **`do_tts` Markdown 清洗调用补接**：v2.4.0 曾出现 import 已加、调用点丢失的漏接（ruff F401 揪出），非唱歌分支统一清洗合成文本；
- **TTS 输入 Markdown 符号清洗**（日志取证：`**清炒蟹粉**` 原样进 TTS）：新增 `core/text_utils.strip_markdown_symbols()`，`do_tts` 非唱歌分支 + 润色输出双接入；清洗 `**`/`*`/反引号/`~~`/`__`/行首 `#`，不触碰 MiMo 官方标签，唱歌歌词豁免；
- **TTS 标签不外露用户侧**：新增 `core/text_utils.strip_tts_tags()`（剥开头 `(风格)` 与 `[音频标签]`/`【…】`，保留正文与普通括号），接入分段全部展示出口与全文路径（含 display_polished 润色文本展示、上游 LLM 自带标签清除）；
- **分段展示文本统一清洗 Markdown**：qq_official 等不支持 markdown 渲染的平台（表格/标题被管道剥掉只剩 `---`）；纯分隔线段（`---`/`***`/`___`）规划为 blank 整段丢弃，不再作为文字气泡发出；
- **静默出口全量加日志**：`on_decorating_result` 的 5 个静默 return（TTS 未激活/空 chain/非 LLM 结果/含语音组件/长短与跳过规则）此前零日志（实测 1200 字回复超 `max_text_length=500` 被静默跳过不可观测），现每个出口记录原因与关键上下文；
- **`enable_segmentation`/`enable_voice_polish` 会话快照修复**：旧实现首次创建会话时快照全局布尔，改全局对已有会话不生效，且 WebUI 会话级覆盖重启后丢失（`sanitize_user_settings` 未列入默认键被剥离）——改为三态 `None` 哨兵（None=实时跟随全局，True/False=会话级覆盖且可持久化），旧状态文件自动迁移。

### 新增

- **配置项 `segment_text_fallback`（默认 true，「文本分段」分组）**：无语音段（掷骰未命中/合成失败）是否纯文本兜底，关闭则丢弃（纯语音流偏好）；短于 `min_text_length` 的段为固定策略无条件发文字。文字与语音时序由 `send_text_async` 承担，两开关职责不重叠；
- **配置项 `display_polished_text`（默认 false，「语音润色（LLM）」分组）**：展示文字用润色后文本，与语音内容一致，兜底小模型不遵守「保持原文不变」导致的文声割裂；全链路覆盖分段 BUNDLED/VOICE_ONLY/TEXT_FIRST/失败兜底与全文同步/异步，代价为文字等待一次润色 LLM 调用；
- **测试**：新增 `tests/test_segmentation.py`（24 项：掷骰/短段/分隔线段/概率边界/rng 注入/决策表 2⁵ 全组合/Markdown 清洗/标签剥离），`core/text_utils` 支持无 AstrBot 运行时的独立导入。

### 优化（对照 MiMO 官方文档校对，speech-synthesis-v2.5 + TTS API）

- **润色提示词 V3**：规则 4 升级「严格保持原文内容一字不变」、新增「输出必须纯文本、禁 Markdown 格式符号」；标签示例全部对齐官方词表（哭笑/情绪/呼吸/停顿四类，[语速加快]/[语速放慢] 非官方词表已移除，[停顿] 官方认可保留），加表现力倾斜（优先 [轻笑]/[叹气]/[气声]/[撒娇]/[激动] 等有感染力标签，避免整段只剩功能性标签），数量收紧 1-3 个防堆砌；模板总长与上一版持平；
- **旧默认模板等值迁移**：`polish_prompt` 配置面板残留的 V1（v2.2.x）/V2（v2.4.x 早期）默认模板自动迁移到 V3（`sing_styles` 预设迁移同款机制）；自定义过模板的用户不受影响；schema 默认值同步；
- **Voice Studio 插件页对齐**：配置表补齐 `segment_text_fallback`/`display_polished_text` 两项（后端 `api_update_config` 白名单动态生成，仅缺展示层）；过期 hint 对齐（`tts_example_inject` 去内部代号、分段/润色组 hint 与 schema 同文）；会话编辑三态语义修复（null=跟随全局不再被勾选框钉死为显式 false，卡片信息条显示「跟随」）；
- 配置面板「普通 TTS 风格示例注入」hint 文案更新（去内部代号，明确默认关闭理由）。

### 重构

- **分段逻辑分层**：新增 `core/segmentation.py`（规划层纯函数：切分掷骰 `plan_segments` + 唯一决策表 `resolve_delivery`，5 种投递动作 BUNDLED/TEXT_FIRST/VOICE_ONLY/TEXT_FALLBACK/DROP，可注入 rng 脱离 AstrBot 单测）与 `handlers/segmenting.py`（执行层只分发不做决策，含失败降级与后台语音队列）；`on_decorating_result` 分段分支从 55 行循环瘦身为「切分 → 执行 → 清空」；
- **main.py 模块化拆分**（849 → 506 行，职责按官方 modular-split 指引收敛为 Star 子类/生命周期/薄 hooks/命令路由/共享访问器）：润色提示词模板与润色调用抽至 `core/polish.py`；自动 TTS 钩子整体抽至 `handlers/auto_tts.py`（`handle_auto_tts` + 后台补发 `send_tts_audio_background`，情感检测收敛为 `_detect_emotion` 单点）；Web API 注册抽至 `webapi.register_web_apis`（路由表白驱动）；sing_styles 预设迁移抽至 `core/config.migrate_sing_styles`；清理零引用代理方法（`_user_settings`/`_recent_files`/`_voice_manager_ref`/`_parse_opt`）与溯源式注释，拆分后全量导入路径 AST 核验通过；
- 引入 ruff F 类（未定义名/未使用导入等）静态扫描作为回归防线，配合 py_compile/单测/node --check 构成本次全链路校验（`astrbot_review_path` 0 error，单测 24/24）。

## 2026-08-18 v2.2.9

### 修复

- **WebUI「已注册音色」删除不可用**（用户反馈）：后端删除逻辑正常（与 `/voiceclone cancel` 同路径），根因是 AstrBot 插件页 webview 中原生 `confirm()` 可能被拦截导致点击无反应——改为**页面内两步确认**（点「删除」→ 按钮变「确认删除/取消」→ 确认后调 `POST /voices/delete`），会话管理页同类问题一并替换；删除成功后同步刷新音色列表与克隆/设计风格控制池；
- `api_delete_voice` 联动清理扩展为**双池防御性清理**（clone + design 风格控制池条目，清理失败不影响删除）；
- 克隆/设计池**空条目回退全局**语义统一：`resolve_clone_style_prompt`/`resolve_clone_audio_tags`/`resolve_design_description` 对"条目存在但值为空"现在正确回退全局（此前 v2.2.8 clone 空条目会返回空串，与"留空=用全局"不一致）。

### 新增（设计音色风格控制池，与风格示例池融合供导演模式）

- **配置面板「声音设计」新增「设计音色风格控制池（JSON）」**（与「克隆音色风格控制池」「唱歌风格库」同款 JSON 编辑器）：每项 `name`（设计音色 ID）/ `description`（音色描述，留空 = 用全局 `design_voice_description`；**可直接填本组「风格示例池」分类名 name 如「温柔甜美」**，自动启用词表提示+画面感例句——与 `/voicegen 温柔甜美` 方案 A 同链路）；
- **配置池成为 design 音色描述的权威数据源**：`resolve_design_description` 改从 `config.design_style_pool` 读取（override > 池条目 > 注册表旧描述（惰性迁移并入池）> 全局）；`/voicegen` 注册与 WebUI「保存为设计音色」均写入同一配置池（双向联动）；
- 新接口 `GET /voices/design-style-pool` + 音色管理页「设计音色风格控制池」区块（镜像克隆池：行内编辑描述保存、复制 JSON、全局值只读提示）；`api_design_voice` 允许空描述（行内清空 = 回退全局）；
- **导演模式素材融合**：本池（per-voice 设计描述）+ 风格示例池（词表/画面感例句）+ 克隆风格控制池（per-voice 风格/标签）三者均为配置面板 JSON 权威源，导演模式（角色/场景/指导三维刻画）可直接引用这些素材。

### 说明

- 行为测试 9/9（新：design 池 normalize/权威/空条目回退/惰性迁移/接口/删除双池清理）+ 回归 10/10 + 11/11 + 12/12 + 9/9；py_compile / ruff / node --check 通过；review_path 0 error（5 warning / 32 info 与既往裁定完全一致，零新增）；
- **用户实测确认固化（R1-R6 全部通过）**：删除两步确认可用、设计池 JSON 出现、分类名方案 A 生效、WebUI 保存 ↔ 配置面板双向联动、行内编辑生效、命令删除与 WebUI 删除均正常清理池条目；
- **已知问题（用户决定暂不处理，已存档设计文档 §13.5）**：`enable_voice_polish` 开启时 LLM 音色润色可能扩写正文（deepseek-v4-flash 等小模型不遵守"保持原文不变"约束，擅自补写并自选风格标签）——日志锚点 `voice polish applied, N chars -> M chars`；修复方向：关润色开关 / 换更强 Provider / 插件侧标签剥离+正文还原。
- **品牌与元数据更新（同版本部署，用户实测确认 S1-S3）**：logo.png 内联 base64 部署到 Voice Studio 侧边栏与关于页标题旁（规避插件页静态资源仅重写 HTML/CSS、Vue 模板内 src 不重写导致的 404——首版相对路径失败显示 alt 文本，已修复）；关于页「功能特性」更新为 16 项；`metadata.yaml` desc 补全 v2.2.x 能力、`astrbot_version` 更新为 `>=4.26.0`；README 徽章同步。版本保持 v2.2.9（force_refresh 同版本部署，配置保留）。

## 2026-08-18 v2.2.8

### 新增（克隆音色风格控制池 → 配置面板联动：conf_schema 为核心）

- **配置面板新增「克隆音色风格控制池（JSON）」**（用户核心需求）：位于「声音克隆」配置分组，与「唱歌风格库」同款 JSON 代码编辑器格式（`type: text` + `editor_mode` + `editor_language: json`），容错解析（缺 `[ ]`/全角引号自动修复，仍错回退空池）。每项 `name`（克隆音色 ID）/ `style`（风格控制，留空 = 用全局 `clone_style_prompt`）/ `audio_tags`（音频标签，留空 = 用全局 `clone_audio_tags`）；
- **配置池成为 per-voice 风格/标签的权威数据源**：`resolve_clone_style_prompt` / `resolve_clone_audio_tags` 改从 `config.clone_style_pool` 读取（override > 池条目 > 全局）；WebUI「保存为音色风格」与音色管理页风格控制池的保存均写入同一配置池——**配置面板改 → 合成链路立即生效；WebUI 改 → 配置面板同步可见**，双向联动；
- **合成页联动显示当前音色风格**（用户核心需求）：克隆模式下切换音色时，「克隆音色风格控制」输入框自动显示**该音色已保存的 per-voice 风格**（无则显示全局），便于直接编辑并保存当前音色；输入框定位从"全局预设"改为"当前音色"（保存即写入该音色池条目）；
- **旧数据惰性迁移**：v2.2.6/v2.2.7 写入注册表条目的 per-voice 数据（`style_prompt`/`audio_tags`），首次合成时自动并入配置池并返回（零数据丢失，之后以配置池为准）；
- **删除联动**：WebUI 删除克隆音色时同步清理配置池对应条目。

### 说明

- 行为测试 10/10（新，配置池联动/迁移/删除清理）+ 回归 9/9 + 12/12 + 11/11；py_compile / ruff / node --check 通过；review_path 0 error（5 warning / 32 info 与既往裁定完全一致，零新增）；
- 语义明确：配置面板「声音克隆」分组的 `clone_style_pool` 是**最常用的配置点**（JSON 直改即联动），音色管理页风格控制池是**可观测辅助**（行内编辑同源）；合成页输入框 = 当前音色 per-voice 编辑 + 实时试听。安装后待用户实测（Q1-Q6，见报告 ⓪-28）。

## 2026-08-18 v2.2.7

### 新增（克隆音色风格控制池 + 音频标签 per-voice）

- **合成页输入框更名**：「克隆风格控制」→「克隆音色全局风格控制」，明确该输入框编辑的是全局 `clone_style_prompt`；
- **音频标签 per-voice 化**：`api_clone_style` 支持同时保存 `style_prompt` 与 `audio_tags`（仅克隆音色，合并保留 audio_path）；新增 `resolve_clone_audio_tags`（override > per-voice `audio_tags` > 全局 `clone_audio_tags`），`build_clone_prompt` 增加 `audio_tags` 参数（缺省读全局，旧调用零变化）——克隆音色专属音频标签（`[笑]` 等）与专属风格一样按音色生效；
- **音色管理页「克隆音色风格控制池」**（用户需求）：新接口 `GET /voices/clone-style-pool` 返回全局风格/标签 + 各克隆音色已保存的 per-voice 记录（空 = 用全局）；页面新增管理区块——每个克隆音色一行，风格控制与音频标签可**行内编辑并保存**（复用 `api_clone_style`），支持**复制整池 JSON** 备份；修改全局值提示前往「插件配置 → 声音克隆」。

### 说明

- 行为测试 11/11（新）+ 回归 9/9（B）+ 12/12（C1+C2）；py_compile / ruff / node --check 通过；review_path 0 error（5 warning / 32 info 与既往裁定完全一致，零新增）；
- 安全：`audio_tags` 截断 500、仅克隆音色可写（404 拒绝）、override 走 `_do_tts` 内存合并不落库、池接口只读克隆音色注册表（不含 design）；安装后待用户实测（P1-P6，见报告 ⓪-27）。

## 2026-08-18 v2.2.6

### 新增（clone 体验闭环：WebUI 试听一键保存 + 对称性修复）

- **合成页「克隆风格控制」实时试听**：克隆模式新增风格输入框（默认预填全局 `clone_style_prompt`），`/tts` 接口支持 `clone_style_prompt` override（仅本次合成不落库）——改风格即试听，与 design 侧 v2.2.5 完全对齐；
- **「保存为音色风格」一键保存**：新接口 `POST /voices/clone-style`，将当前克隆音色的风格控制持久化为 **per-voice style_prompt**（写入音色条目，合并保留原 name / audio_path）——切换克隆音色即切换其专属风格（优先于全局），彻底解决"所有克隆音色共用一份全局风格"；
- 后端新增 `resolve_clone_style_prompt`（override > per-voice style_prompt > 全局 `clone_style_prompt` 回退链）；`build_clone_prompt` 增加 style_prompt 参数（缺省读全局，旧调用行为不变）；
- **clone 对称性修复（§14.11.3，B）**：`/voiceclone cancel <名>` 同步清理 `config.clone_voice_id`（对齐 design cancel）；clone 路由改**当前选中音色优先**（`config.clone_voice_id` 仅兜底兼容老用法）——修复"注册 A→B 后切回 A 合成仍用 B"与"删除音色后 clone 模式报错"两个缺陷。

### 说明

- 行为测试 9/9（B 回归）+ 12/12（C1+C2）；py_compile / ruff / node --check 通过；review_path 0 error（5 warning / 32 info 与既往裁定完全一致，零新增）；
- 安全：保存接口仅允许克隆音色（404 拒绝非克隆/未注册）、合并保留 audio_path 不破坏克隆链路、override 走 `_do_tts` 内存合并不落库；安装后待用户实测（B T1-T4 / C G1-G5，详见报告 ⓪-26）。

## 2026-08-18 v2.2.5

### 新增（design 体验闭环：WebUI 试听一键保存）

- **合成页「设计描述」实时试听**：设计模式下新增描述输入框，`/tts` 接口支持 `design_description` override（优先于选中设计音色描述与配置字段，仅本次合成不落库）——改描述即试听，"试听的即保存的"；
- **「保存为设计音色」一键保存**：描述 + 可选 ID（留空用描述）→ 复用 `api_design_voice` 注册 → 自动刷新音色列表并选中；试听满意直接固化，无需切到音色管理页；
- 后端 `resolve_design_description` 增加 override 参数（缺省 None，命令/旧调用完全兼容）。

### 说明

- 用户实测确认（F1-F5）：设计描述框出现、override 试听生效、一键保存并选中、回退正常、命令链路回归无影响；README 使用说明优化（快速开始 / voicegen 命令新用法 / design 示例）。

## 2026-08-18 v2.2.4

### 新增（design 资产化：示例池一键注册 + 删除闭环）

- **`/voicegen <分类名>` 一键注册设计音色**：单参数未命中已注册音色时，若精确命中 `style_examples` 分类名（如 `/voicegen 温柔甜美`）→ 自动登记为设计音色并切换（方案 A，§14.5）——示例池 6 类风格一键变成可切换的设计音色（`/voice 温柔甜美` 直接切），完整词表提示+画面感例句随示例池条目自动生效；已注册后再次执行走普通切换，不重复注册；
- **`/voicegen cancel <音色名>` 删除闭环**：取消注册设计音色；若当前正在使用该音色，自动回退默认音色并把输出模式切回「默认」；同步清理 `design_voice_id`；
- 双参数 `/voicegen <ID> <描述>` 填分类名时增加方案 A 生效提示；无参帮助补齐新用法与示例。

### 优化

- 与合成链路方案 A 打通：此前注册音色描述走自由文本链路（name 简写如"温柔甜美"可能 extract 漏词），现一键注册直接复用 `match_style_entry_by_name`，注册音色与配置字段行为一致。

## 2026-08-18 v2.2.3

### 优化

- **润色缓存模板指纹**：唱歌润色缓存 key 加入模板指纹与例句指纹——修改 `sing_direct_prompt` / `sing_tag_prompt` / `style_examples` 后，同歌词+同风格**立即换缓存**，新提示词马上生效（此前要等 TTL 600s 过期或换歌词绕过，调听感时容易误以为模板没生效）；同参数重复唱歌仍零 LLM 延迟；
- 默认演唱描述模板抽为常量（配置留空时即缓存基线，改模板自然换缓存）。
- **演唱描述模板约束补充**（用户实测确认）：第 3 条增加「严格贴合【风格】描述演唱，不要被歌词语义带偏」——修复歌词语境（撒娇/叙事等）带偏演唱风格的问题（如小雪组"温柔甜美"曾被歌词撒娇语境带成"慵懒俏皮"）；用户实测听感贴合风格组。

### 说明

- 核实 AstrBot 动态上下文机制：`extra_user_content_parts` 属对话链路请求对象（`on_llm_request`）字段，本插件所有 LLM 调用均为裸 `llm_generate`（独立单轮、无历史无 system_prompt），不适用且无违规；该规范已落档，供未来导演模式对话链路拦截实施时遵守（动态内容必须走 `extra_user_content_parts` + `mark_as_temp()`，禁止逐轮改 system_prompt，避免 provider prefix cache 失效成本 7-20×）。
- 实测确认：E2 同歌词+同风格重复唱歌日志 `polish cache hit`（缓存正常、零 LLM）；E1 改模板后模板指纹变化→换缓存→新模板生效，听感贴合风格组（用户确认）。

## 2026-08-17 v2.2.2

唱歌模式增强正式版（V1 全量落地 + 多轮实测打磨固化；含风格示例池三通道铺开、双通道风格注入定稿与三大提示词优化，设计文档 `docs/sing-mode-feature.md`）。

### 新增

- **唱歌风格库 `sing_styles`**：JSON 数组配置（`type: text` + `editor_mode` 代码编辑器），每项支持 `name` / `style`（风格描述）/ `tags`（演绎词，顿号分隔，走 user 通道自然语言）/ `style_tags`（风格标签词，显式注入）/ `voice`（组绑定音色）/ `speed`（0.5~2.0）/ `pitch`（整数半音）；内置「小雪/小花」双组换行预设；
- **风格优先级链**：`-p` 提示词 / `(风格)` 括号词（同级叠加）> `-s` 风格组 > 会话风格组（`/singstyle set`）> 仅 `(唱歌)` 标签（自动注入）。`-p` 覆盖组内风格描述，组内静态标签与绑定音色/语速/音高仍生效；
- **`/sing` 参数扩展**：`-s 风格组`（一次性）、`-p "提示词"`（支持引号跨空格）、`(风格) <歌词>` 括号简写、`-音色名` 裸写法；多参数顺序无关（统一 flag 解析器，`/mimo_say` 共用）；
- **`/singstyle` 命令组**（ADMIN）：`show` 查看本对话设置 / `list` 列出风格库 / `set <组名>` 切换（按对话隔离持久化）/ `reset` 恢复跟随全局；
- **双通道风格注入**：风格表达走 user 自然语言通道（官方唱歌风格通道，默认 `prompt` 模式）——LLM 产出**画面感演唱描述**（"像…一样"+节奏收尾，官方示例同构）注入控制指令；`core/style_lib.py` 内置官方风格词表（6 类）与标签漏斗（`style_tags` 显式 > 本地词表提取 > LLM 筛选白名单），`sing_style_source` 三态（`prompt` 默认 / `tag` 收窄 / `off`）；
- **歌词 LLM 润色 `sing_lyrics_polish`**（默认关，关闭零影响）：唱歌前调用 LLM 生成演唱描述 / 风格标签筛选，模板 `sing_direct_prompt` / `sing_tag_prompt` 可配（`{text}` / `{style}` 占位符）；失败 / 超时 / 为空自动降级，歌词保持纯净；
- **自然语言触发唱歌（正则快路径）**：`nl_sing_enabled` 开启后，@机器人 说「用X的声线唱<歌词>」「唱<歌词>」直接演唱（零 LLM；风格/音色名白名单、歌词长度、疑问句排除防误触；会话级冷却）；
- **NL 唱歌 LLM 工具兜底**：`nl_sing_tool` 开启后，正则未命中的自由措辞由 LLM 工具 `mimo_sing_song` 解析演唱（立即返回、后台合成不阻塞回复）；
- **唱歌润色专用 Provider** `sing_polish_llm_provider`：Provider 链 唱歌专用 > 通用 `polish_llm_provider` > 当前对话模型，建议选轻量快速模型降低演唱延迟；
- **润色延迟优化**（全部可配）：默认模板"不要思考、第一句直接输出"硬约束 + 结果缓存 `sing_polish_cache_ttl`（默认 600s，相同歌词+风格复用，重复唱歌零延迟）+ 超时看门狗 `sing_polish_timeout`（默认 20s，超时降级不阻塞唱歌）；
- **Voice Studio WebUI**：「唱歌优化」配置分区（风格库 JSON 编辑器 + 风格注入源 + 润色开关/模板/超时/缓存）、合成接口唱歌通道、`/tts_help` 唱歌命令分区；
- **风格组绑定演绎参数**：组内 `voice` / `speed` / `pitch` 选中该组唱歌时自动覆盖（仅本次合成、不持久化）；`sing_voice` 支持填风格库组名自动映射其绑定 voice；
- **style_lib 赋能 design/clone**：官方风格词表升级为全 TTS 风格资产——voicedesign 设计描述与 clone 风格文本中的官方词（温柔/甜美/磁性…）自动提取并追加分类结构化提示（"整体语调温柔…，音色定位甜美…"），零配置零侵入（无官方词时不加）；为导演模式（风格/指导/角色三维）铺路；
- **导演模式先导：风格示例池三通道铺开**（§14）：新配置 `style_examples`（JSON，内置 6 类高质量中文画面感示例）——design 描述命中风格词自动并入"参考示例：…"（零 LLM 零延迟）；`design_voice_description` 填示例池分类名可**精确引用条目**（完整词表提示 + 例句，快速切换风格，§14.5 方案 A）；clone 风格文本按同一规则直拼；唱歌歌词润色时匹配例句作 LLM few-shot 参考（≤2 条、每条 ≤30 字，不直拼防描述冲突）；普通 TTS 可选注入（`tts_example_inject`，**默认关**，emotion→官方词映射 `EMOTION_TO_TAG` 14 组）；无匹配一律零注入；
- **命令体验**：`@bot` 后缀归一化（`/sing@bot 词` 可用）、统一 flag 解析器（顺序无关、引号跨空格值）。
- **三大 LLM 预设提示词全文优化**（专业角色定位 + 结构化指令 + 更好的润色效果）：
  1. `sing_direct_prompt`（演唱描述）：专业演唱指导角色，60 字内画面感描述（"像晨露一样清透"比喻 + 明快/轻柔基调 + 节奏音高走向），保留防收窄词禁令与禁思考约束；
  2. `sing_tag_prompt`（风格标签筛选）：语气风格标签筛选专家角色，词须与描述含义一致、不强行凑数、第一行即结果；
  3. `polish_prompt`（通用语音润色）：专业语音润色专家角色，开头 1 个 () 风格标签 + 关键处 ≤2-3 个 [] 音频标签（宁缺毋滥）、保留原文、第一行即结果；
  同步于 schema default + 代码兜底（配置留空即用新模板）；面板已保存旧值的字段需清空或手动替换。

### 优化

- 配置面板：`sing_styles` 改 `text` + `editor_mode`（修复 `list` 类型导致 Dashboard 渲染异常）；独立「唱歌优化」分组并置于「语音润色（LLM）」下方；
- 风格库 JSON 容错：全角引号自动转直引号、裸对象序列自动补 `[ ]` 数组括号、单裸对象视为单组；`/singstyle list` 对格式错误显式提示修正要点；
- 演唱指导模板防收窄：明确禁止"收束/收紧/压低/减弱"等收窄类词汇（实测会按字面执行成压嗓），并在润色上下文注入实际音色/语速/音高，指导与配置磨合；
- 唱歌 few-shot 例句 ≤30 字（低于 design ≤40 字），token/时延开销极小；缓存 key 含 style_desc，例句变化自然换缓存；
- 内置预设升级为「小雪/小花」双组（小雪：茉莉 / 1.5 / 1 / 轻笑；小花：冰糖 / 1.1 / 1 / 可爱）。

### 修复

- 风格库静态标签 / 润色标签被唱出：实测唱歌模式下 `[]` 音频标签（含 mid-text）会被当作歌词唱出（官方对"唱歌+音频标签"组合零定义）——组内 `tags` 改走 user 通道自然语言演绎指令，歌词保持纯净；
- `/sing (温柔)` 风格词被读出：括号风格词自动移入 user 控制指令，assistant 只保留精确 `(唱歌)`（括号含句读或任一词超 8 字视为歌词原文保留，不误吞）；
- design / clone 输出模式下 `/sing` 走错模型合成失败：唱歌强制回退 `mimo-v2.5-tts` + 预置音色（`sing_voice` > `default_voice` > `mimo_default` 兜底）；
- `/mimo_say` 与 WebUI 合成参数覆盖未进入控制提示词：`build_prompt` 改用合并后的覆盖副本，`-speed` / `-pitch` / `-breath` / `-stress` / `-dialect` / `-volume` / 具名情感恢复生效；
- 多风格括号 `(唱歌 词…)` 在唱歌模式朗读：**实测矩阵（五种括号写法 × 直连服务端）**——`(唱歌 温柔 甜美)`/`(唱歌 温柔，甜美)` 朗读+异常发音、`(唱歌)(温柔)(甜美)` 前半段杂音唱歌、`(唱歌 温柔)` 感情朗读、仅 `(唱歌)` 正常唱歌。唱歌模式只认精确 `(唱歌)` 标签，风格一律走 user 自然语言通道——`tag` 模式收窄为仅收集不注入（防朗读），`style_tags`/官方词表漏斗保留供未来非唱歌场景复用；
- 润色链路配置读取异常：补全缺失的配置属性访问，超时 / 缓存配置实际生效。

### 行为说明

- 唱歌默认走 user 自然语言风格通道（官方唱歌风格通道）；`tag` 标签模式已收窄（仅收集不注入，效果同 off）；
- 歌词润色开关关闭（默认）时，不发起任何 LLM 调用，行为与历史版本一致；
- 组内 `tags` / `style_tags` / `voice` / `speed` / `pitch` 与 `style` 描述正交：`-p` 覆盖描述，组内其余字段仍生效；
- 普通 TTS 示例注入默认关闭（`tts_example_inject=false`），开启后按当前情感匹配示例池并入 user 控制通道。

## 2026-08-16 v2.1.4

### 新增

- `/sing` 开头风格括号语法：`/sing (温柔) <歌词>`（也支持 `(温柔 甜美)` 多词、`(唱歌)(温柔)词` 混排）。括号内的风格词自动移入 user 角色控制指令，assistant 只保留精确 `(唱歌)` 标签——此前 `(温柔)` 会被当作歌词读出来。带守卫：括号内容含句读或任一词超过 8 字时视为歌词原文保留，不误吞。

## 2026-08-16 v2.1.3

### 修复

- 唱歌组合标签归一化（v2.1.2 实测回滚修正）：实测发现官方文档允许的"(唱歌 温柔)"多风格同括号写法会让服务端丢失唱歌判定（进入朗读态，甚至读出标签残留）。现改为**归一化**——assistant 文本只保留精确 `(唱歌)` 标签，组合括号内的附加风格词自动拆出并移入 user 角色控制指令（官方风格控制通道）。`/sing (唱歌 温柔)晚风轻拂` 现等效于 `/sing 晚风轻拂` + 控制指令"温柔"。

## 2026-08-16 v2.1.2

### 修复

- 修复 `/mimo_say` 与 WebUI 合成接口的参数覆盖未进入控制提示词的问题（`build_prompt` 此前重读持久化设置而非合并后的覆盖副本）：`-speed` / `-pitch` / `-breath` / `-stress` / `-dialect` / `-volume` 与具名情感（如 `-emotion happy`）此前静默失效，现恢复生效；`-emotion off` 现可正确关闭情感。曾设置过这些参数的用户升级后可能感觉语音风格"恢复生效"，属预期行为；
- 同时加固：`auto` / `off` 等控制值不再以字面形式（如"用auto的语气"）混入控制提示词；
- 修复 design / clone 输出模式下 `/sing` 走错模型导致合成失败的问题：唱歌强制回退 `mimo-v2.5-tts` + 预置音色（当前音色为自定义克隆/设计音色时，自动按 `sing_voice` → `default_voice` → `mimo_default` 顺序兜底）；
- `apply_singing_tag` 兼容官方"多风格同括号"写法（如 `(唱歌 温柔)`、`（唱歌，欢快）`），不再产生双重 `(唱歌)` 前缀。

### 优化

- 命名矫正：`build_system_prompt` → `build_control_prompt`、`synthesize(system_prompt=)` → `control_prompt=`。两者实际均为 MiMO 官方要求的 **user 角色控制指令**，原命名易被误读为 system prompt（纯内部重命名，零行为变化）。

## 2026-07-13 v2.1.1 

（感谢来自 @ LilycleHeart 的大佬提供的更新）

### 新增

- 文字异步发送：新增全局配置 `send_text_async`（默认关闭）。开启且同时保留文字输出时，文字立即发出，润色 + TTS 在后台合成完成后追加语音，降低首条回复等待；
- 会话级覆盖：每会话可独立设置 `text_async`（`null` 继承全局）；WebUI 会话详情/编辑页同步增加开关与状态展示；
- 插件侧边栏图标：`metadata.yaml` 增加 `icon: mdi-account-voice`。

### 优化

- Voice Studio 主题改为跟随 AstrBot Dashboard：通过 `bridge.onContext()` 监听 `isDark`，移除独立主题切换按钮；页脚改为只读主题状态指示；
- 侧边栏 CSS 简化并提高优先级：去掉 `@property`、复杂光晕/`!important` 堆叠，固定宽度 240px，保证在 Dashboard 中基础布局稳定。

### 修复

- 修复部分 WebView 不支持 `@property` 导致 sidebar 样式解析失败、被 Dashboard 基础样式覆盖的问题。

## 2026-05-30 v2.1.0

### 新增

- 配置面板重构为嵌套分类（10 个 object 组）：API 设置、音色设置、TTS 参数、输出设置、文本分段、语音润色、声音克隆、声音设计、预设描述、高级设置；
- 高级设置新增模型超参：采样温度（temperature）、核采样阈值（top_p），透传至 MiMO API；
- 插件日志系统（WebUI）：文件日志、JSON 格式、7 天滚动清理、级别过滤，不影响 AstrBot 内置日志；
- 命令权限控制：25 个管理指令限制为管理员使用，`/mimo_say`、`/sing`、`/ttsinfo` 公开；
- README 新增命令总览表格。

### 优化

- temp 文件清理上限从 500MB 降至 100MB，滚动清理；
- WebUI 启动优化：Vue/Vue Router 改为本地文件，消除 CDN 延迟；
- WebUI 通知改为 toast 样式（右上角滑入，3s 自动消失）；
- 通过 i18n 覆盖插件页面描述（替换默认的 Plugin Page entry）。

## 2026-05-28 v2.0.0

### 新增

- Voice Studio WebUI 插件页面：内置可视化管理界面，包含语音合成、音色管理、插件配置、会话管理、关于五个分页；
- 会话管理：支持查看完整 UMO、按 UID/UMO 搜索、会话总数统计、编辑/重置/删除会话配置；
- 会话编辑支持独立配置分段与润色开关，首次创建时自动继承全局配置；
- 合成页新增 LLM 润色开关（页面局部，不写回全局配置）；
- `/voicegen` 支持已注册音色 ID 直接切换，自动切换输出模式为设计。

### 优化

- WebUI 安全加固：voice_id 输入过滤、base64 大小限制、配置/会话 key 白名单、文本长度截断；
- 内联 SVG 图标系统，零 CDN 依赖；
- Sidebar Island 模块化设计，入场动画、卡片光晕、响应式布局；
- 会话配置首次初始化时从全局配置继承分段/润色设置。

## 2026-05-26 v1.4.0

### 新增

- 文本分段 TTS：支持 4 种预设正则规则（sentence/paragraph/comma/mixed），长文本自动切分为多段独立发送；
- 分段语音输出概率：0.0~1.0 滑块控制，每段独立掷骰决定是否语音输出；
- 分段数量上限：防止无限切分，默认 10 段；
- 首段快速回复：首段短文本（≤min_text_length）纯文字立即发送，后续段落语音补充；
- LLM 音色润色：调用 LLM 为文本注入 MiMO 音频标签（如 (温柔)[叹气]），增强语音表现力；
- 润色 LLM Provider 选择器：支持指定 AstrBot 内已启用的 LLM Provider，留空使用当前对话模型；
- 润色提示词自定义：支持 `{text}` 占位符；
- 默认音色改为下拉选项（9 种内置音色）；
- 默认语速/音高/触发概率增加滑块控件。

### 优化

- 润色延后执行：仅对确认要发语音的分段调用 LLM，节省 token；
- 分段模式用 `event.send()` 逐段独立发送，兼容 outputpro 等输出增强插件；
- Plain 显示文本剥离音频标签，避免被 outputpro 文本清洗影响；
- `main.py` 进一步拆分：提取 `core/text_utils.py`、`core/user_state.py`、`tts/synthesis.py`，从 1281 行降至 529 行；
- 提升 `astrbot_version` 至 `>=4.5.7`（依赖 `llm_generate` API）。

## 2026-05-12 v1.3.0

### 架构优化

- 将 `main.py` 中的 28 个命令处理器拆分至 `handlers/` 子模块（tts/control/params/preset/voice/settings），`main.py` 仅保留类结构 + 委托调用，从 1855 行降至 1158 行；
- 删除空模块 `core/compat.py`（历史兼容层，已无实际作用）；
- 默认音频输出格式从 `mp3` 改为 `wav`（兼容性最佳），同步更新 `_conf_schema.json`、`ConfigManager`、`MiMOProvider` 默认值；
- 清理 `core/constants.py` 中未被任何模块引用的孤立常量（`DEFAULT_*` 系列）；
- 统一 `max_retries`/`min_text_length`/`max_text_length` 的内联 fallback 与 `_conf_schema.json` 默认值一致；
- `handlers/settings.py` 自行读取 `metadata.yaml` 获取版本号，避免循环导入。

## 2026-05-11

### 修改

- `tts/mimo_provider.py`：TTS 请求头调整为同时发送 `api-key` 与 `Authorization: Bearer <API_KEY>`，增强对 MiMO 原生平台及兼容代理的鉴权兼容性，同时保留原有 `api-key` 行为不变。
- `main.py`：插件版本展示改为从 `metadata.yaml` 动态读取，避免代码中的版本号与插件元数据不一致。
- `requirements.txt`：补充 `pyyaml>=6.0` 依赖，用于读取 `metadata.yaml`。

## 2026-05-08

### 新增

- `/voiceclone <音色名>`：对已注册的克隆音色无需重复指定音频路径，直接切换。
- `/voiceclone cancel <音色名>`：取消注册某个已注册的克隆音色，若当前用户正在使用该音色则自动回退为插件默认音色。
- `/voiceclone`（无参数）：列出所有已注册的克隆音色。
- `/tts_help` 新增 `/voiceclone` 相关提示，包括切换与取消注册用法。

### 修改

- `main.py` 中 `cmd_voiceclone` 重构为三路分支（cancel / 单参数切换 / 双参数注册），原有注册流程完全不变。

## 2026-04-30

### 更新内容

- 唱歌模式 `/sing` 改为单次触发模式，执行后自动恢复原始设置，避免持续污染普通 TTS；
- `/sing` 新增 `-音色名` 参数支持，可临时指定唱歌音色（如 `/sing -冰糖 歌词`）；
- 新增 `sing_voice` 插件配置项，支持通过下拉选择框配置唱歌模式默认音色；
- 唱歌音色优先级：命令参数 > 当前用户音色 > 插件配置 `sing_voice`；
- `main.py` 中 9 个命令处理器（`/text`、`/sing`、`/voice`、`/ttsswitch`、`/preset`、`/voiceclone`、`/voicegen`、`/ttsconfig`、`/ttsraw`）统一改用 `self._parse_cmd()` 提取参数，减少重复的字符串处理代码；
- `main.py` 用户状态持久化：将过期用户淘汰逻辑 `_evict_stale_users()` 移入写锁内，确保淘汰与持久化的原子性，避免并发写入时的竞态条件；
- `tts/mimo_provider.py` 新增不可重试 HTTP 状态码处理：遇到 400（参数错误）、401（未授权）、403（鉴权失败）时立即终止重试，减少无意义的重试等待；
- `voice/voice_manager.py` 收窄 `_backup_corrupted_file()` 的异常捕获范围，由 `except Exception` 改为 `except (OSError, shutil.Error)`，避免意外吞掉非文件系统相关异常；
- 使用 mimo-v2.5-pro 生成。

## 2026-04-28

### 更新内容

- 新增路径白名单安全机制，防止目录穿越攻击；
- 新增 `on_unload()` 资源释放钩子；
- 修复配置引用脱钩、磁盘清理路径异常等问题；
- 消除情感检测逻辑重复，优化代码结构；
- 今日更新使用 mimo-v2.5 对代码和功能进行优化。

## 2025-04-26 v1.2.3

### 更新内容

- 新增 `send_text_with_tts` 配置项，可控制自动 TTS 时是否同时保留文字输出；
- 新增 `/tts_off` 与 `/tts_on`，用于按当前对话关闭/恢复自动 TTS；
- 新增 `/text <on|off>`，用于按当前对话覆盖自动 TTS 的文字同步开关；
- 新增 `/mimo_say <文本>` 作为即时合成命令入口，并移除旧 `/tts <文本>`；
- `ttsconfig` 现会显示当前对话的自动 TTS 开关状态。

## 2025-04-26 v1.2.2

### 更新内容

- 新增用户设置持久化：插件重载、热更新后仍可保留每个用户自己的音色、模式、情感、语速、音高、输出格式等设置；
- 自动 TTS 的装饰阶段优先级已前移，使文本清理类插件可优先处理结果，减少异常文本被直接朗读；
- 增强提示词泄漏拦截，降低 persona / skill / reasoning / system prompt 等内部文本被自动 TTS 朗读的概率；
- 自定义音色注册表迁移到 AstrBot `data` 目录，减少插件更新覆盖导致的注册信息丢失；
- 对齐 AstrBot 大文件存储规范：VoiceClone 参考音频的推荐上传位置调整为 **`data/plugin_data/astrbot_plugin_mimo_tts/clone/`**，推荐命令写法为 `/voiceclone <ID> clone/文件名`。

## 2025-04-26 v1.2.1

### 更新内容

- 修正 `api_base_url` 的兼容处理：现在即使误填为 `https://api.xiaomimimo.com` 或完整的 `.../v1/chat/completions`，插件也会自动归一化到正确的基础地址，避免拼接后出现 404；
- 为 TTS / VoiceClone / VoiceDesign 请求增加更明确的运行日志，失败时会直接带出实际请求 URL 与模型名，便于确认是否命中新逻辑、是否仍在使用错误地址。

## 2025-04-26 v1.2.0

### 更新内容

- 增加 **/ttsswitch**，支持在 **默认 / 设计 / 克隆** 三种输出模式之间切换；
- 调整唱歌逻辑为仅允许 **/sing** 单次触发；
- 完善 **VoiceDesign** 与 **VoiceClone** 的模型接入与配置说明；
- 将 **VoiceClone** 参考音频目录约定收敛为插件根目录下的 **clone/** 文件夹，并同步更新命令帮助与错误提示；
- 修正 **VoiceClone** 调用方式：不再错误请求不存在的 `/audio/voice/clone` 路由，而是在实际合成时按官方文档改用 `chat/completions + audio.voice(data URL)`；
- 修正 **design** 模式的实际合成逻辑：切换到该模式后改为直接使用 `mimo-v2.5-tts-voicedesign`，并将音色描述文本放入 `user` 消息中参与合成；
- 修正 **VoiceDesign** 请求参数，避免对 `mimo-v2.5-tts-voicedesign` 传入不支持的 `audio.voice`，也避免错误使用无效占位音色 ID；
- 新增克隆音色的自然语言风格控制、音频标签控制；
- 接口失败时可直接输出更具体的报错原因。

## 2025-04-24

### 初版发布

- TTS 基本功能可以使用。目前尚未测试 VoiceDesign 与 VoiceClone 功能。

---

> v1.2.0、v1.2.1、v1.2.2 以及 v1.2.3 均使用 GPT-5.4 进行生成。