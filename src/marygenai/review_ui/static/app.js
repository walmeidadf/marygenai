const QUEUE_TYPES = {
  legacy_identity_review: "Legacy identity review",
  publication_candidate_review: "Publication candidate review",
};
const FILTER_LABELS = {
  "": "All PubMed candidates",
  "identity_status:needs_manual_identity_review": "Needs manual identity review",
  "identity_status:new_candidate": "New candidates",
  "priority_tier:direct_title_or_indexed": "Direct title or indexed evidence",
  "full_text_review_priority:high_auto_full_text": "High auto full text",
  "full_text_review_priority:high_manual_full_text": "High manual full text",
};
const WORKFLOW_STATUS_LABELS = {
  open: "Open workflow tasks",
  in_review: "In-review workflow tasks",
  resolved: "Workflow-resolved tasks",
  dismissed: "Dismissed workflow tasks",
  all: "All workflow tasks",
};
const state = {
  items: [],
  queues: [],
  selectedQueueType: "legacy_identity_review",
  selectedWorkflowStatus: "open",
  selectedFilter: "",
  selectedReviewItemId: null,
  provenanceByDocumentId: {},
};

const elements = {
  apiStatus: document.querySelector("#api-status"),
  queueSummary: document.querySelector("#queue-summary"),
  queueTabs: document.querySelectorAll("[data-queue-type]"),
  candidateFilters: document.querySelector("#candidate-filters"),
  filterChips: document.querySelectorAll("[data-filter]"),
  workflowStatusChips: document.querySelectorAll("[data-workflow-status]"),
  activeFilterLabel: document.querySelector("#active-filter-label"),
  activeWorkflowStatusLabel: document.querySelector("#active-workflow-status-label"),
  openItemsHeading: document.querySelector("#open-items-heading"),
  reviewList: document.querySelector("#review-list"),
  detailContent: document.querySelector("#detail-content"),
  selectedItemLabel: document.querySelector("#selected-item-label"),
  refreshButton: document.querySelector("#refresh-button"),
};

elements.refreshButton.addEventListener("click", () => loadDashboard());
elements.queueTabs.forEach((button) => {
  button.addEventListener("click", () => {
    state.selectedQueueType = button.dataset.queueType;
    state.selectedFilter = "";
    state.selectedReviewItemId = null;
    renderControls();
    loadDashboard();
  });
});
elements.filterChips.forEach((button) => {
  button.addEventListener("click", () => {
    state.selectedFilter = button.dataset.filter;
    state.selectedReviewItemId = null;
    renderControls();
    loadDashboard();
  });
});
elements.workflowStatusChips.forEach((button) => {
  button.addEventListener("click", () => {
    state.selectedWorkflowStatus = button.dataset.workflowStatus;
    state.selectedReviewItemId = null;
    renderControls();
    loadDashboard();
  });
});

loadDashboard();

async function loadDashboard() {
  elements.refreshButton.disabled = true;
  try {
    await loadHealth();
    const [queues, items] = await Promise.all([fetchJson("/review/queues"), loadQueueItems()]);
    state.queues = queues;
    renderQueues(queues);
    renderReviewList(items);
    if (items.length > 0) {
      const selectedStillVisible = items.some(
        (item) => item.review_item_id === state.selectedReviewItemId,
      );
      await loadDetail(selectedStillVisible ? state.selectedReviewItemId : items[0].review_item_id);
    } else {
      state.selectedReviewItemId = null;
      elements.selectedItemLabel.textContent = "No item selected";
      elements.detailContent.className = "detail-empty";
      elements.detailContent.textContent = `No ${workflowStatusLabel(
        state.selectedWorkflowStatus,
      ).toLowerCase()} were returned for ${queueLabel(state.selectedQueueType)}.`;
    }
  } catch (error) {
    showApiError(error);
  } finally {
    elements.refreshButton.disabled = false;
  }
}

async function loadHealth() {
  const health = await fetchJson("/health");
  elements.apiStatus.classList.remove("error");
  elements.apiStatus.textContent = health.database_initialized
    ? "API healthy, database ready"
    : "API healthy, database missing";
}

