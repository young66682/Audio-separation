<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import GuitarScore from "./components/GuitarScore.vue";
import TabSheet from "./components/TabSheet.vue";
import {
  artifactUrl,
  audioUrl,
  createSongTranscription,
  createTranscription,
  fetchHealth,
  songArchiveUrl,
  songArtifactUrl,
  songAudioUrl,
  songScoreUrl,
  subscribeToJob,
  subscribeToSongJob,
} from "./api";
import type {
  Health,
  SongTranscriptionJob,
  TranscriptionJob,
  TranscriptionResult,
} from "./types";

type WorkMode = "song" | "guitar";
type GuitarKey = "lead" | "rhythm";

const tuningPresets = [
  { label: "标准调弦", value: "E2,A2,D3,G3,B3,E4" },
  { label: "Drop D", value: "D2,A2,D3,G3,B3,E4" },
  { label: "降半音", value: "Eb2,Ab2,Db3,Gb3,Bb3,Eb4" },
  { label: "Open G", value: "D2,G2,D3,G3,B3,D4" },
  { label: "DADGAD", value: "D2,A2,D3,G3,A3,D4" },
];

const fileInput = ref<HTMLInputElement | null>(null);
const audioPlayer = ref<HTMLAudioElement | null>(null);
const selectedFile = ref<File | null>(null);
const previewUrl = ref<string | null>(null);
const dragging = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
const health = ref<Health | null>(null);
const workMode = ref<WorkMode>("song");
const singleJob = ref<TranscriptionJob | null>(null);
const songJob = ref<SongTranscriptionJob | null>(null);
const selectedGuitar = ref<GuitarKey>("lead");
const currentTime = ref(0);
let stopEvents: (() => void) | null = null;

const settings = reactive({
  autoBpm: true,
  bpm: 120,
  tuning: tuningPresets[0].value,
  capo: 0,
  maxFret: 17,
  maxFretSpan: 5,
  minDuration: 0.08,
  minVelocity: 0.4,
});

const activeJob = computed(() => (workMode.value === "song" ? songJob.value : singleJob.value));
const singleResult = computed(() => singleJob.value?.result ?? null);
const songResult = computed(() => songJob.value?.result ?? null);
const hasResult = computed(() => Boolean(singleResult.value || songResult.value));
const isWorking = computed(
  () =>
    submitting.value ||
    activeJob.value?.status === "queued" ||
    activeJob.value?.status === "running",
);
const cloudReady = computed(() => Boolean(health.value?.cloud_separation_ready));
const startDisabled = computed(
  () =>
    !selectedFile.value ||
    isWorking.value ||
    !health.value?.transcription_ready ||
    (workMode.value === "song" && !cloudReady.value),
);
const acceptedFormats = computed(
  () => health.value?.supported_formats.map((format) => format.slice(1)).join(", ") ?? "音频文件",
);

const selectedPart = computed(() => {
  if (!songResult.value) return null;
  return (
    songResult.value.guitars.find((guitar) => guitar.key === selectedGuitar.value) ??
    songResult.value.guitars[0] ??
    null
  );
});
const selectedTranscription = computed(
  () => selectedPart.value?.transcription ?? null,
);
const currentBeat = computed(() => {
  const transcription = selectedTranscription.value ?? singleResult.value;
  return transcription ? (currentTime.value * transcription.bpm) / 60 : 0;
});

const singleDownloadLinks = computed(() => {
  if (!singleJob.value || !singleResult.value) return [];
  return artifactEntries(singleJob.value.id, singleResult.value, false);
});
const songDownloadLinks = computed(() => {
  if (!songJob.value || !selectedPart.value?.transcription) return [];
  return artifactEntries(
    songJob.value.id,
    selectedPart.value.transcription,
    true,
    selectedPart.value.key,
  );
});

function artifactEntries(
  jobId: string,
  transcription: TranscriptionResult,
  songMode: boolean,
  guitar?: GuitarKey,
) {
  const names: Record<string, string> = {
    tab: "六线谱 TXT",
    midi: "MIDI",
    musicxml: "MusicXML",
    json: "音符数据 JSON",
  };
  return Object.entries(transcription.artifacts).map(([key, filename]) => ({
    key,
    filename,
    label: names[key] ?? filename,
    href:
      songMode && guitar
        ? songArtifactUrl(jobId, guitar, key)
        : artifactUrl(jobId, key),
  }));
}

