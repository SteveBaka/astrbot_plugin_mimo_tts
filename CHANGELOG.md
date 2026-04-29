# CHANGELOG

## 2026-04-30

### 新增
- 唱歌模式 `/sing` 新增 `-音色名` 参数支持，可临时指定唱歌音色（如 `/sing -冰糖 歌词`）。
- 新增 `sing_voice` 插件配置项，支持通过下拉选择框配置唱歌模式默认音色。

### 修改
- 唱歌模式 `/sing` 改为单次触发模式：执行后自动恢复原始设置，避免持续污染普通即时合成与自动 TTS。
- 唱歌音色优先级调整为：命令参数 `-音色名` > 插件配置 `sing_voice` > 当前用户音色。
- 使用 mimo-v2.5-pro 生成。

## 2026-04-28

### 新增
- `voice_manager.py` 新增 `_allowed_audio_roots()` 与 `_is_path_within_allowed_roots()` 两个路径安全方法，`register_voice()` 在存储音频路径前必须校验 resolve 后的位置是否在白名单内。
- `main.py` 新增 `on_unload()` 生命周期钩子，在插件卸载时释放 HTTP session 等资源。
- `emotion/emotion_detector.py` 新增模块级便捷函数 `detect_emotion()`，`tts/prompt_builder.py` 改为从 `emotion_detector` 导入并 re-export，消除两个模块中完全重复的 120+ 行情感关键词字典与检测逻辑。

### 修改
- 优化 `tts/mimo_provider.py` 中 Base64 长度校验：将 `len(audio_b64.encode("utf-8"))` 改为直接 `len(audio_b64)`，避免对大音频文件产生大量临时内存分配（Base64 字符串为纯 ASCII，`len()` 已等于 UTF-8 字节数）。
- 移除 `main.py` 中未使用的 `EmotionDetector` 实例化（`self._detector = EmotionDetector()`），同步清理对应 import。
- `core/compat.py` 清理仅被删除函数使用的死代码（`_ST_STAR_TOOLS` 辅助函数）。
- `main.py` `cmd_voiceclone` 与 `cmd_voicegen` 中的 `self.config.write()` 调用已替换为 AstrBot 推荐的 `self.config.set()` 方法。
- 使用 mimo-v2.5-pro 对代码和功能进行优化。

### 修复
- 修复 `main.py` `_resolve_clone_audio_path()` 的路径穿越风险：新增白名单目录机制（`allowed_roots`），用户输入的路径经 `resolve()` 后必须位于允许目录内才放行，绝对路径也受同样约束；全部候选均不在白名单内时抛出 `PermissionError`。
- 修复 `core/config.py` 配置引用脱钩问题：`get()` 现在同时检查 `super().__dict__["_data"]` 与 `self._extra`，确保运行时通过 `set()` 写入的配置项始终可被 `get()` 读回。
- 修复 `main.py` `_cleanup_recent_files()` 磁盘空间泄漏：调用 `data_path.resolve()` 将相对路径转为绝对路径后才执行 `rglob` 清理，避免 `data_path` 为相对路径时 `rglob` 相对于 CWD 而非数据目录查找文件。
- 修复 `voice_manager.py` `register_voice()` 路径安全问题：在存储音频路径前调用 `_is_path_within_allowed_roots()` 验证 resolve 后的位置必须位于 `clone_audio_dir`、`legacy_plugin_clone_dir` 或 `plugin_dir` 之内，越界时抛出 `PermissionError`。

## 2026-04-26

### 新增
- 新增 `tts_output_mode` 配置与 `/ttsswitch` 命令，用于在默认 / 设计 / 克隆三种 TTS 输出模式间切换。
- 新增 `send_text_with_tts` 配置项，用于控制自动 TTS 输出时是否同时保留文字消息。
- 新增 `clone_style_prompt` 配置，用于对 voiceclone 合成追加自然语言风格控制。
- 新增 `clone_audio_tags` 配置，用于对 voiceclone 合成追加音频标签控制。
- 新增 `design_model` 与 `clone_model` 配置，用于显式指定 voicedesign / voiceclone 所用模型。
- 新增 `design_voice_description` 配置项，替代原先配置面板中的"设计音色ID"输入语义。
- 新增用户状态持久化文件：插件会将每个用户的 TTS 设置保存到 AstrBot `data` 目录中的 `user_state.json`。
- 新增 `/tts_off` 与 `/tts_on` 命令，用于按当前对话关闭 / 恢复自动 TTS。
- 新增 `/mimo_say <文本>` 作为即时合成命令入口。