async function loadQueueItems() {
  const params = new URLSearchParams({ status: state.selectedWorkflowStatus, limit: "100" });
  const filter = parseFilter(state.selectedFilter);
  if (filter) {
    params.set(filter.name, filter.value);
  }
  const items = await fetchJson(
    `/review/queues/${encodeURIComponent(state.selectedQueueType)}/items?${params}`,
  );
  state.items = items;
  return items;
}

async function loadDetail(reviewItemId) {
  if (!reviewItemId) {
    return;
  }
  state.selectedReviewItemId = reviewItemId;
  renderReviewList(state.items);
  elements.selectedItemLabel.textContent = reviewItemId;
  elements.detailContent.className = "detail-empty";
  elements.detailContent.textContent = "Loading publication detail...";
  try {
    const [detail, decisions] = await Promise.all([
      fetchJson(`/review/items/${encodeURIComponent(reviewItemId)}`),
      fetchJson(`/review/items/${encodeURIComponent(reviewItemId)}/identity-decisions`),
    ]);
    const publicationCandidateItem = detail.review_items.find(
      (item) =>
        item.review_item_id === reviewItemId &&
        item.queue_type === "publication_candidate_review",
    );
    const provenance = publicationCandidateItem
      ? await loadPublicationCandidateProvenance(detail.publication.document_id)
      : null;
    renderDetail(detail, reviewItemId, decisions, provenance);
  } catch (error) {
    elements.detailContent.className = "detail-empty";
    elements.detailContent.textContent = error.message;
  }
}

function renderQueues(queues) {
  renderControls();
  elements.openItemsHeading.textContent = `${workflowStatusLabel(
    state.selectedWorkflowStatus,
  )} for ${queueLabel(state.selectedQueueType)}`;
  const queue = queues.find((entry) => entry.queue_type === state.selectedQueueType);
  if (!queue) {
    elements.queueSummary.innerHTML = `<div class="summary-card">No ${escapeHtml(
      state.selectedQueueType,
    )} queue found.</div>`;
    return;
  }
  const cards = [
    ["Open", queue.open_items],
    ["In review", queue.in_review_items],
    ["Workflow-resolved", queue.resolved_items],
    ["Dismissed", queue.dismissed_items],
  ];
  elements.queueSummary.innerHTML = cards
    .map(
      ([label, value]) => `
        <div class="summary-card">
          <strong>${value}</strong>
          <span>${label}</span>
        </div>
      `,
    )
    .join("");
}

function renderReviewList(items) {
  elements.openItemsHeading.textContent = `${workflowStatusLabel(
    state.selectedWorkflowStatus,
  )} for ${queueLabel(state.selectedQueueType)} (${items.length} shown)`;
  if (items.length === 0) {
    elements.reviewList.innerHTML = `<p class="muted">No ${workflowStatusLabel(
      state.selectedWorkflowStatus,
    ).toLowerCase()}.</p>`;
    return;
  }
  elements.reviewList.innerHTML = items
    .map((item) => {
      const title = item.publication.primary_title || "Untitled publication";
      const activeClass = item.review_item_id === state.selectedReviewItemId ? " active" : "";
      const candidateMeta = renderCandidateCardMetadata(item);
      return `
        <button class="review-card${activeClass}" type="button" data-review-item-id="${escapeAttr(
          item.review_item_id,
        )}">
          <span class="review-title">${escapeHtml(title)}</span>
          <span class="review-meta">
            ${escapeHtml(queueItemPrefix(item))}
            / workflow ${escapeHtml(workflowStatusDisplay(item.status))}
            / score ${formatNumber(item.priority_score)}
            / ${escapeHtml(item.priority_tier)}
          </span>
          <span class="review-id">${escapeHtml(item.review_item_id)}</span>
          ${candidateMeta}
        </button>
      `;
    })
    .join("");
  document.querySelectorAll("[data-review-item-id]").forEach((button) => {
    button.addEventListener("click", () => loadDetail(button.dataset.reviewItemId));
  });
}

