<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { fetchAutonomousStatus } from "./api.js";

// This data changes on an hourly cadence (each autonomous role's own
// PeriodicService cycle), not worth polling as aggressively as the
// Agent Status grid's 5s interval.
const REFRESH_INTERVAL_MS = 15000;

// The currently-deployed daily caps (infrastructure/compose/docker-compose.yml's
// AI_PLATFORM_AGENT_AUTONOMOUS_MAX_ACTIONS_PER_DAY/_SPEND_CENTS_PER_DAY,
// identical for all six roles -- ADR-0030/ADR-0031/ADR-0033/ADR-0034's
// explicit choice to reuse ADR-0028's proven defaults). A dashboard
// display convenience, not an enforcement mechanism -- keep in sync by
// hand if the deployed caps ever change.
const MAX_ACTIONS_PER_DAY = 10;
const MAX_SPEND_CENTS_PER_DAY = 100;

const KNOWN_ROLES = [
  {
    key: "scrum-master",
    label: "Scrum Master",
    description:
      "Manages the sprint board: moves cards, comments, closes/relabels/reassigns issues, creates draft items.",
  },
  {
    key: "product-owner",
    label: "Product Owner",
    description:
      "Manages the backlog: creates/edits/closes tickets, archives drafts, reprioritizes, adjusts sprint scope.",
  },
  {
    key: "principal-developer",
    label: "Principal Developer",
    description:
      "Reviews and merges pull requests once required checks pass -- the only role with merge rights.",
  },
  {
    key: "frontend-specialist",
    label: "Frontend Specialist",
    description:
      "Reviews pull requests touching frontend/ (Vue.js). Review-only -- structurally unable to merge.",
  },
  {
    key: "postgres-specialist",
    label: "Postgres Specialist",
    description:
      "Reviews pull requests touching migrations and the persistence layer. Review-only -- structurally unable to merge.",
  },
  {
    key: "backend-specialist",
    label: "Backend Specialist",
    description:
      "Reviews pull requests touching the Python backend (src/ai_platform/). Review-only -- structurally unable to merge.",
  },
  {
    key: "crypto-market",
    label: "Crypto Market",
    description:
      "Watches a cryptocurrency watchlist and records advisory findings. Read-only -- no external write action of any kind.",
  },
  {
    key: "forex-market",
    label: "Forex Market",
    description:
      "Watches a foreign-exchange watchlist and records advisory findings. Read-only -- no external write action of any kind.",
  },
];

const status = ref(null);
const loading = ref(true);
const error = ref(null);

let timerId = null;

async function refresh() {
  try {
    status.value = await fetchAutonomousStatus();
    error.value = null;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

const roleCards = computed(() => {
  const budgetsByRole = new Map((status.value?.role_budgets ?? []).map((b) => [b.role, b]));
  return KNOWN_ROLES.map((role) => {
    const budget = budgetsByRole.get(role.key) ?? { actions_used: 0, spend_cents_used: 0 };
    return {
      ...role,
      actionsUsed: budget.actions_used,
      spendCentsUsed: budget.spend_cents_used,
      actionsPercent: Math.min(100, Math.round((budget.actions_used / MAX_ACTIONS_PER_DAY) * 100)),
      spendPercent: Math.min(
        100,
        Math.round((budget.spend_cents_used / MAX_SPEND_CENTS_PER_DAY) * 100),
      ),
    };
  });
});

const recentActions = computed(() => status.value?.recent_actions ?? []);

onMounted(() => {
  refresh();
  timerId = setInterval(refresh, REFRESH_INTERVAL_MS);
});

onUnmounted(() => {
  if (timerId !== null) clearInterval(timerId);
});
</script>

<template>
  <div class="autonomous-panel">
    <p class="intro">
      Status for the ADR-0026 autonomous roles (ADR-0028/ADR-0030/ADR-0031/ADR-0033/ADR-0034) -- each wakes up
      hourly and takes real write actions with no per-action human approval, bounded by a
      platform-wide kill switch, a daily action/spend cap per role, and a durable audit trail.
      These roles hold no Capability Registry binding, so they never appear in the Agents tab.
    </p>

    <el-alert
      v-if="error"
      type="warning"
      :closable="false"
      show-icon
      :title="`Could not reach the platform (${error}) — showing the last known status.`"
      class="error-banner"
    />

    <el-empty v-if="loading && !status" description="Loading autonomous agent status…" />

    <template v-else-if="status">
      <el-alert
        v-if="status.kill_switch_engaged"
        type="error"
        show-icon
        :closable="false"
        title="Kill switch engaged — all autonomous action-taking is halted"
        class="kill-switch-banner"
      />
      <el-alert
        v-else
        type="success"
        show-icon
        :closable="false"
        title="Kill switch disengaged — all autonomous roles active"
        class="kill-switch-banner"
      />

      <div class="role-grid">
        <el-card v-for="role in roleCards" :key="role.key" class="role-card">
          <h3>{{ role.label }}</h3>
          <p class="role-description">{{ role.description }}</p>
          <div class="progress-row">
            <span class="progress-label">
              Actions today: {{ role.actionsUsed }} / {{ MAX_ACTIONS_PER_DAY }}
            </span>
            <el-progress :percentage="role.actionsPercent" :show-text="false" />
          </div>
          <div class="progress-row">
            <span class="progress-label">
              Spend today: {{ role.spendCentsUsed }}¢ / {{ MAX_SPEND_CENTS_PER_DAY }}¢
            </span>
            <el-progress :percentage="role.spendPercent" :show-text="false" color="#e6a23c" />
          </div>
        </el-card>
      </div>

      <h2 class="recent-heading">Recent actions</h2>
      <el-empty v-if="recentActions.length === 0" description="No autonomous actions recorded yet." />
      <el-table v-else :data="recentActions" class="actions-table">
        <el-table-column label="Occurred" width="200">
          <template #default="{ row }">
            <span class="mono">{{ new Date(row.occurred_at).toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="role" label="Role" width="160" />
        <el-table-column prop="action_type" label="Action" width="160" />
        <el-table-column prop="target" label="Target" />
        <el-table-column label="Result" width="120">
          <template #default="{ row }">
            <el-tag :type="row.result_status === 'SUCCEEDED' ? 'success' : 'danger'">
              {{ row.result_status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<style scoped>
.autonomous-panel {
  max-width: 1100px;
}

.intro {
  color: var(--el-text-color-secondary);
  margin: 0 0 1rem;
}

.error-banner,
.kill-switch-banner {
  margin-bottom: 1.5rem;
}

.role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.role-card h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}

.role-description {
  margin: 0 0 1rem;
  font-size: 0.85rem;
  color: var(--el-text-color-secondary);
}

.progress-row {
  margin-bottom: 0.75rem;
}

.progress-row:last-child {
  margin-bottom: 0;
}

.progress-label {
  display: block;
  font-size: 0.85rem;
  color: var(--el-text-color-secondary);
  margin-bottom: 0.35rem;
}

.recent-heading {
  font-size: 1.05rem;
  margin: 0 0 1rem;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
  white-space: nowrap;
}
</style>