onMounted(async () => {
  await refreshHealth();
});

onBeforeUnmount(() => {
  stopEvents?.();
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
});

watch(selectedGuitar, () => {
  currentTime.value = 0;
});

async function refreshHealth() {
  try {
    health.value = await fetchHealth();
    if (!health.value.transcription_ready) {
      errorMessage.value = "转录引擎未就绪，请检查 Python 3.11 后端环境。";
    } else {
      errorMessage.value = "";
    }
  } catch {
    errorMessage.value = "无法连接扒谱服务，请先启动 FastAPI 后端。";
  }
}

function setMode(mode: WorkMode) {
  if (isWorking.value || workMode.value === mode) return;
  workMode.value = mode;
  singleJob.value = null;
  songJob.value = null;
  currentTime.value = 0;
  errorMessage.value = "";
}

function chooseFile() {
  fileInput.value?.click();
}

function setFile(file: File | undefined) {
  if (!file) return;
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  selectedFile.value = file;
  previewUrl.value = URL.createObjectURL(file);
  singleJob.value = null;
  songJob.value = null;
  currentTime.value = 0;
  if (workMode.value === "guitar") errorMessage.value = "";
}

function onFileInput(event: Event) {
  setFile((event.target as HTMLInputElement).files?.[0]);
}

function onDrop(event: DragEvent) {
  dragging.value = false;
  setFile(event.dataTransfer?.files?.[0]);
}

