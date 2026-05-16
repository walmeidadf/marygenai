const QUEUE_TYPE = "legacy_identity_review";
const state = {
  items: [],
  selectedReviewItemId: null,
};

const elements = {
  apiStatus: document.querySelector("#api-status"),
  queueSummary: document.querySelector("#queue-summary"),
  reviewList: document.querySelector("#review-list"),
  detailContent: document.querySelector("#detail-content"),
  selectedItemLabel: document.querySelector("#selected-item-label"),
  refreshButton: document.querySelector("#refresh-button"),
};

elements.refreshButton.addEventListener("click", () => loadDashboard());

loadDashboard();

async function loadDashboard() {
  elements.refreshButton.disabled = true;
  try {
    await loadHealth();
    const [queues, items] = await Promise.all([fetchJson("/review/queues"), loadQueueItems()]);
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
      elements.detailContent.textContent = "No open legacy identity review items were returned.";
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
  const items = await fetchJson(`/review/queues/${QUEUE_TYPE}/items?status=open&limit=20`);
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
    const detail = await fetchJson(`/review/items/${encodeURIComponent(reviewItemId)}`);
    renderDetail(detail, reviewItemId);
  } catch (error) {
    elements.detailContent.className = "detail-empty";
    elements.detailContent.textContent = error.message;
  }
}

function renderQueues(queues) {
  const queue = queues.find((entry) => entry.queue_type === QUEUE_TYPE);
  if (!queue) {
    elements.queueSummary.innerHTML = `<div class="summary-card">No ${escapeHtml(
      QUEUE_TYPE,
    )} queue found.</div>`;
    return;
  }
  const cards = [
    ["Open", queue.open_items],
    ["In review", queue.in_review_items],
    ["Resolved", queue.resolved_items],
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
  if (items.length === 0) {
    elements.reviewList.innerHTML = `<p class="muted">No open items.</p>`;
    return;
  }
  elements.reviewList.innerHTML = items
    .map((item) => {
      const title = item.publication.primary_title || "Untitled publication";
      const activeClass = item.review_item_id === state.selectedReviewItemId ? " active" : "";
      return `
        <button class="review-card${activeClass}" type="button" data-review-item-id="${escapeAttr(
          item.review_item_id,
        )}">
          <span class="review-title">${escapeHtml(title)}</span>
          <span class="review-meta">
            Legacy study ${escapeHtml(item.publication.legacy_study_id)}
            / score ${formatNumber(item.priority_score)}
            / ${escapeHtml(item.priority_tier)}
          </span>
        </button>
      `;
    })
    .join("");
  document.querySelectorAll("[data-review-item-id]").forEach((button) => {
    button.addEventListener("click", () => loadDetail(button.dataset.reviewItemId));
  });
}

function renderDetail(detail, reviewItemId) {
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

    ${renderStatusForm(activeItem)}
    ${renderLegacyReference(detail.legacy_reference)}
    ${renderIdentities(detail.identities)}
    ${renderOntologyLinks(detail.ontology_links)}
  `;
  const form = document.querySelector("#status-form");
  form.addEventListener("submit", (event) => submitStatusUpdate(event, reviewItemId));
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
