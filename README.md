# MiMO TTS Plugin (Enhanced)

> **⚠️ 免责声明：本项目初版v1.1.0使用同期发布的MiMO-V2.5生成，代码生成时以及发布时个人只对插件需要生成的内容与报错对其进行指正，后期更换其他大模型会在下方更新日志中指出。**

基于 [MiMO-V2.5-TTS](https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5) 的精细化语音合成插件，适配 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 聊天机器人框架。

## 核心特性

- [x]自动语音合成：LLM 回复自动生成语音
- [x]20 种情感：开心、悲伤、愤怒、平静、耳语、惊讶、兴奋、温柔、严肃、浪漫、害怕、厌恶、讽刺、怀旧、俏皮、冷静、焦虑、自豪、柔情、慵懒
- [x]9 种内置音色（含中英文）
- [x]8 个预设：一键切换风格
- [x]方言支持：四川话、粤语、东北话等
- [x]唱歌模式：仅支持 `/sing` 临时触发，避免影响普通 TTS
- [x]笑声 / 停顿 / 呼吸声 / 重音模式
- [x]音量控制：轻声/正常/大声
- [x]语速/音高：0.5-2.0x 语速，-12-+12 音高
- [x]声音克隆 & 设计：支持自定义音色生成与调用
- [x]输出模式切换：支持 默认 / 设计 / 克隆 三种 TTS 输出来源
- [x]错误原因透出：接口失败时直接返回具体报错原因
- [x]多用户独立：每人独立设置，互不干扰

