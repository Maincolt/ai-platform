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

const statusLabel = computed(() => STATUS_LABELS[props.agent.status] ?? props.agent.status);

const statusClass = computed(() => {
  if (props.agent.status === "READY" && props.agent.fresh) return "status-online";
  if (props.agent.status === "STALE") return "status-stale";
  if (props.agent.status === "UNAVAILABLE" || props.agent.status === "DRAINING") {
    return "status-unavailable";
  }
  return "status-unknown";
});

const lastObservedLabel = computed(() => {
  if (!props.agent.last_observed_at) return "Never observed";
  return new Date(props.agent.last_observed_at).toLocaleString();
});

const shortAgentId = computed(() => {
  const id = props.agent.agent_id;
  return id.length > 13 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
});
</script>

<template>
  <article class="agent-card" :class="{ 'agent-card--disabled': !agent.enabled }">
    <div class="card-top">
      <h2 class="capability">{{ agent.capability }}</h2>
      <span class="status-badge" :class="statusClass">
        <span class="status-dot" />
        {{ statusLabel }}
      </span>
    </div>

    <dl class="details">
      <dt>Implementation</dt>
      <dd>{{ agent.implementation_identity }}</dd>

      <dt>Version</dt>
      <dd>{{ agent.capability_version }}</dd>

      <dt>Agent ID</dt>
      <dd :title="agent.agent_id" class="mono">{{ shortAgentId }}</dd>

      <dt>Environment</dt>
      <dd>{{ agent.environment }}</dd>

      <dt>Last observed</dt>
      <dd>{{ lastObservedLabel }}</dd>
    </dl>

    <p v-if="!agent.enabled" class="disabled-note">Disabled in the Capability Registry</p>
  </article>
</template>

<style scoped>
.agent-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 1rem 1.1rem;
  background: var(--surface);
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

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  white-space: nowrap;
}

.status-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: currentColor;
}

.status-online {
  color: var(--status-online-text);
  background: var(--status-online-bg);
}

.status-stale {
  color: var(--status-stale-text);
  background: var(--status-stale-bg);
}

.status-unavailable {
  color: var(--status-unavailable-text);
  background: var(--status-unavailable-bg);
}

.status-unknown {
  color: var(--status-unknown-text);
  background: var(--status-unknown-bg);
}

.details {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 0.75rem;
  row-gap: 0.35rem;
  margin: 0;
  font-size: 0.9rem;
}

.details dt {
  color: var(--muted-text);
}

.details dd {
  margin: 0;
  text-align: right;
  overflow-wrap: anywhere;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
}

.disabled-note {
  margin: 0;
  font-size: 0.8rem;
  color: var(--muted-text);
  font-style: italic;
}
</style>
