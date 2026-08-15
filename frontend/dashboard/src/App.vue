<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { fetchAgents } from "./api.js";
import AgentCard from "./AgentCard.vue";
import AssignmentForm from "./AssignmentForm.vue";

const REFRESH_INTERVAL_MS = 5000;

const activeTab = ref("agents");

const agents = ref([]);
const lastRefreshedAt = ref(null);
const error = ref(null);
const loading = ref(true);

let timerId = null;

async function refresh() {
  try {
    const result = await fetchAgents();
    agents.value = [...result.agents].sort((a, b) => a.capability.localeCompare(b.capability));
    lastRefreshedAt.value = new Date();
    error.value = null;
  } catch (cause) {
    // Keep showing the last known-good list on a transient failure --
    // an empty dashboard would be a worse signal than a stale one, and
    // the banner already makes the staleness visible.
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

const summary = computed(() => {
  const total = agents.value.length;
  const online = agents.value.filter((agent) => agent.status === "READY" && agent.fresh).length;
  return { total, online };
});

onMounted(() => {
  refresh();
  timerId = setInterval(refresh, REFRESH_INTERVAL_MS);
});

onUnmounted(() => {
  if (timerId !== null) clearInterval(timerId);
});
</script>

<template>
  <main>
    <header class="page-header">
      <div>
        <h1>Agent Status</h1>
        <p class="subtitle">Live from the Capability Registry</p>
      </div>
      <div class="header-meta">
        <span class="summary-pill">{{ summary.online }} / {{ summary.total }} online</span>
        <span v-if="lastRefreshedAt" class="last-refreshed">
          Updated {{ lastRefreshedAt.toLocaleTimeString() }}
        </span>
        <button type="button" class="refresh-button" @click="refresh">Refresh now</button>
      </div>
    </header>

    <nav class="tab-nav">
      <button
        type="button"
        class="tab-button"
        :class="{ 'tab-button--active': activeTab === 'agents' }"
        @click="activeTab = 'agents'"
      >
        Agents
      </button>
      <button
        type="button"
        class="tab-button"
        :class="{ 'tab-button--active': activeTab === 'assignment' }"
        @click="activeTab = 'assignment'"
      >
        Submit assignment
      </button>
    </nav>

    <template v-if="activeTab === 'agents'">
      <p v-if="error" class="error-banner">
        Could not reach the platform ({{ error }}) — showing the last known status.
      </p>

      <p v-if="loading && agents.length === 0" class="empty-state">Loading agent status…</p>
      <p v-else-if="!loading && agents.length === 0 && !error" class="empty-state">
        No Agent bindings are declared in the Capability Registry yet.
      </p>

      <div v-else class="agent-grid">
        <AgentCard v-for="agent in agents" :key="`${agent.agent_id}:${agent.capability}`" :agent="agent" />
      </div>
    </template>

    <AssignmentForm v-else />
  </main>
</template>

<style scoped>
main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
}

.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

h1 {
  font-size: 1.75rem;
  margin: 0;
}

.subtitle {
  margin: 0.25rem 0 0;
  color: var(--muted-text);
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.summary-pill {
  font-weight: 600;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: var(--pill-background);
}

.last-refreshed {
  color: var(--muted-text);
  font-size: 0.9rem;
}

.refresh-button {
  border: 1px solid var(--border-color);
  background: var(--surface);
  color: inherit;
  border-radius: 6px;
  padding: 0.4rem 0.9rem;
  cursor: pointer;
  font-size: 0.9rem;
}

.refresh-button:hover {
  background: var(--surface-hover);
}

.tab-nav {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-color);
}

.tab-button {
  border: none;
  background: none;
  color: var(--muted-text);
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  font-size: 0.95rem;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-button:hover {
  color: inherit;
}

.tab-button--active {
  color: inherit;
  font-weight: 600;
  border-bottom-color: var(--text);
}

.error-banner {
  background: var(--error-background);
  color: var(--error-text);
  border: 1px solid var(--error-border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
}

.empty-state {
  color: var(--muted-text);
  padding: 2rem 0;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}
</style>
