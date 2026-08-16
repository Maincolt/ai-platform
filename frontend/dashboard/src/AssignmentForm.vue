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

const STATE_TAG_TYPES = {
  COMPLETED: "success",
  DISPATCHED: "info",
  FAILED: "danger",
};

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

    <el-input
      v-model="text"
      type="textarea"
      :rows="6"
      placeholder="e.g. Proposed schema for a new notifications table, plus a weekly usage report..."
      :disabled="submitting"
    />

    <el-button
      type="primary"
      class="submit-button"
      :loading="submitting"
      :disabled="!text.trim()"
      @click="handleSubmit"
    >
      {{ submitting ? "Routing…" : "Submit assignment" }}
    </el-button>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      show-icon
      :title="error"
      class="error-banner"
    />

    <section v-if="routing" class="routing-result">
      <h2>Routing decision: {{ routing.state }}</h2>
      <el-empty
        v-if="routing.state === 'COMPLETED' && assignments.length === 0"
        description="No capability was recommended for this assignment."
      />
      <p v-else-if="routing.state !== 'COMPLETED'" class="empty-state">
        {{ routing.failure_code }}
      </p>
    </section>

    <el-card v-for="entry in assignments" :key="entry.capability" class="assignment-card">
      <div class="card-top">
        <h3>{{ entry.capability }}</h3>
        <el-tag :type="STATE_TAG_TYPES[entry.state] ?? 'info'">{{ entry.state }}</el-tag>
      </div>
      <p class="rationale">{{ entry.rationale }}</p>
      <pre v-if="entry.outcome?.result" class="result">{{ JSON.stringify(entry.outcome.result, null, 2) }}</pre>
      <p v-else-if="entry.outcome?.failure_code" class="result-failure">
        {{ entry.outcome.failure_code }}
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.assignment-form {
  max-width: 900px;
}

.intro {
  color: var(--el-text-color-secondary);
  margin: 0 0 1rem;
}

.submit-button {
  margin-top: 0.75rem;
}

.error-banner {
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
  color: var(--el-text-color-secondary);
}

.assignment-card {
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

.rationale {
  color: var(--el-text-color-secondary);
  margin: 0.6rem 0;
}

.result {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 0.75rem;
  overflow-x: auto;
  font-size: 0.85rem;
  margin: 0;
}

.result-failure {
  color: var(--el-color-danger);
  margin: 0;
}
</style>
