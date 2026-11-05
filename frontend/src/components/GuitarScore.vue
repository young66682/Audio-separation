<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import * as alphaTab from "@coderline/alphatab";

const props = defineProps<{
  url: string;
}>();

const host = ref<HTMLDivElement | null>(null);
const loading = ref(true);
const errorMessage = ref("");
const renderTimeoutMessage =
  "乐谱仍在排版。长谱首次加载可能需要更久，也可以下载 MusicXML 在 MuseScore 或 Guitar Pro 中打开。";
let api: alphaTab.AlphaTabApi | null = null;
let renderTimeout: number | null = null;

function assetUrl(path: string): string {
  return new URL(path, document.baseURI).href;
}

onMounted(() => {
  if (!host.value) return;
  api = new alphaTab.AlphaTabApi(host.value, {
    core: {
      file: props.url,
      // Vite 会把 alphaTab 字体复制到 /font，而生产资源位于 /assets。
      // 不显式指定字体目录会导致乐谱空白和打印乱码。
      fontDirectory: assetUrl("font/"),
      logLevel: alphaTab.LogLevel.Error,
    },
    display: {
      layoutMode: alphaTab.LayoutMode.Page,
      staveProfile: alphaTab.StaveProfile.ScoreTab,
      scale: 0.92,
      stretchForce: 0.9,
    },
    importer: {
      mergePartGroupsInMusicXml: false,
    },
    player: {
      playerMode: alphaTab.PlayerMode.Disabled,
    },
  });

  api.scoreLoaded.on((score) => {
    for (const track of score.tracks) {
      for (const staff of track.staves) {
        staff.showStandardNotation = true;
        staff.showTablature = true;
      }
    }
    if (score.tracks.length > 1) {
      api?.renderTracks(score.tracks);
    }
  });
  api.renderFinished.on(() => {
    loading.value = false;
    if (errorMessage.value === renderTimeoutMessage) {
      errorMessage.value = "";
    }
    if (renderTimeout !== null) {
      window.clearTimeout(renderTimeout);
      renderTimeout = null;
    }
  });
  api.error.on((error) => {
    loading.value = false;
    errorMessage.value = `乐谱渲染失败：${String(error)}`;
  });
  renderTimeout = window.setTimeout(() => {
    if (loading.value) {
      errorMessage.value = renderTimeoutMessage;
    }
  }, 30000);
});

onBeforeUnmount(() => {
  if (renderTimeout !== null) window.clearTimeout(renderTimeout);
  api?.destroy();
  api = null;
});

function printScore() {
  api?.print();
}
</script>

<template>
  <section class="score-panel">
    <div class="score-toolbar">
      <div>
        <span class="eyebrow">Full guitar score</span>
        <h2>双吉他总谱</h2>
        <p>MVSEP 判定的主音与节奏吉他各含五线谱和六线谱，声部标签需试听确认。</p>
      </div>
      <div class="score-actions">
        <span v-if="loading" class="score-loading">正在排版…</span>
        <button type="button" class="ghost-button" @click="printScore">打印 / PDF</button>
        <a class="download-chip" :href="url" download="guitar-score.musicxml">
          ↓ MusicXML
        </a>
      </div>
    </div>
    <div class="alpha-tab-scroll">
      <div ref="host" class="alpha-tab-host" />
    </div>
    <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
  </section>
</template>
