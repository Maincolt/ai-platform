<script setup>
import { ref } from "vue";
import { pollWorkflowToTerminal, submitWorkflow } from "./api.js";

const ROUTE_CAPABILITY = "assignment.route";

const text = ref("");
const submitting = ref(false);
const error = ref(null);

// One entry per stage of the team-dispatch flow (ADR-0023 Decision 5):
// the routing decision itself, then one entry per recommended capability
// as its own workflow resolves. Mirrors submit-assignment.py's sequence,
// just rendered incrementally instead of printed at the end.
const routing = ref(null);
const assignments = ref([]);

function resetResults() {
  error.value = null;
  routing.value = null;
  assignments.value = [];
}

async function handleSubmit() {
  if (!text.value.trim() || submitting.value) return;
  resetResults();
  submitting.value = true;
  try {
    const submitted = await submitWorkflow(text.value, ROUTE_CAPABILITY);
    const routeOutcome = await pollWorkflowToTerminal(submitted.workflow_id);
    routing.value = routeOutcome;

    if (routeOutcome.state !== "COMPLETED") {
      return;
    }
    const recommendations = routeOutcome.result?.assignments ?? [];
    assignments.value = recommendations.map((recommendation) => ({
      capability: recommendation.capability,
      rationale: recommendation.rationale,
      state: "DISPATCHED",
      outcome: null,
    }));

    // Fan out in parallel, same as submit-assignment.py; each entry
    // updates independently as its own workflow resolves rather than
    // waiting for the slowest one before showing anything.
    await Promise.all(
      assignments.value.map(async (entry) => {
        try {
          const submittedEntry = await submitWorkflow(text.value, entry.capability);
          const outcome = await pollWorkflowToTerminal(submittedEntry.workflow_id);
          entry.state = outcome.state;
          entry.outcome = outcome;
        } catch (cause) {
          entry.state = "FAILED";
          entry.outcome = { failure_code: cause instanceof Error ? cause.message : String(cause) };
        }
      }),
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="assignment-form">
    <p class="intro">
      Describe an assignment in free text. The team routes it automatically (ADR-0023): one AI
      call decides which capabilities apply, then each recommended capability reviews the same
      text independently.
    </p>

    <textarea
      v-model="text"
      class="assignment-input"
      rows="6"
      placeholder="e.g. Proposed schema for a new notifications table, plus a weekly usage report..."
      :disabled="submitting"
    />

    <button type="button" class="submit-button" :disabled="submitting || !text.trim()" @click="handleSubmit">
      {{ submitting ? "Routing…" : "Submit assignment" }}
    </button>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <section v-if="routing" class="routing-result">
      <h2>Routing decision: {{ routing.state }}</h2>
      <p v-if="routing.state === 'COMPLETED' && assignments.length === 0" class="empty-state">
        No capability was recommended for this assignment.
      </p>
      <p v-else-if="routing.state !== 'COMPLETED'" class="empty-state">
        {{ routing.failure_code }}
      </p>
    </section>

    <section v-for="entry in assignments" :key="entry.capability" class="assignment-card">
      <div class="card-top">
        <h3>{{ entry.capability }}</h3>
        <span class="state-badge" :class="`state-${entry.state.toLowerCase()}`">{{ entry.state }}</span>
      </div>
      <p class="rationale">{{ entry.rationale }}</p>
      <pre v-if="entry.outcome?.result" class="result">{{ JSON.stringify(entry.outcome.result, null, 2) }}</pre>
      <p v-else-if="entry.outcome?.failure_code" class="result-failure">
        {{ entry.outcome.failure_code }}
      </p>
    </section>
  </div>
</template>

<style scoped>
.assignment-form {
  max-width: 900px;
}

.intro {
  color: var(--muted-text);
  margin: 0 0 1rem;
}

.assignment-input {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--surface);
  color: inherit;
  padding: 0.75rem;
  font-family: inherit;
  font-size: 0.95rem;
  resize: vertical;
}

.submit-button {
  margin-top: 0.75rem;
  border: 1px solid var(--border-color);
  background: var(--surface);
  color: inherit;
  border-radius: 6px;
  padding: 0.5rem 1.1rem;
  cursor: pointer;
  font-size: 0.9rem;
}

.submit-button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.submit-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-banner {
  background: var(--error-background);
  color: var(--error-text);
  border: 1px solid var(--error-border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-top: 1rem;
}

.routing-result {
  margin-top: 1.5rem;
}

.routing-result h2 {
  font-size: 1.05rem;
  margin: 0 0 0.5rem;
}

.empty-state {
  color: var(--muted-text);
}

.assignment-card {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 1rem 1.1rem;
  background: var(--surface);
  margin-top: 1rem;
}

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.card-top h3 {
  margin: 0;
  font-size: 1rem;
}

.state-badge {
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  white-space: nowrap;
}

.state-completed {
  color: var(--status-online-text);
  background: var(--status-online-bg);
}

.state-dispatched {
  color: var(--status-unknown-text);
  background: var(--status-unknown-bg);
}

.state-failed {
  color: var(--status-unavailable-text);
  background: var(--status-unavailable-bg);
}

.rationale {
  color: var(--muted-text);
  margin: 0.6rem 0;
}

.result {
  background: var(--pill-background);
  border-radius: 6px;
  padding: 0.75rem;
  overflow-x: auto;
  font-size: 0.85rem;
  margin: 0;
}

.result-failure {
  color: var(--status-unavailable-text);
  margin: 0;
}
</style>
