(function () {
  const ReactRef = window.React;
  const ReactDOMRef = window.ReactDOM;

  if (!ReactRef || !ReactDOMRef) {
    console.warn("QCSoftUI: React/ReactDOM no estan disponibles.");
    return;
  }

  const e = ReactRef.createElement;

  function SoftBadge(props) {
    const tone = props.tone || "indigo";
    const toneMap = {
      indigo: "bg-indigo-50 text-indigo-700 border border-indigo-100",
      emerald: "bg-emerald-50 text-emerald-700 border border-emerald-100",
      rose: "bg-rose-50 text-rose-700 border border-rose-100",
      amber: "bg-amber-50 text-amber-700 border border-amber-100"
    };

    return e(
      "span",
      {
        className:
          "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium tracking-tight " +
          (toneMap[tone] || toneMap.indigo)
      },
      props.text || "Badge"
    );
  }

  function SoftHeaderStrip(props) {
    const items = Array.isArray(props.items) ? props.items : [];
    return e(
      "div",
      {
        className:
          "mb-5 overflow-x-auto rounded-2xl border border-gray-100 bg-white/90 px-4 py-3 shadow-sm transition-all duration-300"
      },
      e(
        "div",
        { className: "flex min-w-max flex-wrap items-center gap-2" },
        items.map(function (item, idx) {
          return e(SoftBadge, {
            key: "badge-" + idx,
            tone: item.tone,
            text: item.text
          });
        })
      )
    );
  }

  function SoftPanelHeading(props) {
    const title = props.title || "Seccion";
    const subtitle = props.subtitle || "";
    const tone = props.tone || "indigo";

    return e(
      "div",
      { className: "flex items-center gap-2.5" },
      e("span", {
        className:
          "inline-flex h-8 w-8 items-center justify-center rounded-xl border border-gray-100 bg-white text-gray-500 shadow-sm",
        "data-lucide": props.icon || "layout-panel-left"
      }),
      e(
        "div",
        null,
        e("p", { className: "m-0 text-sm font-semibold tracking-tight text-gray-900" }, title),
        subtitle ? e("p", { className: "m-0 text-xs text-gray-500" }, subtitle) : null
      ),
      e("div", { className: "ml-1.5" }, e(SoftBadge, { tone: tone, text: "Live" }))
    );
  }

  function SoftKpiRow(props) {
    const items = Array.isArray(props.items) ? props.items : [];

    return e(
      "div",
      { className: "kpis" },
      items.map(function (item, idx) {
        return e(
          "article",
          { key: "kpi-" + idx, className: "flat card" },
          e("p", { className: "kpi-label" }, item.label || "Metrica"),
          e("div", { className: "kpi-number", id: item.valueId || undefined }, item.initialValue || "0"),
          e(
            "div",
            {
              className: "kpi-trend",
              id: item.subtitleId || undefined
            },
            item.subtitle || ""
          )
        );
      })
    );
  }

  function SoftActionButtons(props) {
    const items = Array.isArray(props.items) ? props.items : [];

    return e(
      "div",
      { className: "flex flex-wrap gap-2" },
      items.map(function (item, idx) {
        const tone = item.tone || "ghost";
        const toneClass =
          tone === "primary"
            ? "rounded-xl bg-indigo-50 text-indigo-600 font-medium hover:bg-indigo-100 transition-colors duration-200"
            : "rounded-xl text-gray-500 hover:bg-gray-50 hover:text-gray-900 transition-colors duration-200";

        return e(
          "button",
          {
            key: "action-" + idx,
            id: item.id || undefined,
            type: item.type || "button",
            className: "btn " + toneClass
          },
          item.text || "Accion"
        );
      })
    );
  }

  function SoftEmptyState(props) {
    return e(
      "div",
      {
        className:
          "empty rounded-2xl border border-dashed border-gray-200 bg-white/90 text-gray-500"
      },
      props.text || "Sin resultados"
    );
  }

  function SoftCardHeader(props) {
    const title = props.title || "Seccion";
    const action = props.action || null;

    return e(
      "div",
      { className: "card-head" },
      e("h3", null, title),
      action
        ? e(
            "button",
            {
              id: action.id || undefined,
              type: action.type || "button",
              className: action.className || "btn"
            },
            action.text || "Accion"
          )
        : null
    );
  }

  function mountSoftHeaderStrip(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftHeaderStrip, props || {}));

    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  function mountSoftPanelHeading(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftPanelHeading, props || {}));

    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  function mountSoftKpiRow(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftKpiRow, props || {}));
  }

  function mountSoftActionButtons(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftActionButtons, props || {}));
  }

  function mountSoftEmptyState(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftEmptyState, props || {}));
  }

  function mountSoftCardHeader(targetId, props) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const root = ReactDOMRef.createRoot(target);
    root.render(e(SoftCardHeader, props || {}));
  }

  window.QCSoftUI = {
    mountSoftHeaderStrip: mountSoftHeaderStrip,
    mountSoftPanelHeading: mountSoftPanelHeading,
    mountSoftKpiRow: mountSoftKpiRow,
    mountSoftActionButtons: mountSoftActionButtons,
    mountSoftEmptyState: mountSoftEmptyState,
    mountSoftCardHeader: mountSoftCardHeader
  };
})();
