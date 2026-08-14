<script setup lang="ts">
import MetricHelpPopover from './MetricHelpPopover.vue'
import type { MetricCard, MetricDefinition } from './monitoring-data'

defineProps<{
  cards: MetricCard[]
  definitions: Record<string, MetricDefinition>
}>()

function toneClass(tone?: string): string {
  return ['good', 'warning', 'danger', 'neutral'].includes(String(tone)) ? String(tone) : 'neutral'
}
</script>

<template>
  <section class="metric-kpi-strip">
    <article v-for="card in cards" :key="card.key" :class="`tone-${toneClass(card.tone)}`">
      <header>
        <span>{{ card.label }}</span>
        <MetricHelpPopover :definition="definitions[card.definition_key || card.key]" :label="card.label" />
      </header>
      <b>{{ card.value }}</b>
      <small>{{ card.helper }}</small>
    </article>
  </section>
</template>
