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

const STATE_TAG_TYPES = {
  COMPLETED: "success",
  DISPATCHED: "info",
  RECEIVED: "info",
  PENDING: "info",
  FAILED: "danger",
};

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
      <span class="filter-label">Capability</span>
      <el-select v-model="capability" placeholder="All capabilities" @change="onCapabilityChange">
        <el-option
          v-for="option in CAPABILITY_FILTERS"
          :key="option"
          :label="option || 'All capabilities'"
          :value="option"
        />
      </el-select>
      <el-button @click="load()">Refresh</el-button>
    </div>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      show-icon
      :title="error"
      class="error-banner"
    />
    <el-empty v-if="loading" description="Loading history…" />
    <el-empty v-else-if="!loading && entries.length === 0 && !error" description="No submissions yet." />

    <el-table v-else :data="entries" class="history-table">
      <el-table-column label="Submitted" width="200">
        <template #default="{ row }">
          <span class="mono">{{ new Date(row.submitted_at).toLocaleString() }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="capability" label="Capability" width="180" />
      <el-table-column label="Input">
        <template #default="{ row }">
          <span :title="row.input_text">{{ truncate(row.input_text) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="State" width="140">
        <template #default="{ row }">
          <el-tag :type="STATE_TAG_TYPES[row.state] ?? 'info'">{{ row.state }}</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-button
      v-if="nextBefore"
      class="load-more-button"
      :loading="loadingMore"
      @click="load({ append: true })"
    >
      {{ loadingMore ? "Loading…" : "Load older" }}
    </el-button>
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

.filter-label {
  color: var(--el-text-color-secondary);
  font-size: 0.9rem;
}

.error-banner {
  margin-bottom: 1rem;
}

.load-more-button {
  margin-top: 1rem;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
  white-space: nowrap;
}
</style>
