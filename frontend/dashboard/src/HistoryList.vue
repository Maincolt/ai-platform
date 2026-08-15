<script setup>
import { onMounted, ref } from "vue";
import { fetchWorkflowHistory } from "./api.js";

const CAPABILITY_FILTERS = [
  "",
  "assignment.route",
  "text.summarize",
  "code.review",
  "ui.review",
  "architecture.review",
  "data.analysis",
  "technical.review",
  "text.word-count",
];

const entries = ref([]);
const nextBefore = ref(null);
const capability = ref("");
const loading = ref(false);
const loadingMore = ref(false);
const error = ref(null);

async function load({ append = false } = {}) {
  error.value = null;
  if (append) {
    loadingMore.value = true;
  } else {
    loading.value = true;
  }
  try {
    const page = await fetchWorkflowHistory({
      capability: capability.value || undefined,
      before: append ? nextBefore.value : undefined,
    });
    entries.value = append ? [...entries.value, ...page.entries] : page.entries;
    nextBefore.value = page.next_before ?? null;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

function onCapabilityChange() {
  nextBefore.value = null;
  load();
}

function truncate(text, max = 160) {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

onMounted(() => load());
</script>

<template>
  <div class="history-list">
    <div class="history-controls">
      <label for="capability-filter">Capability</label>
      <select id="capability-filter" v-model="capability" @change="onCapabilityChange">
        <option v-for="option in CAPABILITY_FILTERS" :key="option" :value="option">
          {{ option || "All capabilities" }}
        </option>
      </select>
      <button type="button" class="refresh-button" @click="load()">Refresh</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="loading" class="empty-state">Loading history…</p>
    <p v-else-if="!loading && entries.length === 0 && !error" class="empty-state">
      No submissions yet.
    </p>

    <table v-else class="history-table">
      <thead>
        <tr>
          <th>Submitted</th>
          <th>Capability</th>
          <th>Input</th>
          <th>State</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="entry in entries" :key="entry.workflow_id">
          <td class="mono">{{ new Date(entry.submitted_at).toLocaleString() }}</td>
          <td>{{ entry.capability }}</td>
          <td class="input-cell" :title="entry.input_text">{{ truncate(entry.input_text) }}</td>
          <td>
            <span class="state-badge" :class="`state-${entry.state.toLowerCase()}`">
              {{ entry.state }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <button
      v-if="nextBefore"
      type="button"
      class="load-more-button"
      :disabled="loadingMore"
      @click="load({ append: true })"
    >
      {{ loadingMore ? "Loading…" : "Load older" }}
    </button>
  </div>
</template>

<style scoped>
.history-list {
  max-width: 1100px;
}

.history-controls {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 1rem;
}

.history-controls label {
  color: var(--muted-text);
  font-size: 0.9rem;
}

.history-controls select {
  border: 1px solid var(--border-color);
  background: var(--surface);
  color: inherit;
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  font-size: 0.9rem;
}

.refresh-button,
.load-more-button {
  border: 1px solid var(--border-color);
  background: var(--surface);
  color: inherit;
  border-radius: 6px;
  padding: 0.4rem 0.9rem;
  cursor: pointer;
  font-size: 0.9rem;
}

.refresh-button:hover,
.load-more-button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.load-more-button {
  margin-top: 1rem;
}

.load-more-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-banner {
  background: var(--error-background);
  color: var(--error-text);
  border: 1px solid var(--error-border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.empty-state {
  color: var(--muted-text);
  padding: 2rem 0;
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.history-table th {
  text-align: left;
  color: var(--muted-text);
  font-weight: 600;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.history-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
  vertical-align: top;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
  white-space: nowrap;
}

.input-cell {
  max-width: 420px;
  overflow-wrap: anywhere;
}

.state-badge {
  display: inline-flex;
  align-items: center;
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  white-space: nowrap;
}

.state-completed {
  color: var(--status-online-text);
  background: var(--status-online-bg);
}

.state-dispatched,
.state-received,
.state-pending {
  color: var(--status-unknown-text);
  background: var(--status-unknown-bg);
}

.state-failed {
  color: var(--status-unavailable-text);
  background: var(--status-unavailable-bg);
}
</style>
