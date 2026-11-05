<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import TabSheet from "./components/TabSheet.vue";
import {
  artifactUrl,
  audioUrl,
  createSeparation,
  createSongTranscription,
  createTranscription,
  fetchHealth,
  fetchRecentJobs,
  fetchSeparationJob,
  fetchSongJob,
  fetchTranscriptionJob,
  retrySongTranscription,
  searchAvailableScores,
  searchMarketAvailability,
  separationArchiveUrl,
  separationAudioUrl,
  separationSourceAudioUrl,
  songArchiveUrl,
  songArtifactUrl,
  songAudioUrl,
  songScoreUrl,
  subscribeToJob,
  subscribeToSeparationJob,
  subscribeToSongJob,
} from "./api";
import type {
  Health,
  MarketSearchResponse,
  ScoreSearchResponse,
  SeparationJob,
  SeparationModel,
  SeparationQuality,
  SongTranscriptionJob,
  TranscriptionJob,
  TranscriptionResult,
} from "./types";

type WorkMode = "separate" | "song" | "guitar";
type GuitarKey = "lead" | "rhythm";
type Theme = "light" | "dark";
type StoredJob = {
  jobId: string;
  mode: WorkMode;
};

const LAST_JOB_KEY = "fretline-last-job";
const RESET_MARKER_KEY = "fretline-reset";

const GuitarScore = defineAsyncComponent(
  () => import("./components/GuitarScore.vue"),
);

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
const workMode = ref<WorkMode>("separate");
const singleJob = ref<TranscriptionJob | null>(null);
const songJob = ref<SongTranscriptionJob | null>(null);
const separationJob = ref<SeparationJob | null>(null);
const selectedGuitar = ref<GuitarKey>("lead");
const currentTime = ref(0);
const theme = ref<Theme>(readTheme());
let stopEvents: (() => void) | null = null;
let marketSearchVersion = 0;
let scoreSearchVersion = 0;

