<script setup lang="ts">
import { computed } from "vue";
import type { GuitarEvent } from "../types";

const props = defineProps<{
  events: GuitarEvent[];
  bpm: number;
  tuning: string;
  capo: number;
  currentBeat: number;
}>();

const emit = defineEmits<{
  seek: [seconds: number];
}>();

const subdivisions = 4;
const beatsPerMeasure = 4;
const stepsPerMeasure = subdivisions * beatsPerMeasure;

const totalSteps = computed(() => {
  const lastStep = props.events.reduce(
    (maximum, event) =>
      Math.max(maximum, Math.ceil(event.start_beat * subdivisions)),
    0,
  );
  return Math.max(stepsPerMeasure, Math.ceil((lastStep + 1) / stepsPerMeasure) * stepsPerMeasure);
});

const measures = computed(() =>
  Array.from({ length: totalSteps.value / stepsPerMeasure }, (_, index) => index + 1),
);

const eventLookup = computed(() => {
  const lookup = new Map<string, GuitarEvent>();
  for (const event of props.events) {
    const step = Math.round(event.start_beat * subdivisions);
    lookup.set(`${event.string}:${step}`, event);
  }
  return lookup;
});

const currentStep = computed(() => Math.floor(props.currentBeat * subdivisions));

function eventAt(stringNumber: number, step: number): GuitarEvent | undefined {
  return eventLookup.value.get(`${stringNumber}:${step}`);
}

function seekStep(step: number) {
  emit("seek", (step / subdivisions) * (60 / props.bpm));
}

function isCurrent(step: number): boolean {
  return step === currentStep.value;
}
</script>

<template>
  <section class="tab-panel">
    <div class="tab-toolbar">
      <div>
        <span class="eyebrow">Guitar tablature</span>
        <h2>自动生成的六线谱</h2>
      </div>
      <div class="tab-meta">
        <span>{{ bpm.toFixed(1) }} BPM</span>
        <span>Capo {{ capo }}</span>
        <span>{{ events.length }} notes</span>
      </div>
    </div>

    <div class="tab-scroll">
      <div class="tab-canvas">
        <div
          class="measure-row"
          :style="{ gridTemplateColumns: `32px repeat(${totalSteps}, 31px)` }"
        >
          <span class="string-spacer" />
          <template v-for="measure in measures" :key="measure">
            <span
              v-for="localStep in stepsPerMeasure"
              :key="`${measure}-${localStep}`"
              class="measure-cell"
              :class="{ 'measure-start': localStep === 1 }"
            >
              {{ localStep === 1 ? `${measure}` : "" }}
            </span>
          </template>
        </div>

        <div
          v-for="stringNumber in 6"
          :key="stringNumber"
          class="string-row"
          :style="{ gridTemplateColumns: `32px repeat(${totalSteps}, 31px)` }"
        >
          <span class="string-name">{{ stringNumber }}</span>
          <button
            v-for="step in totalSteps"
            :key="step"
            type="button"
            class="tab-cell"
            :class="{
              'measure-start': step % stepsPerMeasure === 1,
              'has-note': eventAt(stringNumber, step - 1),
              current: isCurrent(step - 1),
            }"
            :title="
              eventAt(stringNumber, step - 1)
                ? `${eventAt(stringNumber, step - 1)?.pitch_name} · ${eventAt(stringNumber, step - 1)?.duration_beats} 拍`
                : '跳转到这一拍'
            "
            @click="seekStep(step - 1)"
          >
            {{ eventAt(stringNumber, step - 1)?.fret ?? "" }}
          </button>
        </div>
      </div>
    </div>

    <div class="tab-footer">
      <span>调弦 {{ tuning }}</span>
      <span>点击格子可跳转试听</span>
    </div>
  </section>
</template>

