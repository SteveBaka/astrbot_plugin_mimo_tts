# MiMO TTS Plugin (Enhanced)

基于 [MiMO-V2.5-TTS](https://platform.xiaomimimo.com/docs/usage-guide/speech-synthesis-v2.5) 的精细化语音合成插件，适配 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 聊天机器人框架。

## 核心特性

- 自动语音合成：LLM 回复自动生成语音
- 20 种情感：happy/sad/angry/neutral/whisper/surprised/excited/gentle/serious/romantic/fearful/disgusted/sarcastic/nostalgic/playful/calm/anxious/proud/tender/lazy
- 9 种内置音色（含中英文）
- 8 个预设：一键切换风格
- 方言支持：四川话、粤语、东北话等
- 唱歌模式：用唱歌的方式演绎
- 笑声 / 停顿 / 呼吸声 / 重音模式
- 音量控制：轻声/正常/大声
- 语速/音高：0.5~2.0x 语速，-12~+12 音高
- 声音克隆 & 设计：自定义音色
- 多用户独立：每人独立设置，互不干扰

## 安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/yourname/astrbot_plugin_mimo_tts.git
cd astrbot_plugin_mimo_tts
pip install -r requirements.txt
```

重启 AstrBot 后在插件管理中启用。

## 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | MiMO API Key（必填） | - |
| `api_base_url` | API 地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `model` | 模型名称 | `mimo-v2.5-tts` |
| `default_voice` | 默认音色 | `mimo_default` |
| `audio_format` | 输出格式(mp3/wav/ogg) | `mp3` |
| `auto_tts` | 自动拦截 LLM 输出 | `true` |
| `auto_tts_in_group` | 群聊中自动 TTS | `true` |
| `default_speed` | 默认语速 | `1.0` |
| `default_pitch` | 默认音高 | `0` |
| `emotion_override` | 情感覆盖(auto=自动) | - |

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

### 20 种情感
```
/emotion <情感名|auto|off>
/emotions   # 列出所有情感
```

**情感列表**: happy, sad, angry, neutral, whisper, surprised, excited, gentle, serious, romantic, fearful, disgusted, sarcastic, nostalgic, playful, calm, anxious, proud, tender, lazy

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
/voiceclone <ID> <路径>    # 声音克隆
/voicegen <ID> <描述>      # 声音设计
/voiceclonelist            # 查看已注册自定义音色
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
/ttsconfig                  # 查看配置
/ttsconfig reset            # 重置个人设置
/ttsinfo                    # 插件信息
/ttsraw <文本>              # 纯文本合成（不带情感）
```

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
| 情感 | `-emotion` | 20 种 | happy/sad/angry/whisper 等 |
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

## License

MIT