async function loadPublicationCandidateProvenance(documentId) {
  if (state.provenanceByDocumentId[documentId]) {
    return state.provenanceByDocumentId[documentId];
  }
  const provenance = await fetchJson(
    `/publication-candidates/${encodeURIComponent(documentId)}/provenance`,
  );
  state.provenanceByDocumentId[documentId] = provenance;
  return provenance;
}

function renderCandidateCardMetadata(item) {
  if (item.queue_type !== "publication_candidate_review") {
    return "";
  }
  const metadata = item.metadata || {};
  return `
    <span class="candidate-badges">
      ${badge(metadata.identity_status)}
      ${badge(metadata.cannabinoid_focus)}
      ${badge(metadata.full_text_review_priority)}
    </span>
    <span class="review-meta">
      ${metaInline("PMID", item.publication.pmid)}
      ${metaInline("PMCID", item.publication.pmcid)}
      ${metaInline("DOI", item.publication.doi)}
    </span>
  `;
}

function renderDetail(detail, reviewItemId, decisions, candidateProvenance) {
  const publication = detail.publication;
  const activeItem =
    detail.review_items.find((item) => item.review_item_id === reviewItemId) ||
    detail.review_items[0];
  const title = publication.primary_title || "Untitled publication";
  elements.detailContent.className = "detail-body";
  elements.detailContent.innerHTML = `
    <h3 class="detail-title">${escapeHtml(title)}</h3>
    <div class="meta-grid">
      ${meta("Document", publication.document_id)}
      ${meta("Year", publication.publication_year)}
      ${meta("PMID", publication.pmid)}
      ${meta("PMCID", publication.pmcid)}
      ${meta("DOI", publication.doi)}
      ${meta("Legacy type", publication.legacy_study_type)}
      ${meta("Canonical URL", linkOrText(publication.canonical_url))}
      ${meta("Review state", publication.review_state)}
    </div>

    ${renderPublicationCandidateProvenance(candidateProvenance)}
    ${renderStatusForm(activeItem)}
    ${renderDecisionForm(detail, activeItem)}
    ${renderDecisions(decisions)}
    ${renderDecisionApplication(decisions)}
    ${renderLegacyReference(detail.legacy_reference)}
    ${renderIdentities(detail.identities)}
    ${renderOntologyLinks(detail.ontology_links)}
  `;
  const statusForm = document.querySelector("#status-form");
  statusForm.addEventListener("submit", (event) => submitStatusUpdate(event, reviewItemId));
  const decisionForm = document.querySelector("#identity-decision-form");
  decisionForm.addEventListener("submit", (event) =>
    submitIdentityDecision(event, detail, reviewItemId),
  );
  const applyButton = document.querySelector("#apply-decision-button");
  if (applyButton) {
    applyButton.addEventListener("click", () => applyIdentityDecision(reviewItemId));
  }
}

function renderPublicationCandidateProvenance(provenance) {
  if (!provenance) {
    return "";
  }
  return `
    <section class="detail-section candidate-provenance">
      <h3>Publication candidate provenance</h3>
      <div class="meta-grid">
        ${meta("Identity status", provenance.identity_status)}
        ${meta("Cannabinoid focus", provenance.cannabinoid_focus)}
        ${meta("Full text priority", provenance.full_text_review_priority)}
        ${meta("Legacy match type", provenance.legacy_match_type)}
        ${meta("Legacy match confidence", formatNumber(provenance.legacy_match_confidence))}
        ${meta("Source candidate", provenance.source_candidate_id)}
        ${meta("PMID", provenance.publication.pmid)}
        ${meta("PMCID", provenance.publication.pmcid)}
        ${meta("DOI", provenance.publication.doi)}
      </div>
      <div class="data-list compact-list">
        ${renderValueList("Review reasons", provenance.review_reasons)}
        ${renderValueList("Score reasons", provenance.score_reasons)}
        ${renderValueList("Query names", provenance.query_names)}
        ${renderValueList("Legacy study IDs", provenance.legacy_study_ids)}
      </div>
      <details class="provenance-json">
        <summary>Raw provenance</summary>
        <pre>${escapeHtml(JSON.stringify(provenance.provenance, null, 2))}</pre>
      </details>
    </section>
  `;
}

