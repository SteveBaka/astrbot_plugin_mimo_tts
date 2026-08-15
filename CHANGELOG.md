# CHANGELOG

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