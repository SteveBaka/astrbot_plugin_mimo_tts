# CHANGELOG

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