function renderValueList(label, values) {
  const items = Array.isArray(values) ? values : [];
  return `
    <div class="data-row">
      <strong>${escapeHtml(label)}</strong><br />
      ${
        items.length === 0
          ? '<span class="muted">Not recorded</span>'
          : `<ul>${items.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>`
      }
    </div>
  `;
}

function renderStatusForm(item) {
  if (!item) {
    return "";
  }
  return `
    <section class="detail-section">
      <h3>Review action</h3>
      <form id="status-form" class="status-form">
        <label>
          Status
          <select name="status">
            ${["open", "in_review", "resolved", "dismissed"]
              .map(
                (status) =>
                  `<option value="${status}" ${status === item.status ? "selected" : ""}>${status}</option>`,
              )
              .join("")}
          </select>
        </label>
        <label>
          Note
          <textarea name="note" rows="3" placeholder="Optional review note"></textarea>
        </label>
        <div class="form-actions">
          <button type="submit">Update status</button>
          <span id="status-message" class="message" role="status"></span>
        </div>
      </form>
    </section>
  `;
}

function renderDecisionForm(detail, item) {
  if (!item) {
    return "";
  }
  const publication = detail.publication;
  return `
    <section class="detail-section">
      <h3>Identity decision</h3>
      <form id="identity-decision-form" class="decision-form">
        <div class="form-grid">
          <label>
            Reviewer
            <input name="reviewer" type="text" autocomplete="name" required />
          </label>
          <label>
            Decision
            <select name="decision" required>
              <option value="confirmed_identity">Confirmed identity</option>
              <option value="corrected_identity">Corrected identity</option>
              <option value="not_same_publication">Not same publication</option>
              <option value="unresolved">Unresolved</option>
            </select>
          </label>
          <label>
            Reviewed PMID
            <input name="reviewed_pmid" type="text" value="${escapeAttr(publication.pmid || "")}" />
          </label>
          <label>
            Reviewed PMCID
            <input name="reviewed_pmcid" type="text" value="${escapeAttr(publication.pmcid || "")}" />
          </label>
          <label>
            Reviewed DOI
            <input name="reviewed_doi" type="text" value="${escapeAttr(publication.doi || "")}" />
          </label>
          <label>
            Reviewed canonical URL
            <input name="reviewed_canonical_url" type="url" value="${escapeAttr(
              publication.canonical_url || "",
            )}" />
          </label>
        </div>
        <label>
          Rationale
          <textarea name="rationale" rows="3" placeholder="Why this identity decision is appropriate"></textarea>
        </label>
        <div class="form-actions">
          <button type="submit">Save identity decision</button>
          <span id="decision-message" class="message" role="status"></span>
        </div>
      </form>
    </section>
  `;
}

function renderDecisions(decisions) {
  return `
    <section class="detail-section">
      <h3>Saved identity decisions</h3>
      <div class="data-list">
        ${
          decisions.length === 0
            ? `<p class="muted">No structured identity decisions saved yet.</p>`
            : decisions
                .map(
                  (decision) => `
                    <div class="data-row">
                      <strong>${escapeHtml(decision.decision)}</strong>
                      <span class="muted">${escapeHtml(decision.reviewer)} / ${escapeHtml(
                        decision.created_at,
                      )}</span><br />
                      ${metaInline("PMID", decision.reviewed_pmid)}
                      ${metaInline("PMCID", decision.reviewed_pmcid)}
                      ${metaInline("DOI", decision.reviewed_doi)}
                      ${metaInline("URL", decision.reviewed_canonical_url)}
                      <p>${formatValue(decision.rationale)}</p>
                    </div>
                  `,
                )
                .join("")
        }
      </div>
    </section>
  `;
}

function renderDecisionApplication(decisions) {
  const latestDecision = decisions[0];
  const canApply =
    latestDecision &&
    ["confirmed_identity", "corrected_identity", "not_same_publication"].includes(
      latestDecision.decision,
    );
  const helper = latestDecision
    ? `Latest decision: ${escapeHtml(latestDecision.decision)}`
    : "Save a structured identity decision before applying it to workflow.";
  return `
    <section class="detail-section">
      <h3>Workflow application</h3>
      <div class="form-actions">
        <button id="apply-decision-button" type="button" ${canApply ? "" : "disabled"}>
          Apply decision to workflow
        </button>
        <span id="apply-decision-message" class="message" role="status">${helper}</span>
      </div>
    </section>
  `;
}

function renderLegacyReference(reference) {
  const values = Object.entries(reference.reference_values || {});
  return `
    <section class="detail-section">
      <h3>Legacy reference</h3>
      <div class="meta-grid">
        ${meta("Legacy study", reference.legacy_study_id)}
        ${meta("Title EN", reference.title_en)}
        ${meta("Title PT", reference.title_pt)}
        ${meta("Normalized title", reference.normalized_title)}
        ${meta("Legacy result", reference.legacy_result)}
      </div>
      <div class="data-list">
        ${values
          .slice(0, 12)
          .map(([key, value]) => `<div class="data-row"><strong>${escapeHtml(key)}</strong><br />${escapeHtml(formatValue(value))}</div>`)
          .join("")}
      </div>
    </section>
  `;
}

function renderIdentities(identities) {
  return `
    <section class="detail-section">
      <h3>Identity signals</h3>
      <div class="data-list">
        ${
          identities.length === 0
            ? `<p class="muted">No identity signals recorded.</p>`
            : identities
                .map(
                  (identity) => `
                    <div class="data-row">
                      <strong>${escapeHtml(identity.identifier_type)}</strong>
                      <code>${escapeHtml(identity.identifier_value)}</code><br />
                      <span class="muted">${escapeHtml(identity.source)} / confidence ${formatNumber(
                        identity.confidence,
                      )} / ${escapeHtml(identity.association_state)}</span>
                    </div>
                  `,
                )
                .join("")
        }
      </div>
    </section>
  `;
}

function renderOntologyLinks(links) {
  return `
    <section class="detail-section">
      <h3>Ontology links</h3>
      <div class="data-list">
        ${
          links.length === 0
            ? `<p class="muted">No ontology links recorded.</p>`
            : links
                .slice(0, 24)
                .map(
                  (link) => `
                    <div class="data-row">
                      <strong>${escapeHtml(link.canonical_label_en || link.canonical_label)}</strong>
                      <span class="muted">${escapeHtml(link.entity_type)} / ${escapeHtml(
                        link.review_state,
                      )}</span>
                    </div>
                  `,
                )
                .join("")
        }
      </div>
    </section>
  `;
}

function parseFilter(value) {
  if (!value) {
    return null;
  }
  const [name, filterValue] = value.split(":", 2);
  if (!name || !filterValue) {
    return null;
  }
  return { name, value: filterValue };
}

function renderControls() {
  const supportsCandidateFilters = state.selectedQueueType === "publication_candidate_review";
  if (!supportsCandidateFilters && state.selectedFilter) {
    state.selectedFilter = "";
  }
  elements.queueTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.queueType === state.selectedQueueType);
  });
  elements.candidateFilters.hidden = !supportsCandidateFilters;
  elements.filterChips.forEach((button) => {
    button.classList.toggle("active", button.dataset.filter === state.selectedFilter);
  });
  elements.workflowStatusChips.forEach((button) => {
    button.classList.toggle(
      "active",
      button.dataset.workflowStatus === state.selectedWorkflowStatus,
    );
  });
  elements.activeFilterLabel.textContent = FILTER_LABELS[state.selectedFilter] || "Filtered view";
  elements.activeWorkflowStatusLabel.textContent =
    WORKFLOW_STATUS_LABELS[state.selectedWorkflowStatus] || "Filtered workflow tasks";
}

