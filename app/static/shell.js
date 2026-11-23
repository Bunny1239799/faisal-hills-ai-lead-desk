/* Premium product shell - navigation, theme, map and future modules.
 *
 * This file ADDS the shell around the operator desk; it owns nothing
 * the desk owns. Views are switched client-side; the desk view keeps
 * every id the existing tests assert. The map runs fully OFFLINE:
 * Leaflet and the OpenStreetMap tiles are bundled locally under
 * /static (no network request is made at runtime, no API key exists,
 * and no lead/inventory/conversation data ever leaves the page).
 *
 * Coming-soon modules are honest: static content, a local-only
 * waitlist note, and nothing that pretends to work.
 */
"use strict";

(function () {

  var $ = function (id) { return document.getElementById(id); };

  /* ---------------------------------------------------------------- */
  /* theme                                                             */
  /* ---------------------------------------------------------------- */
  var themeToggle = $("theme-toggle");
  var themeMeta = document.querySelector('meta[name="theme-color"]');

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    if (themeMeta) themeMeta.setAttribute("content",
      theme === "dark" ? "#0e1116" : "#f4f6f8");
    if (themeToggle) {
      themeToggle.setAttribute("aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    }
    try { localStorage.setItem("fh-theme", theme); } catch (e) { /* page memory only */ }
  }

  (function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("fh-theme"); } catch (e) { /* none */ }
    setTheme(saved === "light" || saved === "dark" ? saved : "dark");
  })();

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      setTheme(document.documentElement.getAttribute("data-theme") === "dark"
        ? "light" : "dark");
    });
  }

  /* ---------------------------------------------------------------- */
  /* views + sidebar                                                   */
  /* ---------------------------------------------------------------- */
  var VIEWS = ["desk", "map", "followups", "reports", "status", "module"];

  function showView(name) {
    VIEWS.forEach(function (view) {
      var node = $("view-" + view);
      if (node) node.classList.toggle("active", view === name);
    });
    Array.prototype.forEach.call(
      document.querySelectorAll("#sidebar-nav .nav-item"), function (item) {
        var active = item.getAttribute("data-view") === name;
        item.classList.toggle("active", active);
        if (active) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
    if (name === "map") initMap();
    if (name === "followups") loadFollowUps();
    if (name === "reports") loadReport();
    if (name === "status") loadStatus();
  }

  Array.prototype.forEach.call(
    document.querySelectorAll("#sidebar-nav .nav-item"), function (item) {
      item.addEventListener("click", function () {
        if (item.hasAttribute("data-module")) {
          renderModule(item.getAttribute("data-module"));
          showView("module");
        } else {
          showView(item.getAttribute("data-view") || "desk");
        }
      });
    });

  var collapse = $("sidebar-collapse");
  if (collapse) {
    collapse.addEventListener("click", function () {
      var collapsed = !document.body.classList.contains("sidebar-collapsed");
      document.body.classList.toggle("sidebar-collapsed", collapsed);
      collapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
      collapse.setAttribute("aria-label",
        collapsed ? "Expand sidebar" : "Collapse sidebar");
    });
  }

  /* ---------------------------------------------------------------- */
  /* notifications - real escalations from the loaded conversations    */
  /* ---------------------------------------------------------------- */
  var notifBtn = $("notifications");
  var notifPop = $("notif-pop");
  var notifDot = $("notif-dot");

  function renderNotifications() {
    if (!notifPop || !window.operatorDesk) return;
    var escalated = [];
    (window.operatorDesk.sessions || []).forEach(function (session) {
      if (session.escalation || session.takenOver) {
        escalated.push(session);
      }
    });
    if (notifDot) notifDot.hidden = escalated.length === 0;
    notifPop.textContent = "";
    if (!escalated.length) {
      var empty = document.createElement("p");
      empty.className = "notif-empty";
      empty.textContent = "No escalations or take-overs in this page session.";
      notifPop.appendChild(empty);
      return;
    }
    escalated.forEach(function (session) {
      var row = document.createElement("div");
      row.className = "notif-row";
      row.textContent = (session.label || session.id) + ": " +
        (session.escalation ? "escalation - human review required"
                            : "taken over by the operator");
      notifPop.appendChild(row);
    });
  }

  if (notifBtn && notifPop) {
    notifBtn.addEventListener("click", function () {
      var open = notifPop.hidden;
      renderNotifications();
      notifPop.hidden = !open;
      notifBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* The desk publishes its sessions so the shell can read them
     without owning them. */
  window.operatorDesk = window.operatorDesk || {};
  var publishSessions = function () {
    /* the desk keeps sessions in its closure; the shell re-reads the
       rail's rendered state through the same public surface it already
       exposes for tests (events) plus the DOM chips */
    var rows = [];
    Array.prototype.forEach.call(
      document.querySelectorAll("#rail-list .rail-button"), function (btn) {
        rows.push({
          label: btn.querySelector(".rail-label")
            ? btn.querySelector(".rail-label").textContent : "",
          escalation: /Escalated/.test(btn.textContent),
          takenOver: /Taken over/.test(btn.textContent)
        });
      });
    window.operatorDesk.railSnapshot = rows;
  };
  window.operatorDesk.publishSessions = publishSessions;

  /* patch the desk's renderAll through the exposed hook: simplest is a
     MutationObserver on the rail */
  var railList = $("rail-list");
  if (railList && typeof MutationObserver !== "undefined") {
    new MutationObserver(function () {
      publishSessions();
      if (notifDot) {
        var any = (window.operatorDesk.railSnapshot || []).some(function (row) {
          return row.escalation || row.takenOver;
        });
        notifDot.hidden = !any;
      }
    }).observe(railList, { childList: true });
  }

  /* ---------------------------------------------------------------- */
  /* the offline map (Leaflet + bundled local tiles)                   */
  /* ---------------------------------------------------------------- */
  /* Faisal Hills sits near Taxila on the GT Road (N-5) corridor. The
     block markers are ILLUSTRATIVE positions around the society area -
     the page says so permanently, and no plot coordinates exist here. */
  var SITE = { lat: 33.992, lng: 72.864 };
  var BLOCKS = {
    "A": { name: "Block A", lat: SITE.lat + 0.006, lng: SITE.lng - 0.006,
           status: "active",
           context: "Within the active serving scope (Blocks A, B, C). General location context only." },
    "B": { name: "Block B", lat: SITE.lat + 0.003, lng: SITE.lng + 0.004,
           status: "active",
           context: "Within the active serving scope (Blocks A, B, C). General location context only." },
    "C": { name: "Block C", lat: SITE.lat - 0.004, lng: SITE.lng + 0.002,
           status: "active",
           context: "Within the active serving scope (Blocks A, B, C). General location context only." },
    "D": { name: "Block D", lat: SITE.lat - 0.008, lng: SITE.lng - 0.005,
           status: "parked",
           context: "Parked scope: the application does not answer about Block D yet." },
    "E": { name: "Executive Block", lat: SITE.lat + 0.001, lng: SITE.lng - 0.011,
           status: "parked",
           context: "Parked scope: the application does not answer about the Executive block yet." },
    "P": { name: "Prime", lat: null, lng: null, status: "unknown",
           context: "Prime is not in the approved inventory. No location or availability is shown until it is." }
  };
  var LANDMARKS = [
    { lat: 33.992, lng: 72.864, label: "Faisal Hills (area)" },
    { lat: 33.990, lng: 72.909, label: "Taxila (toward GT Road east)" },
    { lat: 34.020, lng: 72.820, label: "GT Road / N-5 corridor (north-west)" }
  ];

  var mapInstance = null;
  var mapInitialised = false;

  function initMap() {
    var canvas = $("map-canvas");
    if (!canvas || mapInitialised || typeof L === "undefined") return;
    mapInitialised = true;

    mapInstance = L.map("map-canvas", {
      center: [SITE.lat, SITE.lng],
      zoom: 13,
      minZoom: 10,
      maxZoom: 14,
      zoomControl: true,
      attributionControl: true
    });
    /* fully local tiles: no runtime network request of any kind */
    L.tileLayer("/static/map/tiles/{z}/{x}/{y}.png", {
      minZoom: 10,
      maxZoom: 14,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(mapInstance);

    LANDMARKS.forEach(function (mark) {
      L.circleMarker([mark.lat, mark.lng], {
        radius: 5, color: "#5b9cff", weight: 2, fillOpacity: 0.9
      }).addTo(mapInstance).bindTooltip(mark.label, { direction: "top" });
    });

    Object.keys(BLOCKS).forEach(function (key) {
      var block = BLOCKS[key];
      if (block.lat === null) return;
      var icon = L.divIcon({
        className: "",
        html: '<div class="block-marker' +
              (block.status === "parked" ? " parked" : "") + '"></div>',
        iconSize: [14, 14], iconAnchor: [7, 7]
      });
      L.marker([block.lat, block.lng], { icon: icon })
        .addTo(mapInstance)
        .bindTooltip(block.name + " (illustrative position)", { direction: "top" });
    });

    setTimeout(function () { mapInstance.invalidateSize(); }, 60);
  }

  Array.prototype.forEach.call(
    document.querySelectorAll(".map-filters [data-block]"), function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-block");
        var block = BLOCKS[key];
        $("map-panel-title").textContent = block ? block.name : "Block";
        if (!block) return;
        var body = $("map-panel-body");
        body.textContent = block.context;
        var note = document.createElement("p");
        note.className = "map-note";
        note.textContent = block.lat === null
          ? "Not in the approved inventory - nothing is shown for it."
          : "Plot-level mapping coming soon. Position shown is illustrative, not a survey.";
        var old = $("map-panel").querySelector(".map-note");
        if (old) old.remove();
        $("map-panel").appendChild(note);
        if (block.lat !== null && mapInstance) {
          mapInstance.setView([block.lat, block.lng], 13);
        }
      });
    });

  /* ---------------------------------------------------------------- */
  /* coming-soon modules                                               */
  /* ---------------------------------------------------------------- */
  var MODULES = {
    inventory: {
      name: "Inventory",
      value: "Your inventory becomes the source of truth.",
      caps: ["Inventory upload", "Validation", "Availability status",
             "Owner-controlled promotion"],
      benefit: "Load your own plots once, and every answer in the desk is grounded in them - nothing else."
    },
    viz3d: {
      name: "3D Visualization",
      value: "Help customers understand plots and communities visually.",
      caps: ["3D plot view", "Community overview", "Block visualization",
             "Interactive property context"],
      benefit: "Customers see what they are buying into - fewer site visits wasted on mismatched expectations."
    },
    voice: {
      name: "Voice AI",
      value: "Handle inbound inquiries through voice with human-controlled escalation.",
      caps: ["Voice-to-lead-state", "Spoken property summaries", "Call handoff",
             "Operator review"],
      benefit: "Answer every call instantly at off-hours, with a human one click away."
    },
    intel: {
      name: "Sales Intelligence",
      value: "Understand what customers want that your inventory does not currently offer.",
      caps: ["Demand trends", "Inventory gaps", "Popular sizes and budgets",
             "Missed-opportunity signals"],
      benefit: "Buy land where the demand actually is, before your competitors see it."
    },
    settings: {
      name: "Settings",
      value: "Configure your agency workspace safely.",
      caps: ["Agency profile", "Business rules", "AI model selection",
             "User roles and permissions"],
      benefit: "Your rules, your inventory, your model - controlled by you, not by us."
    }
  };

  var MODULE_ICONS = {
    inventory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M3.5 6h17v13h-17zM3.5 10.5h17M9 6v13"/></svg>',
    viz3d: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M12 3 20 7.5v9L12 21 4 16.5v-9zM12 12l8-4.5M12 12 4 7.5M12 12v9"/></svg>',
    voice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    intel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 20V10M9.3 20V4M14.7 20v-9M20 20V7"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="12" cy="12" r="3.4"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/></svg>'
  };

  function renderModule(key) {
    var mod = MODULES[key];
    if (!mod) return;
    $("module-icon").innerHTML = MODULE_ICONS[key] || "";
    $("module-name").textContent = mod.name;
    $("module-value").textContent = mod.value;
    var caps = $("module-caps");
    caps.textContent = "";
    mod.caps.forEach(function (cap) {
      var li = document.createElement("li");
      li.textContent = cap;
      caps.appendChild(li);
    });
    $("module-benefit").textContent =
      "Expected benefit: " + mod.benefit;
    var waitlist = $("module-waitlist");
    waitlist.textContent = "Join waitlist";
    waitlist.disabled = false;
  }

  var waitlistBtn = $("module-waitlist");
  if (waitlistBtn) {
    waitlistBtn.addEventListener("click", function () {
      waitlistBtn.disabled = true;
      waitlistBtn.textContent = "Noted locally - nothing was sent";
      var note = document.createElement("p");
      note.className = "module-note";
      note.textContent = "Interest recorded on this page only. No data left this machine.";
      waitlistBtn.parentNode.insertBefore(note, waitlistBtn.nextSibling);
    });
  }

  /* ---------------------------------------------------------------- */
  /* follow-ups queue (ACTIVE module)                                  */
  /* ---------------------------------------------------------------- */
  var STAGE_LABEL = { NEW: "New", QUALIFYING: "Qualifying",
    QUALIFIED: "Qualified", FOLLOW_UP: "Follow up", ESCALATED: "Escalated",
    TAKEN_OVER: "Taken over", CLOSED_LOST: "Closed - lost",
    CLOSED_WON: "Closed - won" };
  var SECTION_TITLES = {
    today: "Due today", overdue: "Overdue", this_week: "This week",
    no_activity: "No recent activity", escalated: "Escalated",
    unmet: "Unmet demand"
  };

  function fqBadge(text, cls) {
    var span = document.createElement("span");
    span.className = "temp " + (cls || "");
    span.textContent = text;
    return span;
  }

  function loadFollowUps() {
    var wrap = $("fq-wrap");
    var empty = $("fq-empty");
    if (!wrap) return;
    if (empty) { empty.textContent = "Loading the follow-up queue..."; empty.hidden = false; }
    fetch("/api/follow-ups").then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (data) {
      wrap.textContent = "";
      if (empty) empty.remove();
      var sections = data.sections || {};
      var total = 0;
      Object.keys(SECTION_TITLES).forEach(function (key) {
        var items = sections[key] || [];
        total += items.length;
        var head = document.createElement("h2");
        head.className = "fq-section-title";
        head.textContent = SECTION_TITLES[key] + " (" + items.length + ")";
        wrap.appendChild(head);
        if (!items.length) {
          var none = document.createElement("p");
          none.className = "empty-note";
          none.textContent = "Nothing here.";
          wrap.appendChild(none);
          return;
        }
        var fqSource = $("fq-source");
        var wanted = fqSource ? fqSource.value : "";
        items.forEach(function (item) {
          if (!wanted || (item.source || "OPERATOR_DESK") === wanted) {
            wrap.appendChild(fqCard(item));
          }
        });
      });
      if (!total) {
        var quiet = document.createElement("p");
        quiet.className = "empty-note";
        quiet.textContent = "No lead currently needs a follow-up.";
        wrap.appendChild(quiet);
      }
    }).catch(function () {
      if (empty) {
        empty.textContent =
          "The follow-up queue could not be loaded. Retry from this page.";
        empty.hidden = false;
      }
    });
  }

  function fqCard(item) {
    var card = document.createElement("div");
    card.className = "option-card fq-card";

    var head = document.createElement("div");
    head.className = "opt-head";
    var name = document.createElement("span");
    name.className = "cell";
    name.textContent = item.label || item.lead_id;
    head.appendChild(name);
    head.appendChild(fqBadge(STAGE_LABEL[item.stage] || item.stage));
    head.appendChild(fqBadge(item.temperature,
      item.temperature === "HOT" ? "hot" :
      item.temperature === "WARM" ? "warm" : "cold"));
    head.appendChild(fqBadge("Score " + item.score.score, ""));
    card.appendChild(head);

    var meta = document.createElement("p");
    meta.className = "opt-foot";
    var last = item.days_since_activity === null ? "no activity recorded"
      : item.days_since_activity + " day(s) since activity";
    meta.textContent = "Last contact: " + last +
      " · Reason: " + (item.follow_up_reason || "-") +
      " · Routing: " + item.routing;
    card.appendChild(meta);

    var draft = item.follow_up_draft || {};
    var box = document.createElement("details");
    box.className = "fq-draft";
    var summary = document.createElement("summary");
    summary.textContent = "AI-drafted follow-up (human approval required)";
    box.appendChild(summary);
    var text = document.createElement("p");
    text.textContent = draft.draft || "";
    box.appendChild(text);
    var notes = document.createElement("p");
    notes.className = "opt-disclaimer";
    notes.textContent = "Reason: " + (draft.reason || "-") +
      " · Evidence: requirements the customer stated (" +
      ((draft.evidence || {}).fields_known || []).join(", ") + ")" +
      " · Draft only - nothing was sent.";
    box.appendChild(notes);
    card.appendChild(box);

    var actions = document.createElement("div");
    actions.className = "fq-actions";
    [["followup_approved", "Approve"], ["followup_edited", "Edit"],
     ["followup_rejected", "Reject"], ["followup_copied", "Copy draft"]]
      .forEach(function (pair) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn" + (pair[0] === "followup_rejected"
          ? " danger" : "");
        btn.textContent = pair[1];
        btn.addEventListener("click", function () {
          fetch("/api/conversation/" + encodeURIComponent(item.lead_id) +
                "/draft-action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: pair[0] })
          }).then(function (response) {
            if (!response.ok) throw new Error("HTTP " + response.status);
            btn.disabled = true;
            btn.textContent = pair[1] + " - recorded";
          }).catch(function () {
            btn.disabled = true;
            btn.textContent = pair[1] + " - NOT recorded (visible failure)";
          });
        });
        actions.appendChild(btn);
      });
    card.appendChild(actions);
    return card;
  }

  /* ---------------------------------------------------------------- */
  /* lead detail drawer                                                */
  /* ---------------------------------------------------------------- */
  function openLeadDrawer(leadId) {
    var drawer = $("lead-drawer");
    var scrim = $("drawer-scrim");
    var body = $("drawer-body");
    if (!drawer || !body) return;
    drawer.hidden = false;
    scrim.hidden = false;
    body.textContent = "Loading lead...";
    $("drawer-title").textContent = "Lead";

    fetch("/api/leads-pipeline/" + encodeURIComponent(leadId))
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (view) { renderDrawer(view); })
      .catch(function () {
        body.textContent = "The lead details could not be loaded. " +
          "Close and retry.";
      });
  }

  function drawerSection(title) {
    var head = document.createElement("h3");
    head.textContent = title;
    $("drawer-body").appendChild(head);
  }

  function drawerLine(text) {
    var line = document.createElement("p");
    line.className = "context-sub";
    line.textContent = text;
    $("drawer-body").appendChild(line);
  }

  function postLead(leadId, path, payload) {
    return fetch("/api/leads-pipeline/" + encodeURIComponent(leadId) + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    });
  }

  function renderDrawer(view) {
    var body = $("drawer-body");
    body.textContent = "";
    $("drawer-title").textContent = view.label || view.lead_id;

    drawerSection("Pipeline");
    drawerLine("Stage: " + (STAGE_LABEL[view.stage] || view.stage) +
      " · Temperature: " + view.temperature +
      " · Score: " + view.score.score + "/100");
    drawerLine(view.temperature_rule);
    drawerLine("Routing suggestion: " + view.routing +
      " (a suggestion - the operator stays in control)");
    drawerLine("System suggests stage: " +
      (STAGE_LABEL[view.suggested_stage] || view.suggested_stage) +
      " - you approve any change.");

    var sourceRow = document.createElement("div");
    sourceRow.className = "fq-actions";
    var sourceSelect = document.createElement("select");
    sourceSelect.setAttribute("aria-label", "Lead source");
    var sources = ["OPERATOR_DESK", "DEMO", "MANUAL_ENTRY",
                   "WHATSAPP_MANUAL", "WEBSITE", "REFERRAL", "OTHER"];
    sources.forEach(function (source) {
      var option = document.createElement("option");
      option.value = source;
      option.textContent = source.replace("_", " ").toLowerCase();
      if ((view.source || "OPERATOR_DESK") === source) option.selected = true;
      sourceSelect.appendChild(option);
    });
    sourceRow.appendChild(sourceSelect);
    var sourceBtn = document.createElement("button");
    sourceBtn.type = "button";
    sourceBtn.className = "btn";
    sourceBtn.textContent = "Set source";
    sourceBtn.addEventListener("click", function () {
      postLead(view.lead_id, "/source",
               { source: sourceSelect.value }).then(function (fresh) {
        sourceBtn.textContent = "Source recorded";
        renderDrawer(fresh);
      }).catch(function () {
        sourceBtn.textContent = "Not recorded (visible failure)";
      });
    });
    sourceRow.appendChild(sourceBtn);
    body.appendChild(sourceRow);

    var stageRow = document.createElement("div");
    stageRow.className = "fq-actions";
    var stageSelect = document.createElement("select");
    stageSelect.setAttribute("aria-label", "New stage");
    Object.keys(STAGE_LABEL).forEach(function (stage) {
      var option = document.createElement("option");
      option.value = stage;
      option.textContent = STAGE_LABEL[stage];
      if (stage === view.stage) option.selected = true;
      stageSelect.appendChild(option);
    });
    stageRow.appendChild(stageSelect);
    var stageBtn = document.createElement("button");
    stageBtn.type = "button";
    stageBtn.className = "btn primary";
    stageBtn.textContent = "Approve stage";
    stageBtn.addEventListener("click", function () {
      postLead(view.lead_id, "/stage",
               { stage: stageSelect.value }).then(function (fresh) {
        stageBtn.textContent = "Stage recorded";
        renderDrawer(fresh);
      }).catch(function () {
        stageBtn.textContent = "Not recorded (visible failure)";
      });
    });
    stageRow.appendChild(stageBtn);
    body.appendChild(stageRow);

    drawerSection("Summary");
    drawerLine(view.conversation_summary);
    drawerLine("Missing information: " +
      (view.score.missing.join(", ") || "none"));
    drawerLine("Next best action: " + view.routing);

    drawerSection("Follow-up");
    drawerLine("Due: " + (view.follow_up.due_at
      ? view.follow_up.due_at.slice(0, 10) : "not scheduled"));
    var fuRow = document.createElement("div");
    fuRow.className = "fq-actions";
    var fuInput = document.createElement("input");
    fuInput.type = "date";
    fuInput.setAttribute("aria-label", "Follow-up date");
    fuRow.appendChild(fuInput);
    var fuBtn = document.createElement("button");
    fuBtn.type = "button";
    fuBtn.className = "btn";
    fuBtn.textContent = "Set date";
    fuBtn.addEventListener("click", function () {
      postLead(view.lead_id, "/follow-up",
               { due_at: fuInput.value || null }).then(function (fresh) {
        fuBtn.textContent = "Recorded";
        renderDrawer(fresh);
      }).catch(function () {
        fuBtn.textContent = "Not recorded (visible failure)";
      });
    });
    fuRow.appendChild(fuBtn);
    body.appendChild(fuRow);

    drawerSection("Notes");
    (view.notes || []).forEach(function (note) {
      drawerLine(note.text + " - " + note.by + ", " +
        (note.at || "").slice(0, 10));
    });
    var noteRow = document.createElement("div");
    noteRow.className = "fq-actions";
    var noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.placeholder = "Add an operator note";
    noteInput.setAttribute("aria-label", "New note");
    noteRow.appendChild(noteInput);
    var noteBtn = document.createElement("button");
    noteBtn.type = "button";
    noteBtn.className = "btn";
    noteBtn.textContent = "Add note";
    noteBtn.addEventListener("click", function () {
      postLead(view.lead_id, "/note", { text: noteInput.value })
        .then(function (fresh) {
          noteInput.value = "";
          renderDrawer(fresh);
        }).catch(function () {
          noteBtn.textContent = "Not recorded (visible failure)";
        });
    });
    noteRow.appendChild(noteBtn);
    body.appendChild(noteRow);

    drawerSection("Stage history");
    (view.stage_history || []).forEach(function (entry) {
      if (entry.kind === "source") {
        drawerLine("source: " + (entry.from || "-") + " -> " + entry.to +
          " - " + entry.by + ", " +
          (entry.at || "").slice(0, 16).replace("T", " "));
      } else {
        drawerLine((entry.from || "start") + " -> " + entry.to +
          " - " + entry.by + ", " +
          (entry.at || "").slice(0, 16).replace("T", " ") +
          " (" + entry.reason + ")");
      }
    });

    /* ---- pilot feedback: operator-entered, structured ------------ */
    drawerSection("Pilot feedback");
    var fbRow = document.createElement("div");
    fbRow.className = "fq-actions fq-feedback";
    var fbFields = [
      ["quality", "Response quality",
       ["USEFUL", "NEEDS_EDIT", "NOT_USEFUL"]],
      ["grounding", "Inventory grounding",
       ["GROUNDED", "PARTIALLY_GROUNDED", "NOT_GROUNDED"]],
      ["time_saved", "Time saved", ["NONE", "LOW", "MEDIUM", "HIGH"]],
      ["would_send", "Would send to customer",
       ["YES", "NO", "NEEDS_REVIEW"]],
      ["issue", "Main issue",
       ["NONE", "WRONG_INFORMATION", "MISSING_INVENTORY",
        "CLARIFICATION_NEEDED", "ESCALATION_NEEDED", "UI_CONFUSION",
        "OTHER"]],
    ];
    fbFields.forEach(function (field) {
      var select = document.createElement("select");
      select.setAttribute("aria-label", field[1]);
      select.dataset.fbField = field[0];
      field[2].forEach(function (value, index) {
        var option = document.createElement("option");
        option.value = value;
        option.textContent = field[1] + ": " + value.replace(/_/g, " ");
        if (index === 0) option.selected = true;
        select.appendChild(option);
      });
      fbRow.appendChild(select);
    });
    var fbNote = document.createElement("input");
    fbNote.type = "text";
    fbNote.placeholder = "Optional operator note";
    fbNote.setAttribute("aria-label", "Feedback note");
    fbNote.dataset.fbField = "note";
    fbRow.appendChild(fbNote);
    var fbBtn = document.createElement("button");
    fbBtn.type = "button";
    fbBtn.className = "btn primary";
    fbBtn.textContent = "Save feedback";
    fbBtn.addEventListener("click", function () {
      var payload = {};
      [].slice.call(fbRow.querySelectorAll("[data-fb-field]"))
        .forEach(function (node) {
          payload[node.dataset.fbField] = node.value;
        });
      fetch("/api/pilot-feedback/" + encodeURIComponent(view.lead_id), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      }).then(function () {
        fbBtn.textContent = "Feedback recorded";
        return fetch("/api/pilot-feedback/" +
                     encodeURIComponent(view.lead_id));
      }).then(function (response) { return response.json(); })
        .then(function (data) { renderFeedbackHistory(data.feedback); })
        .catch(function () {
          fbBtn.textContent = "Not recorded (visible failure)";
        });
    });
    fbRow.appendChild(fbBtn);
    body.appendChild(fbRow);

    var fbHistory = document.createElement("div");
    fbHistory.id = "drawer-feedback-history";
    body.appendChild(fbHistory);
    fetch("/api/pilot-feedback/" + encodeURIComponent(view.lead_id))
      .then(function (response) { return response.json(); })
      .then(function (data) { renderFeedbackHistory(data.feedback); })
      .catch(function () { /* history stays absent, never invented */ });

    function renderFeedbackHistory(entries) {
      var box = $("drawer-feedback-history");
      if (!box) return;
      box.textContent = "";
      if (!entries.length) {
        var line = document.createElement("p");
        line.className = "context-sub";
        line.textContent = "No feedback recorded for this lead yet.";
        box.appendChild(line);
        return;
      }
      entries.slice().reverse().forEach(function (entry) {
        var line = document.createElement("p");
        line.className = "context-sub";
        line.textContent = entry.created_at.slice(0, 16)
          .replace("T", " ") + " - " + entry.quality.toLowerCase() +
          ", " + entry.grounding.toLowerCase().replace(/_/g, " ") +
          ", time saved " + entry.time_saved.toLowerCase() +
          ", would send " + entry.would_send.toLowerCase() +
          ", issue " + entry.issue.toLowerCase().replace(/_/g, " ") +
          (entry.note ? ' - "' + entry.note + '"' : "") +
          " (" + entry.context_ref + ")";
        box.appendChild(line);
      });
    }
  }

  var drawerCloseBtn = $("drawer-close");
  var drawerScrimEl = $("drawer-scrim");
  function closeDrawer() {
    var drawer = $("lead-drawer");
    if (drawer) drawer.hidden = true;
    if (drawerScrimEl) drawerScrimEl.hidden = true;
  }
  if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", closeDrawer);
  if (drawerScrimEl) drawerScrimEl.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  var detailsBtn = $("lead-details-open");
  if (detailsBtn) {
    detailsBtn.addEventListener("click", function () {
      var active = window.operatorDesk && window.operatorDesk.activeLeadId;
      if (active) openLeadDrawer(active);
    });
  }
  window.operatorDesk = window.operatorDesk || {};
  window.operatorDesk.openLeadDrawer = openLeadDrawer;

  /* ---------------------------------------------------------------- */
  /* weekly owner report (ACTIVE module)                               */
  /* ---------------------------------------------------------------- */
  var SOURCES = ["OPERATOR_DESK", "DEMO", "MANUAL_ENTRY",
                 "WHATSAPP_MANUAL", "WEBSITE", "REFERRAL", "OTHER"];
  var lastReport = null;

  (function initSourceSelects() {
    var reportSource = $("report-source");
    if (reportSource) {
      SOURCES.forEach(function (source) {
        var option = document.createElement("option");
        option.value = source;
        option.textContent = source.replace("_", " ").toLowerCase();
        reportSource.appendChild(option);
      });
    }
    ["fq-source", "rail-source"].forEach(function (id) {
      var select = $(id);
      if (!select) return;
      SOURCES.forEach(function (source) {
        var option = document.createElement("option");
        option.value = source;
        option.textContent = source.replace("_", " ").toLowerCase();
        select.appendChild(option);
      });
    });
  })();

  function reportQuery() {
    var days = $("report-days") ? $("report-days").value : "7";
    var source = $("report-source") ? $("report-source").value : "";
    return "days=" + encodeURIComponent(days) +
           (source ? "&source=" + encodeURIComponent(source) : "");
  }

  function kpiCard(label, value) {
    var card = document.createElement("div");
    card.className = "kpi-card";
    var top = document.createElement("div");
    top.className = "kpi-value";
    top.textContent = value;
    var bottom = document.createElement("div");
    bottom.className = "kpi-label";
    bottom.textContent = label;
    card.appendChild(top);
    card.appendChild(bottom);
    return card;
  }

  function reportSection(title, lines) {
    var box = document.createElement("div");
    box.className = "option-card";
    var head = document.createElement("h3");
    head.textContent = title;
    box.appendChild(head);
    lines.forEach(function (line) {
      var p = document.createElement("p");
      p.className = "context-sub";
      p.textContent = line;
      box.appendChild(p);
    });
    return box;
  }

  function pct(value) {
    return value === null || value === undefined ? "-" :
      Math.round(value * 100) + "%";
  }

  function loadReport() {
    var wrap = $("reports-wrap");
    var empty = $("reports-empty");
    if (!wrap) return;
    if (empty) { empty.textContent = "Loading the report..."; empty.hidden = false; }
    fetch("/api/weekly-report?" + reportQuery()).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (report) {
      lastReport = report;
      renderReport(report);
    }).catch(function () {
      if (empty) {
        empty.textContent = "The report could not be loaded. " +
          "Press Refresh to retry.";
        empty.hidden = false;
      }
    });
  }

  function renderReport(report) {
    var wrap = $("reports-wrap");
    var empty = $("reports-empty");
    wrap.textContent = "";
    if (empty) empty.remove();
    var o = report.lead_overview, ai = report.ai_performance,
        q = report.response_quality, inv = report.inventory_intelligence,
        fu = report.follow_up_performance, s = report.safety,
        r = report.recommended_next_actions;

    var kpis = document.createElement("div");
    kpis.className = "kpi-row";
    [[o.total_leads, "leads"], [o.new_leads_in_range, "new in range"],
     [ai.total_ai_drafts, "AI drafts"],
     [pct(ai.approval_rate), "approval rate"],
     [pct(ai.edit_rate), "edit rate"],
     [o.follow_ups_overdue, "overdue follow-ups"],
     [s.privacy_leaks, "privacy leaks"],
     [s.price_leaks, "price leaks"]].forEach(function (pair) {
      kpis.appendChild(kpiCard(String(pair[1]), pair[0]));
    });
    wrap.appendChild(kpis);

    wrap.appendChild(reportSection("Lead overview", [
      "total " + o.total_leads + " · new in range " + o.new_leads_in_range +
      " · qualified " + o.qualified + " · escalated " + o.escalated +
      " · taken over " + o.taken_over + " · closed " + o.closed,
      "follow-ups due " + o.follow_ups_due + " · overdue " +
      o.follow_ups_overdue,
      "by source: " + (Object.keys(o.by_source).map(function (key) {
        return key + " " + o.by_source[key]; }).join(", ") || "none"),
    ]));
    wrap.appendChild(reportSection("AI performance", [
      "drafts " + ai.total_ai_drafts + " · approved as-is " +
      ai.approved_as_is + " · edited " + ai.edited + " · rejected " +
      ai.rejected + " · copied " + ai.copied,
      "approval " + pct(ai.approval_rate) + " · edit " +
      pct(ai.edit_rate) + " · rejection " + pct(ai.rejection_rate),
    ]));
    wrap.appendChild(reportSection("Response quality", [
      q.time_metric + ": " + q.median_minutes + " min over " +
      q.samples + " sample(s)",
      "quality " + JSON.stringify(q.quality) + " · grounding " +
      JSON.stringify(q.grounding),
      "would send " + JSON.stringify(q.would_send) + " · top issues: " +
      (q.top_issues.map(function (t) {
        return t[0] + " (" + t[1] + ")"; }).join(", ") || "none reported"),
    ]));
    wrap.appendChild(reportSection("Inventory intelligence", [
      "top unmet shapes: " + (inv.top_unmet_shapes.map(function (x) {
        return x.size_marla + " marla " + x.block + " x" + x.count;
      }).join(", ") || "none recorded"),
      "most common missing fields: " +
      (inv.most_common_missing_fields.map(function (t) {
        return t[0] + " (" + t[1] + ")"; }).join(", ") || "none"),
      "thin cells: " + (inv.thin_cells.map(function (c) {
        return c.block + "/" + c.size_marla; }).join(", ") || "none"),
      inv.note,
    ]));
    wrap.appendChild(reportSection("Follow-up performance", [
      "due " + fu.due + " · completed " + fu.completed + " · overdue " +
      fu.overdue,
      "follow-up drafts: " + (Object.keys(fu.drafts).map(function (k) {
        return k + " " + fu.drafts[k]; }).join(", ") || "none"),
    ]));
    wrap.appendChild(reportSection("Safety", [
      "replies scanned " + s.replies_scanned + " · price leaks " +
      s.price_leaks + " · privacy leaks " + s.privacy_leaks,
      s.numbers_flagged_for_review +
      " number(s) flagged for review (outside the per-cell allowlist)",
      s.price_leaks_basis,
      "escalations recorded: " + s.escalations_honored,
    ]));
    wrap.appendChild(reportSection("Recommended next actions", [
      "inventory gaps: " + (r.inventory_gaps.join("; ") ||
                            "none stand out"),
      "response quality: " + (r.response_quality_issues.join("; ") ||
                              "none reported"),
      "operator workflow: " + r.operator_workflow_improvements.join("; "),
      "evaluation set: " + (r.questions_for_eval_set.join("; ") ||
                            "nothing to add yet"),
    ]));

    var note = document.createElement("p");
    note.className = "opt-disclaimer";
    note.textContent = r.basis + ". Generated " +
      report.generated_at.slice(0, 19).replace("T", " ") + " UTC.";
    wrap.appendChild(note);
  }

  function downloadExport(format) {
    var url = "/api/weekly-report/" + format + "?" + reportQuery();
    fetch(url).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.text();
    }).then(function (text) {
      var blob = new Blob([text],
        { type: format === "csv" ? "text/csv" : "text/markdown" });
      var link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "weekly-owner-report." + format;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
    }).catch(function () {
      var empty = $("reports-empty");
      if (empty) {
        empty.textContent = "The export failed. Press Refresh and retry.";
        empty.hidden = false;
      }
    });
  }

  ["report-refresh", "report-export-md", "report-export-csv"]
    .forEach(function (id) {
      var button = $(id);
      if (!button) return;
      button.addEventListener("click", function () {
        if (id === "report-refresh") loadReport();
        else downloadExport(id === "report-export-csv" ? "csv"
                                                       : "markdown");
      });
    });
  var fqSourceSelect = $("fq-source");
  if (fqSourceSelect) {
    fqSourceSelect.addEventListener("change", loadFollowUps);
  }
  var reportDays = $("report-days");
  var reportSource = $("report-source");
  if (reportDays) reportDays.addEventListener("change", loadReport);
  if (reportSource) reportSource.addEventListener("change", loadReport);

  /* ---------------------------------------------------------------- */
  /* system status - live infrastructure truth from this server        */
  /* ---------------------------------------------------------------- */
  var statusLoaded = false;

  function cel(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function fmtUptime(seconds) {
    if (seconds < 60) return seconds + "s";
    var mins = Math.floor(seconds / 60);
    if (mins < 60) return mins + "m " + (seconds % 60) + "s";
    return Math.floor(mins / 60) + "h " + (mins % 60) + "m";
  }

  function fmtWhen(iso) {
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso || ""; }
  }

  function storeTotal(counts) {
    var total = 0;
    Object.keys(counts || {}).forEach(function (k) { total += counts[k]; });
    return total;
  }

  function statusCard(title, chipOk, chipText, rows, note) {
    var card = cel("div", "status-card");
    var head = cel("h3");
    head.appendChild(cel("span", null, title));
    head.appendChild(cel("span",
      "verify-chip" + (chipOk ? "" : " attention"), chipText));
    card.appendChild(head);
    (rows || []).forEach(function (row) {
      var line = cel("div", "status-kv");
      line.appendChild(cel("span", "k", row[0]));
      line.appendChild(cel("span", "v", row[1]));
      card.appendChild(line);
    });
    if (note) card.appendChild(cel("p", "status-note", note));
    return card;
  }

  function renderStatus(data) {
    var grid = $("status-grid");
    var updated = $("status-updated");
    var error = $("status-error");
    if (!grid) return;
    grid.textContent = "";
    if (error) error.hidden = true;
    if (updated) {
      updated.textContent = "Live from the server \u00b7 checked " +
        new Date().toLocaleTimeString();
    }

    var guards = data.guards || {};
    var guardsOk = !!(guards.fact_guard && guards.evidence && guards.pipeline);

    grid.appendChild(statusCard("Server", data.status === "ok", "VERIFIED", [
      ["Status", data.status],
      ["Version", (data.app && data.app.version) || ""],
      ["Uptime", fmtUptime((data.runtime && data.runtime.uptime_seconds) || 0)]
    ], "Started " + fmtWhen(data.runtime && data.runtime.started_at)));

    var db = data.database || {};
    grid.appendChild(statusCard("Database", !!db.reachable,
      db.reachable ? "VERIFIED" : "ATTENTION", [
      ["Reachable", db.reachable ? "yes" : "no"],
      ["Rows recorded", String(storeTotal(db.tables))]
    ], "The database the desk serves from. Market figures come only from the approved master."));

    var stores = data.stores || {};
    grid.appendChild(statusCard("Operator stores", true, "VERIFIED", [
      ["Conversation log", storeTotal(stores.conversation_log) + " rows"],
      ["Lead state", storeTotal(stores.lead_state) + " rows"],
      ["Unmet demand", storeTotal(stores.unmet_demand) + " rows"],
      ["Lead pipeline", storeTotal(stores.lead_pipeline) + " rows"],
      ["Pilot feedback", storeTotal(stores.pilot_feedback) + " rows"]
    ]));

    var inv = data.inventory || {};
    var invSource = inv.mode === "workspace" ? "Workspace version"
      : inv.mode === "master" ? "Approved master" : "unknown";
    grid.appendChild(statusCard("Inventory serving", !!inv.serving,
      inv.serving ? "VERIFIED" : "ATTENTION", [
      ["Active source", invSource]
    ], "The stamp (fingerprint, rows, dates) is served on the Inventory page, from the guarded route."));

    grid.appendChild(statusCard("Safety guards", guardsOk,
      guardsOk ? "ARMED" : "ATTENTION", [
      ["Fact guard", guards.fact_guard ? "loaded" : "missing"],
      ["Evidence builder", guards.evidence ? "loaded" : "missing"],
      ["Reply pipeline", guards.pipeline ? "loaded" : "missing"]
    ], "Behaviour is validated by the offline test suite - see docs/VERIFICATION.md."));

    var tests = data.tests;
    if (tests && tests.collected) {
      grid.appendChild(statusCard("Test evidence", tests.failed === 0,
        tests.failed === 0 ? "VERIFIED" : "ATTENTION", [
        ["Collected", String(tests.collected)],
        ["Failed", String(tests.failed)],
        ["Recorded", (tests.ran_at || "").split("T")[0]],
        ["Command", tests.command || ""]
      ], "Written by the verification run; this page never invents it."));
    } else {
      grid.appendChild(statusCard("Test evidence", false, "EVIDENCE PENDING", [
        ["Status", "No recorded run found"]
      ], "Run the suite and record the evidence file to fill this card."));
    }
  }

  function loadStatus(force) {
    if (statusLoaded && !force) return;
    var grid = $("status-grid");
    if (!grid) return;
    fetch("/api/system-status").then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (data) {
      statusLoaded = true;
      renderStatus(data);
    }).catch(function () {
      statusLoaded = false;
      if (grid) grid.textContent = "";
      var error = $("status-error");
      if (error) {
        error.textContent = "The server did not answer the status request. " +
          "Start the desk server, then press Refresh.";
        error.hidden = false;
      }
    });
  }

  var statusRefresh = $("status-refresh");
  if (statusRefresh) {
    statusRefresh.addEventListener("click", function () { loadStatus(true); });
  }
})();
