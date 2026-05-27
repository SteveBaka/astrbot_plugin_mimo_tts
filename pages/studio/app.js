(function () {
  'use strict';

  const { createApp, ref, reactive, computed, watch, onMounted, nextTick } = Vue;
  const { createRouter, createWebHashHistory } = VueRouter;

  function getBridge() {
    return window.AstrBotPluginPage;
  }

  async function apiGet(endpoint) {
    try {
      return await getBridge().apiGet(endpoint);
    } catch (e) {
      console.error(`[Studio] GET ${endpoint}`, e);
      return null;
    }
  }

  async function apiPost(endpoint, body) {
    try {
      return await getBridge().apiPost(endpoint, body);
    } catch (e) {
      console.error(`[Studio] POST ${endpoint}`, e);
      return null;
    }
  }

  async function apiUpload(endpoint, fileOrFormData) {
    try {
      return await getBridge().upload(endpoint, fileOrFormData);
    } catch (e) {
      console.error(`[Studio] UPLOAD ${endpoint}`, e);
      return null;
    }
  }

  const EMOTIONS = [
    'happy', 'sad', 'angry', 'neutral', 'whisper', 'surprised', 'excited',
    'gentle', 'serious', 'romantic', 'fearful', 'disgusted', 'sarcastic',
    'nostalgic', 'playful', 'calm', 'anxious', 'proud', 'tender', 'lazy'
  ];

  const BUILTIN_VOICES = [
    { id: 'mimo_default', name: 'MiMo-默认' },
    { id: '冰糖', name: '冰糖' },
    { id: '茉莉', name: '茉莉' },
    { id: '苏打', name: '苏打' },
    { id: '白桦', name: '白桦' },
    { id: 'Mia', name: 'Mia' },
    { id: 'Chloe', name: 'Chloe' },
    { id: 'Milo', name: 'Milo' },
    { id: 'Dean', name: 'Dean' }
  ];

  const FORMATS = ['wav', 'mp3', 'ogg'];

  const PRESETS = [
    { name: 'default', label: '默认', emotion: 'neutral', speed: 1.0, pitch: 0, breath: false, stress: false, voice: 'mimo_default' },
    { name: 'gentle_female', label: '温柔女生', emotion: 'gentle', speed: 0.95, pitch: 2, breath: true, stress: false, voice: '冰糖' },
    { name: 'energetic', label: '活力', emotion: 'excited', speed: 1.2, pitch: 1, breath: false, stress: true, voice: '茉莉' },
    { name: 'news_anchor', label: '新闻播报', emotion: 'serious', speed: 1.05, pitch: 0, breath: false, stress: true, voice: '苏打' },
    { name: 'bedtime_story', label: '睡前故事', emotion: 'gentle', speed: 0.85, pitch: 1, breath: true, stress: false, voice: '茉莉' },
    { name: 'sad_comfort', label: '温柔安慰', emotion: 'tender', speed: 0.9, pitch: -1, breath: true, stress: false, voice: '白桦' },
    { name: 'dramatic', label: '戏剧', emotion: 'angry', speed: 1.1, pitch: 2, breath: false, stress: true, voice: 'Dean' },
    { name: 'whisper_secret', label: '悄悄话', emotion: 'whisper', speed: 0.8, pitch: -2, breath: true, stress: false, voice: 'Chloe' }
  ];

  const CONFIG_SECTIONS = [
    {
      title: 'API 设置', icon: '🔑',
      fields: [
        { key: 'api_key', label: 'MiMO API Key', type: 'password', hint: '从 MiMO 开放平台获取' },
        { key: 'api_base_url', label: 'API Base URL', type: 'text', hint: '默认 https://api.xiaomimimo.com/v1' },
        { key: 'model', label: '默认模型', type: 'text', hint: '当前仅支持 mimo-v2.5-tts' }
      ]
    },
    {
      title: '音色设置', icon: '🎵',
      fields: [
        { key: 'default_voice', label: '默认音色', type: 'select', options: ['mimo_default', '冰糖', '茉莉', '苏打', '白桦', 'Mia', 'Chloe', 'Milo', 'Dean'] },
        { key: 'sing_voice', label: '唱歌默认音色', type: 'select', options: ['', '冰糖', '茉莉', '苏打', '白桦', 'Mia', 'Chloe', 'Milo', 'Dean'] },
        { key: 'tts_output_mode', label: 'TTS 输出模式', type: 'select', options: ['default', 'design', 'clone'] }
      ]
    },
    {
      title: '输出设置', icon: '🔊',
      fields: [
        { key: 'auto_tts', label: '自动 TTS', type: 'bool', hint: '拦截 LLM 回复生成语音' },
        { key: 'send_text_with_tts', label: 'TTS 同步发送文字', type: 'bool' },
        { key: 'audio_format', label: '音频格式', type: 'select', options: ['wav', 'mp3', 'ogg'] },
        { key: 'emotion_override', label: '默认情感覆盖', type: 'text', hint: '留空=自动检测' },
        { key: 'probability', label: '自动 TTS 触发概率', type: 'slider', min: 0, max: 1, step: 0.1 }
      ]
    },
    {
      title: 'TTS 参数', icon: '🎛️',
      fields: [
        { key: 'default_speed', label: '默认语速', type: 'slider', min: 0.5, max: 2.0, step: 0.1 },
        { key: 'default_pitch', label: '默认音高', type: 'slider', min: -12, max: 12, step: 1 },
        { key: 'style_hint', label: '风格提示', type: 'text', hint: '温柔甜美、活泼可爱...' },
        { key: 'breath_enabled', label: '呼吸声', type: 'bool' },
        { key: 'stress_enabled', label: '重音模式', type: 'bool' },
        { key: 'laughter_enabled', label: '笑声', type: 'bool' },
        { key: 'pause_enabled', label: '停顿模式', type: 'bool' }
      ]
    },
    {
      title: '文本分段', icon: '✂️',
      fields: [
        { key: 'enable_segmentation', label: '启用文本分段', type: 'bool' },
        { key: 'segment_pattern', label: '分段规则', type: 'select', options: ['sentence', 'paragraph', 'comma', 'mixed'] },
        { key: 'segment_max_count', label: '分段数量上限', type: 'number', hint: '0=不限制' },
        { key: 'segment_voice_probability', label: '分段语音概率', type: 'slider', min: 0, max: 1, step: 0.1 },
        { key: 'min_text_length', label: '最小文本长度', type: 'number' },
        { key: 'max_text_length', label: '最大文本长度', type: 'number' }
      ]
    },
    {
      title: '语音润色', icon: '✨',
      fields: [
        { key: 'enable_voice_polish', label: '启用 LLM 润色', type: 'bool', hint: '产生额外 LLM 调用' },
        { key: 'polish_llm_provider', label: '润色 LLM Provider', type: 'text', hint: '留空使用当前对话模型' },
        { key: 'polish_prompt', label: '润色提示词', type: 'textarea', hint: '{text} 为原文占位符' }
      ]
    },
    {
      title: '声音克隆', icon: '🎤',
      fields: [
        { key: 'clone_model', label: '克隆模型', type: 'text' },
        { key: 'clone_voice_id', label: '克隆音色 ID', type: 'text' },
        { key: 'clone_style_prompt', label: '克隆风格控制', type: 'text' },
        { key: 'clone_audio_tags', label: '克隆音频标签', type: 'text' }
      ]
    },
    {
      title: '声音设计', icon: '🎨',
      fields: [
        { key: 'design_model', label: '设计模型', type: 'text' },
        { key: 'design_voice_description', label: '设计音色描述', type: 'textarea' }
      ]
    },
    {
      title: '预设描述', icon: '📝',
      fields: [
        { key: 'preset_gentle_female', label: '温柔女生', type: 'text' },
        { key: 'preset_serious_male', label: '严肃男声', type: 'text' },
        { key: 'preset_cute_girl', label: '可爱女孩', type: 'text' },
        { key: 'preset_storyteller', label: '讲故事', type: 'text' },
        { key: 'preset_news_anchor', label: '新闻播报', type: 'text' }
      ]
    },
    {
      title: '高级设置', icon: '⚙️',
      fields: [
        { key: 'timeout', label: 'API 超时(秒)', type: 'number' },
        { key: 'max_retries', label: '重试次数', type: 'number' }
      ]
    }
  ];

  function detectEmotionClient(text) {
    const t = text.toLowerCase();
    if (/开心|高兴|快乐|happy|哈哈|笑/.test(t)) return 'happy';
    if (/伤心|难过|悲伤|sad|哭|泪/.test(t)) return 'sad';
    if (/生气|愤怒|angry|怒/.test(t)) return 'angry';
    if (/低语|whisper|悄悄|耳语/.test(t)) return 'whisper';
    if (/惊喜|惊讶|surprised|wow|天/.test(t)) return 'surprised';
    if (/兴奋|excited|太棒|耶/.test(t)) return 'excited';
    if (/温柔|gentle|轻声/.test(t)) return 'gentle';
    if (/严肃|serious|认真/.test(t)) return 'serious';
    if (/浪漫|romantic|爱/.test(t)) return 'romantic';
    if (/恐惧|害怕|fearful|怕/.test(t)) return 'fearful';
    if (/厌恶|disgusted|恶心/.test(t)) return 'disgusted';
    if (/讽刺|sarcastic/.test(t)) return 'sarcastic';
    if (/怀旧|nostalgic|回忆/.test(t)) return 'nostalgic';
    if (/俏皮|playful|调皮/.test(t)) return 'playful';
    if (/平静|calm|安静/.test(t)) return 'calm';
    if (/焦虑|anxious|紧张/.test(t)) return 'anxious';
    if (/骄傲|proud|自豪/.test(t)) return 'proud';
    if (/柔情|tender/.test(t)) return 'tender';
    if (/慵懒|lazy|懒/.test(t)) return 'lazy';
    return 'neutral';
  }

  function resolveAudioSrc(result) {
    if (!result) return '';
    if (result instanceof Blob) return URL.createObjectURL(result);
    if (typeof result === 'string') {
      if (result.startsWith('data:') || result.startsWith('http') || result.startsWith('blob:')) return result;
      return result;
    }
    if (result.audio_url) return result.audio_url;
    if (result.url) return result.url;
    if (result.path) return result.path;
    if (result.data) {
      const blob = new Blob([result.data], { type: 'audio/wav' });
      return URL.createObjectURL(blob);
    }
    return '';
  }

  const SynthesisPage = {
    setup() {
      const text = ref('');
      const voiceMode = ref('default');
      const selectedVoice = ref('mimo_default');
      const emotion = ref('auto');
      const speed = ref(1.0);
      const pitch = ref(0);
      const audioFormat = ref('wav');
      const breathEnabled = ref(false);
      const stressEnabled = ref(false);
      const laughterEnabled = ref(false);
      const pauseEnabled = ref(false);
      const dialect = ref('');
      const volume = ref('');
      const showAdvanced = ref(false);
      const activePreset = ref('');
      const synthesizing = ref(false);
      const audioSrc = ref('');
      const audioRef = ref(null);
      const errorMsg = ref('');
      const successMsg = ref('');
      const registeredVoices = ref([]);

      const modes = [
        { value: 'default', label: '默认' },
        { value: 'design', label: '设计' },
        { value: 'clone', label: '克隆' }
      ];

      const filteredVoices = computed(() => {
        if (voiceMode.value === 'default') return BUILTIN_VOICES;
        const type = voiceMode.value === 'design' ? 'design' : 'clone';
        const custom = registeredVoices.value.filter(v => v.type === type);
        if (custom.length === 0) return [{ id: '', name: '— 无可用音色 —' }];
        return custom.map(v => ({ id: v.id, name: v.name || v.id }));
      });

      watch(voiceMode, () => {
        const list = filteredVoices.value;
        if (list.length > 0 && !list.find(v => v.id === selectedVoice.value)) {
          selectedVoice.value = list[0].id;
        }
      });

      async function loadVoices() {
        const res = await apiGet('voices');
        if (res) {
          registeredVoices.value = res.registered || [];
        }
      }

      function showError(msg) {
        errorMsg.value = msg;
        setTimeout(() => { errorMsg.value = ''; }, 4000);
      }

      function showSuccessNotification(msg) {
        successMsg.value = msg;
        setTimeout(() => { successMsg.value = ''; }, 3000);
      }

      function applyPreset(preset) {
        activePreset.value = preset.name;
        voiceMode.value = 'default';
        selectedVoice.value = preset.voice;
        emotion.value = preset.emotion;
        speed.value = preset.speed;
        pitch.value = preset.pitch;
        breathEnabled.value = preset.breath;
        stressEnabled.value = preset.stress;
      }

      function runDetectEmotion() {
        if (!text.value.trim()) {
          showError('请先输入文本');
          return;
        }
        const detected = detectEmotionClient(text.value);
        emotion.value = detected;
        showSuccessNotification(`检测到情感: ${detected}`);
      }

      async function synthesize() {
        if (!text.value.trim()) {
          showError('请输入要合成的文本');
          return;
        }
        synthesizing.value = true;
        errorMsg.value = '';
        audioSrc.value = '';

        const body = {
          text: text.value.trim(),
          uid: 'webui',
          tts_mode: voiceMode.value,
          voice: selectedVoice.value,
          speed: speed.value,
          pitch: pitch.value,
          breath: breathEnabled.value,
          stress: stressEnabled.value,
          laughter: laughterEnabled.value,
          pause: pauseEnabled.value,
          format: audioFormat.value
        };

        if (emotion.value && emotion.value !== 'auto') {
          body.emotion = emotion.value;
        }
        if (dialect.value) body.dialect = dialect.value;
        if (volume.value) body.volume = volume.value;

        try {
          const result = await apiPost('tts', body);
          if (!result) {
            showError('合成失败：无响应');
          } else if (result.error) {
            showError(result.error);
          } else {
            audioSrc.value = resolveAudioSrc(result);
            await nextTick();
            if (audioRef.value) {
              audioRef.value.load();
              audioRef.value.play().catch(() => {});
            }
          }
        } catch (e) {
          showError('合成失败：' + (e.message || e));
        } finally {
          synthesizing.value = false;
        }
      }

      onMounted(() => { loadVoices(); });

      return {
        text, voiceMode, selectedVoice, emotion, speed, pitch, audioFormat,
        breathEnabled, stressEnabled, laughterEnabled, pauseEnabled,
        dialect, volume, showAdvanced, activePreset, synthesizing,
        audioSrc, audioRef, errorMsg, successMsg, registeredVoices,
        modes, filteredVoices, EMOTIONS, FORMATS, PRESETS,
        applyPreset, runDetectEmotion, synthesize
      };
    },
    template: `
<div class="page synthesis-page">
  <div class="page-header"><h2>语音合成</h2></div>

  <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
  <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>

  <div class="section">
    <textarea v-model="text" placeholder="输入要合成的文本..." rows="5" class="text-input"></textarea>
  </div>

  <div class="section controls-grid">
    <div class="control-group">
      <label class="control-label">音色模式</label>
      <div class="mode-selector">
        <button v-for="m in modes" :key="m.value"
          :class="['mode-btn', { active: voiceMode === m.value }]"
          @click="voiceMode = m.value">{{ m.label }}</button>
      </div>
    </div>

    <div class="control-group">
      <label class="control-label">音色</label>
      <select v-model="selectedVoice" class="select-input">
        <option v-for="v in filteredVoices" :key="v.id" :value="v.id">{{ v.name }}</option>
      </select>
    </div>

    <div class="control-group">
      <label class="control-label">情感</label>
      <div class="emotion-row">
        <select v-model="emotion" class="select-input">
          <option value="auto">自动检测</option>
          <option value="off">关闭</option>
          <option v-for="e in EMOTIONS" :key="e" :value="e">{{ e }}</option>
        </select>
        <button class="btn-small" @click="runDetectEmotion" title="检测文本情感">🔍</button>
      </div>
    </div>

    <div class="control-group">
      <label class="control-label">音频格式</label>
      <select v-model="audioFormat" class="select-input">
        <option v-for="f in FORMATS" :key="f" :value="f">{{ f.toUpperCase() }}</option>
      </select>
    </div>
  </div>

  <div class="section">
    <div class="control-group">
      <label class="control-label">语速: {{ speed.toFixed(1) }}</label>
      <input type="range" class="slider" v-model.number="speed" min="0.5" max="2.0" step="0.1">
    </div>
    <div class="control-group">
      <label class="control-label">音高: {{ pitch >= 0 ? '+' : '' }}{{ pitch }}</label>
      <input type="range" class="slider" v-model.number="pitch" min="-12" max="12" step="1">
    </div>
  </div>

  <div class="section toggles-row">
    <div class="toggle-item">
      <span>呼吸声</span>
      <label class="toggle"><input type="checkbox" v-model="breathEnabled"><span class="toggle-slider"></span></label>
    </div>
    <div class="toggle-item">
      <span>重音</span>
      <label class="toggle"><input type="checkbox" v-model="stressEnabled"><span class="toggle-slider"></span></label>
    </div>
    <div class="toggle-item">
      <span>笑声</span>
      <label class="toggle"><input type="checkbox" v-model="laughterEnabled"><span class="toggle-slider"></span></label>
    </div>
    <div class="toggle-item">
      <span>停顿</span>
      <label class="toggle"><input type="checkbox" v-model="pauseEnabled"><span class="toggle-slider"></span></label>
    </div>
  </div>

  <div class="section presets-row">
    <span class="preset-chip" v-for="p in PRESETS" :key="p.name"
      :class="{ active: activePreset === p.name }"
      @click="applyPreset(p)">{{ p.label }}</span>
  </div>

  <div class="section">
    <button class="btn-link" @click="showAdvanced = !showAdvanced">
      {{ showAdvanced ? '收起高级设置 ▴' : '高级设置 ▾' }}
    </button>
    <div v-show="showAdvanced" class="advanced-panel">
      <div class="control-group">
        <label class="control-label">方言口音</label>
        <input type="text" v-model="dialect" placeholder="留空表示无方言" class="text-input">
      </div>
      <div class="control-group">
        <label class="control-label">音量</label>
        <select v-model="volume" class="select-input">
          <option value="">默认</option>
          <option value="轻声">轻声</option>
          <option value="正常">正常</option>
          <option value="大声">大声</option>
        </select>
      </div>
    </div>
  </div>

  <div class="section action-bar">
    <button class="btn-primary" @click="synthesize" :disabled="synthesizing">
      {{ synthesizing ? '合成中...' : '🎙️ 合成语音' }}
    </button>
  </div>

  <div v-if="audioSrc" class="section audio-section">
    <audio ref="audioRef" :src="audioSrc" controls class="audio-player"></audio>
  </div>
</div>
`
  };

  const VoicesPage = {
    setup() {
      const designId = ref('');
      const designName = ref('');
      const designDesc = ref('');
      const cloneId = ref('');
      const cloneFile = ref(null);
      const registeredVoices = ref([]);
      const loading = ref(false);
      const errorMsg = ref('');
      const successMsg = ref('');

      function showError(msg) {
        errorMsg.value = msg;
        setTimeout(() => { errorMsg.value = ''; }, 4000);
      }

      function showSuccessNotification(msg) {
        successMsg.value = msg;
        setTimeout(() => { successMsg.value = ''; }, 3000);
      }

      async function loadVoices() {
        loading.value = true;
        const res = await apiGet('voices');
        if (res) {
          registeredVoices.value = res.registered || [];
        }
        loading.value = false;
      }

      async function submitDesign() {
        if (!designId.value.trim() || !designDesc.value.trim()) {
          showError('请填写音色 ID 和描述');
          return;
        }
        const res = await apiPost('voices/design', {
          voice_id: designId.value.trim(),
          name: designName.value.trim() || designId.value.trim(),
          description: designDesc.value.trim()
        });
        if (res && res.error) {
          showError(res.error);
        } else if (res) {
          showSuccessNotification('设计音色已创建');
          designId.value = '';
          designName.value = '';
          designDesc.value = '';
          loadVoices();
        } else {
          showError('创建失败');
        }
      }

      function onCloneFileChange(e) {
        cloneFile.value = e.target.files[0] || null;
      }

      async function submitClone() {
        if (!cloneId.value.trim()) {
          showError('请输入音色 ID');
          return;
        }
        if (!cloneFile.value) {
          showError('请选择参考音频文件');
          return;
        }
        const initRes = await apiPost('voices/clone-init', { voice_id: cloneId.value.trim() });
        if (!initRes || initRes.error) {
          showError(initRes?.error || '初始化失败');
          return;
        }
        const res = await apiUpload('voices/clone-file', cloneFile.value);
        if (res && res.error) {
          showError(res.error);
        } else if (res) {
          showSuccessNotification('克隆音色已上传');
          cloneId.value = '';
          cloneFile.value = null;
          loadVoices();
        } else {
          showError('上传失败');
        }
      }

      async function deleteVoice(voiceId) {
        if (!confirm('确定要删除音色 ' + voiceId + ' 吗？')) return;
        const res = await apiPost('voices/delete', { voice_id: voiceId });
        if (res && res.error) {
          showError(res.error);
        } else {
          showSuccessNotification('已删除: ' + voiceId);
          loadVoices();
        }
      }

      onMounted(() => { loadVoices(); });

      return {
        designId, designName, designDesc, cloneId, cloneFile,
        registeredVoices, loading, errorMsg, successMsg,
        submitDesign, onCloneFileChange, submitClone, deleteVoice
      };
    },
    template: `
<div class="page voices-page">
  <div class="page-header"><h2>音色管理</h2></div>

  <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
  <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>

  <div class="section card">
    <h3>🎨 声音设计</h3>
    <div class="form-grid">
      <div class="control-group">
        <label class="control-label">音色 ID</label>
        <input type="text" v-model="designId" placeholder="my_voice" class="text-input">
      </div>
      <div class="control-group">
        <label class="control-label">名称（可选）</label>
        <input type="text" v-model="designName" placeholder="显示名称" class="text-input">
      </div>
      <div class="control-group full-width">
        <label class="control-label">音色描述</label>
        <textarea v-model="designDesc" placeholder="如：温柔甜美的年轻女声，语速适中" rows="3" class="text-input"></textarea>
      </div>
    </div>
    <button class="btn-primary" @click="submitDesign">创建设计音色</button>
  </div>

  <div class="section card">
    <h3>🎤 声音克隆</h3>
    <div class="form-grid">
      <div class="control-group">
        <label class="control-label">音色 ID</label>
        <input type="text" v-model="cloneId" placeholder="my_clone" class="text-input">
      </div>
      <div class="control-group">
        <label class="control-label">参考音频（mp3/wav）</label>
        <input type="file" accept=".mp3,.wav" @change="onCloneFileChange" class="file-input">
      </div>
    </div>
    <button class="btn-primary" @click="submitClone">上传克隆音色</button>
  </div>

  <div class="section card">
    <h3>📋 已注册音色</h3>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="registeredVoices.length === 0" class="empty-hint">暂无自定义音色</div>
    <div v-else class="voice-list">
      <div v-for="v in registeredVoices" :key="v.id" class="voice-card">
        <div class="voice-info">
          <span class="voice-name">{{ v.name || v.id }}</span>
          <span class="voice-type badge" :class="v.type">{{ v.type === 'design' ? '设计' : '克隆' }}</span>
        </div>
        <button class="btn-danger-small" @click="deleteVoice(v.id)">删除</button>
      </div>
    </div>
  </div>
</div>
`
  };

  const ConfigPage = {
    setup() {
      const config = reactive({});
      const loading = ref(false);
      const saving = ref(false);
      const errorMsg = ref('');
      const successMsg = ref('');
      const sections = CONFIG_SECTIONS;

      function showError(msg) {
        errorMsg.value = msg;
        setTimeout(() => { errorMsg.value = ''; }, 4000);
      }

      function showSuccessNotification(msg) {
        successMsg.value = msg;
        setTimeout(() => { successMsg.value = ''; }, 3000);
      }

      async function loadConfig() {
        loading.value = true;
        const res = await apiGet('config');
        if (res && res.config) {
          Object.keys(res.config).forEach(k => {
            config[k] = res.config[k];
          });
        }
        loading.value = false;
      }

      async function saveSection(section) {
        saving.value = true;
        const payload = {};
        section.fields.forEach(f => {
          if (config[f.key] !== undefined) {
            payload[f.key] = config[f.key];
          }
        });
        const res = await apiPost('config/update', payload);
        if (res && res.error) {
          showError(res.error);
        } else if (res) {
          showSuccessNotification(section.title + ' 已保存');
        } else {
          showError('保存失败');
        }
        saving.value = false;
      }

      onMounted(() => { loadConfig(); });

      return { config, loading, saving, errorMsg, successMsg, sections, saveSection };
    },
    template: `
<div class="page config-page">
  <div class="page-header"><h2>插件配置</h2></div>

  <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
  <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>
  <div v-if="loading" class="loading">加载中...</div>

  <template v-if="!loading">
    <div v-for="section in sections" :key="section.title" class="section card config-section">
      <h3>{{ section.icon }} {{ section.title }}</h3>
      <div class="config-fields">
        <div v-for="field in section.fields" :key="field.key" class="config-field">
          <label class="control-label">{{ field.label }}</label>

          <template v-if="field.type === 'text' || field.type === 'password'">
            <input :type="field.type" v-model="config[field.key]" class="text-input"
              :placeholder="field.hint || ''">
          </template>

          <template v-else-if="field.type === 'number'">
            <input type="number" v-model.number="config[field.key]" class="text-input"
              :placeholder="field.hint || ''">
          </template>

          <template v-else-if="field.type === 'bool'">
            <label class="toggle">
              <input type="checkbox" v-model="config[field.key]">
              <span class="toggle-slider"></span>
            </label>
          </template>

          <template v-else-if="field.type === 'select'">
            <select v-model="config[field.key]" class="select-input">
              <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt || '(空)' }}</option>
            </select>
          </template>

          <template v-else-if="field.type === 'slider'">
            <div class="slider-row">
              <input type="range" class="slider" v-model.number="config[field.key]"
                :min="field.min" :max="field.max" :step="field.step">
              <span class="slider-value">{{ config[field.key] }}</span>
            </div>
          </template>

          <template v-else-if="field.type === 'textarea'">
            <textarea v-model="config[field.key]" rows="5" class="text-input"
              :placeholder="field.hint || ''"></textarea>
          </template>

          <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
        </div>
      </div>
      <div class="section-actions">
        <button class="btn-primary" @click="saveSection(section)" :disabled="saving">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </template>
</div>
`
  };

  const SessionsPage = {
    setup() {
      const sessions = ref({});
      const loading = ref(false);
      const editingUid = ref('');
      const editForm = reactive({
        voice: '', emotion: '', speed: 1.0, pitch: 0,
        tts_mode: '', tts_enabled: true, text_enabled: true, format: 'wav'
      });
      const errorMsg = ref('');
      const successMsg = ref('');

      function showError(msg) {
        errorMsg.value = msg;
        setTimeout(() => { errorMsg.value = ''; }, 4000);
      }

      function showSuccessNotification(msg) {
        successMsg.value = msg;
        setTimeout(() => { successMsg.value = ''; }, 3000);
      }

      async function loadSessions() {
        loading.value = true;
        const res = await apiGet('sessions');
        if (res && res.sessions) {
          sessions.value = res.sessions;
        }
        loading.value = false;
      }

      function startEdit(uid) {
        editingUid.value = uid;
        const s = sessions.value[uid];
        if (s) {
          const settings = s.settings || {};
          editForm.voice = settings.voice || '';
          editForm.emotion = settings.emotion || '';
          editForm.speed = settings.speed ?? 1.0;
          editForm.pitch = settings.pitch ?? 0;
          editForm.tts_mode = settings.tts_mode || '';
          editForm.tts_enabled = settings.tts_enabled !== false;
          editForm.text_enabled = settings.text_enabled !== false;
          editForm.format = s.format || 'wav';
        }
      }

      function cancelEdit() {
        editingUid.value = '';
      }

      async function saveSession(uid) {
        const payload = {
          uid: uid,
          settings: {
            voice: editForm.voice,
            emotion: editForm.emotion,
            speed: editForm.speed,
            pitch: editForm.pitch,
            tts_mode: editForm.tts_mode,
            tts_enabled: editForm.tts_enabled,
            text_enabled: editForm.text_enabled
          }
        };
        const res = await apiPost('sessions/update', payload);
        if (res && res.error) {
          showError(res.error);
        } else {
          showSuccessNotification('会话已更新');
          editingUid.value = '';
          loadSessions();
        }
      }

      async function resetSession(uid) {
        if (!confirm('确定要重置会话 ' + uid + ' 的配置吗？')) return;
        const res = await apiPost('sessions/reset', { uid });
        if (res && res.error) {
          showError(res.error);
        } else {
          showSuccessNotification('会话已重置');
          loadSessions();
        }
      }

      async function deleteSession(uid) {
        if (!confirm('确定要删除会话 ' + uid + ' 吗？')) return;
        const res = await apiPost('sessions/delete', { uid });
        if (res && res.error) {
          showError(res.error);
        } else {
          showSuccessNotification('会话已删除');
          delete sessions.value[uid];
        }
      }

      function formatMode(mode) {
        if (mode === 'design') return '设计';
        if (mode === 'clone') return '克隆';
        return '默认';
      }

      onMounted(() => { loadSessions(); });

      return {
        sessions, loading, editingUid, editForm, errorMsg, successMsg,
        loadSessions, startEdit, cancelEdit, saveSession, resetSession,
        deleteSession, formatMode, EMOTIONS, FORMATS
      };
    },
    template: `
<div class="page sessions-page">
  <div class="page-header">
    <h2>会话管理</h2>
    <button class="btn-small" @click="loadSessions">刷新</button>
  </div>

  <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
  <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>
  <div v-if="loading" class="loading">加载中...</div>

  <div v-else-if="Object.keys(sessions).length === 0" class="empty-hint">暂无会话数据</div>

  <div v-else class="sessions-list">
    <div v-for="(data, uid) in sessions" :key="uid" class="section card session-card">
      <div class="session-header">
        <span class="session-uid">{{ uid }}</span>
        <div class="session-actions">
          <button class="btn-small" @click="startEdit(uid)">编辑</button>
          <button class="btn-small" @click="resetSession(uid)">重置</button>
          <button class="btn-danger-small" @click="deleteSession(uid)">删除</button>
        </div>
      </div>

      <div class="session-info">
        <span class="info-item">音色: <b>{{ data.settings?.voice || '-' }}</b></span>
        <span class="info-item">情感: <b>{{ data.settings?.emotion || '自动' }}</b></span>
        <span class="info-item">语速: <b>{{ data.settings?.speed ?? '-' }}</b></span>
        <span class="info-item">音高: <b>{{ data.settings?.pitch ?? '-' }}</b></span>
        <span class="info-item">模式: <b>{{ formatMode(data.settings?.tts_mode) }}</b></span>
        <span class="info-item">TTS: <b>{{ data.settings?.tts_enabled !== false ? '开' : '关' }}</b></span>
        <span class="info-item">文字: <b>{{ data.settings?.text_enabled !== false ? '开' : '关' }}</b></span>
        <span class="info-item">格式: <b>{{ data.format || 'wav' }}</b></span>
      </div>

      <div v-if="editingUid === uid" class="edit-form">
        <div class="form-grid">
          <div class="control-group">
            <label class="control-label">音色</label>
            <input type="text" v-model="editForm.voice" class="text-input">
          </div>
          <div class="control-group">
            <label class="control-label">情感</label>
            <select v-model="editForm.emotion" class="select-input">
              <option value="">自动</option>
              <option v-for="e in EMOTIONS" :key="e" :value="e">{{ e }}</option>
            </select>
          </div>
          <div class="control-group">
            <label class="control-label">语速: {{ editForm.speed.toFixed(1) }}</label>
            <input type="range" class="slider" v-model.number="editForm.speed" min="0.5" max="2.0" step="0.1">
          </div>
          <div class="control-group">
            <label class="control-label">音高: {{ editForm.pitch >= 0 ? '+' : '' }}{{ editForm.pitch }}</label>
            <input type="range" class="slider" v-model.number="editForm.pitch" min="-12" max="12" step="1">
          </div>
          <div class="control-group">
            <label class="control-label">模式</label>
            <select v-model="editForm.tts_mode" class="select-input">
              <option value="">默认</option>
              <option value="default">默认</option>
              <option value="design">设计</option>
              <option value="clone">克隆</option>
            </select>
          </div>
          <div class="control-group">
            <label class="control-label">格式</label>
            <select v-model="editForm.format" class="select-input">
              <option v-for="f in FORMATS" :key="f" :value="f">{{ f.toUpperCase() }}</option>
            </select>
          </div>
          <div class="control-group">
            <span>自动 TTS</span>
            <label class="toggle"><input type="checkbox" v-model="editForm.tts_enabled"><span class="toggle-slider"></span></label>
          </div>
          <div class="control-group">
            <span>文字同步</span>
            <label class="toggle"><input type="checkbox" v-model="editForm.text_enabled"><span class="toggle-slider"></span></label>
          </div>
        </div>
        <div class="edit-actions">
          <button class="btn-primary" @click="saveSession(uid)">保存</button>
          <button class="btn-secondary" @click="cancelEdit">取消</button>
        </div>
      </div>
    </div>
  </div>
</div>
`
  };

  const AboutPage = {
    setup() {
      const version = ref('unknown');
      const features = [
        '20 种情感精细控制',
        '8 种内置音色（中英双语）',
        '声音克隆（参考音频）',
        '声音设计（文字描述）',
        '文本分段 TTS',
        'LLM 语音润色',
        '唱歌模式',
        '预设系统（8 种预设）',
        '方言口音 / 音量控制',
        '呼吸声 / 重音 / 笑声 / 停顿',
        '多格式输出（WAV/MP3/OGG）',
        'Per-chat 独立配置'
      ];

      async function loadVersion() {
        const res = await apiGet('health');
        if (res && res.version) {
          version.value = res.version;
        }
      }

      onMounted(() => { loadVersion(); });

      return { version, features };
    },
    template: `
<div class="page about-page">
  <div class="page-header"><h2>关于</h2></div>

  <div class="section card about-card">
    <h3>🎙️ astrbot_plugin_mimo_tts</h3>
    <p class="version">版本: {{ version }}</p>
    <p class="desc">基于 MiMO-V2.5-TTS 的精细化语音合成插件</p>
  </div>

  <div class="section card">
    <h3>功能特性</h3>
    <ul class="feature-list">
      <li v-for="f in features" :key="f">{{ f }}</li>
    </ul>
  </div>

  <div class="section card">
    <h3>链接</h3>
    <div class="links">
      <a href="https://github.com/SteveBaka/astrbot_plugin_mimo_tts" target="_blank" class="link">GitHub 仓库</a>
    </div>
  </div>
</div>
`
  };

  const App = {
    setup() {
      const isDark = ref(true);
      const isMobile = ref(window.innerWidth < 768);
      const pluginReady = ref(true);

      const navItems = [
        { path: '/', label: '合成', icon: '🎙️' },
        { path: '/voices', label: '音色', icon: '🎤' },
        { path: '/config', label: '配置', icon: '⚙️' },
        { path: '/sessions', label: '会话', icon: '💬' },
        { path: '/about', label: '关于', icon: 'ℹ️' }
      ];

      function toggleTheme() {
        isDark.value = !isDark.value;
        document.documentElement.setAttribute('data-theme', isDark.value ? '' : 'light');
      }

      function checkMobile() {
        isMobile.value = window.innerWidth < 768;
      }

      onMounted(() => {
        checkMobile();
        window.addEventListener('resize', checkMobile);
      });

      return { isDark, isMobile, pluginReady, navItems, toggleTheme };
    },
    template: `
<div id="studio-root" :class="{ 'dark-theme': isDark }" v-if="pluginReady">
  <aside class="sidebar" v-show="!isMobile">
    <div class="sidebar-header">
      <h2>🎙️ Voice Studio</h2>
    </div>
    <nav class="sidebar-nav">
      <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="nav-link">
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </router-link>
    </nav>
    <div class="sidebar-footer">
      <button class="theme-btn" @click="toggleTheme" :title="isDark ? '切换亮色' : '切换暗色'">
        {{ isDark ? '☀️' : '🌙' }}
      </button>
    </div>
  </aside>

  <main class="main-content">
    <router-view></router-view>
  </main>

  <nav class="mobile-bar" v-show="isMobile">
    <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="mobile-link">
      <span class="mobile-icon">{{ item.icon }}</span>
      <span class="mobile-label">{{ item.label }}</span>
    </router-link>
    <button class="mobile-link" @click="toggleTheme">
      <span class="mobile-icon">{{ isDark ? '☀️' : '🌙' }}</span>
      <span class="mobile-label">主题</span>
    </button>
  </nav>
</div>
`
  };

  const router = createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: '/', component: SynthesisPage },
      { path: '/voices', component: VoicesPage },
      { path: '/config', component: ConfigPage },
      { path: '/sessions', component: SessionsPage },
      { path: '/about', component: AboutPage }
    ]
  });

  async function init() {
    let retries = 0;
    while (!window.AstrBotPluginPage && retries < 50) {
      await new Promise(r => setTimeout(r, 100));
      retries++;
    }
    const br = window.AstrBotPluginPage;
    if (br && typeof br.ready === 'function') {
      await br.ready();
    }
    const app = createApp(App);
    app.use(router);
    app.mount('#app');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