### 修改
- 唱歌模式改为仅允许通过 `/sing` 临时触发，不再使用全局唱歌开关影响普通即时合成与自动 TTS。
- 唱歌合成时会自动在目标文本开头补齐官方建议的 `(唱歌)` 标签；若用户已手动填写则不重复追加。
- TTS 主合成请求已调整为更符合 MiMO v2.5 文档的结构：
  - 使用 `audio.voice` / `audio.format`
  - 使用 `user` role 传控制提示
  - 使用 `assistant` role 传待合成文本
- voiceclone 参考音频上传增加本地文件校验：存在性、是否为文件、后缀白名单、最小体积。
- voiceclone 上传时的 MIME 类型改为根据文件后缀自动推断。
- voiceclone 在 clone 模式下支持独立拼接自然语言风格控制与音频标签；若配置留空，则不注入额外控制文本，保留官方默认行为。
- voiceclone 的本地参考音频目录已对齐 AstrBot 大文件存储规范，默认调整到 `data/plugin_data/astrbot_plugin_mimo_tts/clone/`，并同步更新命令帮助、路径解析与错误提示。
- `VoiceManager` 现在会自动创建并使用 AstrBot 数据目录下的 `clone/` 目录，便于直接存放待克隆音频文件。
- `/voiceclone` 的语义调整为"登记本地参考音频"，不再尝试调用不存在的远端预注册接口。
- 自动 TTS 装饰阶段优先级已调整，使文本清理插件能够更早处理回复结果，再由本插件执行朗读。
- 自定义音色注册表默认迁移到 AstrBot `data` 目录下保存，同时兼容读取旧版插件目录中的注册表文件。
- README 已补充 VoiceClone 参考音频上传位置说明，推荐将音频放到 `data/plugin_data/astrbot_plugin_mimo_tts/clone/` 文件夹，并使用 `/voiceclone <ID> clone/文件名` 进行登记。
- README 与命令说明已同步更新为优先使用 `/mimo_say`，并补充当前对话级别自动 TTS 开关说明。

### 修复
- 修复 `api_base_url` 的兼容问题：若用户误将配置填写为根域名 `https://api.xiaomimimo.com` 或完整接口地址 `.../chat/completions`，provider 现在会自动归一化，避免再次拼接 `chat/completions` 后触发 404。
- provider 在接口调用失败时，现会记录并透出更明确的错误原因，便于 `/tts`、`/voiceclone`、`/voicegen`、`/ttsraw` 等命令直接反馈失败详情。
- voicedesign 调用已支持显式传入模型名。
- 修复 voicedesign 请求参数错误：调用 `mimo-v2.5-tts-voicedesign` 时不再传入不支持的 `audio.voice`，避免出现 `audio.voice is not supported for voice design model` 的 400 报错。
- 修复 design 模式错误使用占位音色 ID 的问题：移除内部默认值 `1`，避免触发 `Unknown voice: 1` 的 400 报错。
- 修复 design 输出模式下的模型使用逻辑：切换到该模式后直接使用 `mimo-v2.5-tts-voicedesign`，并将音色描述文本作为 `user` 消息传入，使最终朗读更符合设计描述。
- 修复 `/voiceclone` 的 404 问题：改为在实际合成时通过 `POST /chat/completions` 调用 `mimo-v2.5-tts-voiceclone`，并将本地参考音频编码成 `data:{MIME_TYPE};base64,...` 填入 `audio.voice`。
- 进一步增强运行态诊断：HTTP 错误信息现在会附带实际请求 URL 与模型名，便于确认 404 是来自接口地址配置错误还是运行中仍在加载旧版本代码。
- 修复插件重载或更新后用户个人 TTS 配置丢失的问题。
- 修复自动 TTS 误朗读 persona / skill / system prompt / reasoning 等提示词溢出文本的问题。
- 修复 clone 大文件仍落在插件代码目录中的问题，改为优先使用 AstrBot 官方建议的 `data/plugin_data/{plugin_name}/` 存储位置，并保留旧路径兼容读取。
- 修复"想只听语音却仍被文本刷屏"的问题：关闭 `send_text_with_tts` 后，自动 TTS 会尽量只保留语音输出。

