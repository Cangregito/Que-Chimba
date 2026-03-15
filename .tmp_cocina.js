
    (function () {
      const API_QUEUE_URL = "/api/pedidos?estado=recibido,en_preparacion,listo";
      const API_STATUS_BASE = "/api/pedidos";
      const REFRESH_MS = 15000;

      const nodes = {
        board: document.getElementById("kanbanBoard"),
        recibido: document.getElementById("orders-recibido"),
        prep: document.getElementById("orders-prep"),
        listo: document.getElementById("orders-listo"),
        cRec: document.getElementById("count-recibido"),
        cPrep: document.getElementById("count-prep"),
        cListo: document.getElementById("count-listo"),
        kTotal: document.getElementById("kpi-total"),
        kRec: document.getElementById("kpi-recibidos"),
        kPrep: document.getElementById("kpi-prep"),
        kListo: document.getElementById("kpi-listos"),
        zone: document.getElementById("zoneContainer"),
        last: document.getElementById("lastUpdate"),
        err: document.getElementById("errorText"),
        refresh: document.getElementById("btn-refresh")
      };

      let currentOrders = [];
      let refreshTimer = null;
      let isFetching = false;

      function esc(value) {
        return String(value == null ? "" : value)
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }

      function jsEsc(value) {
        return String(value == null ? "" : value)
          .replaceAll("\\", "\\\\")
          .replaceAll("'", "\\'")
          .replaceAll("\n", " ");
      }

      function showError(message) {
        nodes.err.textContent = message;
        nodes.err.classList.add("show");
      }

      function clearError() {
        nodes.err.classList.remove("show");
        nodes.err.textContent = "";
      }

      function getField(obj, keys, fallback = "-") {
        for (const key of keys) {
          const value = obj && obj[key];
          if (value !== undefined && value !== null && value !== "") return value;
        }
        return fallback;
      }

      function asArray(value) {
        return Array.isArray(value) ? value : [];
      }

      function formatHour(value) {
        const dt = new Date(value || "");
        if (Number.isNaN(dt.getTime())) return "-";
        return dt.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
      }

      function minutesSince(value) {
        const dt = new Date(value || "");
        if (Number.isNaN(dt.getTime())) return null;
        return Math.max(0, Math.floor((Date.now() - dt.getTime()) / 60000));
      }

      function priority(minutes) {
        if (minutes == null) return "normal";
        if (minutes >= 25) return "urgent";
        if (minutes >= 15) return "warn";
        return "normal";
      }

      function stateLabel(value) {
        if (value === "en_preparacion") return "En preparacion";
        if (value === "recibido") return "Recibido";
        if (value === "listo") return "Listo";
        return value || "-";
      }

      function stateChip(state) {
        if (state === "recibido") return "<span class='chip blue'>Recibido</span>";
        if (state === "en_preparacion") return "<span class='chip amber'>En preparacion</span>";
        if (state === "listo") return "<span class='chip green'>Listo</span>";
        return "<span class='chip red'>" + esc(state) + "</span>";
      }

      function normalizeOrder(raw) {
        const id = getField(raw, ["pedido_id", "id", "numero"], "");
        const number = getField(raw, ["numero_pedido", "numero", "pedido_id", "id"], id || "-");
        const customer = [raw && raw.nombre, raw && raw.apellidos].filter(Boolean).join(" ").trim() || getField(raw, ["cliente_nombre", "cliente"], "Cliente sin nombre");
        const state = String(getField(raw, ["estado"], "recibido")).toLowerCase();
        const receivedAt = getField(raw, ["creado_en", "recibido_en", "hora_recepcion"], "-");
        const address = getField(raw, ["direccion_entrega", "direccion"], "Direccion no disponible");
        const postalCode = String(getField(raw, ["codigo_postal", "cp"], "00000"));
        const items = asArray(getField(raw, ["items", "productos", "detalle"], []));
        const totalQty = Number(getField(raw, ["cantidad_total", "total_cantidad"], NaN));
        return {
          id,
          number,
          customer,
          state,
          receivedAt,
          address,
          postalCode,
          items,
          totalQty: Number.isNaN(totalQty) ? items.reduce((a, it) => a + Number(getField(it, ["cantidad"], 0)), 0) : totalQty
        };
      }

      function renderProducts(items) {
        if (!items.length) return "<li>Sin detalle de productos</li>";
        return items.map((it) => {
          if (typeof it === "string") return "<li>" + esc(it) + "</li>";
          const name = getField(it, ["producto", "nombre", "tipo"], "Producto");
          const qty = getField(it, ["cantidad", "qty"], "-");
          return "<li>" + esc(name) + " x " + esc(qty) + "</li>";
        }).join("");
      }

      function buildCard(order) {
        const mins = minutesSince(order.receivedAt);
        const p = priority(mins);
        const ageText = mins == null ? "Sin hora" : (mins + " min");
        const actions = [];
        if (order.state === "recibido") {
          actions.push("<button class='btn' data-action='prep' data-id='" + esc(order.id) + "'>En preparacion</button>");
        }
        if (order.state === "recibido" || order.state === "en_preparacion") {
          actions.push("<button class='btn primary' data-action='ready' data-id='" + esc(order.id) + "'>Listo para entregar</button>");
        }
        actions.push("<button class='btn' data-action='print' data-id='" + esc(order.id) + "'>Imprimir QR</button>");

        return (
          "<article class='card " + p + "' draggable='true' data-draggable-id='" + esc(order.id) + "'>" +
            "<div class='card-head'>" +
              "<h4>Pedido #" + esc(order.number) + "</h4>" +
              "<div style='display:flex; gap:6px; align-items:center; flex-wrap:wrap;'>" +
                (p === "urgent" ? "<span class='chip red'>" + esc(ageText) + "</span>" : (p === "warn" ? "<span class='chip amber'>" + esc(ageText) + "</span>" : "<span class='chip blue'>" + esc(ageText) + "</span>")) +
                stateChip(order.state) +
              "</div>" +
            "</div>" +
            "<div class='meta'>" +
              "<div><span>Cliente:</span> <strong>" + esc(order.customer) + "</strong></div>" +
              "<div><span>Hora:</span> <strong>" + esc(formatHour(order.receivedAt)) + "</strong></div>" +
              "<div><span>Cantidad:</span> <strong>" + esc(order.totalQty) + "</strong></div>" +
              "<div><span>CP:</span> <strong>" + esc(order.postalCode) + "</strong></div>" +
            "</div>" +
            "<ul class='products'>" + renderProducts(order.items) + "</ul>" +
            "<div class='actions'>" + actions.join("") + "</div>" +
          "</article>"
        );
      }

      function renderOrders() {
        const weight = { urgent: 3, warn: 2, normal: 1 };
        const sorter = (a, b) => {
          const pa = priority(minutesSince(a.receivedAt));
          const pb = priority(minutesSince(b.receivedAt));
          if (weight[pb] !== weight[pa]) return weight[pb] - weight[pa];
          const ta = new Date(a.receivedAt).getTime() || 0;
          const tb = new Date(b.receivedAt).getTime() || 0;
          return ta - tb;
        };

        const rec = currentOrders.filter((o) => o.state === "recibido").sort(sorter);
        const prep = currentOrders.filter((o) => o.state === "en_preparacion").sort(sorter);
        const listo = currentOrders.filter((o) => o.state === "listo").sort(sorter);

        nodes.cRec.textContent = String(rec.length);
        nodes.cPrep.textContent = String(prep.length);
        nodes.cListo.textContent = String(listo.length);

        nodes.kTotal.textContent = String(currentOrders.length);
        nodes.kRec.textContent = String(rec.length);
        nodes.kPrep.textContent = String(prep.length);
        nodes.kListo.textContent = String(listo.length);

        nodes.recibido.innerHTML = rec.length ? rec.map(buildCard).join("") : "<div class='empty'>No hay pedidos recibidos.</div>";
        nodes.prep.innerHTML = prep.length ? prep.map(buildCard).join("") : "<div class='empty'>No hay pedidos en preparacion.</div>";
        nodes.listo.innerHTML = listo.length ? listo.map(buildCard).join("") : "<div class='empty'>No hay pedidos listos.</div>";

        setDragAndDrop();
      }

      function renderZones() {
        if (!currentOrders.length) {
          nodes.zone.innerHTML = "<div class='empty'>Sin pedidos para agrupar.</div>";
          return;
        }

        const map = new Map();
        [...currentOrders].sort((a, b) => String(a.postalCode).localeCompare(String(b.postalCode))).forEach((order) => {
          const key = order.postalCode || "00000";
          if (!map.has(key)) map.set(key, []);
          map.get(key).push(order);
        });

        const html = [];
        for (const [cp, orders] of map.entries()) {
          html.push(
            "<section class='zone'>" +
              "<h4>CP " + esc(cp) + "</h4>" +
              "<ul>" +
                orders.map((o) => "<li>#" + esc(o.number) + " - " + esc(o.customer) + " (" + esc(stateLabel(o.state)) + ")</li>").join("") +
              "</ul>" +
            "</section>"
          );
        }
        nodes.zone.innerHTML = html.join("");
      }

      function setDragAndDrop() {
        document.querySelectorAll(".card[draggable='true']").forEach((card) => {
          card.addEventListener("dragstart", (event) => {
            const id = card.getAttribute("data-draggable-id");
            if (!id || !event.dataTransfer) return;
            event.dataTransfer.setData("text/plain", id);
            event.dataTransfer.effectAllowed = "move";
          });
        });

        document.querySelectorAll(".col[data-drop-state]").forEach((col) => {
          col.addEventListener("dragover", (event) => {
            event.preventDefault();
            col.classList.add("drag-over");
          });
          col.addEventListener("dragleave", () => {
            col.classList.remove("drag-over");
          });
          col.addEventListener("drop", async (event) => {
            event.preventDefault();
            col.classList.remove("drag-over");
            const state = col.getAttribute("data-drop-state");
            const id = event.dataTransfer ? event.dataTransfer.getData("text/plain") : "";
            if (!state || !id) return;
            const order = currentOrders.find((o) => String(o.id) === String(id));
            if (!order || order.state === state) return;
            await updateOrderStatus(id, state);
          });
        });
      }

      async function fetchOrders(force) {
        if (isFetching && !force) return;
        isFetching = true;
        try {
          const res = await fetch(API_QUEUE_URL, {
            method: "GET",
            credentials: "same-origin",
            headers: { "Accept": "application/json" }
          });

          if (res.redirected && res.url) {
            window.location.href = res.url;
            return;
          }

          const ct = (res.headers.get("content-type") || "").toLowerCase();
          if (!ct.includes("application/json")) {
            if (ct.includes("text/html")) window.location.href = "/login";
            throw new Error("Respuesta no valida");
          }

          const payload = await res.json().catch(() => ({}));
          const raw = Array.isArray(payload)
            ? payload
            : (Array.isArray(payload.data) ? payload.data : (Array.isArray(payload.pedidos) ? payload.pedidos : []));

          currentOrders = raw.map(normalizeOrder);
          renderOrders();
          renderZones();
          clearError();
          nodes.last.textContent = "Ultima actualizacion: " + new Date().toLocaleTimeString("es-MX");
        } catch (err) {
          showError("No se pudo actualizar la cola: " + (err && err.message ? err.message : "error"));
        } finally {
          isFetching = false;
        }
      }

      async function updateOrderStatus(orderId, newState) {
        try {
          const res = await fetch(API_STATUS_BASE + "/" + orderId + "/estado", {
            method: "PATCH",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              "Accept": "application/json"
            },
            body: JSON.stringify({ estado: newState })
          });

          if (res.redirected && res.url) {
            window.location.href = res.url;
            return;
          }
          if (!res.ok) {
            throw new Error("Error " + res.status + " al cambiar estado");
          }
          await fetchOrders(true);
        } catch (err) {
          showError("No se pudo actualizar el pedido #" + orderId + ": " + (err && err.message ? err.message : "error"));
        }
      }

      function scheduleRefresh() {
        if (refreshTimer) clearTimeout(refreshTimer);
        refreshTimer = setTimeout(async () => {
          if (!document.hidden) {
            await fetchOrders(false);
          }
          scheduleRefresh();
        }, REFRESH_MS);
      }

      function printOrderLabel(orderId) {
        const order = currentOrders.find((o) => String(o.id) === String(orderId) || String(o.number) === String(orderId));
        if (!order) {
          showError("No se encontro el pedido #" + orderId + " para imprimir.");
          return;
        }

        const payload = {
          pedido: order.number,
          cliente: order.customer,
          cp: order.postalCode,
          direccion: order.address,
          estado: order.state
        };

        const w = window.open("", "_blank", "width=420,height=640");
        if (!w) {
          showError("El navegador bloqueo la ventana de impresion.");
          return;
        }

        w.document.write(
          "<!doctype html><html lang='es'><head><meta charset='UTF-8'><title>Etiqueta Pedido #" + esc(order.number) + "</title>" +
          "<script src='https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js'><\/script>" +
          "<style>body{font-family:system-ui,-apple-system,sans-serif;margin:16px;color:#111}.sheet{border:1px solid #333;border-radius:8px;padding:12px}h1{font-size:18px;margin-bottom:8px}p{font-size:14px;margin:6px 0}.address{font-weight:500;font-size:15px}#qr{margin-top:10px;width:180px;height:180px}</style>" +
          "</head><body><div class='sheet'><h1>Que Chimba - Pedido #" + esc(order.number) + "</h1><p><strong>Cliente:</strong> " + esc(order.customer) + "</p><p><strong>Estado:</strong> " + esc(stateLabel(order.state)) + "</p><p class='address'><strong>Direccion:</strong> " + esc(order.address) + "</p><div id='qr'></div></div>" +
          "<script>new QRCode(document.getElementById('qr'),{text:" + JSON.stringify(JSON.stringify(payload)) + ",width:180,height:180,correctLevel:QRCode.CorrectLevel.H});setTimeout(function(){window.print();},400);<\/script></body></html>"
        );
        w.document.close();
      }

      nodes.board.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.getAttribute("data-action");
        const id = target.getAttribute("data-id");
        if (!action || !id) return;
        if (action === "prep") {
          await updateOrderStatus(id, "en_preparacion");
        } else if (action === "ready") {
          await updateOrderStatus(id, "listo");
        } else if (action === "print") {
          printOrderLabel(id);
        }
      });

      nodes.refresh.addEventListener("click", () => {
        fetchOrders(true);
      });

      fetchOrders(true).catch(() => {});
      scheduleRefresh();

      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
          fetchOrders(true).catch(() => {});
        }
      });

      window.addEventListener("beforeunload", () => {
        if (refreshTimer) clearTimeout(refreshTimer);
      });
    })();
  
