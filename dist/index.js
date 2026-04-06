(function (deckyFrontendLib, React) {
  'use strict';

  // ── Steam helpers (OpenGOAL-style) ──────────────────────────────────────────
  // steam64 completo para auth backend
  const getSteamID64 = () => window.App?.m_CurrentUser?.strSteamID ?? "0";

  // steam32 para la ruta de shortcuts.vdf  (igual que OpenGOAL)
  const getSteamID32 = () =>
    BigInt.asUintN(32, BigInt(window.App?.m_CurrentUser?.strSteamID ?? "0")).toString();

  // ── Steam restart (igual que OpenGOAL) ──────────────────────────────────────
  const restartSteam = () => SteamClient.User.StartRestart();
  const showRestartConfirm = () => {
    deckyFrontendLib.showModal(
      window.SP_REACT.createElement(deckyFrontendLib.ConfirmModal, {
        strTitle: "¿Reiniciar Steam?",
        strCancelButtonText: "Más tarde",
        strOKButtonText: "Reiniciar ahora",
        strDescription:
          "Steam necesita reiniciarse para que el acceso directo aparezca en tu biblioteca.",
        onOK: restartSteam,
      })
    );
  };

  // ── Formatters ──────────────────────────────────────────────────────────────
  const fmtSize = (bytes) => {
    if (!bytes) return "";
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    return `${(bytes / 1e6).toFixed(0)} MB`;
  };

  const fmtDate = (iso) => {
    if (!iso) return "Nunca";
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        day: "2-digit", month: "short", year: "numeric",
      });
    } catch { return iso; }
  };

  // ── Status badge ────────────────────────────────────────────────────────────
  const STATUS_COLOR = {
    idle: "#8899aa", scanning: "#f0c040", downloading: "#40aaff",
    installing: "#40aaff", completed: "#39ff14", error: "#ff4444",
  };

  const StatusBadge = ({ status }) =>
    window.SP_REACT.createElement("div", {
      style: {
        display: "inline-flex", alignItems: "center", gap: "6px",
        padding: "3px 10px", borderRadius: "99px",
        background: `${STATUS_COLOR[status] || "#888"}22`,
        border: `1px solid ${STATUS_COLOR[status] || "#888"}55`,
      }
    }, [
      window.SP_REACT.createElement("div", {
        key: "dot",
        style: {
          width: 7, height: 7, borderRadius: "50%",
          background: STATUS_COLOR[status] || "#888",
          boxShadow: `0 0 6px ${STATUS_COLOR[status] || "#888"}`,
        }
      }),
      window.SP_REACT.createElement("span", {
        key: "txt",
        style: { color: STATUS_COLOR[status] || "#888", fontSize: "11px", fontWeight: 600 }
      }, (status || "Unknown").toUpperCase())
    ]);

  // ── Progress bar ─────────────────────────────────────────────────────────────
  const ProgressBar = ({ pct, speed, eta }) =>
    window.SP_REACT.createElement("div", { style: { width: "100%", marginTop: 4 } }, [
      window.SP_REACT.createElement("div", {
        key: "bg",
        style: { position: "relative", height: 6, borderRadius: 3, background: "rgba(255,255,255,0.1)", overflow: "hidden" }
      }, window.SP_REACT.createElement("div", {
        style: {
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: `${pct}%`, background: "linear-gradient(90deg,#1a73e8,#40aaff)",
          transition: "width 0.4s ease", borderRadius: 3,
        }
      })),
      window.SP_REACT.createElement("div", {
        key: "info",
        style: { display: "flex", justifyContent: "space-between", marginTop: 2, fontSize: "9px", color: "#8899aa" }
      }, [
        window.SP_REACT.createElement("span", { key: "p" }, `${pct.toFixed(1)}%`),
        speed && window.SP_REACT.createElement("span", { key: "s" }, speed),
        eta   && window.SP_REACT.createElement("span", { key: "e" }, `ETA: ${eta}`)
      ])
    ]);

  // ── Pack card (Manual tab) ───────────────────────────────────────────────────
  const PackCard = ({ entry, busy, onInstall }) => {
    const [expanded, setExpanded] = React.useState(false);
    const hasError = entry.remote_version === "0";

    return window.SP_REACT.createElement("div", {
      style: { width: "100%", borderBottom: "1px solid rgba(255,255,255,0.06)", paddingBottom: 8 }
    }, [
      window.SP_REACT.createElement("div", {
        key: "hdr",
        style: { display: "flex", justifyContent: "space-between", alignItems: "center" }
      }, [
        window.SP_REACT.createElement("div", { key: "info", style: { flex: 1 } }, [
          window.SP_REACT.createElement("div", {
            key: "name",
            style: { fontSize: "12px", fontWeight: "bold", color: "#fff" }
          }, entry.friendly_name),
          window.SP_REACT.createElement("div", {
            key: "ver",
            style: { fontSize: "9px", color: hasError ? "#ff4444" : "#8899aa", marginTop: 1 }
          }, hasError
            ? "❌ No se pudo contactar el mirror"
            : `Local v${entry.local_version} → Remote v${entry.remote_version}${entry.file_size ? "  ·  " + fmtSize(entry.file_size) : ""}`
          ),
        ]),
        window.SP_REACT.createElement(deckyFrontendLib.ButtonItem, {
          key: "btn",
          layout: "inline",
          disabled: busy || !entry.needs_update || hasError,
          onClick: () => onInstall(entry.pack_name)
        }, entry.needs_update ? "Update" : "OK"),
      ]),
      entry.description && window.SP_REACT.createElement("div", { key: "expand" }, [
        window.SP_REACT.createElement("button", {
          key: "toggle",
          onClick: () => setExpanded(!expanded),
          style: {
            background: "none", border: "none", color: "#8899aa",
            fontSize: "9px", cursor: "pointer", padding: "2px 0", marginTop: 2
          }
        }, expanded ? "▲ Ocultar" : "▼ Ver detalles"),
        expanded && window.SP_REACT.createElement("div", {
          key: "desc",
          style: {
            fontSize: "9px", color: "#aabbcc", marginTop: 4,
            whiteSpace: "pre-wrap", lineHeight: 1.5,
            background: "rgba(255,255,255,0.04)", borderRadius: 4, padding: "6px 8px"
          }
        }, entry.description)
      ]),
    ]);
  };

  // ── MOTD card ────────────────────────────────────────────────────────────────
  const MotdCard = ({ item }) => {
    const [expanded, setExpanded] = React.useState(false);
    return window.SP_REACT.createElement("div", {
      style: { borderBottom: "1px solid rgba(255,255,255,0.06)", paddingBottom: 8, marginBottom: 6 }
    }, [
      window.SP_REACT.createElement("div", {
        key: "title",
        style: { fontSize: "11px", fontWeight: "bold", color: item.titlecolour || "#fff" }
      }, item.title),
      window.SP_REACT.createElement("button", {
        key: "toggle",
        onClick: () => setExpanded(!expanded),
        style: { background: "none", border: "none", color: "#8899aa", fontSize: "9px", cursor: "pointer", padding: "2px 0" }
      }, expanded ? "▲ Ocultar" : "▼ Leer"),
      expanded && window.SP_REACT.createElement("div", {
        key: "sub",
        style: {
          fontSize: "9px", color: item.SubColour || "#ccc", marginTop: 4,
          whiteSpace: "pre-wrap", lineHeight: 1.5,
          background: "rgba(255,255,255,0.04)", borderRadius: 4, padding: "6px 8px"
        }
      }, item.sub)
    ]);
  };

  // ── Plugin icon from logo.png (base64, loaded once) ──────────────────────────
  // Se carga en el mount del componente raíz y se guarda en estado global.
  let _logoBase64 = null;
  const LogoIcon = ({ serverAPI }) => {
    const [src, setSrc] = React.useState(_logoBase64);
    React.useEffect(() => {
      if (_logoBase64) { setSrc(_logoBase64); return; }
      serverAPI.callPluginMethod("read_logo_image_as_base64", {}).then(res => {
        if (res.success && res.result) {
          _logoBase64 = res.result;
          setSrc(res.result);
        }
      });
    }, []);
    if (!src) return window.SP_REACT.createElement("span", { style: { color: "#1a73e8", fontWeight: "bold" } }, "Δ");
    return window.SP_REACT.createElement("img", {
      src: `data:image/png;base64,${src}`,
      style: { width: "10%", height: "10%", objectFit: "contain" }
    });
  };

  // ── Main content ─────────────────────────────────────────────────────────────
  const Content = ({ serverAPI }) => {
    const [state, setState] = React.useState({
      status: "idle", logs: [], progress: {}, queue: [], remote: [],
      motd: [], scan_frequency: "manual", last_scan: null
    });
    const [tab, setTab] = React.useState("auto");
    const [shortcutExists, setShortcutExists] = React.useState(false);

    const call = async (method, params = {}) => {
      const res = await serverAPI.callPluginMethod(method, params);
      return res.success ? res.result : null;
    };

    const refresh = async () => {
      const s = await call("get_state");
      if (s) setState(s);
    };

    // Comprueba si el shortcut ya existe al cargar
    const checkShortcut = async () => {
      const exists = await call("shortcut_already_created", { steam32: getSteamID32() });
      setShortcutExists(!!exists);
    };

    React.useEffect(() => {
      refresh();
      checkShortcut();
      const iv = setInterval(refresh, 5000);
      return () => clearInterval(iv);
    }, []);

    const busy = ["scanning", "downloading", "installing"].includes(state.status);
    const TABS = ["auto", "manual", "news", "settings", "logs"];

    // ── Función para crear shortcut + imágenes + reinicio (OpenGOAL-style) ────
    const handleCreateShortcut = async () => {
      const steam32 = getSteamID32();

      // 1. Crear el shortcut en shortcuts.vdf
      const appId = await call("create_shortcut", { steam32 });
      window.console.log("[DeckyDelta] shortcut appId:", appId);

      if (appId !== null && appId !== undefined) {
        // 2. Pequeña cápsula (portrait) — tipo 0
        const smallData = await call("read_small_image_as_base64");
        if (smallData) await SteamClient.Apps.SetCustomArtworkForApp(appId, smallData, "png", 0);

        // 3. Hero (banner) — tipo 1
        const heroData = await call("read_hero_image_as_base64");
        if (heroData) await SteamClient.Apps.SetCustomArtworkForApp(appId, heroData, "png", 1);

        // 4. Logo — tipo 2
        const logoData = await call("read_logo_image_as_base64");
        if (logoData) await SteamClient.Apps.SetCustomArtworkForApp(appId, logoData, "png", 2);

        // 5. Cápsula ancha (horizontal) — tipo 3
        const wideData = await call("read_wide_image_as_base64");
        if (wideData) await SteamClient.Apps.SetCustomArtworkForApp(appId, wideData, "png", 3);

        // NOTA: el icono del .exe se establece directamente en el campo "icon" del shortcut VDF

        setShortcutExists(true);
        showRestartConfirm();
      }
    };

    // ── Tab bar ────────────────────────────────────────────────────────────────
    const tabBar = window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "tabs" },
      window.SP_REACT.createElement("div", { style: { display: "flex", gap: "3px", width: "100%" } },
        TABS.map(t => window.SP_REACT.createElement("button", {
          key: t,
          className: `d-tab ${tab === t ? "d-active" : "d-inactive"}`,
          onClick: () => setTab(t)
        }, t === "auto" ? "AUTO" : t === "manual" ? "MANUAL" : t === "news" ? "NEWS" : t === "settings" ? "⚙" : "LOGS"))
      )
    );

    // ── AUTO tab ───────────────────────────────────────────────────────────────
    const tabAuto = tab === "auto" && window.SP_REACT.createElement(window.SP_REACT.Fragment, null, [
      // Botón Scan
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "scan" },
        window.SP_REACT.createElement(deckyFrontendLib.ButtonItem, {
          layout: "below", disabled: busy,
          onClick: () => call("scan_mirrors")
        }, "🔍 Buscar Actualizaciones")
      ),
      // Botón Instalar todo
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "install" },
        window.SP_REACT.createElement(deckyFrontendLib.ButtonItem, {
          layout: "below", disabled: busy || state.remote.length === 0,
          onClick: () => call("install_auto", { steam64: getSteamID64() })
        }, `⬇ Instalar Todo${state.remote.filter(e => e.needs_update).length > 0 ? ` (${state.remote.filter(e => e.needs_update).length})` : ""}`)
      ),
      // Botón Crear acceso directo (siempre visible en AUTO, atenuado si ya existe)
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "shortcut" },
        window.SP_REACT.createElement(deckyFrontendLib.Field, {
          childrenLayout: "below",
          description: shortcutExists
            ? "✅ Acceso directo ya creado (Proton Experimental + XACT aplicados)"
            : "Añade Delta Online a tu biblioteca con Proton Experimental y XACT fix automáticos"
        },
          window.SP_REACT.createElement(deckyFrontendLib.DialogButton, {
            disabled: shortcutExists,
            onClick: handleCreateShortcut
          }, "🎮 Crear Acceso Directo")
        )
      ),
      // Último scan
      state.last_scan && window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "lastscan" },
        window.SP_REACT.createElement("div", {
          style: { fontSize: "9px", color: "#8899aa" }
        }, `Último scan: ${fmtDate(state.last_scan)}`)
      ),
    ]);

    // ── MANUAL tab ─────────────────────────────────────────────────────────────
    const tabManual = tab === "manual" && window.SP_REACT.createElement(window.SP_REACT.Fragment, null,
      state.remote.length === 0
        ? window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "empty" },
            window.SP_REACT.createElement("div", { style: { color: "#8899aa", fontSize: "10px" } },
              "Haz Scan primero desde la pestaña AUTO.")
          )
        : state.remote.map(entry =>
            window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: entry.pack_name },
              window.SP_REACT.createElement(PackCard, {
                entry, busy,
                onInstall: (pn) => call("install_manual", { pack_name: pn, steam64: getSteamID64() })
              })
            )
          )
    );

    // ── NEWS tab ───────────────────────────────────────────────────────────────
    const tabNews = tab === "news" && window.SP_REACT.createElement(window.SP_REACT.Fragment, null,
      state.motd.length === 0
        ? window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "nonews" },
            window.SP_REACT.createElement("div", { style: { color: "#8899aa", fontSize: "10px" } }, "Cargando noticias…")
          )
        : state.motd.map((item, i) =>
            window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: i },
              window.SP_REACT.createElement(MotdCard, { item })
            )
          )
    );

    // ── SETTINGS tab ──────────────────────────────────────────────────────────
    const FREQ_OPTIONS = [
      { value: "manual",  label: "Manual (sin auto-scan)" },
      { value: "daily",   label: "Cada día" },
      { value: "15days",  label: "Cada 15 días" },
      { value: "30days",  label: "Cada 30 días" },
    ];

    const tabSettings = tab === "settings" && window.SP_REACT.createElement(window.SP_REACT.Fragment, null, [
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "freqlabel" },
        window.SP_REACT.createElement("div", { style: { fontSize: "10px", color: "#ccc", marginBottom: 4 } },
          "🔄 Frecuencia de auto-scan")
      ),
      ...FREQ_OPTIONS.map(opt =>
        window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: opt.value },
          window.SP_REACT.createElement("div", {
            style: {
              display: "flex", alignItems: "center", justifyContent: "space-between",
              width: "100%", cursor: "pointer",
              padding: "4px 8px", borderRadius: 6,
              background: state.scan_frequency === opt.value ? "rgba(26,115,232,0.18)" : "transparent",
              border: state.scan_frequency === opt.value ? "1px solid #1a73e8" : "1px solid transparent",
            },
            onClick: () => call("set_scan_frequency", { frequency: opt.value })
          }, [
            window.SP_REACT.createElement("span", { key: "lbl", style: { fontSize: "10px", color: "#ddd" } }, opt.label),
            state.scan_frequency === opt.value &&
              window.SP_REACT.createElement("span", { key: "chk", style: { color: "#39ff14", fontSize: "12px" } }, "✔")
          ])
        )
      ),
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "lastscan" },
        window.SP_REACT.createElement("div", { style: { fontSize: "9px", color: "#8899aa" } },
          `Último scan: ${fmtDate(state.last_scan)}`)
      ),
    ]);

    // ── LOGS tab ───────────────────────────────────────────────────────────────
    const tabLogs = tab === "logs" && window.SP_REACT.createElement(window.SP_REACT.Fragment, null, [
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "logbox" },
        window.SP_REACT.createElement("div", { className: "log-box" },
          state.logs.map((l, i) => window.SP_REACT.createElement("div", { key: i }, l))
        )
      ),
      window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "clr" },
        window.SP_REACT.createElement(deckyFrontendLib.ButtonItem, {
          layout: "below",
          onClick: () => call("clear_logs")
        }, "🗑 Clear Logs")
      ),
    ]);

    // ── Render ─────────────────────────────────────────────────────────────────
    return window.SP_REACT.createElement(window.SP_REACT.Fragment, null, [
      window.SP_REACT.createElement("style", { key: "css" }, `
        .d-tab { flex:1; padding:5px 2px; border:none; border-radius:4px; font-size:9px; font-weight:bold; cursor:pointer; }
        .d-active { background:#1a73e8; color:white; }
        .d-inactive { background:rgba(255,255,255,0.05); color:#889; }
        .log-box { background:#000; color:#0f0; font-family:monospace; font-size:9px; padding:8px; max-height:150px; overflow-y:auto; border-radius:4px; }
      `),
      window.SP_REACT.createElement(deckyFrontendLib.PanelSection, { key: "panel" }, [
        window.SP_REACT.createElement(deckyFrontendLib.PanelSectionRow, { key: "hdr" },
          window.SP_REACT.createElement("div", {
            style: { display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }
          }, [
            window.SP_REACT.createElement("b", { key: "title" }, "Decky Delta"),
            window.SP_REACT.createElement(StatusBadge, { key: "badge", status: state.status })
          ])
        ),
        tabBar,
        tabAuto,
        tabManual,
        tabNews,
        tabSettings,
        tabLogs,
      ])
    ]);
  };

  // ── Plugin definition ────────────────────────────────────────────────────────
  // El icono usa LogoIcon que carga logo.png via base64 desde el backend,
  // reemplazando el triángulo azul "Δ" anterior.
  var index = deckyFrontendLib.definePlugin((serverApi) => ({
    title:   window.SP_REACT.createElement("div", { className: deckyFrontendLib.staticClasses.Title }, "Decky Delta"),
    content: window.SP_REACT.createElement(Content, { serverAPI: serverApi }),
    icon:    window.SP_REACT.createElement(LogoIcon, { serverAPI: serverApi }),
    onDismount() {}
  }));

  return index;

})(DFL, SP_REACT);
