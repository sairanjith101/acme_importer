// helpers
function qs(sel) {
  return document.querySelector(sel);
}
function qsa(sel) {
  return Array.from(document.querySelectorAll(sel));
}

const uploadBtn = qs("#uploadBtn");
const csvfile = qs("#csvfile");
const progressBar = qs("#progressBar");
const uploadStatus = qs("#uploadStatus");
const uploadMeta = qs("#uploadMeta");

uploadBtn.addEventListener("click", async () => {
  if (!csvfile.files[0]) return alert("Choose CSV");
  const fd = new FormData();
  fd.append("file", csvfile.files[0]);
  uploadStatus.innerText = "Uploading...";
  const resp = await fetch("/api/upload/", { method: "POST", body: fd });
  if (!resp.ok) {
    uploadStatus.innerText = "Upload failed";
    return;
  }
  const data = await resp.json();
  const upload_id = data.upload_id;
  uploadStatus.innerText = "Upload queued: " + upload_id;
  pollProgress(upload_id);
});

async function pollProgress(upload_id) {
  const interval = setInterval(async () => {
    const r = await fetch(`/api/upload/${upload_id}/progress/`);
    if (r.status !== 200) {
      uploadStatus.innerText = "Progress not found";
      clearInterval(interval);
      return;
    }
    const d = await r.json();
    progressBar.value = d.percent || 0;
    uploadStatus.innerText = `${d.status} - ${d.percent || 0}%`;
    if (d.processed && d.total) {
      uploadMeta.innerText = `Processed: ${d.processed} / ${d.total}`;
    }
    if (
      d.status === "complete" ||
      d.status === "empty" ||
      d.status === "failed"
    ) {
      clearInterval(interval);
      if (d.status === "failed")
        uploadStatus.innerText = "Import failed: " + (d.reason || "");
    }
  }, 1500);
}

// PRODUCTS - listing, search, ordering, create/update
const refreshBtn = qs("#refreshList");
const productsDiv = qs("#products");
const searchInput = qs("#search");
const orderSelect = qs("#order");

refreshBtn.addEventListener("click", loadProducts);

async function loadProducts(page = 1) {
  const q = encodeURIComponent(searchInput.value || "");
  const ordering = orderSelect.value || "-updated_at";
  const resp = await fetch(
    `/api/products/?search=${q}&ordering=${ordering}&page=${page}`
  );
  const data = await resp.json();
  const items = data.results || data;
  productsDiv.innerHTML = items
    .map(
      (p) => `
    <div class="card" id="prod-${p.id}">
      <div><strong>${p.sku}</strong> - ${p.name}</div>
      <div>Price: ${p.price || "N/A"} | ${
        p.active ? "Active" : "Inactive"
      }</div>
      <div>
        <button onclick="openEdit('${p.id}','${escapeHtml(
        p.sku
      )}','${escapeHtml(p.name)}','${escapeHtml(p.description || "")}','${
        p.price || ""
      }')">Edit</button>
        <button onclick="deleteProduct('${p.id}')">Delete</button>
      </div>
    </div>
  `
    )
    .join("");
}

