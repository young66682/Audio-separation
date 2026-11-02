<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import * as alphaTab from "@coderline/alphatab";

const props = defineProps<{
  url: string;
}>();

const host = ref<HTMLDivElement | null>(null);
const loading = ref(true);
const errorMessage = ref("");
let api: alphaTab.AlphaTabApi | null = null;
let renderTimeout: number | null = null;

onMounted(() => {
  if (!host.value) return;
  api = new alphaTab.AlphaTabApi(host.value, {
    core: {
      file: props.url,
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
      errorMessage.value =
        "乐谱排版超时。可以下载 MusicXML 在 MuseScore 或 Guitar Pro 中打开。";
    }
  }, 15000);
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
        <p>主音吉他与节奏吉他各含五线谱和六线谱，共用小节与节拍。</p>
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