function readTheme(): Theme {
  try {
    return localStorage.getItem("fretline-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function applyTheme(value: Theme) {
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme =
    value === "dark" ? "dark" : "light";
  try {
    localStorage.setItem("fretline-theme", value);
  } catch {
    // 浏览器禁用本地存储时仍可正常切换当前页面主题。
  }
  const icon = document.querySelector<HTMLLinkElement>("[data-theme-icon]");
  if (icon) {
    icon.href = value === "dark" ? "/favicon-dark.png" : "/favicon.png";
  }
  const themeColor = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  if (themeColor) {
    themeColor.content = value === "dark" ? "#111813" : "#edf8ff";
  }
}

function toggleTheme() {
  theme.value = theme.value === "dark" ? "light" : "dark";
}

watch(theme, applyTheme, { immediate: true });

function isWorkMode(value: string | null): value is WorkMode {
  return value === "separate" || value === "song" || value === "guitar";
}

function readLastJob(): StoredJob | null {
  try {
    const raw = localStorage.getItem(LAST_JOB_KEY);
    if (!raw) return null;
    const stored = JSON.parse(raw) as Partial<StoredJob>;
    if (
      typeof stored.jobId !== "string"
      || !stored.jobId
      || !isWorkMode(stored.mode ?? null)
    ) {
      return null;
    }
    return { jobId: stored.jobId, mode: stored.mode as WorkMode };
  } catch {
    return null;
  }
}

function writeJobUrl(jobId: string | null, mode?: WorkMode) {
  const url = new URL(window.location.href);
  if (jobId && mode) {
    url.searchParams.set("job", jobId);
    url.searchParams.set("mode", mode);
  } else {
    url.searchParams.delete("job");
    url.searchParams.delete("mode");
  }
  window.history.replaceState({}, "", url);
}

function rememberJob(jobId: string, mode: WorkMode) {
  try {
    localStorage.setItem(
      LAST_JOB_KEY,
      JSON.stringify({ jobId, mode } satisfies StoredJob),
    );
    sessionStorage.removeItem(RESET_MARKER_KEY);
  } catch {
    // 本地存储不可用时仍通过地址栏恢复任务。
  }
  writeJobUrl(jobId, mode);
}

function clearRememberedJob() {
  try {
    localStorage.removeItem(LAST_JOB_KEY);
    sessionStorage.setItem(RESET_MARKER_KEY, "1");
  } catch {
    // 忽略浏览器禁用存储的情况。
  }
  writeJobUrl(null);
}

function resetWasRequested(): boolean {
  try {
    return sessionStorage.getItem(RESET_MARKER_KEY) === "1";
  } catch {
    return false;
  }
}

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

const separationSettings = reactive<{
  model: string;
  removeStems: string[];
  quality: SeparationQuality;
}>({
  model: "htdemucs",
  removeStems: ["vocals"],
  quality: "balanced",
});
const marketQuery = reactive({
  title: "",
  artist: "",
});
const marketSearch = ref<MarketSearchResponse | null>(null);
const marketSearching = ref(false);
const marketSearchError = ref("");
const lookupTab = ref<"market" | "scores">("market");
const scoreSearch = ref<ScoreSearchResponse | null>(null);
const scoreSearching = ref(false);
const scoreSearchError = ref("");

const activeJob = computed(() => {
  if (workMode.value === "separate") return separationJob.value;
  if (workMode.value === "song") return songJob.value;
  return singleJob.value;
});
const singleResult = computed(() => singleJob.value?.result ?? null);
const songResult = computed(() => songJob.value?.result ?? null);
const separationResult = computed(() => separationJob.value?.result ?? null);
const hasResult = computed(() =>
  Boolean(singleResult.value || songResult.value || separationResult.value),
);
const isWorking = computed(
  () =>
    submitting.value ||
    activeJob.value?.status === "queued" ||
    activeJob.value?.status === "running",
);
const cloudReady = computed(() => Boolean(health.value?.cloud_separation_ready));
const localSeparationReady = computed(() =>
  Boolean(health.value?.local_separation_ready),
);
const separationModels = computed<SeparationModel[]>(
  () => health.value?.separation_models ?? [],
);
const selectedSeparationModel = computed(
  () =>
    separationModels.value.find(
      (model) => model.key === separationSettings.model,
    ) ?? separationModels.value[0] ?? null,
);
const availableSeparationStems = computed(
  () => selectedSeparationModel.value?.stems ?? [],
);
const startDisabled = computed(
  () => {
    if (!selectedFile.value || isWorking.value) return true;
    if (workMode.value === "separate") return !localSeparationReady.value;
    if (!health.value?.transcription_ready) return true;
    return workMode.value === "song" && !cloudReady.value;
  },
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
  await restoreCurrentJob();
});

onBeforeUnmount(() => {
  stopEvents?.();
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
});

watch(selectedGuitar, () => {
  currentTime.value = 0;
});

watch(
  availableSeparationStems,
  (stems) => {
    const validKeys = new Set(stems.map((stem) => stem.key));
    separationSettings.removeStems = separationSettings.removeStems.filter(
      (key) => validKeys.has(key),
    );
    if (separationSettings.removeStems.length === 0 && stems.length > 0) {
      separationSettings.removeStems = [
        stems.find((stem) => stem.key === "vocals")?.key ?? stems[0].key,
      ];
    }
  },
  { immediate: true },
);

async function refreshHealth() {
  try {
    health.value = await fetchHealth();
    if (workMode.value === "separate" && !health.value.local_separation_ready) {
      errorMessage.value =
        "本地分离引擎未就绪，请安装后端 Demucs 与 ffmpeg。";
    } else if (
      workMode.value !== "separate" &&
      !health.value.transcription_ready
    ) {
      errorMessage.value = "转录引擎未就绪，请检查 Python 3.11 后端环境。";
    } else {
      errorMessage.value = "";
    }
  } catch {
    errorMessage.value = "无法连接扒谱服务，请先启动 FastAPI 后端。";
  }
}

async function restoreJob(jobId: string, mode: WorkMode) {
  stopEvents?.();
  stopEvents = null;
  workMode.value = mode;
  singleJob.value = null;
  songJob.value = null;
  separationJob.value = null;
  currentTime.value = 0;
  errorMessage.value = "";

  if (mode === "song") {
    const job = await fetchSongJob(jobId);
    songJob.value = job;
    if (job.status === "queued" || job.status === "running") {
      watchSongJob(jobId);
    } else if (job.status === "failed") {
      errorMessage.value = job.error ?? "整曲任务失败";
    }
  } else if (mode === "separate") {
    const job = await fetchSeparationJob(jobId);
    separationJob.value = job;
    if (job.status === "queued" || job.status === "running") {
      watchSeparationJob(jobId);
    } else if (job.status === "failed") {
      errorMessage.value = job.error ?? "音轨分离失败";
    }
  } else {
    const job = await fetchTranscriptionJob(jobId);
    singleJob.value = job;
    if (job.status === "queued" || job.status === "running") {
      watchSingleJob(jobId);
    } else if (job.status === "failed") {
      errorMessage.value = job.error ?? "扒谱任务失败";
    }
  }
  rememberJob(jobId, mode);
}

async function restoreCurrentJob() {
  const params = new URLSearchParams(window.location.search);
  const urlJobId = params.get("job");
  const urlMode = params.get("mode");
  if (urlJobId && isWorkMode(urlMode)) {
    try {
      sessionStorage.removeItem(RESET_MARKER_KEY);
    } catch {
      // 忽略浏览器禁用存储的情况。
    }
  }

  const stored = readLastJob();
  const candidates: StoredJob[] = [];
  if (urlJobId && isWorkMode(urlMode)) {
    candidates.push({ jobId: urlJobId, mode: urlMode });
  }
  if (
    stored
    && !candidates.some((candidate) => candidate.jobId === stored.jobId)
  ) {
    candidates.push(stored);
  }

  let lastError: unknown = null;
  for (const candidate of candidates) {
    try {
      await restoreJob(candidate.jobId, candidate.mode);
      return;
    } catch (error) {
      lastError = error;
      try {
        localStorage.removeItem(LAST_JOB_KEY);
      } catch {
        // 忽略浏览器禁用存储的情况。
      }
    }
  }

  if (!resetWasRequested()) {
    try {
      const recent = await fetchRecentJobs(1);
      const latest = recent.jobs[0];
      if (latest) {
        await restoreJob(latest.id, latest.mode);
        return;
      }
    } catch (error) {
      lastError = error;
    }
  }

  if (lastError) {
    errorMessage.value =
      lastError instanceof Error ? lastError.message : "无法恢复任务结果";
  }
}

function setMode(mode: WorkMode) {
  if (isWorking.value || workMode.value === mode) return;
  workMode.value = mode;
  singleJob.value = null;
  songJob.value = null;
  separationJob.value = null;
  currentTime.value = 0;
  errorMessage.value = "";
  if (mode === "separate" && !localSeparationReady.value) {
    errorMessage.value =
      "本地分离引擎未就绪，请安装后端 Demucs 与 ffmpeg。";
  } else if (mode !== "separate" && !health.value?.transcription_ready) {
    errorMessage.value = "转录引擎未就绪，请检查 Python 3.11 后端环境。";
  }
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
  separationJob.value = null;
  marketQuery.title = titleFromFilename(file.name);
  marketQuery.artist = "";
  searchAllLookups();
  currentTime.value = 0;
  if (workMode.value !== "song") errorMessage.value = "";
}

function watchSongJob(jobId: string) {
  stopEvents = subscribeToSongJob(
    jobId,
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
}

function watchSeparationJob(jobId: string) {
  stopEvents = subscribeToSeparationJob(
    jobId,
    (job) => {
      separationJob.value = job;
      submitting.value = false;
      if (job.status === "failed") {
        errorMessage.value = job.error ?? "音轨分离失败";
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

function watchSingleJob(jobId: string) {
  stopEvents = subscribeToJob(
    jobId,
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

function searchAllLookups() {
  void searchForAccompaniment();
  void searchForScores();
}

function titleFromFilename(filename: string): string {
  return filename
    .replace(/\.[^.]+$/, "")
    .replace(/[_]+/g, " ")
    .replace(
      /[\[(](official|lyrics?|audio|video|mv|hq|hd|live|伴奏|纯音乐)[^\])]*[\])]/gi,
      " ",
    )
    .replace(/\s+/g, " ")
    .trim();
}

async function searchForAccompaniment() {
  const title = marketQuery.title.trim();
  if (!title) return;
  const requestVersion = ++marketSearchVersion;
  marketSearching.value = true;
  marketSearch.value = null;
  marketSearchError.value = "";
  try {
    const response = await searchMarketAvailability({
      title,
      artist: marketQuery.artist.trim(),
      removeStems:
        workMode.value === "separate"
          ? separationSettings.removeStems
          : [],
    });
    if (requestVersion === marketSearchVersion) {
      marketSearch.value = response;
    }
  } catch (error) {
    if (requestVersion === marketSearchVersion) {
      marketSearch.value = null;
      marketSearchError.value =
        error instanceof Error ? error.message : "联网伴奏查询失败";
    }
  } finally {
    if (requestVersion === marketSearchVersion) {
      marketSearching.value = false;
    }
  }
}

async function searchForScores() {
  const title = marketQuery.title.trim();
  if (!title) return;
  const requestVersion = ++scoreSearchVersion;
  scoreSearching.value = true;
  scoreSearch.value = null;
  scoreSearchError.value = "";
  try {
    const response = await searchAvailableScores({
      title,
      artist: marketQuery.artist.trim(),
    });
    if (requestVersion === scoreSearchVersion) {
      scoreSearch.value = response;
    }
  } catch (error) {
    if (requestVersion === scoreSearchVersion) {
      scoreSearch.value = null;
      scoreSearchError.value =
        error instanceof Error ? error.message : "联网曲谱查询失败";
    }
  } finally {
    if (requestVersion === scoreSearchVersion) {
      scoreSearching.value = false;
    }
  }
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
    if (workMode.value === "separate") {
      const created = await createSeparation(selectedFile.value, {
        model: selectedSeparationModel.value?.key ?? separationSettings.model,
        remove_stems: separationSettings.removeStems,
        quality: separationSettings.quality,
      });
      rememberJob(created.job_id, "separate");
      watchSeparationJob(created.job_id);
    } else if (workMode.value === "song") {
      const created = await createSongTranscription(selectedFile.value, options);
      rememberJob(created.job_id, "song");
      watchSongJob(created.job_id);
    } else {
      const created = await createTranscription(selectedFile.value, options);
      rememberJob(created.job_id, "guitar");
      watchSingleJob(created.job_id);
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "提交任务失败";
    submitting.value = false;
  }
}

async function retryCurrentSongJob() {
  if (!songJob.value || songJob.value.status !== "failed") return;
  errorMessage.value = "";
  submitting.value = true;
  stopEvents?.();
  stopEvents = null;
  try {
    const created = await retrySongTranscription(songJob.value.id);
    rememberJob(created.job_id, "song");
    watchSongJob(created.job_id);
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "重试任务失败";
    submitting.value = false;
  }
}

function reset() {
  stopEvents?.();
  stopEvents = null;
  singleJob.value = null;
  songJob.value = null;
  separationJob.value = null;
  currentTime.value = 0;
  errorMessage.value = "";
  clearRememberedJob();
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
        <img
          class="brand-mark"
          :src="
            theme === 'dark'
              ? '/brand-icon-dark.png'
              : '/brand-icon.png'
          "
          alt=""
          width="56"
          height="56"
        />
        <span>
          <strong>Fretline</strong>
          <small>扒谱与器乐分离工作台</small>
        </span>
      </a>
      <div class="header-actions">
        <button
          type="button"
          class="theme-toggle"
          :aria-label="theme === 'dark' ? '切换到浅色模式' : '切换到深夜模式'"
          :title="theme === 'dark' ? '切换到浅色模式' : '切换到深夜模式'"
          @click="toggleTheme"
        >
          <span class="theme-toggle-icon" aria-hidden="true">
            {{ theme === "dark" ? "☀" : "☾" }}
          </span>
          <span>{{ theme === "dark" ? "浅色模式" : "深夜模式" }}</span>
        </button>
        <div
          class="system-state"
          :class="{
            offline:
              workMode === 'separate'
                ? !localSeparationReady
                : !health?.transcription_ready,
          }"
        >
          <span class="state-dot" />
          <template v-if="workMode === 'separate'">
            {{ localSeparationReady ? "本地分离引擎就绪" : "本地分离引擎未就绪" }}
            <span v-if="health?.separation_device" class="state-separator">/</span>
            {{ health?.separation_device?.toUpperCase() }}
          </template>
          <template v-else-if="health?.transcription_ready">
            扒谱引擎就绪
            <span class="state-separator">/</span>
            {{ cloudReady ? "双吉他云端可用" : "本地模式" }}
          </template>
          <template v-else>扒谱引擎未就绪</template>
        </div>
      </div>
    </header>

    <main>
      <section v-if="!hasResult" class="hero">
        <div class="hero-copy">
          <span class="eyebrow">Separate · remove · transcribe</span>
          <h1 v-if="workMode === 'separate'">
            拆开整首歌，<br /><em>做你需要的伴奏。</em>
          </h1>
          <h1 v-else-if="workMode === 'song'">
            上传整首歌，<br /><em>生成双吉他谱。</em>
          </h1>
          <h1 v-else>
            上传吉他音轨，<br /><em>生成六线谱。</em>
          </h1>
          <p v-if="workMode === 'separate'">
            在本地分离人声、鼓、贝斯、吉他、钢琴和其他乐器。勾选任意乐器，
            自动生成“去掉该乐器”的伴奏，并保留全部独立音轨。
          </p>
          <p v-else-if="workMode === 'song'">
            先由 MVSEP 推断出主音吉他、节奏吉他和伴奏三个声部，再分别在本地识别音高、
            分配琴弦和品丝。每个声部都会得到独立六线谱，模型标签请试听确认。
          </p>
          <p v-else>
            适合已分离的 guitar stem 或独奏录音。系统会识别多音、自动测速，
            并导出六线谱、MIDI 与 MusicXML。
          </p>
          <div class="signal-strip">
            <template v-if="workMode === 'separate'">
              <span>Demucs 本地分离</span>
              <span>4 / 6 轨模型</span>
              <span>指定乐器伴奏</span>
              <span>ZIP 批量导出</span>
            </template>
            <template v-else>
              <span>{{ workMode === "song" ? "Lead / Rhythm 双源分离" : "Basic Pitch 多音识别" }}</span>
              <span>自动测速</span>
              <span>六弦约束</span>
              <span>十六分音符量化</span>
            </template>
          </div>
          <div class="hero-tools">
            <div class="mode-switch" role="tablist" aria-label="输入模式">
              <button
                type="button"
                :class="{ active: workMode === 'separate' }"
                :disabled="isWorking"
                @click="setMode('separate')"
              >
                <span class="mode-index">01</span>
                <span class="mode-copy">
                  <strong>分离与伴奏</strong>
                  <small>本地 Demucs · 不上传</small>
                </span>
                <span class="mode-arrow">→</span>
              </button>
              <button
                type="button"
                :class="{ active: workMode === 'song' }"
                :disabled="isWorking"
                @click="setMode('song')"
              >
                <span class="mode-index">02</span>
                <span class="mode-copy">
                  <strong>整曲双吉他</strong>
                  <small>MVSEP 云端分离 · 音频会上传</small>
                </span>
                <span class="mode-arrow">→</span>
              </button>
              <button
                type="button"
                :class="{ active: workMode === 'guitar' }"
                :disabled="isWorking"
                @click="setMode('guitar')"
              >
                <span class="mode-index">03</span>
                <span class="mode-copy">
                  <strong>单吉他音轨</strong>
                  <small>完全本地 · 已有 stem</small>
                </span>
                <span class="mode-arrow">→</span>
              </button>
            </div>

            <section class="market-card" aria-live="polite">
              <div class="market-heading">
                <div>
                  <span class="eyebrow">Online market check</span>
                  <h2>{{ lookupTab === "market" ? "市面伴奏速查" : "现有曲谱速查" }}</h2>
                </div>
                <span class="market-source">
                  {{ lookupTab === "market" ? "网易云音乐 · 国内" : "弹琴吧 · 国内" }}
                </span>
              </div>
              <div class="lookup-tabs" role="tablist" aria-label="联网速查类型">
                <button
                  type="button"
                  :class="{ active: lookupTab === 'market' }"
                  @click="lookupTab = 'market'"
                >
                  伴奏
                  <span>{{ marketSearch?.suggestions.length ?? 0 }}</span>
                </button>
                <button
                  type="button"
                  :class="{ active: lookupTab === 'scores' }"
                  @click="lookupTab = 'scores'"
                >
                  曲谱
                  <span>{{ scoreSearch?.suggestions.length ?? 0 }}</span>
                </button>
              </div>
              <form class="market-form" @submit.prevent="searchAllLookups">
                <label>
                  <span>歌曲名</span>
                  <input
                    v-model="marketQuery.title"
                    type="text"
                    maxlength="200"
                    placeholder="上传后自动识别文件名"
                  />
                </label>
                <label>
                  <span>艺人（可选）</span>
                  <input
                    v-model="marketQuery.artist"
                    type="text"
                    maxlength="200"
                    placeholder="例如：周杰伦"
                  />
                </label>
                <button
                  type="submit"
                  class="market-search-button"
                  :disabled="marketSearching || scoreSearching || !marketQuery.title.trim()"
                >
                  <span v-if="marketSearching || scoreSearching" class="spinner dark" />
                  {{ marketSearching || scoreSearching ? "查询中" : "联网查询" }}
                </button>
              </form>

              <p class="market-hint">
                {{
                  lookupTab === "market"
                    ? "从网易云音乐搜索伴奏、纯音乐、伴唱和指定乐器去轨版本。"
                    : "优先搜索弹琴吧等中文曲谱，国际谱库作为备用入口。"
                }}
              </p>
              <p
                v-if="lookupTab === 'market' && marketSearchError"
                class="market-error"
              >
                {{ marketSearchError }}
              </p>
              <div
                v-else-if="lookupTab === 'market' && marketSearch?.suggestions.length"
                class="market-results"
              >
                <article
                  v-for="item in marketSearch.suggestions"
                  :key="item.id"
                  class="market-result"
                >
                  <img
                    v-if="item.artwork_url"
                    :src="item.artwork_url"
                    :alt="`${item.album || item.title} 封面`"
                    loading="lazy"
                  />
                  <div class="market-result-copy">
                    <span class="market-kind">{{ item.kind }}</span>
                    <strong>{{ item.title }}</strong>
                    <small>{{ item.artist }}<template v-if="item.album"> · {{ item.album }}</template></small>
                    <audio
                      v-if="item.preview_url"
                      :src="item.preview_url"
                      controls
                      preload="none"
                    />
                  </div>
                  <a
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    查看 ↗
                  </a>
                </article>
              </div>
              <div
                v-else-if="lookupTab === 'market' && marketSearch && !marketSearching"
                class="market-empty"
              >
                暂未找到现成伴奏。可以调整歌曲名或艺人后重新查询，也可以直接使用本地分离生成。
              </div>
              <div
                v-else-if="lookupTab === 'market' && !marketSearching"
                class="market-empty"
              >
                选择歌曲后会自动联网查询；也可先输入歌名。
              </div>

              <p
                v-if="lookupTab === 'scores' && scoreSearchError"
                class="market-error"
              >
                {{ scoreSearchError }}
              </p>
              <div
                v-else-if="lookupTab === 'scores' && scoreSearch?.suggestions.length"
                class="market-results score-results"
              >
                <article
                  v-for="(item, index) in scoreSearch.suggestions"
                  :key="item.id"
                  class="market-result score-result"
                  :class="{ 'best-match': index === 0 }"
                >
                  <span class="score-type">
                    <b>{{ item.type }}</b>
                    <small v-if="index === 0">最相关</small>
                  </span>
                  <div class="market-result-copy">
                    <strong>{{ item.title }}</strong>
                    <small>
                      {{ item.artist }}
                      <template v-if="item.meta"> · {{ item.meta }}</template>
                      <template v-if="item.version"> · 制谱 {{ item.version }}</template>
                      <template v-if="item.rating > 0">
                        · ★ {{ item.rating.toFixed(1) }}
                      </template>
                      <template v-if="item.votes > 0">
                        · {{ item.votes }} 票
                      </template>
                    </small>
                  </div>
                  <a
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开曲谱 ↗
                  </a>
                </article>
              </div>
              <div
                v-else-if="lookupTab === 'scores' && scoreSearch && !scoreSearching"
                class="market-empty"
              >
                暂未找到可直接打开的曲谱。可以使用下方其他谱库继续搜索，或上传音频自动扒谱。
              </div>
              <div
                v-else-if="lookupTab === 'scores' && !scoreSearching"
                class="market-empty"
              >
                选择歌曲后会自动查询现成曲谱；也可先输入歌名。
              </div>

              <div
                v-if="lookupTab === 'scores' && scoreSearch?.libraries.length"
                class="score-libraries"
              >
                <span>其他谱库</span>
                <a
                  v-for="library in scoreSearch.libraries"
                  :key="library.name"
                  :href="library.url"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {{ library.name }} ↗
                </a>
              </div>
            </section>
          </div>
        </div>

        <div class="work-card">
          <div class="card-heading">
            <span>01</span>
            <div>
              <h2>
                {{
                  workMode === "separate"
                    ? "导入要处理的歌曲"
                    : workMode === "song"
                      ? "导入整首歌曲"
                      : "导入吉他音轨"
                }}
              </h2>
              <p>
                {{
                  workMode === "separate"
                    ? "模型首次使用时会自动下载，之后可离线运行"
                    : workMode === "song"
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

          <div v-if="workMode === 'separate' && !localSeparationReady" class="config-notice">
            <span>本地分离未就绪</span>
            <p>
              需要后端安装 Demucs、PyTorch 和 ffmpeg。启动时若缺少模型，
              首次分离会自动下载。
            </p>
            <button type="button" @click="refreshHealth">重新检测</button>
          </div>

          <div v-if="workMode === 'separate'" class="separation-settings">
            <label class="setting wide">
              <span>分离模型</span>
              <select v-model="separationSettings.model" :disabled="isWorking">
                <option
                  v-for="model in separationModels"
                  :key="model.key"
                  :value="model.key"
                >
                  {{ model.label }} · {{ model.memory_hint }}
                </option>
              </select>
              <small class="setting-help">
                {{ selectedSeparationModel?.description }}
              </small>
            </label>

            <div class="setting wide">
              <span>要移除并生成对应伴奏的乐器</span>
              <div class="stem-picker">
                <label
                  v-for="stem in availableSeparationStems"
                  :key="stem.key"
                  class="stem-option"
                  :class="{ active: separationSettings.removeStems.includes(stem.key) }"
                >
                  <input
                    v-model="separationSettings.removeStems"
                    type="checkbox"
                    :value="stem.key"
                    :disabled="isWorking"
                  />
                  <strong>{{ stem.label }}</strong>
                  <small>生成去{{ stem.label }}伴奏</small>
                </label>
              </div>
              <small class="setting-help">
                每勾选一项会额外生成一个伴奏文件；独立音轨始终全部保留。
              </small>
            </div>

            <label class="setting wide">
              <span>处理质量</span>
              <select v-model="separationSettings.quality" :disabled="isWorking">
                <option value="fast">快速 · CPU 最省时间</option>
                <option value="balanced">均衡 · 推荐</option>
                <option value="best">高质量 · 最慢</option>
              </select>
            </label>
          </div>

          <div v-else class="settings-grid">
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
                  :style="{
                    '--range-progress': `${((settings.minDuration - 0.04) / 0.26) * 100}%`,
                  }"
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
                  :style="{
                    '--range-progress': `${((settings.minVelocity - 0.1) / 0.6) * 100}%`,
                  }"
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
                ? workMode === "separate"
                  ? "正在分离并生成伴奏…"
                  : workMode === "song"
                  ? "正在分离并扒谱…"
                  : "正在扒谱…"
                : workMode === "separate"
                  ? "开始分离并生成伴奏"
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
          <button
            v-if="workMode === 'song' && songJob?.status === 'failed'"
            type="button"
            class="retry-button"
            :disabled="submitting"
            @click="retryCurrentSongJob"
          >
            ↻ 重试当前任务（复用已下载音轨）
          </button>
        </div>
      </section>

      <section
        v-else-if="separationResult && separationJob"
        class="result-view"
      >
        <div class="result-heading">
          <div>
            <span class="eyebrow">Separation & accompaniment complete</span>
            <h1>{{ separationResult.title }}</h1>
            <p>
              {{ separationResult.stems.length }} 条独立音轨 ·
              {{ separationResult.accompaniments.length }} 个指定乐器伴奏 ·
              {{ separationResult.model.label }}
            </p>
          </div>
          <div class="result-actions">
            <button type="button" class="ghost-button" @click="reset">
              处理另一首歌
            </button>
            <a
              class="download-chip archive-chip"
              :href="separationArchiveUrl(separationJob.id)"
            >
              ↓ 下载全部音轨 ZIP
            </a>
          </div>
        </div>

        <div class="separation-layout">
          <aside class="playback-card source-summary">
            <span class="eyebrow">Source audio</span>
            <h2>原始歌曲</h2>
            <audio
              :src="separationSourceAudioUrl(separationJob.id)"
              controls
              preload="metadata"
            />
            <dl>
              <div>
                <dt>分离设备</dt>
                <dd>{{ separationResult.device.toUpperCase() }}</dd>
              </div>
              <div>
                <dt>处理质量</dt>
                <dd>
                  {{
                    separationResult.quality === "fast"
                      ? "快速"
                      : separationResult.quality === "best"
                        ? "高质量"
                        : "均衡"
                  }}
                </dd>
              </div>
              <div>
                <dt>音频时长</dt>
                <dd>
                  {{
                    separationResult.duration_seconds
                      ? `${Math.floor(separationResult.duration_seconds / 60)}:${String(
                          Math.round(separationResult.duration_seconds % 60),
                        ).padStart(2, "0")}`
                      : "未知"
                  }}
                </dd>
              </div>
            </dl>
            <div v-if="separationResult.warnings.length" class="warning-box">
              <strong>需要复核</strong>
              <p
                v-for="warning in separationResult.warnings"
                :key="warning"
              >
                {{ warning }}
              </p>
            </div>
          </aside>

          <div class="track-workspace">
            <section class="track-section">
              <div class="track-section-heading">
                <div>
                  <span class="eyebrow">Isolated stems</span>
                  <h2>独立乐器音轨</h2>
                </div>
                <span>{{ separationResult.stems.length }} 条</span>
              </div>
              <div class="track-grid">
                <article
                  v-for="stem in separationResult.stems"
                  :key="stem.key"
                  class="track-card"
                >
                  <div class="track-card-heading">
                    <span class="track-badge">{{ stem.key.toUpperCase() }}</span>
                    <strong>{{ stem.label }}</strong>
                    <small>{{ stem.audio_format.toUpperCase() }}</small>
                  </div>
                  <audio
                    :src="separationAudioUrl(separationJob.id, 'stem', stem.key)"
                    controls
                    preload="none"
                  />
                  <a
                    class="track-download"
                    :href="separationAudioUrl(separationJob.id, 'stem', stem.key)"
                    :download="stem.filename"
                  >
                    ↓ 下载{{ stem.label }}音轨
                  </a>
                </article>
              </div>
            </section>

            <section class="track-section accompaniment-section">
              <div class="track-section-heading">
                <div>
                  <span class="eyebrow">Custom accompaniment</span>
                  <h2>去掉指定乐器的伴奏</h2>
                </div>
                <span>{{ separationResult.accompaniments.length }} 个</span>
              </div>
              <div
                v-if="separationResult.accompaniments.length"
                class="track-grid"
              >
                <article
                  v-for="track in separationResult.accompaniments"
                  :key="track.key"
                  class="track-card accompaniment-card"
                >
                  <div class="track-card-heading">
                    <span class="track-badge">MINUS {{ track.removed_stem.toUpperCase() }}</span>
                    <strong>{{ track.label }}</strong>
                    <small>{{ track.audio_format.toUpperCase() }}</small>
                  </div>
                  <audio
                    :src="separationAudioUrl(
                      separationJob.id,
                      'accompaniment',
                      track.key,
                    )"
                    controls
                    preload="none"
                  />
                  <a
                    class="track-download"
                    :href="separationAudioUrl(
                      separationJob.id,
                      'accompaniment',
                      track.key,
                    )"
                    :download="track.filename"
                  >
                    ↓ 下载{{ track.label }}
                  </a>
                </article>
              </div>
              <div v-else class="empty-accompaniment">
                未勾选要移除的乐器。返回后重新选择即可生成指定伴奏。
              </div>
            </section>
          </div>
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
              MVSEP 模型判定的主音与节奏吉他 · {{ songResult.bpm.toFixed(1) }} BPM ·
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

        <div v-if="songResult.warnings.length" class="warning-box song-review">
          <strong>主音 / 节奏标签需要试听确认</strong>
          <p v-for="warning in songResult.warnings" :key="warning">
            {{ warning }}
          </p>
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
              {{ part.transcription.note_count }} 个音符 · 模型判定
            </small>
            <small v-else>{{ part.error ?? "生成失败" }}</small>
          </button>
        </div>

        <div v-if="selectedPart?.transcription" class="result-grid">
          <aside class="playback-card">
            <span class="eyebrow">Separated guitar · model-inferred role</span>
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
              <div><dt>声部标签</dt><dd>模型判定，需试听确认</dd></div>
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
      <span>Fretline · local-first separation & transcription</span>
      <span>分离与扒谱结果均为 AI 初稿，发布或演出前请人工复核。</span>
    </footer>
  </div>
</template>