function escapeHtml(s) {
  return (s || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function deleteProduct(id) {
  if (!confirm("Delete product?")) return;
  await fetch(`/api/products/${id}/`, { method: "DELETE" });
  loadProducts();
}

// Create / Edit modal
const modal = qs("#modal");
const modalTitle = qs("#modalTitle");
const m_sku = qs("#m_sku");
const m_name = qs("#m_name");
const m_desc = qs("#m_desc");
const m_price = qs("#m_price");
const saveProductBtn = qs("#saveProduct");
const closeModalBtn = qs("#closeModal");
let editingId = null;

qs("#openCreate").addEventListener("click", () => {
  editingId = null;
  modalTitle.innerText = "Create Product";
  m_sku.value = "";
  m_name.value = "";
  m_desc.value = "";
  m_price.value = "";
  modal.style.display = "block";
});
window.openEdit = (id, sku, name, desc, price) => {
  editingId = id;
  modalTitle.innerText = "Edit Product";
  m_sku.value = sku;
  m_name.value = name;
  m_desc.value = desc;
  m_price.value = price;
  modal.style.display = "block";
};
saveProductBtn.addEventListener("click", async () => {
  const payload = {
    sku: m_sku.value.trim(),
    name: m_name.value.trim(),
    description: m_desc.value,
    price: m_price.value || null,
  };
  if (!payload.sku) return alert("SKU required");
  if (editingId) {
    await fetch(`/api/products/${editingId}/`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } else {
    await fetch("/api/products/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }
  modal.style.display = "none";
  loadProducts();
});
closeModalBtn.addEventListener("click", () => (modal.style.display = "none"));

// Bulk delete (async)
qs("#bulkDelete").addEventListener("click", async () => {
  if (!confirm("Are you sure? This will delete ALL products")) return;
  const resp = await fetch("/api/products/bulk_delete/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
  const j = await resp.json();
  const task_id = j.task_id;
  if (!task_id) return alert("Failed to start delete");
  // poll delete progress
  const key = `bulkdelete:${task_id}:progress`;
  const interval = setInterval(async () => {
    const r = await fetch(`/__redis_probe?key=${encodeURIComponent(key)}`); // helper route added below
    const data = await r.json();
    if (!data) return;
    const obj = data;
    if (obj.status === "complete" || obj.status === "failed") {
      clearInterval(interval);
      alert("Bulk delete: " + obj.status);
      loadProducts();
    } else {
      console.log("bulk progress", obj);
    }
  }, 2000);
});

// WEBHOOKS
const webhookArea = qs("#webhookArea");
qs("#newWebhookBtn").addEventListener("click", showWebhookForm);
async function loadWebhooks() {
  const r = await fetch("/api/webhooks/");
  const j = await r.json();
  const items = j.results || j;
  webhookArea.innerHTML = `
    <div>${items
      .map(
        (w) => `<div class="card" id="wh-${w.id}">
      <div>${w.id} - <strong>${w.url}</strong> [${w.event}] - ${
          w.enabled ? "Enabled" : "Disabled"
        }</div>
      <div>
        <button onclick="testWebhook(${w.id})">Test</button>
        <button onclick="viewWebhookLogs(${w.id})">Logs</button>
        <button onclick="deleteWebhook(${w.id})">Delete</button>
      </div>
      <div id="logs-${w.id}"></div>
    </div>`
      )
      .join("")}</div>`;
}

window.showWebhookForm = () => {
  const html = `<div class="card">
    URL: <input id='whurl' style="width:60%"/><br>
    Event:
    <select id='whevent'>
      <option value='product.created'>product.created</option>
      <option value='product.updated'>product.updated</option>
      <option value='product.deleted'>product.deleted</option>
      <option value='import.completed'>import.completed</option>
    </select><br>
    <button id='createWh'>Create</button>
  </div>`;
  webhookArea.insertAdjacentHTML("afterbegin", html);
  qs("#createWh").addEventListener("click", async () => {
    const url = qs("#whurl").value.trim();
    const event = qs("#whevent").value;
    if (!url) return alert("URL required");
    await fetch("/api/webhooks/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, event, enabled: true }),
    });
    loadWebhooks();
  });
};

window.testWebhook = async (id) => {
  await fetch(`/api/webhooks/${id}/test/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: { test: true } }),
  });
  alert("Test triggered");
};

window.viewWebhookLogs = async (id) => {
  const r = await fetch(`/api/webhooks/${id}/logs/`);
  const j = await r.json();
  const box = qs(`#logs-${id}`);
  box.innerHTML = `<pre>${JSON.stringify(j.logs, null, 2)}</pre>`;
};
window.deleteWebhook = async (id) => {
  if (!confirm("Delete webhook?")) return;
  await fetch(`/api/webhooks/${id}/`, { method: "DELETE" });
  loadWebhooks();
};

// Helper route to read Redis keys (only for local dev)
async function readRedisKey(key) {
  const resp = await fetch(`/__redis_probe?key=${encodeURIComponent(key)}`);
  if (resp.status !== 200) return null;
  return await resp.json();
}

// Initialize
loadProducts();
loadWebhooks();