function queueLabel(queueType) {
  return QUEUE_TYPES[queueType] || queueType;
}

function workflowStatusLabel(status) {
  return WORKFLOW_STATUS_LABELS[status] || `${status} workflow tasks`;
}

function workflowStatusDisplay(status) {
  if (status === "resolved") {
    return "workflow-resolved";
  }
  return status;
}

function queueItemPrefix(item) {
  if (item.queue_type === "publication_candidate_review") {
    return `PMID ${item.publication.pmid || "not recorded"}`;
  }
  return `Legacy study ${item.publication.legacy_study_id}`;
}

function badge(value) {
  if (!value) {
    return "";
  }
  return `<span class="badge">${escapeHtml(value)}</span>`;
}

async function submitStatusUpdate(event, reviewItemId) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#status-message");
  const submitButton = form.querySelector("button[type='submit']");
  const formData = new FormData(form);
  submitButton.disabled = true;
  message.classList.remove("error");
  message.textContent = "Updating...";
  try {
    const payload = {
      status: formData.get("status"),
      note: formData.get("note") || null,
    };
    const result = await fetchJson(`/review/items/${encodeURIComponent(reviewItemId)}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    message.textContent = `Updated from ${result.previous_status} to ${result.status}.`;
    await loadDashboard();
  } catch (error) {
    message.classList.add("error");
    message.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
}

async function submitIdentityDecision(event, detail, reviewItemId) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#decision-message");
  const submitButton = form.querySelector("button[type='submit']");
  const formData = new FormData(form);
  submitButton.disabled = true;
  message.classList.remove("error");
  message.textContent = "Saving...";
  try {
    const payload = {
      review_item_id: reviewItemId,
      document_id: detail.publication.document_id,
      reviewer: formData.get("reviewer"),
      decision: formData.get("decision"),
      reviewed_pmid: emptyToNull(formData.get("reviewed_pmid")),
      reviewed_pmcid: emptyToNull(formData.get("reviewed_pmcid")),
      reviewed_doi: emptyToNull(formData.get("reviewed_doi")),
      reviewed_canonical_url: emptyToNull(formData.get("reviewed_canonical_url")),
      rationale: emptyToNull(formData.get("rationale")),
      original_identity_signals: {
        publication: detail.publication,
        identities: detail.identities,
        legacy_reference: detail.legacy_reference,
      },
      provenance: {
        source: "marygenai.review_ui",
        queue_type: state.selectedQueueType,
      },
    };
    const result = await fetchJson(
      `/review/items/${encodeURIComponent(reviewItemId)}/identity-decisions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    message.textContent = `Saved ${result.decision}.`;
    await loadDetail(reviewItemId);
  } catch (error) {
    message.classList.add("error");
    message.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
}

async function applyIdentityDecision(reviewItemId) {
  const message = document.querySelector("#apply-decision-message");
  const button = document.querySelector("#apply-decision-button");
  button.disabled = true;
  message.classList.remove("error");
  message.textContent = "Applying...";
  try {
    const result = await fetchJson(
      `/review/items/${encodeURIComponent(reviewItemId)}/identity-decisions/apply`,
      {
        method: "POST",
      },
    );
    message.textContent = `Applied ${result.decision}; status is now ${result.status}.`;
    await loadDashboard();
  } catch (error) {
    message.classList.add("error");
    message.textContent = error.message;
    button.disabled = false;
  }
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : response.statusText;
    throw new Error(detail);
  }
  return payload;
}

function showApiError(error) {
  elements.apiStatus.classList.add("error");
  elements.apiStatus.textContent = "API unavailable";
  elements.reviewList.innerHTML = `<p class="message error">${escapeHtml(error.message)}</p>`;
}

function meta(label, value) {
  return `<div><strong>${escapeHtml(label)}</strong><br />${formatValue(value)}</div>`;
}

function metaInline(label, value) {
  if (!value) {
    return "";
  }
  return `<span class="inline-meta"><strong>${escapeHtml(label)}:</strong> ${formatValue(value)}</span>`;
}

function linkOrText(value) {
  if (!value) {
    return null;
  }
  const escaped = escapeAttr(value);
  return `<a href="${escaped}" target="_blank" rel="noreferrer">${escapeHtml(value)}</a>`;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return '<span class="muted">Not recorded</span>';
  }
  if (typeof value === "string" && value.startsWith("<a ")) {
    return value;
  }
  if (typeof value === "object") {
    return escapeHtml(JSON.stringify(value));
  }
  return escapeHtml(String(value));
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "0";
  }
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function emptyToNull(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const trimmed = String(value).trim();
  return trimmed === "" ? null : trimmed;
}
