<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { fetchAgents } from "./api.js";
import AgentCard from "./AgentCard.vue";
import AssignmentForm from "./AssignmentForm.vue";
import AutonomousAgentsPanel from "./AutonomousAgentsPanel.vue";
import HistoryList from "./HistoryList.vue";

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
  <el-container class="page">
    <el-header class="page-header" height="auto">
      <div>
        <h1>Agent Status</h1>
        <p class="subtitle">Live from the Capability Registry</p>
      </div>
      <div class="header-meta">
        <el-tag type="success" round>{{ summary.online }} / {{ summary.total }} online</el-tag>
        <span v-if="lastRefreshedAt" class="last-refreshed">
          Updated {{ lastRefreshedAt.toLocaleTimeString() }}
        </span>
        <el-button size="small" @click="refresh">Refresh now</el-button>
      </div>
    </el-header>

    <el-main class="page-main">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="Agents" name="agents">
          <el-alert
            v-if="error"
            type="warning"
            :closable="false"
            show-icon
            class="error-banner"
            :title="`Could not reach the platform (${error}) — showing the last known status.`"
          />

          <el-empty v-if="loading && agents.length === 0" description="Loading agent status…" />
          <el-empty
            v-else-if="!loading && agents.length === 0 && !error"
            description="No Agent bindings are declared in the Capability Registry yet."
          />

          <div v-else class="agent-grid">
            <AgentCard
              v-for="agent in agents"
              :key="`${agent.agent_id}:${agent.capability}`"
              :agent="agent"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="Submit assignment" name="assignment" lazy>
          <AssignmentForm />
        </el-tab-pane>

        <el-tab-pane label="History" name="history" lazy>
          <HistoryList />
        </el-tab-pane>

        <el-tab-pane label="Autonomous Agents" name="autonomous" lazy>
          <AutonomousAgentsPanel />
        </el-tab-pane>
      </el-tabs>
    </el-main>
  </el-container>
</template>

<style scoped>
.page {
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
  padding: 0 0 1.5rem;
}

h1 {
  font-size: 1.75rem;
  margin: 0;
}

.subtitle {
  margin: 0.25rem 0 0;
  color: var(--el-text-color-secondary);
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.last-refreshed {
  color: var(--el-text-color-secondary);
  font-size: 0.9rem;
}

.page-main {
  padding: 0;
}

.error-banner {
  margin-bottom: 1.5rem;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}
</style>
