const $ = (id) => document.getElementById(id);

async function submit() {
  const res = await fetch("/api/tasks/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      count: parseInt($("count").value, 10),
      enable_pro_trial: $("pro").checked,
    }),
  });
  const data = await res.json();
  $("result").textContent = data.batch_id
    ? `已入队: ${data.queued} 个 (${data.batch_id})` : `错误: ${JSON.stringify(data)}`;
}

function connectWS() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("conn").textContent = "(已连接)"; $("conn").className = "ok"; };
  ws.onclose = () => { $("conn").textContent = "(未连接)"; $("conn").className = "fail";
                        setTimeout(connectWS, 3000); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "task") upsertTask(m.task);
  };
}

function upsertTask(t) {
  const tbody = document.querySelector("#tasks tbody");
  let row = document.querySelector(`#tasks tr[data-id="${t.id}"]`);
  if (!row) {
    row = document.createElement("tr");
    row.dataset.id = t.id;
    tbody.prepend(row);
  }
  row.innerHTML = `<td>${t.id}</td><td>${t.email}</td>
    <td class="${t.status === 'success' ? 'ok' : (t.status === 'failed' ? 'fail' : '')}">${t.status}</td>
    <td>${t.reason || ""}</td>`;
}

$("submit").addEventListener("click", submit);
connectWS();