async function startTranscription() {
  if (!selectedFile.value || startDisabled.value) return;
  errorMessage.value = "";
  submitting.value = true;
  stopEvents?.();
  const options = {
    bpm: settings.autoBpm ? 0 : settings.bpm,
    tuning: settings.tuning,
    capo: settings.capo,
    maxFret: settings.maxFret,
    maxFretSpan: settings.maxFretSpan,
    minDuration: settings.minDuration,
    minVelocity: settings.minVelocity,
  };

  try {
    if (workMode.value === "song") {
      const created = await createSongTranscription(selectedFile.value, options);
      stopEvents = subscribeToSongJob(
        created.job_id,
        (job) => {
          songJob.value = job;
          submitting.value = false;
          if (job.status === "failed") {
            errorMessage.value = job.error ?? "整曲双吉他处理失败";
          }
        },
        () => {
          stopEvents?.();
          stopEvents = null;
        },
        (message) => {
          errorMessage.value = message;
          submitting.value = false;
        },
      );
    } else {
      const created = await createTranscription(selectedFile.value, options);
      stopEvents = subscribeToJob(
        created.job_id,
        (job) => {
          singleJob.value = job;
          submitting.value = false;
          if (job.status === "failed") {
            errorMessage.value = job.error ?? "扒谱失败，请调整参数后重试。";
          }
        },
        () => {
          stopEvents?.();
          stopEvents = null;
        },
        (message) => {
          errorMessage.value = message;
          submitting.value = false;
        },
      );
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "提交任务失败";
    submitting.value = false;
  }
}

function reset() {
  stopEvents?.();
  stopEvents = null;
  singleJob.value = null;
  songJob.value = null;
  currentTime.value = 0;
  errorMessage.value = "";
}

function seek(seconds: number) {
  if (!audioPlayer.value) return;
  audioPlayer.value.currentTime = seconds;
  void audioPlayer.value.play();
}

function selectGuitar(key: GuitarKey) {
  selectedGuitar.value = key;
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="Fretline home">
        <span class="brand-mark">
          <i v-for="line in 6" :key="line" />
        </span>
        <span>
          <strong>Fretline</strong>
          <small>吉他扒谱工作台</small>
        </span>
      </a>
      <div class="system-state" :class="{ offline: !health?.transcription_ready }">
        <span class="state-dot" />
        <template v-if="health?.transcription_ready">
          转录引擎就绪
          <span class="state-separator">/</span>
          {{ cloudReady ? "双吉他云端可用" : "仅本地单吉他" }}
        </template>
        <template v-else>转录引擎未就绪</template>
      </div>
    </header>

    <main>
      <section v-if="!hasResult" class="hero">
        <div class="hero-copy">
          <span class="eyebrow">Audio → lead + rhythm → tabs</span>
          <h1 v-if="workMode === 'song'">
            上传整首歌，<br /><em>生成双吉他谱。</em>
          </h1>
          <h1 v-else>
            上传吉他音轨，<br /><em>生成六线谱。</em>
          </h1>
          <p v-if="workMode === 'song'">
            先由 MVSEP 把整曲分离成主音吉他、节奏吉他和伴奏，再分别在本地识别音高、
            分配琴弦和品丝。每首歌会得到两套独立六线谱。
          </p>
          <p v-else>
            适合已分离的 guitar stem 或独奏录音。系统会识别多音、自动测速，
            并导出六线谱、MIDI 与 MusicXML。
          </p>
          <div class="signal-strip">
            <span>{{ workMode === "song" ? "Lead / Rhythm 双源分离" : "Basic Pitch 多音识别" }}</span>
            <span>自动测速</span>
            <span>六弦约束</span>
            <span>十六分音符量化</span>
          </div>
          <div class="mode-switch" role="tablist" aria-label="输入模式">
            <button
              type="button"
              :class="{ active: workMode === 'song' }"
              :disabled="isWorking"
              @click="setMode('song')"
            >
              <strong>整曲双吉他</strong>
              <small>MVSEP 云端分离 · 音频会上传</small>
            </button>
            <button
              type="button"
              :class="{ active: workMode === 'guitar' }"
              :disabled="isWorking"
              @click="setMode('guitar')"
            >
              <strong>单吉他音轨</strong>
              <small>完全本地 · 已有 stem</small>
            </button>
          </div>
        </div>

        <div class="work-card">
          <div class="card-heading">
            <span>01</span>
            <div>
              <h2>{{ workMode === "song" ? "导入整首歌曲" : "导入吉他音轨" }}</h2>
              <p>
                {{
                  workMode === "song"
                    ? "免费账号单曲上限 10 分钟 / 100 MB"
                    : "建议使用分离后的 guitar stem 或独奏录音"
                }}
              </p>
            </div>
          </div>

          <button
            type="button"
            class="drop-zone"
            :class="{ dragging, ready: selectedFile }"
            :disabled="isWorking"
            @click="chooseFile"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <input
              ref="fileInput"
              type="file"
              accept="audio/*,.wav,.mp3,.flac,.m4a,.ogg,.aiff"
              hidden
              @change="onFileInput"
            />
            <span class="upload-symbol">{{ selectedFile ? "✓" : "↥" }}</span>
            <strong>{{ selectedFile?.name ?? "拖入音频，或点击选择" }}</strong>
            <small v-if="selectedFile">
              {{ (selectedFile.size / 1024 / 1024).toFixed(2) }} MB · 点击更换
            </small>
            <small v-else>支持 {{ acceptedFormats }}，最大 {{ health?.max_upload_mb ?? 100 }} MB</small>
          </button>

          <div v-if="workMode === 'song' && !cloudReady" class="config-notice">
            <span>云分离未配置</span>
            <p>
              在 <code>backend/.env</code> 中填写免费的
              <code>MVSEP_API_TOKEN</code>，然后重启后端。
            </p>
            <button type="button" @click="refreshHealth">重新检测</button>
          </div>

          <div class="settings-grid">
            <label class="setting wide">
              <span>调弦</span>
              <select v-model="settings.tuning" :disabled="isWorking">
                <option v-for="preset in tuningPresets" :key="preset.value" :value="preset.value">
                  {{ preset.label }} · {{ preset.value }}
                </option>
              </select>
            </label>

            <label class="setting">
              <span>BPM</span>
              <div class="inline-control">
                <input
                  v-model.number="settings.bpm"
                  type="number"
                  min="30"
                  max="300"
                  :disabled="settings.autoBpm || isWorking"
                />
                <label class="check">
                  <input v-model="settings.autoBpm" type="checkbox" :disabled="isWorking" />
                  自动
                </label>
              </div>
            </label>

            <label class="setting">
              <span>变调夹</span>
              <select v-model.number="settings.capo" :disabled="isWorking">
                <option v-for="fret in 13" :key="fret" :value="fret - 1">
                  {{ fret - 1 === 0 ? "不使用" : `${fret - 1} 品` }}
                </option>
              </select>
            </label>

            <label class="setting">
              <span>最高品数</span>
              <input
                v-model.number="settings.maxFret"
                type="number"
                min="5"
                max="24"
                :disabled="isWorking"
              />
            </label>

            <label class="setting">
              <span>和弦跨度</span>
              <select v-model.number="settings.maxFretSpan" :disabled="isWorking">
                <option v-for="span in 9" :key="span" :value="span + 1">
                  {{ span + 1 }} 品
                </option>
              </select>
            </label>

            <label class="setting">
              <span>最短音符</span>
              <div class="range-wrap">
                <input
                  v-model.number="settings.minDuration"
                  type="range"
                  min="0.04"
                  max="0.3"
                  step="0.01"
                  :disabled="isWorking"
                />
                <b>{{ settings.minDuration.toFixed(2) }}s</b>
              </div>
            </label>

            <label class="setting">
              <span>力度门槛</span>
              <div class="range-wrap">
                <input
                  v-model.number="settings.minVelocity"
                  type="range"
                  min="0.1"
                  max="0.7"
                  step="0.02"
                  :disabled="isWorking"
                />
                <b>{{ Math.round(settings.minVelocity * 100) }}%</b>
              </div>
            </label>
          </div>

          <audio
            v-if="previewUrl"
            :src="previewUrl"
            controls
            preload="metadata"
            class="source-audio"
          />

          <button
            type="button"
            class="primary-button"
            :disabled="startDisabled"
            @click="startTranscription"
          >
            <span v-if="isWorking" class="spinner" />
            {{
              isWorking
                ? workMode === "song"
                  ? "正在分离并扒谱…"
                  : "正在扒谱…"
                : workMode === "song"
                  ? "分离双吉他的六线谱"
                  : "开始生成六线谱"
            }}
          </button>

          <div v-if="activeJob && isWorking" class="progress-card" aria-live="polite">
            <div class="progress-meta">
              <span>{{ activeJob.message }}</span>
              <strong>{{ activeJob.progress }}%</strong>
            </div>
            <div class="progress-track">
              <span :style="{ width: `${activeJob.progress}%` }" />
            </div>
          </div>

          <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        </div>
      </section>

      <section v-else-if="singleResult && singleJob" class="result-view">
        <div class="result-heading">
          <div>
            <span class="eyebrow">Transcription complete</span>
            <h1>{{ singleResult.title }}</h1>
            <p>
              {{ singleResult.note_count }} 个可演奏音符 · 原始检测
              {{ singleResult.raw_note_count }} 个 · {{ singleResult.bpm.toFixed(1) }} BPM
            </p>
          </div>
          <div class="result-actions">
            <button type="button" class="ghost-button" @click="reset">重新扒谱</button>
            <a
              v-for="link in singleDownloadLinks"
              :key="link.key"
              class="download-chip"
              :href="link.href"
              :download="link.filename"
            >
              ↓ {{ link.label }}
            </a>
          </div>
        </div>

        <div class="result-grid">
          <aside class="playback-card">
            <span class="eyebrow">Source audio</span>
            <h2>对照试听</h2>
            <audio
              ref="audioPlayer"
              :src="audioUrl(singleJob.id)"
              controls
              preload="metadata"
              @timeupdate="currentTime = audioPlayer?.currentTime ?? 0"
            />
            <dl>
              <div><dt>调弦</dt><dd>{{ singleResult.tuning }}</dd></div>
              <div><dt>变调夹</dt><dd>{{ singleResult.capo }} 品</dd></div>
              <div><dt>最高品</dt><dd>{{ singleResult.max_fret }}</dd></div>
              <div><dt>导出文件</dt><dd>{{ Object.keys(singleResult.artifacts).length }} 个</dd></div>
            </dl>
            <div v-if="singleResult.warnings.length" class="warning-box">
              <strong>需要复核</strong>
              <p v-for="warning in singleResult.warnings" :key="warning">{{ warning }}</p>
            </div>
          </aside>

          <TabSheet
            :events="singleResult.events"
            :bpm="singleResult.bpm"
            :tuning="singleResult.tuning"
            :capo="singleResult.capo"
            :current-beat="currentBeat"
            @seek="seek"
          />
        </div>

        <details class="text-tab">
          <summary>查看并复制文本六线谱</summary>
          <pre>{{ singleResult.tab_text }}</pre>
        </details>
      </section>

      <section v-else-if="songResult && songJob" class="result-view">
        <div class="result-heading">
          <div>
            <span class="eyebrow">Dual guitar transcription complete</span>
            <h1>{{ songResult.title }}</h1>
            <p>
              主音与节奏吉他分别识别 · {{ songResult.bpm.toFixed(1) }} BPM ·
              {{ songResult.guitars.length }} 个吉他声部
            </p>
          </div>
          <div class="result-actions">
            <button type="button" class="ghost-button" @click="reset">处理另一首歌</button>
            <a class="download-chip archive-chip" :href="songArchiveUrl(songJob.id)">
              ↓ 下载整套项目 ZIP
            </a>
          </div>
        </div>

        <GuitarScore
          v-if="songResult.score_artifact"
          :key="songJob.id"
          :url="songScoreUrl(songJob.id)"
        />

        <div class="editor-divider">
          <span>分轨试听与逐音检查</span>
        </div>

        <div class="guitar-switcher">
          <button
            v-for="part in songResult.guitars"
            :key="part.key"
            type="button"
            class="guitar-option"
            :class="{ active: selectedGuitar === part.key, unavailable: !part.transcription }"
            @click="selectGuitar(part.key)"
          >
            <span>{{ part.key === "lead" ? "LEAD" : "RHYTHM" }}</span>
            <strong>{{ part.label }}</strong>
            <small v-if="part.transcription">
              {{ part.transcription.note_count }} 个音符
            </small>
            <small v-else>{{ part.error ?? "生成失败" }}</small>
          </button>
        </div>

        <div v-if="selectedPart?.transcription" class="result-grid">
          <aside class="playback-card">
            <span class="eyebrow">Separated guitar</span>
            <h2>{{ selectedPart.label }}</h2>
            <audio
              ref="audioPlayer"
              :src="songAudioUrl(songJob.id, selectedPart.key)"
              controls
              preload="metadata"
              @timeupdate="currentTime = audioPlayer?.currentTime ?? 0"
            />
            <dl>
              <div><dt>识别模型</dt><dd>Basic Pitch</dd></div>
              <div><dt>分离模型</dt><dd>{{ health?.cloud_separation_model ?? "MVSEP" }}</dd></div>
              <div><dt>调弦</dt><dd>{{ selectedPart.transcription.tuning }}</dd></div>
              <div><dt>可演奏音符</dt><dd>{{ selectedPart.transcription.note_count }}</dd></div>
              <div><dt>伴奏音轨</dt><dd>{{ songResult.backing_available ? "已保留" : "无" }}</dd></div>
            </dl>
            <div class="result-actions part-downloads">
              <a
                v-for="link in songDownloadLinks"
                :key="link.key"
                class="download-chip"
                :href="link.href"
                :download="link.filename"
              >
                ↓ {{ link.label }}
              </a>
            </div>
            <div v-if="selectedPart.transcription.warnings.length" class="warning-box">
              <strong>需要复核</strong>
              <p
                v-for="warning in selectedPart.transcription.warnings"
                :key="warning"
              >
                {{ warning }}
              </p>
            </div>
          </aside>

          <TabSheet
            :events="selectedPart.transcription.events"
            :bpm="selectedPart.transcription.bpm"
            :tuning="selectedPart.transcription.tuning"
            :capo="selectedPart.transcription.capo"
            :current-beat="currentBeat"
            @seek="seek"
          />
        </div>

        <div v-else class="empty-part">
          <h2>{{ selectedPart?.label ?? "吉他声部" }} 未能转录</h2>
          <p>{{ selectedPart?.error ?? "请检查分离结果或重新处理。" }}</p>
        </div>

        <details v-if="selectedPart?.transcription" class="text-tab">
          <summary>查看并复制 {{ selectedPart.label }} 文本六线谱</summary>
          <pre>{{ selectedPart.transcription.tab_text }}</pre>
        </details>
      </section>
    </main>

    <footer>
      <span>Fretline · local-first transcription</span>
      <span>AI 结果仅供扒谱初稿，请结合原曲校正节奏、声部与指法。</span>
    </footer>
  </div>
</template>
