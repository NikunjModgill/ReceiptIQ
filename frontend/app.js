/* ReceiptIQ frontend: plain JS, no build step. Talks to the FastAPI backend on the same origin. */
(() => {
  const $ = (id) => document.getElementById(id);
  const ALLOWED = [".png", ".jpg", ".jpeg", ".pdf"];

  const el = {
    dropzone: $("dropzone"), input: $("file-input"),
    status: $("status"), statusMsg: $("status-msg"),
    preview: $("preview"), previewImg: $("preview-img"), previewPdf: $("preview-pdf"),
    resultCard: $("result-card"), items: $("r-items"), warnings: $("r-warnings"), json: $("r-json"),
    body: $("receipts-body"), count: $("count"), refresh: $("refresh"), engine: $("engine-badge"),
  };

  // ---------------------------------------------------------------- helpers
  const money = (v, cur) => (v == null ? "—" : `${cur === "USD" || !cur ? "$" : cur + " "}${Number(v).toFixed(2)}`);
  const text = (v) => (v == null || v === "" ? "—" : String(v));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function setStatus(state, msg = "") {
    el.status.className = `status ${state}`;
    el.status.textContent = { idle: "Idle", loading: "Loading", success: "Success", error: "Error" }[state];
    el.statusMsg.textContent = msg;
  }

  // ---------------------------------------------------------------- upload
  function showPreview(file) {
    el.preview.hidden = false;
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    el.previewImg.hidden = isPdf;
    el.previewPdf.hidden = !isPdf;
    if (isPdf) {
      el.previewPdf.textContent = `PDF selected: ${file.name}`;
    } else {
      el.previewImg.src = URL.createObjectURL(file);
    }
  }

  async function upload(file) {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ALLOWED.includes(ext)) {
      setStatus("error", `Unsupported file type "${ext}". Use png, jpg, jpeg or pdf.`);
      return;
    }
    showPreview(file);
    setStatus("loading", `Extracting ${file.name} …`);
    el.dropzone.classList.add("busy");
    const form = new FormData();
    form.append("file", file);
    const started = performance.now();
    try {
      const res = await fetch("/upload", { method: "POST", body: form });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : `HTTP ${res.status}`);
      const secs = ((performance.now() - started) / 1000).toFixed(1);
      setStatus("success", `${body.merchant_name || "Receipt"} · ${money(body.total_amount, body.extracted.currency)} · ${secs}s`);
      renderResult(body);
      await loadReceipts();
    } catch (err) {
      setStatus("error", err.message || "Upload failed");
    } finally {
      el.dropzone.classList.remove("busy");
      el.input.value = "";
    }
  }

  el.input.addEventListener("change", () => el.input.files[0] && upload(el.input.files[0]));
  ["dragenter", "dragover"].forEach((ev) => el.dropzone.addEventListener(ev, (e) => { e.preventDefault(); el.dropzone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => el.dropzone.addEventListener(ev, (e) => { e.preventDefault(); el.dropzone.classList.remove("over"); }));
  el.dropzone.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  el.dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.input.click(); } });

  // ---------------------------------------------------------------- result card
  function renderResult(rec) {
    const x = rec.extracted;
    el.resultCard.hidden = false;
    $("r-merchant").textContent = text(x.merchant_name);
    $("r-date").textContent = text(x.date);
    $("r-total").textContent = money(x.total_amount, x.currency);
    $("r-subtotal").textContent = money(x.subtotal, x.currency);
    $("r-tax").textContent = money(x.tax, x.currency);
    $("r-tip").textContent = money(x.tip, x.currency);
    $("r-payment").textContent = text(x.payment_method);
    $("r-engine").textContent = text(x.engine);

    el.items.innerHTML = x.line_items.length
      ? x.line_items.map((it, i) => `<tr><td>${i + 1}</td><td>${esc(it.name)}</td><td class="num">${it.quantity ?? ""}</td><td class="num">${money(it.price, x.currency)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="empty">No line items detected</td></tr>`;

    if (x.warnings && x.warnings.length) {
      el.warnings.hidden = false;
      el.warnings.innerHTML = `<strong>Needs review</strong><ul>${x.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`;
    } else {
      el.warnings.hidden = true;
    }
    el.json.textContent = JSON.stringify(rec, null, 2);
  }

  // ---------------------------------------------------------------- receipts table
  async function loadReceipts() {
    try {
      const res = await fetch("/receipts?limit=200");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      el.count.textContent = data.count;
      renderTable(data.receipts);
    } catch (err) {
      el.body.innerHTML = `<tr><td colspan="10" class="empty">Could not load receipts: ${esc(err.message)}</td></tr>`;
    }
  }

  function renderTable(rows) {
    if (!rows.length) {
      el.body.innerHTML = `<tr><td colspan="10" class="empty">No receipts yet — upload one above.</td></tr>`;
      return;
    }
    el.body.innerHTML = rows.map((r) => {
      const x = r.extracted;
      const warn = x.warnings && x.warnings.length ? ` <span class="pill flag" title="${esc(x.warnings.join("\n"))}">review</span>` : "";
      return `
        <tr class="row" data-id="${r.id}">
          <td>${r.id}</td>
          <td class="wrap">${esc(r.filename)}</td>
          <td class="wrap merchant">${esc(text(r.merchant_name))}${warn}</td>
          <td>${esc(text(r.date))}</td>
          <td class="num">${money(r.total_amount, x.currency)}</td>
          <td class="num">${money(x.tax, x.currency)}</td>
          <td class="num">${money(x.tip, x.currency)}</td>
          <td class="num">${x.line_items.length}</td>
          <td>${esc(r.created_at.replace("T", " ").replace("+00:00", ""))}</td>
          <td><button class="btn small danger" data-del="${r.id}" type="button" title="Delete">✕</button></td>
        </tr>
        <tr class="detail" data-detail="${r.id}" hidden>
          <td colspan="10">
            <div class="detail-grid">
              <div>
                <strong>Line items</strong>
                <table class="items"><tbody>
                  ${x.line_items.map((it) => `<tr><td class="wrap">${esc(it.name)}</td><td class="num">${it.quantity ?? ""}</td><td class="num">${money(it.price, x.currency)}</td></tr>`).join("") || `<tr><td class="empty">none</td></tr>`}
                </tbody></table>
                ${x.warnings && x.warnings.length ? `<div class="warnings"><ul>${x.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
              </div>
              <div>
                <strong>extracted_json</strong>
                <pre>${esc(JSON.stringify({ ...x, raw_text: undefined }, null, 2))}</pre>
                <strong>raw OCR text</strong>
                <pre>${esc(x.raw_text || "")}</pre>
              </div>
            </div>
          </td>
        </tr>`;
    }).join("");
  }

  el.body.addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      const id = del.dataset.del;
      if (!confirm(`Delete receipt #${id}?`)) return;
      const res = await fetch(`/receipts/${id}`, { method: "DELETE" });
      if (res.ok || res.status === 404) await loadReceipts();
      return;
    }
    const row = e.target.closest("tr.row");
    if (row) {
      const detail = el.body.querySelector(`tr[data-detail="${row.dataset.id}"]`);
      if (detail) detail.hidden = !detail.hidden;
    }
  });

  el.refresh.addEventListener("click", loadReceipts);

  // ---------------------------------------------------------------- boot
  fetch("/health").then((r) => r.json()).then((h) => {
    el.engine.textContent = h.llm_enabled ? `OCR + LLM · ${h.llm_model}` : "local OCR + rules";
  }).catch(() => { el.engine.textContent = "engine unavailable"; });
  setStatus("idle");
  loadReceipts();
})();
