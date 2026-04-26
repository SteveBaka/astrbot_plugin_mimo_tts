# CHANGELOG

## 2026-04-26

### 新增
- 新增 `tts_output_mode` 配置与 `/ttsswitch` 命令，用于在默认 / 设计 / 克隆三种 TTS 输出模式间切换。
- 新增 `clone_style_prompt` 配置，用于对 voiceclone 合成追加自然语言风格控制。
- 新增 `clone_audio_tags` 配置，用于对 voiceclone 合成追加音频标签控制。
- 新增 `design_model` 与 `clone_model` 配置，用于显式指定 voicedesign / voiceclone 所用模型。
- 新增 `design_voice_description` 配置项，替代原先配置面板中的“设计音色ID”输入语义。

### 修改
- 唱歌模式改为仅允许通过 `/sing` 临时触发，不再使用全局唱歌开关影响普通 `/tts` 与自动 TTS。
- 唱歌合成时会自动在目标文本开头补齐官方建议的 `(唱歌)` 标签；若用户已手动填写则不重复追加。
- TTS 主合成请求已调整为更符合 MiMO v2.5 文档的结构：
  - 使用 `audio.voice` / `audio.format`
  - 使用 `user` role 传控制提示
  - 使用 `assistant` role 传待合成文本
- voiceclone 参考音频上传增加本地文件校验：存在性、是否为文件、后缀白名单、最小体积。
- voiceclone 上传时的 MIME 类型改为根据文件后缀自动推断。
- voiceclone 在 clone 模式下支持独立拼接自然语言风格控制与音频标签；若配置留空，则不注入额外控制文本，保留官方默认行为。

### 修复
- provider 在接口调用失败时，现会记录并透出更明确的错误原因，便于 `/tts`、`/voiceclone`、`/voicegen`、`/ttsraw` 等命令直接反馈失败详情。
- voicedesign 调用已支持显式传入模型名。
- 修复 voicedesign 请求参数错误：调用 `mimo-v2.5-tts-voicedesign` 时不再传入不支持的 `audio.voice`，避免出现 `audio.voice is not supported for voice design model` 的 400 报错。
- 修复 design 输出模式下的模型使用逻辑：VoiceDesign 仅负责生成音色，后续实际朗读改为使用常规 TTS 模型配合生成后的 `voice_id`，避免设计描述未正确体现在最终朗读结果中。