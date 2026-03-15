
    (function () {
      let allPedidos = [];
      let refreshTimer = null;
      let isLoadingPedidos = false;

      const ordersContainer = document.getElementById("orders-container");
      const routeContainer = document.getElementById("route-container");

      const msgSuccess = document.getElementById("msg-success");
      const msgError = document.getElementById("msg-error");

      const statListos = document.getElementById("stat-listos");
      const statPendientes = document.getElementById("stat-pendientes");
      const statCps = document.getElementById("stat-cps");

      const REFRESH_MS = 12000;

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

      function hideMessages() {
        msgSuccess.classList.remove("show");
        msgError.classList.remove("show");
      }

      function showSuccess(message) {
        msgError.classList.remove("show");
        msgSuccess.textContent = message;
        msgSuccess.classList.add("show");
        setTimeout(() => msgSuccess.classList.remove("show"), 4200);
      }

      function showError(message) {
        msgSuccess.classList.remove("show");
        msgError.textContent = message;
        msgError.classList.add("show");
        setTimeout(() => msgError.classList.remove("show"), 4600);
      }

      function normalizePayload(payload) {
        const ok = Boolean(payload && (payload.ok === true || payload.success === true));
        const rawData = payload && (payload.data !== undefined ? payload.data : payload.pedidos);
        const data = Array.isArray(rawData) ? rawData : [];
        const error = payload && (payload.error || payload.mensaje);
        return { ok, data, error };
      }

      function toText(value, fallback) {
        return value == null || value === "" ? fallback : String(value);
      }

      function normalizePedido(p) {
        const pedidoId = p.pedido_id ?? p.id ?? p.order_id;
        const direccion = p.direccion_entrega ?? p.direccion ?? p.direccion_texto ?? "Sin direccion";
        const cliente = p.cliente_nombre ?? p.nombre_cliente ?? p.cliente ?? "Cliente";
        const cp = p.codigo_postal ?? p.cp ?? p.postal_code ?? "00000";

        let productos = p.productos;
        if (Array.isArray(productos)) {
          productos = productos.map((it) => {
            if (typeof it === "string") return it;
            const nombre = it.producto ?? it.nombre ?? "Producto";
            const cantidad = it.cantidad ?? 1;
            return cantidad + " x " + nombre;
          }).join("\n");
        }

        return {
          id: pedidoId,
          estado: String(p.estado || "").toLowerCase(),
          direccion: toText(direccion, "Sin direccion"),
          cliente: toText(cliente, "Cliente"),
          cp: toText(cp, "00000"),
          productos: toText(productos, "Sin detalle de productos")
        };
      }

      function onlyListos(pedidos) {
        return pedidos.filter((p) => p.estado === "listo");
      }

      async function loadPedidos(force) {
        if (isLoadingPedidos && !force) return;
        isLoadingPedidos = true;
        hideMessages();
        try {
          const res = await fetch("/api/repartidor/pedidos", {
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

          const payload = await res.json();
          const normalized = normalizePayload(payload);

          if (!res.ok || !normalized.ok) {
            showError(normalized.error || "No se pudieron cargar los pedidos asignados.");
            allPedidos = [];
            render();
            return;
          }

          allPedidos = normalized.data.map(normalizePedido).filter((p) => p.id !== undefined && p.id !== null);
          render();
        } catch (_err) {
          allPedidos = [];
          render();
          showError("Error de conexion al cargar pedidos de repartidor.");
        } finally {
          isLoadingPedidos = false;
        }
      }

      function scheduleRefresh() {
        if (refreshTimer) clearTimeout(refreshTimer);
        refreshTimer = setTimeout(async () => {
          if (!document.hidden) {
            await loadPedidos(false);
          }
          scheduleRefresh();
        }, REFRESH_MS);
      }

      function render() {
        const pedidosListos = onlyListos(allPedidos);
        renderStats(pedidosListos);
        renderPedidos(pedidosListos);
        renderRuta(pedidosListos);
      }

      function renderStats(pedidosListos) {
        const cps = new Set(pedidosListos.map((p) => p.cp));
        statListos.textContent = String(pedidosListos.length);
        statPendientes.textContent = String(pedidosListos.length);
        statCps.textContent = String(cps.size);
      }

      function renderPedidos(pedidos) {
        if (!pedidos.length) {
          ordersContainer.innerHTML = "<div class='empty'>No hay pedidos en estado listo para este repartidor.</div>";
          return;
        }

        ordersContainer.innerHTML = pedidos.map((pedido) => {
          const inputId = "codigo-" + pedido.id;
          const boxId = "confirm-" + pedido.id;
          return (
            "<article class='order-card' data-pedido-id='" + esc(pedido.id) + "'>" +
              "<div class='order-head'>" +
                "<h4 class='order-id'>Pedido #" + esc(pedido.id) + "</h4>" +
                "<span class='chip green'>listo</span>" +
              "</div>" +

              "<div class='grid'>" +
                "<div><span>Cliente:</span> <strong>" + esc(pedido.cliente) + "</strong></div>" +
                "<div><span>CP:</span> <strong>" + esc(pedido.cp) + "</strong></div>" +
                "<div style='grid-column:1 / -1;'><span>Direccion:</span> <strong>" + esc(pedido.direccion) + "</strong></div>" +
              "</div>" +

              "<div class='products'>" + esc(pedido.productos) + "</div>" +

              "<div class='actions'>" +
                "<button class='btn primary' type='button' onclick='openConfirm(" + Number(pedido.id) + ")'>Confirmar entrega</button>" +
                "<button class='btn' type='button' onclick='reenviarCodigo(" + Number(pedido.id) + ")'>Reenviar codigo</button>" +
                "<button class='btn' type='button' onclick='openMaps(\'" + jsEsc(pedido.direccion) + "\')'>Abrir Maps</button>" +
              "</div>" +

              "<div class='confirm-box' id='" + boxId + "'>" +
                "<label for='" + inputId + "'>Ingresa el codigo del cliente:</label>" +
                "<div class='confirm-row'>" +
                  "<input id='" + inputId + "' type='text' maxlength='12' autocomplete='off' placeholder='Ej: 483920' />" +
                  "<button class='btn primary' type='button' onclick='confirmarEntrega(" + Number(pedido.id) + ")'>Enviar</button>" +
                  "<button class='btn' type='button' onclick='closeConfirm(" + Number(pedido.id) + ")'>Cancelar</button>" +
                "</div>" +
              "</div>" +
            "</article>"
          );
        }).join("");
      }

      function renderRuta(pedidosListos) {
        if (!pedidosListos.length) {
          routeContainer.innerHTML = "<div class='empty'>Sin pedidos para calcular ruta.</div>";
          return;
        }

        const ordenados = [...pedidosListos].sort((a, b) => String(a.cp).localeCompare(String(b.cp)));
        routeContainer.innerHTML = ordenados.map((pedido, idx) => (
          "<article class='route-card'>" +
            "<div class='route-order'>" + (idx + 1) + "</div>" +
            "<div class='route-main'><strong>Pedido #" + esc(pedido.id) + "</strong><br>" + esc(pedido.cliente) + "<br>" + esc(pedido.direccion) + "<br><span class='chip amber'>CP " + esc(pedido.cp) + "</span></div>" +
            "<button class='btn' type='button' onclick='openMaps(\'" + jsEsc(pedido.direccion) + "\')'>Maps</button>" +
          "</article>"
        )).join("");
      }

      function openConfirm(pedidoId) {
        document.querySelectorAll(".confirm-box.active").forEach((el) => el.classList.remove("active"));
        const box = document.getElementById("confirm-" + pedidoId);
        const input = document.getElementById("codigo-" + pedidoId);
        if (box) box.classList.add("active");
        if (input) {
          input.value = "";
          input.focus();
        }
      }

      function closeConfirm(pedidoId) {
        const box = document.getElementById("confirm-" + pedidoId);
        if (box) box.classList.remove("active");
      }

      async function confirmarEntrega(pedidoId) {
        hideMessages();
        const input = document.getElementById("codigo-" + pedidoId);
        const codigo = input && input.value ? input.value.trim() : "";
        if (!codigo) {
          showError("Debes ingresar el codigo del cliente para confirmar la entrega.");
          return;
        }

        try {
          const confirmRes = await fetch("/api/pedidos/" + pedidoId + "/confirmar", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ codigo_entrega: codigo })
          });

          if (confirmRes.redirected && confirmRes.url) {
            window.location.href = confirmRes.url;
            return;
          }

          const confirmPayload = await confirmRes.json().catch(() => ({}));
          const confirmOk = Boolean(confirmPayload && (confirmPayload.ok === true || confirmPayload.success === true));

          if (!confirmRes.ok || !confirmOk) {
            const msg = (confirmPayload && (confirmPayload.error || confirmPayload.mensaje)) || "Codigo incorrecto. No se pudo confirmar la entrega.";
            showError(msg);
            return;
          }

          showSuccess("Entrega confirmada correctamente. Pedido marcado como entregado.");

          try {
            await fetch("/api/evaluaciones/programar", {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ pedido_id: pedidoId, retraso_minutos: 15 })
            });
          } catch (_e) {
          }

          closeConfirm(pedidoId);
          await loadPedidos(true);
        } catch (_err) {
          showError("No fue posible confirmar la entrega en este momento.");
        }
      }

      async function reenviarCodigo(pedidoId) {
        hideMessages();
        try {
          const res = await fetch("/api/pedidos/" + pedidoId + "/reenviar-codigo", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" }
          });

          if (res.redirected && res.url) {
            window.location.href = res.url;
            return;
          }

          const payload = await res.json().catch(() => ({}));
          const ok = Boolean(payload && (payload.ok === true || payload.success === true));

          if (!res.ok || !ok) {
            const msg = (payload && (payload.error || payload.mensaje)) || "No se pudo reenviar el codigo al cliente.";
            showError(msg);
            return;
          }

          const data = payload && payload.data ? payload.data : {};
          const codigo = data && data.codigo_entrega ? String(data.codigo_entrega).trim() : "";
          if (codigo) {
            showSuccess("Codigo listo para reenviar: " + codigo);
          } else {
            showSuccess("Codigo reenviado al cliente por WhatsApp.");
          }
        } catch (_err) {
          showError("Error de red al reenviar el codigo.");
        }
      }

      function openMaps(direccion) {
        const q = encodeURIComponent(direccion || "");
        window.open("https://www.google.com/maps/search/?api=1&query=" + q, "_blank", "noopener");
      }

      window.openConfirm = openConfirm;
      window.closeConfirm = closeConfirm;
      window.confirmarEntrega = confirmarEntrega;
      window.reenviarCodigo = reenviarCodigo;
      window.openMaps = openMaps;

      document.getElementById("btn-refresh").addEventListener("click", () => {
        loadPedidos(true);
      });

      loadPedidos(true).catch(() => {});
      scheduleRefresh();

      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
          loadPedidos(true).catch(() => {});
        }
      });

      window.addEventListener("beforeunload", () => {
        if (refreshTimer) clearTimeout(refreshTimer);
      });
    })();
  
