<script setup>
import { computed } from "vue";

const props = defineProps({
  agent: {
    type: Object,
    required: true,
  },
});

const STATUS_LABELS = {
  READY: "Online",
  STALE: "Stale",
  UNKNOWN: "Unknown",
  UNAVAILABLE: "Unavailable",
  DRAINING: "Draining",
};

// One line per capability explaining what it actually does -- the
// capability name alone (e.g. "technical.review") doesn't say much on
// its own. Static/hand-maintained: add an entry here whenever a new
// capability is registered.
const CAPABILITY_DESCRIPTIONS = {
  "text.summarize": "Summarizes free-text input into a concise digest.",
  "code.review": "Reviews source code diffs for bugs, style, and correctness issues.",
  "ui.review": "Captures a live page with Playwright and reviews it for UI/accessibility issues.",
  "architecture.review": "Reviews architectural or system-design proposals for soundness.",
  "data.analysis": "Analyzes a dataset for trends, correlations, and anomalies.",
  "technical.review": "Reviews technical/API/schema design proposals for issues.",
  "assignment.route": "Routes a free-text assignment to the capability(ies) best suited to review it.",
  "security.review": "Reviews code for security vulnerabilities (injection, auth gaps, secrets, etc.).",
  "scrum.status": "Fetches the live GitHub Projects v2 board and reports its status.",
  "text.word-count": "Counts words in the input text (the platform's built-in test capability).",
};

const statusLabel = computed(() => STATUS_LABELS[props.agent.status] ?? props.agent.status);

const capabilityDescription = computed(
  () => CAPABILITY_DESCRIPTIONS[props.agent.capability] ?? null,
);

const statusTagType = computed(() => {
  if (props.agent.status === "READY" && props.agent.fresh) return "success";
  if (props.agent.status === "STALE") return "warning";
  if (props.agent.status === "UNAVAILABLE" || props.agent.status === "DRAINING") return "danger";
  return "info";
});

const lastObservedLabel = computed(() => {
  if (!props.agent.last_observed_at) return "Never observed";
  return new Date(props.agent.last_observed_at).toLocaleString();
});

const isBusy = computed(() => (props.agent.in_flight_count ?? 0) > 0);

const busyLabel = computed(() => {
  const count = props.agent.in_flight_count ?? 0;
  return count === 1 ? "Busy · 1 in flight" : `Busy · ${count} in flight`;
});

const shortAgentId = computed(() => {
  const id = props.agent.agent_id;
  return id.length > 13 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
});
</script>

<template>
  <el-card class="agent-card" :class="{ 'agent-card--disabled': !agent.enabled }" shadow="hover">
    <div class="card-top">
      <h2 class="capability">{{ agent.capability }}</h2>
      <el-tag :type="statusTagType" round>{{ statusLabel }}</el-tag>
    </div>

    <p v-if="capabilityDescription" class="description">{{ capabilityDescription }}</p>

    <el-tag v-if="isBusy" type="primary" size="small" class="busy-tag">{{ busyLabel }}</el-tag>

    <el-descriptions :column="1" size="small" border class="details">
      <el-descriptions-item label="Implementation">
        {{ agent.implementation_identity }}
      </el-descriptions-item>
      <el-descriptions-item label="Version">{{ agent.capability_version }}</el-descriptions-item>
      <el-descriptions-item label="Agent ID">
        <span :title="agent.agent_id" class="mono">{{ shortAgentId }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="Environment">{{ agent.environment }}</el-descriptions-item>
      <el-descriptions-item label="Last observed">{{ lastObservedLabel }}</el-descriptions-item>
    </el-descriptions>

    <p v-if="!agent.enabled" class="disabled-note">Disabled in the Capability Registry</p>
  </el-card>
</template>

<style scoped>
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.agent-card--disabled {
  opacity: 0.6;
}

.card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.capability {
  font-size: 1.05rem;
  margin: 0;
  word-break: break-word;
}

.description {
  margin: 0;
  font-size: 0.85rem;
  color: var(--el-text-color-secondary);
}

.busy-tag {
  align-self: flex-start;
}

.details {
  margin-top: 0.25rem;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
}

.disabled-note {
  margin: 0;
  font-size: 0.8rem;
  color: var(--el-text-color-secondary);
  font-style: italic;
}
</style>
