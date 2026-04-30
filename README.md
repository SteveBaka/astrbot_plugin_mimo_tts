# astrbot_plugin_mimo_tts

[![AstrBot](https://img.shields.io/badge/AstrBot-v3.4.0+-blue)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

> **⚠️ 免责声明：本项目初版v1.1.0使用同期发布的MiMO-V2.5生成，代码生成时以及发布时个人只对插件需要生成的内容与报错对其进行指正，后期若更换其他大模型会在下方更新日志中指出。**

基于 [MiMO-V2.5-TTS](https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5) 的精细化语音合成插件，适配 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 聊天机器人框架。

> **⚠️ 免责声明：本项目意在调用mimo-v2.5-tts series的API服务进行文本生成语音（TTS）服务，请不要将其用于不正当用途以及骚扰他人。**

> 如果你对这个项目有兴趣，可以看看*README.md*中的提示板块，我会根据我的测试对提示里面的内容进行补充，希望对每一个爱折腾的你有一定的帮助。遇到问题提交一份issue也是对我有莫大的帮助，在此表示由衷的感谢。

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
- [x]文字同步开关：可控制自动 TTS 时是否同时保留文字消息
- [x]错误原因透出：接口失败时直接返回具体报错原因
- [x]多用户独立：每人独立设置，互不干扰

[安装](#安装) · [命令列表](#命令列表) · [更新日志](#更新日志)· [提示](#作者的碎碎念)

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
| `send_text_with_tts` | 自动 TTS 时是否同步发送文字 | `true` |
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
| `sing_voice` | 唱歌模式默认音色（下拉选择） | 空（使用当前音色） |

### 输出模式说明

- `default`：使用插件默认音色或当前选中的普通内置音色。
- `design`：优先使用当前已登记的设计音色描述，或配置中的 `design_voice_description` 进行合成。
- `clone`：优先使用 `clone_voice_id` 对应的本地参考音频，或当前选中的已登记克隆音色进行合成。

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
/mimo_say <文本> [-emotion 情感] [-speed 速度] [-pitch 音高] [-voice 音色]
                [-breath on/off] [-stress on/off] [-dialect 方言] [-volume 音量]
```

### 唱歌
```
/sing [-音色名] <歌词>
```

> 唱歌模式仅由 `/sing` 单次触发，执行后自动恢复原始设置，避免普通即时合成与自动语音输出被持续污染。支持通过 `-音色名` 临时指定唱歌音色（如 `/sing -冰糖 小星星`），优先级：命令参数 > 当前用户音色 > 插件配置 `sing_voice`。

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
- 插件配置中的"设计音色描述"用于全局控制设计音色风格。
- 使用 `/voicegen <ID> <描述>` 可生成新的设计音色，并同步更新配置中的设计音色信息。
- `mimo-v2.5-tts-voicedesign` 会直接读取 `user` 消息中的音色描述文本来生成定制音色，不依赖普通 TTS 的预置 `audio.voice`。
- 当输出模式切换为 `design` 时，插件会改用 `design_model` 发起合成，并优先采用当前设计音色描述或配置中的 `design_voice_description`。
- 若使用 `/voicegen <ID> <描述>`，插件会记录这条描述，之后切到 `design` 模式时可继续按该描述进行设计音色朗读。

#### 声音克隆（VoiceClone）

- 当前按官方能力接入 `mimo-v2.5-tts-voiceclone` 模型。
- 使用 `/voiceclone <ID> <本地音频路径>` 可登记一个"本地参考音频音色"。
- **推荐上传位置：AstrBot 数据目录下的 `data/plugin_data/astrbot_plugin_mimo_tts/clone/` 文件夹。**
- 插件启动时会自动创建该 `clone/` 目录，可直接把待克隆音频放进去使用。
- 推荐流程如下：
  1. 将参考音频上传/放入 AstrBot 的 `data/plugin_data/astrbot_plugin_mimo_tts/clone/` 文件夹；
  2. 例如文件实际放置为 `data/plugin_data/astrbot_plugin_mimo_tts/clone/sample.wav`；
  3. 然后执行 `/voiceclone my_clone clone/sample.wav` 完成登记；
- 也支持绝对路径、相对当前工作目录路径、相对 AstrBot 数据目录路径，以及旧版相对插件目录路径；但为了避免路径歧义，**最推荐始终使用 `clone/文件名` 的写法**。
- 按 AstrBot 插件开发规范，大文件应尽量放在 `data/plugin_data/{plugin_name}/` 下，因此 clone 参考音频现在也按该规范存放，而不是继续放在插件代码目录中。
- 已加入本地文件存在性、文件类型、最小体积校验。
- `/voiceclone` 不会再调用不存在的"预注册接口"；插件会在真正合成时，将参考音频转成 `data:{MIME_TYPE};base64,...` 后通过 `chat/completions` 的 `audio.voice` 传给官方 `mimo-v2.5-tts-voiceclone` 模型。
- 执行 `/voiceclone` 后，插件会自动记录该参考音频路径，并可配合 `/ttsswitch clone` 进入克隆输出模式。
- 支持通过以下两个配置项细化克隆音色的输出风格：
  - `clone_style_prompt`：自然语言风格控制
  - `clone_audio_tags`：音频标签控制
- 若这两个配置留空，则保持官方 API 默认行为，不额外注入控制文本。

##### VoiceClone 快速示例

```text
AstrBot/
├─ data/
│  └─ plugin_data/
│     └─ astrbot_plugin_mimo_tts/
│        └─ clone/
│           └─ sample.wav
```

```bash
/voiceclone my_clone clone/sample.wav
/ttsswitch clone
/mimo_say 这是一段使用克隆音色生成的测试语音
```

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
/tts_help                  # 快速查看常用指令
/ttsconfig                  # 查看配置
/ttsconfig reset            # 重置个人设置
/tts_restore               # 将当前对话配置恢复为插件默认设置
/tts_<on/off>              # 关闭或重新开启当前对话自动 TTS
/text <on|off>              # 当前对话内控制自动 TTS 是否同步发送文字
/ttsinfo                    # 插件信息
/ttsraw <文本>              # 纯文本合成（不带情感）
```

### 自动 TTS 文字同步说明

- 插件配置项 `send_text_with_tts` 用于控制：自动 TTS 触发时，是否在发送语音的同时保留原始文字消息。
- 开启时：保持原有行为，文本 + 语音同时发送。
- 关闭时：插件会尽量只保留语音输出，以减少对话中消息过多的问题。
- `/tts_off` 与 `/tts_on` 作用于**当前对话**，并会持久化保存该对话的自动 TTS 开关状态。
- `/tts_on` 只会恢复当前对话的自动 TTS，不会改动插件配置面板中的全局 `auto_tts` 开关。
- `/text on|off` 可在**当前对话**内临时覆盖 `send_text_with_tts` 的实际生效结果，不会改动插件配置面板中的全局 `send_text_with_tts` 开关。

### 报错说明

- 当前版本已增强接口失败提示。
- 当 TTS 合成、声音设计、声音克隆调用失败时，插件会尽量直接返回接口错误原因，便于排查配置、鉴权或请求参数问题。

## 使用示例

```bash
# 开心地说一段话
/mimo_say 今天天气真好啊！ -emotion happy

# 用粤语低声说话
/mimo_say 你好呀 -dialect 粤语 -volume 轻声 -emotion whisper

# 应用睡前故事预设
/preset bedtime_story
/mimo_say 从前有一座山，山里有一座庙...

# 唱歌模式
/sing 小星星，亮晶晶，满天都是小星星

# 唱歌模式指定音色
/sing -冰糖 小星星，亮晶晶，满天都是小星星

# 快速切换参数
/mimo_say 滚！ -emotion angry -speed 1.3 -stress on
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

## 安全机制

- 路径白名单：`/voiceclone` 与 `/voicegen` 在存储音频文件路径前，会将用户输入经 `resolve()` 后校验是否位于允许目录（`data/plugin_data/astrbot_plugin_mimo_tts/clone/`）内，防止目录穿越攻击。
- 配置引用一致性：插件运行时通过 `set()` 写入的配置项始终可被 `get()` 读回，避免热更新后配置脱钩。
- 磁盘清理可靠性：自动清理过期合成文件时始终使用绝对路径，避免相对路径导致的清理失效。
- 资源释放：插件卸载时自动关闭 HTTP session 等资源，避免连接泄漏。

## 更新日志

- 2025年4月24日，初版发布，**TTS**基本功能可以使用。目前尚未测试**VoiceDesign**与**VoiceClone**功能。
- 2025年4月26日，v1.2.0更新：
  - 增加 **/ttsswitch**，支持在 **默认 / 设计 / 克隆** 三种输出模式之间切换；
  - 调整唱歌逻辑为仅允许 **/sing** 单次触发；
  - 完善 **VoiceDesign** 与 **VoiceClone** 的模型接入与配置说明；
  - 将 **VoiceClone** 参考音频目录约定收敛为插件根目录下的 **clone/** 文件夹，并同步更新命令帮助与错误提示；
  - 修正 **VoiceClone** 调用方式：不再错误请求不存在的 `/audio/voice/clone` 路由，而是在实际合成时按官方文档改用 `chat/completions + audio.voice(data URL)`；
  - 修正 **design** 模式的实际合成逻辑：切换到该模式后改为直接使用 `mimo-v2.5-tts-voicedesign`，并将音色描述文本放入 `user` 消息中参与合成；
  - 修正 **VoiceDesign** 请求参数，避免对 `mimo-v2.5-tts-voicedesign` 传入不支持的 `audio.voice`，也避免错误使用无效占位音色 ID；
  - 新增克隆音色的自然语言风格控制、音频标签控制；
  - 接口失败时可直接输出更具体的报错原因。
- 2025年4月26日，v1.2.1更新：
  - 修正 `api_base_url` 的兼容处理：现在即使误填为 `https://api.xiaomimimo.com` 或完整的 `.../v1/chat/completions`，插件也会自动归一化到正确的基础地址，避免拼接后出现 404；
  - 为 TTS / VoiceClone / VoiceDesign 请求增加更明确的运行日志，失败时会直接带出实际请求 URL 与模型名，便于确认是否命中新逻辑、是否仍在使用错误地址。
- v1.2.0、v1.2.1、v1.2.2 以及 v1.2.3 均使用GPT-5.4进行生成。
- 2025年4月26日，v1.2.2更新：
  - 新增用户设置持久化：插件重载、热更新后仍可保留每个用户自己的音色、模式、情感、语速、音高、输出格式等设置；
  - 自动 TTS 的装饰阶段优先级已前移，使文本清理类插件可优先处理结果，减少异常文本被直接朗读；
  - 增强提示词泄漏拦截，降低 persona / skill / reasoning / system prompt 等内部文本被自动 TTS 朗读的概率；
  - 自定义音色注册表迁移到 AstrBot `data` 目录，减少插件更新覆盖导致的注册信息丢失；
  - 对齐 AstrBot 大文件存储规范：VoiceClone 参考音频的推荐上传位置调整为 **`data/plugin_data/astrbot_plugin_mimo_tts/clone/`**，推荐命令写法为 `/voiceclone <ID> clone/文件名`。
- 2025年4月26日，v1.2.3更新：
  - 新增 `send_text_with_tts` 配置项，可控制自动 TTS 时是否同时保留文字输出；
  - 新增 `/tts_off` 与 `/tts_on`，用于按当前对话关闭/恢复自动 TTS；
  - 新增 `/text <on|off>`，用于按当前对话覆盖自动 TTS 的文字同步开关；
  - 新增 `/mimo_say <文本>` 作为即时合成命令入口，并移除旧 `/tts <文本>`；
  - `ttsconfig` 现会显示当前对话的自动 TTS 开关状态。
- 2026年4月28日更新：
  - 新增路径白名单安全机制，防止目录穿越攻击；
  - 新增 `on_unload()` 资源释放钩子；
  - 修复配置引用脱钩、磁盘清理路径异常等问题；
  - 消除情感检测逻辑重复，优化代码结构；
  - 今日更新使用 mimo-v2.5 对代码和功能进行优化。
- 2026年4月30日更新：
  - 唱歌模式 `/sing` 改为单次触发模式，执行后自动恢复原始设置，避免持续污染普通 TTS；
  - `/sing` 新增 `-音色名` 参数支持，可临时指定唱歌音色（如 `/sing -冰糖 歌词`）；
  - 新增 `sing_voice` 插件配置项，支持通过下拉选择框配置唱歌模式默认音色；
  - 唱歌音色优先级：命令参数 > 当前用户音色 > 插件配置 `sing_voice`；
  - `main.py` 中 9 个命令处理器（`/text`、`/sing`、`/voice`、`/ttsswitch`、`/preset`、`/voiceclone`、`/voicegen`、`/ttsconfig`、`/ttsraw`）统一改用 `self._parse_cmd()` 提取参数，减少重复的字符串处理代码；
  - `main.py` 用户状态持久化：将过期用户淘汰逻辑 `_evict_stale_users()` 移入写锁内，确保淘汰与持久化的原子性，避免并发写入时的竞态条件；
  - `tts/mimo_provider.py` 新增不可重试 HTTP 状态码处理：遇到 400（参数错误）、401（未授权）、403（鉴权失败）时立即终止重试，减少无意义的重试等待；
  - `voice/voice_manager.py` 收窄 `_backup_corrupted_file()` 的异常捕获范围，由 `except Exception` 改为 `except (OSError, shutil.Error)`，避免意外吞掉非文件系统相关异常；
  - 使用 mimo-v2.5-pro 生成。

## 作者的碎碎念

经过测试，在多次使用**voiceclone**以及**voicedesign**连续生成TTS后，可能会产生不一样的声音。可以等待几分钟或更改提示词后继续生成，基本上可以正常使用，该问题在*MiMO Studio*试用时也出现过。

若开启笑声模式，部分情况下在使用**voiceclone**模式时，可能会出现长句子出现语句间有杂音的问题。

**/sing**目前还是会有较短句出现效果不合预期的情况，可能需要参考`/sing`指令的操作，对输出的唱歌音色进行控制。

4月30日更：唱歌模式我也力竭了，还特地上了兜底机制，让输出音色（至少？）可被控制，最后我还是推荐**中文环境下**指定使用**茉莉**作为唱歌音色，我认为是声调相对最舒服的那一档。

> 笑话1:使用*voiceclone*不要学习作者在测试时，上传并使用非官方支持的*中文/English*以外的语言，效果自测（就是很奇怪罢了）。「被mimo-v2.5-pro重构了一次插件，没想到效果变好了很多，这对吗？」

> 笑话2:为了唱歌模式的优化，已经尝试去官方的TTS交流群上点压力了，可惜只回了个*get*。


## License

MIT