[安装](#安装) · [命令列表](#命令列表) · [更新日志](#更新日志)

## 安装


请在 **AstrBot 插件** 内使用本仓库地址下载安装本插件。

安装后在插件管理中启用并配置插件。

## 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | MiMO API Key（必填） | - |
| `api_base_url` | API 地址 | `https://api.xiaomimimo.com/v1` |
| `model` | 模型名称 | `mimo-v2.5-tts` |
| `default_voice` | 默认音色 | `mimo_default` |
| `audio_format` | 输出格式(mp3/wav/ogg) | `mp3` |
| `auto_tts` | 自动拦截 LLM 输出 | `true` |
| `auto_tts_in_group` | 群聊中自动 TTS | `true` |
| `default_speed` | 默认语速 | `1.0` |
| `default_pitch` | 默认音高 | `0` |
| `emotion_override` | 情感覆盖(auto=自动) | - |
| `tts_output_mode` | TTS 输出来源模式（default/design/clone） | `default` |
| `design_model` | 音色设计模型 | `mimo-v2.5-tts-voicedesign` |
| `design_voice_description` | 设计音色描述 | - |
| `clone_model` | 音色克隆模型 | `mimo-v2.5-tts-voiceclone` |
| `clone_voice_id` | 克隆音色 ID | - |
| `clone_style_prompt` | 克隆音色自然语言风格控制 | - |
| `clone_audio_tags` | 克隆音色音频标签控制 | - |

### 输出模式说明

- `default`：使用插件默认音色或当前选中的普通内置音色。
- `design`：优先使用 `design_voice_id` / 已生成的设计音色进行合成。
- `clone`：优先使用 `clone_voice_id` / 已注册的克隆音色进行合成。

可通过命令 `/ttsswitch <default|design|clone>` 在运行时快速切换。

## 预置音色列表

使用时，可在 `{"audio": {"voice": "mimo_default"}}` 中设置预置音色。

| 音色名 | Voice ID | 语言 | 性别 |
|--------|----------|------|------|
| MiMo-默认 | mimo_default | 因部署集群而异，中国集群默认为冰糖 | - |
| 冰糖 | 冰糖 | 中文 | 女性 |
| 茉莉 | 茉莉 | 中文 | 女性 |
| 苏打 | 苏打 | 中文 | 男性 |
| 白桦 | 白桦 | 中文 | 男性 |
| Mia | Mia | 英文 | 女性 |
| Chloe | Chloe | 英文 | 女性 |
| Milo | Milo | 英文 | 男性 |
| Dean | Dean | 英文 | 男性 |

## 命令列表

### 即时合成
```
/tts <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]
           [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]
```

### 唱歌
```
/sing <歌词>
```

> 当前版本不再建议使用“全局唱歌开关”，唱歌模式仅由 `/sing` 单次触发，避免普通 `/tts` 与自动语音输出被持续污染。

### 20 种情感
```
/emotion <情感名|auto|off>
/emotions   # 列出所有情感
```

**情感列表（简体中文）**：开心、悲伤、愤怒、平静、耳语、惊讶、兴奋、温柔、严肃、浪漫、害怕、厌恶、讽刺、怀旧、俏皮、冷静、焦虑、自豪、柔情、慵懒

**对应参数值**：`happy`、`sad`、`angry`、`neutral`、`whisper`、`surprised`、`excited`、`gentle`、`serious`、`romantic`、`fearful`、`disgusted`、`sarcastic`、`nostalgic`、`playful`、`calm`、`anxious`、`proud`、`tender`、`lazy`

### 语速 / 音高
```
/speed <0.5~2.0>
/pitch <-12~+12>
```

### 呼吸声 / 重音
```
/breath <on|off>
/stress <on|off>
```

### 方言
```
/dialect <方言名|off>
# 示例: /dialect 四川话、/dialect 粤语、/dialect 东北话
```

### 音量
```
/volume <轻声|正常|大声|off>
```

### 笑声 / 停顿
```
/laughter <on|off>
/pause <on|off>
```

### 音色
```
/voice [音色ID]           # 查看/切换音色
/voices                    # 列出所有内置音色
/ttsswitch <模式>          # 切换 default / design / clone 输出模式
/voiceclone <ID> <路径>    # 声音克隆
/voicegen <ID> <描述>      # 声音设计
/voiceclonelist            # 查看已注册自定义音色
```

#### 声音设计（VoiceDesign）

- 当前按官方能力接入 `mimo-v2.5-tts-voicedesign` 模型。
- 插件配置中的“设计音色描述”用于全局控制设计音色风格。
- 使用 `/voicegen <ID> <描述>` 可生成新的设计音色，并同步更新配置中的设计音色信息。
- `mimo-v2.5-tts-voicedesign` 的职责是“生成音色”，不作为最终朗读模型直接使用。
- 当输出模式切换为 `design` 时，插件会优先使用已生成的 `design_voice_id` 进行合成，实际朗读阶段回到常规 TTS 模型，并显式携带该 `voice_id`。
- 这样可避免把 VoiceDesign 误当成直接朗读模型，减少“生成后的声音与填写描述不一致”或音色跑偏的问题。

#### 声音克隆（VoiceClone）

- 当前按官方能力接入 `mimo-v2.5-tts-voiceclone` 模型。
- 使用 `/voiceclone <ID> <本地音频路径>` 可注册克隆音色。
- 已加入本地文件存在性、文件类型、最小体积校验。
- 支持通过以下两个配置项细化克隆音色的输出风格：
  - `clone_style_prompt`：自然语言风格控制
  - `clone_audio_tags`：音频标签控制
- 若这两个配置留空，则保持官方 API 默认行为，不额外注入控制文本。

### 预设
```
/preset [预设名]     # 查看/应用预设
/presetlist          # 列出所有预设
```

| 预设名 | 情感 | 语速 | 音高 | 音色 |
|--------|------|------|------|------|
| default | neutral | 1.0 | 0 | mimo_default |
| gentle_female | gentle | 0.95 | +2 | 冰糖 |
| energetic | excited | 1.2 | +1 | 茉莉 |
| news_anchor | serious | 1.05 | 0 | 苏打 |
| bedtime_story | gentle | 0.85 | +1 | 茉莉 |
| sad_comfort | tender | 0.9 | -1 | 白桦 |
| dramatic | angry | 1.1 | +2 | Dean |
| whisper_secret | whisper | 0.8 | -2 | Chloe |

### 其他
```
/ttsformat <mp3|wav|ogg>   # 设置音频格式
/ttsconfig                  # 查看配置
/ttsconfig reset            # 重置个人设置
/ttsinfo                    # 插件信息
/ttsraw <文本>              # 纯文本合成（不带情感）
```

### 报错说明

- 当前版本已增强接口失败提示。
- 当 TTS 合成、声音设计、声音克隆调用失败时，插件会尽量直接返回接口错误原因，便于排查配置、鉴权或请求参数问题。

## 使用示例

```bash
# 开心地说一段话
/tts 今天天气真好啊！ -emotion happy

# 用粤语低声说话
/tts 你好呀 -dialect 粤语 -volume 轻声 -emotion whisper

# 应用睡前故事预设
/preset bedtime_story
/tts 从前有一座山，山里有一座庙...

# 唱歌模式
/sing 小星星，亮晶晶，满天都是小星星

# 快速切换参数
/tts 滚！ -emotion angry -speed 1.3 -stress on
```

## 控制维度总览

| 维度 | 参数 | 范围 | 说明 |
|------|------|------|------|
| 情感 | `-emotion` | 20 种 | 开心/悲伤/愤怒/耳语等 |
| 语速 | `-speed` | 0.5~2.0 | 倍速 |
| 音高 | `-pitch` | -12~+12 | 半音偏移 |
| 呼吸声 | `-breath` | on/off | 自然呼吸音效 |
| 重音 | `-stress` | on/off | 重点词加重 |
| 唱歌 | `/sing` | on | 演唱模式 |
| 方言 | `-dialect` | 自由文本 | 四川话/粤语等 |
| 音量 | `-volume` | 轻声/正常/大声 | 音量控制 |
| 笑声 | `-laughter` | on/off | 自然笑声 |
| 停顿 | `-pause` | on/off | 句间停顿 |

## 技术说明

- API 认证使用 `api-key` 头（符合官方规范）
- 控制指令放在 `user` role，待合成文本放在 `assistant` role
- 支持 mp3/wav/ogg 音频格式
- 每用户独立设置，支持内联参数覆盖

## 更新日志

- 2025年4月24日，初版发布，**TTS**基本功能可以使用。目前尚未测试**VoiceDesign**与**VoiceClone**功能。
- 2025年4月26日，v1.2.0更新：
  - 增加 **/ttsswitch**，支持在 **默认 / 设计 / 克隆** 三种输出模式之间切换；
  - 调整唱歌逻辑为仅允许 **/sing** 单次触发；
  - 完善 **VoiceDesign** 与 **VoiceClone** 的模型接入与配置说明；
  - 修正 **design** 模式的实际合成逻辑：`VoiceDesign` 仅用于生成音色，正式朗读改为使用普通 TTS 模型配合生成后的 `voice_id`；
  - 修正 **VoiceDesign** 请求参数，避免对 `mimo-v2.5-tts-voicedesign` 传入不支持的 `audio.voice`；
  - 新增克隆音色的自然语言风格控制、音频标签控制；
  - 接口失败时可直接输出更具体的报错原因；
  - 本版本使用GPT-5.4进行更新。
## License

MIT