## 2025-04-26 (v1.2.3)

### 新增
- 新增 `send_text_with_tts` 配置项，可控制自动 TTS 时是否同时保留文字输出。
- 新增 `/tts_off` 与 `/tts_on`，用于按当前对话关闭/恢复自动 TTS。
- 新增 `/text <on|off>`，用于按当前对话覆盖自动 TTS 的文字同步开关。
- 新增 `/mimo_say <文本>` 作为即时合成命令入口，并移除旧 `/tts <文本>`。
- `ttsconfig` 现会显示当前对话的自动 TTS 开关状态。

> v1.2.0、v1.2.1、v1.2.2 以及 v1.2.3 均使用 GPT-5.4 进行生成。

## 2025-04-26 (v1.2.2)

### 新增
- 新增用户设置持久化：插件重载、热更新后仍可保留每个用户自己的音色、模式、情感、语速、音高、输出格式等设置。

### 修改
- 自动 TTS 的装饰阶段优先级已前移，使文本清理类插件可优先处理结果，减少异常文本被直接朗读。
- 增强提示词泄漏拦截，降低 persona / skill / reasoning / system prompt 等内部文本被自动 TTS 朗读的概率。
- 自定义音色注册表迁移到 AstrBot `data` 目录，减少插件更新覆盖导致的注册信息丢失。
- 对齐 AstrBot 大文件存储规范：VoiceClone 参考音频的推荐上传位置调整为 `data/plugin_data/astrbot_plugin_mimo_tts/clone/`，推荐命令写法为 `/voiceclone <ID> clone/文件名`。

## 2025-04-26 (v1.2.1)

### 修复
- 修正 `api_base_url` 的兼容处理：现在即使误填为 `https://api.xiaomimimo.com` 或完整的 `.../v1/chat/completions`，插件也会自动归一化到正确的基础地址，避免拼接后出现 404。

### 修改
- 为 TTS / VoiceClone / VoiceDesign 请求增加更明确的运行日志，失败时会直接带出实际请求 URL 与模型名，便于确认是否命中新逻辑、是否仍在使用错误地址。

## 2025-04-26 (v1.2.0)

### 新增
- 增加 `/ttsswitch`，支持在默认 / 设计 / 克隆三种输出模式之间切换。
- 完善 VoiceDesign 与 VoiceClone 的模型接入与配置说明。
- 新增克隆音色的自然语言风格控制、音频标签控制。

### 修改
- 调整唱歌逻辑为仅允许 `/sing` 单次触发。
- 将 VoiceClone 参考音频目录约定收敛为插件根目录下的 `clone/` 文件夹，并同步更新命令帮助与错误提示。

### 修复
- 修正 VoiceClone 调用方式：不再错误请求不存在的 `/audio/voice/clone` 路由，而是在实际合成时按官方文档改用 `chat/completions + audio.voice(data URL)`。
- 修正 design 模式的实际合成逻辑：切换到该模式后改为直接使用 `mimo-v2.5-tts-voicedesign`，并将音色描述文本放入 `user` 消息中参与合成。
- 修正 VoiceDesign 请求参数，避免对 `mimo-v2.5-tts-voicedesign` 传入不支持的 `audio.voice`，也避免错误使用无效占位音色 ID。
- 接口失败时可直接输出更具体的报错原因。

## 2025-04-24 (v1.0.0)

### 初版发布
- TTS 基本功能可以使用。
- 目前尚未测试 VoiceDesign 与 VoiceClone 功能。