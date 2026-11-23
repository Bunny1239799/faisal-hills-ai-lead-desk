/* M12.1 / M12.2 - the operator desk.
 *
 * The page shows only what the backend returns. It never invents a
 * field, a status, a statistic or a reply, and it is never silent:
 * every failure becomes a visible line in the conversation area with a
 * Retry, and a network failure also raises the server banner.
 *
 * The dealer's own words travel in a JSON body, never in a URL.
 *
 * M12.2: the conversation list, the transcript after a reload and the
 * operator activity all come from the backend, and every draft action
 * is recorded on the server as well as in this page. A list, a
 * transcript or a recording that fails is shown, never swallowed.
 */
"use strict";

(function () {

  var REQUEST_TIMEOUT_MS = 20000;

  var FIELDS = [
    { key: "size", label: "Size" },
    { key: "block", label: "Block" },
    { key: "budget", label: "Budget" },
    { key: "purpose", label: "Purpose" },
    { key: "timeline", label: "Timeline" }
  ];

  var STATUS_TEXT = {
    unknown: "Not provided",
    stated: "Stated",
    corrected: "Corrected"
  };

  var state = {
    sessions: [],
    activeId: null,
    busy: false,
    busySessionId: null,
    filter: "open",
    filterX: "all",
    searchText: "",
    sourceFilter: "",
    counter: 0,
    unmetCount: null,
    activity: null
  };

  var draftEvents = [];

  /* ---------------------------------------------------------------- */
  /* recording the operator actions on the server                      */
  /* ---------------------------------------------------------------- */
  function postDraftAction(sessionId, action) {
    return fetch("/api/conversation/" + encodeURIComponent(sessionId) +
                 "/draft-action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action })
    }).then(function (response) {
      if (!response.ok) {
        throw new DeskError("The desk answered " + response.status, "api");
      }
      return response.json();
    }).then(function () {
      loadActivity();
    });
  }

  function recordAction(session, action, draftId) {
    /* The page keeps its own event list and records the action on the
       server. A recording that fails is shown, never swallowed. */
    pushDraftEvent(session.id, draftId, action);
    postDraftAction(session.id, action).catch(function (error) {
      session.messages.push({
        kind: "error",
        text: "The action was not recorded on the server: " + error.message,
        retry: null
      });
      announce("The action was not recorded on the server.");
      renderAll();
    });
  }

  /* ---------------------------------------------------------------- */
  /* small helpers                                                     */
  /* ---------------------------------------------------------------- */
  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function newSessionId() {
    var bytes = new Uint8Array(8);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var i = 0; i < bytes.length; i += 1) {
        bytes[i] = Math.floor(Math.random() * 256);
      }
    }
    var hex = "";
    for (var j = 0; j < bytes.length; j += 1) {
      hex += ("0" + bytes[j].toString(16)).slice(-2);
    }
    return "s-" + hex;
  }

  function money(value) {
    return "PKR " + Number(value).toLocaleString("en-US");
  }

  function formatValue(key, value) {
    if (value === null || value === undefined || value === "") return "";
    if (key === "size" && typeof value === "number") {
      return String(value) + " marla";
    }
    if (key === "block") {
      return "Block " + String(value);
    }
    if (key === "budget" && typeof value === "object") {
      var min = value.min_pkr;
      var max = value.max_pkr;
      if (min !== undefined && min !== null && max !== undefined && max !== null) {
        if (min === max) return money(min);
        return money(min) + " to " + money(max);
      }
      if (min !== undefined && min !== null) return money(min) + " and above";
      if (max !== undefined && max !== null) return money(max) + " and below";
      return "";
    }
    return String(value);
  }

  /* ---------------------------------------------------------------- */
  /* the in-page draft event list (M12.2 persists it)                  */
  /* ---------------------------------------------------------------- */
  function pushDraftEvent(sessionId, draftId, action) {
    var event = {
      session: sessionId,
      draft_id: draftId,
      action: action,
      time: new Date().toISOString()
    };
    draftEvents.push(event);
    if (window.operatorDesk && typeof window.operatorDesk.onDraftAction === "function") {
      window.operatorDesk.onDraftAction(event);
    }
    return event;
  }

  window.operatorDesk = {
    version: "m12.2",
    events: draftEvents,
    onDraftAction: function (event) {
      return event;
    }
  };

  /* ---------------------------------------------------------------- */
  /* sessions                                                          */
  /* ---------------------------------------------------------------- */
  function createSession() {
    state.counter += 1;
    var session = {
      id: newSessionId(),
      label: "Lead " + ("000" + state.counter).slice(-4),
      messages: [],
      route: null,
      escalation: false,
      takenOver: false,
      takenOverAt: null,
      state: null,
      options: [],
      reason: "",
      nextAction: null,
      unmet: null,
      policy: null,
      gates: null,
      draftCounter: 0,
      restored: false,
      preview: null,
      lastActivity: null
    };
    state.sessions.push(session);
    state.activeId = session.id;
    return session;
  }

  function sessionById(sessionId) {
    for (var i = 0; i < state.sessions.length; i += 1) {
      if (state.sessions[i].id === sessionId) return state.sessions[i];
    }
    return null;
  }

  function activeSession() {
    for (var i = 0; i < state.sessions.length; i += 1) {
      if (state.sessions[i].id === state.activeId) return state.sessions[i];
    }
    return null;
  }

  function latestDraft(session) {
    for (var i = session.messages.length - 1; i >= 0; i -= 1) {
      if (session.messages[i].kind === "draft") return session.messages[i];
    }
    return null;
  }

  function summaryOf(session) {
    if (!session.state || !session.state.fields) return "No requirements yet";
    var parts = [];
    FIELDS.forEach(function (field) {
      var entry = session.state.fields[field.key];
      if (!entry || entry.status === "unknown") return;
      var text = formatValue(field.key, entry.value);
      if (text) parts.push(text);
    });
    return parts.length ? parts.join(" · ") : "No requirements yet";
  }

  function chipOf(session) {
    if (session.takenOver) return { cls: "taken", text: "Taken over" };
    if (!session.route) return { cls: "", text: "New" };
    if (session.route === "escalate") return { cls: "escalate", text: "Escalated" };
    if (session.route === "exact") return { cls: "exact", text: "Match found" };
    if (session.route === "alternative") return { cls: "alternative", text: "Alternatives" };
    if (session.route === "clarify") return { cls: "clarify", text: "Qualifying" };
    return { cls: "", text: session.route };
  }

  /* The ladder rung the backend returned. The backend's decision
     action is the ladder step, so the panel never invents a rung. */
  var LADDER = {
    quote_exact_match: "Exact match",
    offer_verified_alternatives: "Verified alternatives",
    ask_clarifying_question: "Clarifying question",
    escalate_to_human: "Human escalation"
  };

  function ladderRung(session) {
    if (!session.nextAction || !session.nextAction.action) return "";
    return LADDER[session.nextAction.action] || "";
  }

  /* The last message the operator can see, for the rail preview. For a
     session restored from the backend, the preview the backend served
     is used until the thread is opened here. */
  function previewOf(session) {
    for (var i = session.messages.length - 1; i >= 0; i -= 1) {
      var message = session.messages[i];
      if (message.kind !== "dealer" && message.kind !== "operator") continue;
      var text = String(message.text || "").replace(/\s+/g, " ").trim();
      if (!text) continue;
      return text.length > 60 ? text.slice(0, 59) + "\u2026" : text;
    }
    if (session.preview) return session.preview;
    return session.lastActivity ? "No messages loaded yet" : "No messages yet";
  }

  function shortTime(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    /* Compact: the clock time when it happened today, the date when it
       did not - so the rail's one-line summary never clips the stamp. */
    var now = new Date();
    if (date.toDateString() === now.toDateString()) {
      return date.toLocaleTimeString(undefined,
        { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString(undefined,
      { month: "short", day: "numeric" });
  }

  /* Announce a status change to assistive technology. */
  function announce(text) {
    var node = $("desk-status");
    if (node) node.textContent = text;
  }

  /* ---------------------------------------------------------------- */
  /* the request                                                       */
  /* ---------------------------------------------------------------- */
  function DeskError(message, kind) {
    this.name = "DeskError";
    this.message = message;
    this.kind = kind;
  }

  function postTurn(session, text) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    return fetch("/api/conversation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: session.id, message: text }),
      signal: controller.signal
    }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (body) {
          throw new DeskError(
            "The desk answered " + response.status +
            (body ? " (" + body.slice(0, 200) + ")" : ""), "api");
        });
      }
      return response.json();
    }).then(function (data) {
      if (!data || typeof data.reply !== "string" || !data.reply) {
        throw new DeskError("The desk sent no reply", "api");
      }
      return data;
    }).catch(function (error) {
      if (error && error.name === "AbortError") {
        throw new DeskError("The desk did not answer within 20 seconds", "timeout");
      }
      if (error instanceof DeskError) throw error;
      throw new DeskError("The server is unreachable", "network");
    }).then(function (data) {
      clearTimeout(timer);
      return data;
    }, function (error) {
      clearTimeout(timer);
      throw error;
    });
  }

  function applyTurn(session, data) {
    session.route = data.route;
    session.escalation = !!data.escalation;
    session.reason = data.reason || "";
    session.options = data.verified_options || [];
    session.nextAction = data.next_action || null;
    session.unmet = data.unmet_demand || null;
    session.policy = data.policy || null;
    session.gates = data.gates || null;
    session.state = data.lead_state || null;
    if (data.taken_over_at) {
      session.takenOver = true;
      session.takenOverAt = data.taken_over_at;
    }

    var normalized = data.normalized || {};
    (normalized.changes || []).forEach(function (change) {
      session.messages.push({
        kind: "system",
        text: "Read “" + change.before + "” as “" + change.after + "”"
      });
    });

    (data.changes || []).forEach(function (change) {
      if (change.turn !== data.turn) return;
      var label = change.field;
      FIELDS.forEach(function (field) {
        if (field.key === change.field) label = field.label;
      });
      session.messages.push({
        kind: "system",
        text: label + " corrected to " + formatValue(change.field, change.new)
      });
    });

    announce("The application drafted a reply. It has not been sent.");
    session.draftCounter += 1;
    var checked = !!(data.gates && data.gates.traceability_ok === true &&
                      data.gates.claim_guard_ok === true);
    session.messages.push({
      kind: "draft",
      id: "d" + session.draftCounter,
      text: data.reply,
      status: "draft",
      checked: checked,
      inventoryVersion: data.inventory_version || null
    });
  }

  function sendMessage(text, options) {
    var trimmed = String(text || "").trim();
    if (!trimmed) return;
    if (state.busy) return;

    var session = activeSession();
    if (!session) session = createSession();

    if (!options || !options.keepDealerMessage) {
      session.messages.push({ kind: "dealer", text: trimmed });
    }

    state.busy = true;
    state.busySessionId = session.id;
    renderAll();

    postTurn(session, trimmed).then(function (data) {
      applyTurn(session, data);
      /* the backend has recorded the turn: re-sync the rail from the
         record so the ordering and the chips are the server's truth */
      loadConversations();
      loadLeads();
    }).catch(function (error) {
      session.messages.push({
        kind: "error",
        text: error.message,
        retry: trimmed
      });
      announce("The desk did not answer. " + error.message);
      if (error.kind === "network") showServerBanner(error.message);
    }).then(function () {
      state.busy = false;
      state.busySessionId = null;
      renderAll();
    });
  }

  /* ---------------------------------------------------------------- */
  /* draft actions (this page only)                                    */
  /* ---------------------------------------------------------------- */
  function copyDraft() {
    var session = activeSession();
    if (!session) return;
    var draft = latestDraft(session);
    if (!draft || !draft.text) return;

    var done = function () {
      session.messages.push({
        kind: "system", text: "Draft copied to the clipboard on this page."
      });
      announce("The draft was copied. It has not been sent.");
      postDraftAction(session.id, "copied");
      renderAll();
    };
    var fail = function () { copyViaTextarea(); };
    /* the classic fallback: some locked-down browsers (and headless
       test contexts) refuse the async clipboard API */
    function copyViaTextarea() {
      var area = document.createElement("textarea");
      area.value = draft.text;
      area.setAttribute("readonly", "readonly");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(area);
      if (ok) {
        done();
      } else {
        session.messages.push({
          kind: "error",
          text: "The clipboard refused the copy. Select the draft text and copy manually.",
          retry: null
        });
        renderAll();
      }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(draft.text).then(done, fail);
    } else {
      copyViaTextarea();
    }
  }

  function draftAction(action) {
    var session = activeSession();
    if (!session) return;
    var draft = latestDraft(session);
    if (!draft || session.takenOver) return;

    if (action === "edited") {
      var text = $("composer-input").value.trim();
      if (!text) {
        session.messages.push({
          kind: "error",
          text: "There is no edited text to save. Type the edited draft first.",
          retry: null
        });
        renderAll();
        return;
      }
      draft.text = text;
      draft.status = "edited";
      announce("The draft was edited on this page. It has not been sent.");
      session.messages.push({ kind: "system", text: "Draft edited on this page" });
    } else if (action === "rejected") {
      draft.status = "rejected";
      announce("The draft was rejected on this page.");
      session.messages.push({ kind: "system", text: "Draft rejected on this page" });
    } else if (action === "sent") {
      draft.status = "sent";
      announce("The draft was marked as sent on this page. No message was delivered.");
      session.messages.push({ kind: "system", text: "Draft marked as sent on this page" });
    } else {
      return;
    }

    recordAction(session, action, draft.id);
    renderAll();
  }

  function takeOver() {
    var session = activeSession();
    if (!session || session.takenOver) return;

    fetch("/api/conversation/" + encodeURIComponent(session.id) + "/take-over", {
      method: "POST"
    }).then(function (response) {
      if (!response.ok) {
        throw new DeskError("The desk answered " + response.status, "api");
      }
      return response.json();
    }).then(function (data) {
      session.takenOver = true;
      session.takenOverAt = data.taken_over_at;
      session.messages.push({
        kind: "system",
        text: "Taken over by the operator. The application no longer drafts here."
      });
      announce("The operator took over this conversation.");
      loadActivity();
      renderAll();
    }).catch(function (error) {
      session.messages.push({ kind: "error", text: error.message, retry: null });
      renderAll();
    });
  }

  /* ---------------------------------------------------------------- */
  /* rendering                                                         */
  /* ---------------------------------------------------------------- */
  /* The rail is ordered by the last activity the BACKEND recorded -
     the newest conversation first. A conversation started in this page
     that has not completed a turn yet keeps its place at the end until
     the backend has recorded it. */
  function byLastActivity(left, right) {
    var a = left.lastActivity ? Date.parse(left.lastActivity) || 0 : 0;
    var b = right.lastActivity ? Date.parse(right.lastActivity) || 0 : 0;
    return b - a;
  }

  /* Lead temperature: a TRANSPARENT reading of how much the dealer has
     told us, shown with the rule itself - never a guess about intent.
     Hot = 4+ of the 5 qualification fields stated, Warm = 1-3, Cold =
     nothing stated yet. */
  function temperatureOf(session) {
    var stated = 0;
    var fields = (session.state && session.state.fields) || {};
    FIELDS.forEach(function (field) {
      var entry = fields[field.key];
      if (entry && entry.status !== "unknown" && entry.value !== null) stated += 1;
    });
    if (stated >= 4) return { cls: "hot", text: "Hot" };
    if (stated >= 1) return { cls: "warm", text: "Warm" };
    return { cls: "cold", text: "Cold" };
  }

  function renderRail() {
    var list = $("rail-list");
    clear(list);

    var shown = state.sessions.filter(function (session) {
      return state.filter === "taken" ? session.takenOver : !session.takenOver;
    }).sort(byLastActivity);

    /* the extended filters read the same honest backend state */
    if (state.filterX && state.filterX !== "all") {
      shown = shown.filter(function (session) {
        if (state.filterX === "new") return !session.route;
        if (state.filterX === "qualified")
          return session.route === "clarify" || session.route === "exact" ||
                 session.route === "alternative";
        if (state.filterX === "review" || state.filterX === "escalated")
          return session.route === "escalate" || !!session.escalation;
        if (state.filterX === "unmet") return !!session.unmet;
        return true;
      });
    }

    if (state.sourceFilter) {
      shown = shown.filter(function (session) {
        return (session.pipeline && session.pipeline.source) ===
          state.sourceFilter;
      });
    }

    if (state.searchText) {
      var needle = state.searchText.toLowerCase();
      shown = shown.filter(function (session) {
        return (session.label + " " + previewOf(session)).toLowerCase()
          .indexOf(needle) >= 0;
      });
    }

    $("rail-empty").hidden = shown.length > 0;

    shown.forEach(function (session) {
      var item = el("li", "rail-item");
      var button = el("button", "rail-button");
      button.title = session.id;
      button.type = "button";
      if (session.id === state.activeId) button.setAttribute("aria-current", "true");

      var row = el("div", "rail-row-1");
      row.appendChild(el("span", "rail-label", session.label));
      var chip = chipOf(session);
      row.appendChild(el("span", "chip " + chip.cls, chip.text));
      button.appendChild(row);

      /* Showcase readiness (2026-11-22): the qualification signals stay on
         the rail - the browser tests pin them (score "/100", the NEW
         badge, the session id) - but on their own quiet line, so the
         title is never squeezed to a letter again. */
      var badges = el("div", "rail-row-2");
      if (session.pipeline) {
        var stageBadge = el("span", "temp stage",
                            session.pipeline.stage.replace("_", " "));
        stageBadge.title = "Pipeline stage. The system suggests; the " +
          "operator approves changes.";
        badges.appendChild(stageBadge);
      }
      var temp = temperatureOf(session);
      var tempBadge = el("span", "temp " + temp.cls, temp.text);
      tempBadge.title = "Fields stated by the dealer: " + temp.text +
        " (a reading of qualification progress, not intent)";
      badges.appendChild(tempBadge);
      if (session.pipeline) {
        badges.appendChild(el("span", "temp score",
                              session.pipeline.score.score + "/100"));
      }
      if (session.unmet) {
        badges.appendChild(el("span", "mini-badge unmet", "Unmet"));
      }
      badges.appendChild(el("span", "rail-id", session.id));
      button.appendChild(badges);

      var summary = el("div", "rail-summary");
      summary.appendChild(el("span", "rail-meta",
                             shortTime(session.lastActivity)));
      summary.appendChild(document.createTextNode(previewOf(session)));
      button.appendChild(summary);
      button.addEventListener("click", function () {
        state.activeId = session.id;
        if (session.restored && !session.messages.length) {
          openSession(session);
        }
        renderAll();
      });

      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function draftCard(draft) {
    var card = el("div", "draft-card");
    var head = el("div", "draft-card-head");

    var title = "AI draft, not sent";
    if (draft.status === "edited") title = "AI draft, edited";
    else if (draft.status === "rejected") title = "AI draft, rejected";
    else if (draft.status === "sent") title = "AI draft, marked as sent";
    head.appendChild(el("span", "draft-card-title", title));

    if (draft.status !== "draft") {
      var label = draft.status === "edited" ? "Edited"
        : draft.status === "rejected" ? "Rejected" : "Sent";
      head.appendChild(el("span", "status-tag " + draft.status, label));
    }
    card.appendChild(head);
    card.appendChild(el("div", "draft-card-body", draft.text));

    var caption = "";
    if (draft.status === "draft" && draft.checked) {
      caption = "Checked: numbers, claims";
    } else if (draft.status === "edited") {
      caption = "Edited on this page. Not sent.";
    } else if (draft.status === "rejected") {
      caption = "Rejected on this page. Not sent.";
    } else if (draft.status === "sent") {
      caption = "Marked as sent on this page. No message was delivered.";
    }
    if (caption) card.appendChild(el("div", "draft-card-caption", caption));

    /* Stage 1: the draft card names the inventory version it was answered
       from - id + fingerprint + row count - so an old turn keeps its own
       stamp even after a different version is activated. */
    if (draft.inventoryVersion) {
      var version = draft.inventoryVersion;
      var versionLabel = version.version_id
        ? "Inventory " + version.version_id
        : "Inventory master";
      if (version.fingerprint) {
        versionLabel += " \u00b7 " + String(version.fingerprint).slice(0, 8);
      }
      if (version.rows !== null && version.rows !== undefined) {
        versionLabel += " \u00b7 " + version.rows + " rows";
      }
      card.appendChild(el("div", "draft-card-caption inventory-stamp", versionLabel));
    }
    return card;
  }

  function renderThread() {
    var session = activeSession();
    var messages = $("messages");
    var empty = $("thread-empty");
    clear(messages);

    if (!session) {
      empty.hidden = false;
      messages.hidden = true;
      $("thread-title").textContent = "Lead desk";
      $("thread-sub").textContent = "Select a conversation to begin";
      return;
    }

    empty.hidden = true;
    messages.hidden = false;
    $("thread-title").textContent = session.label;
    $("thread-sub").textContent = session.takenOver
      ? "You are replying as the operator"
      : "The application drafts, a human sends";

    var draftIndex = -1;
    for (var i = session.messages.length - 1; i >= 0; i -= 1) {
      if (session.messages[i].kind === "draft") { draftIndex = i; break; }
    }

    session.messages.forEach(function (message, index) {
      if (message.kind === "system") {
        var system = el("div", "msg system");
        system.appendChild(el("div", "system-text", message.text));
        messages.appendChild(system);
        return;
      }

      if (message.kind === "error") {
        var errorBox = el("div", "msg draft");
        var bubble = el("div", "bubble");
        bubble.appendChild(el("div", "who", "Error"));
        bubble.appendChild(el("div", null, message.text));
        if (message.retry) {
          var retry = el("button", "btn retry-btn", "Retry");
          retry.type = "button";
          retry.addEventListener("click", function () {
            var index = session.messages.indexOf(message);
            if (index >= 0) session.messages.splice(index, 1);
            sendMessage(message.retry, { keepDealerMessage: true });
          });
          bubble.appendChild(retry);
        }
        errorBox.appendChild(bubble);
        messages.appendChild(errorBox);
        return;
      }

      var wrapper = el("div", "msg " + message.kind);
      if (message.kind === "draft" && index === draftIndex && !session.takenOver) {
        wrapper.appendChild(draftCard(message));
      } else {
        var body = el("div", "bubble");
        var who = message.kind === "dealer" ? "Dealer"
          : message.kind === "operator" ? "Operator reply" : "Draft reply";
        body.appendChild(el("div", "who", who));
        body.appendChild(el("div", null, message.text));
        if (message.kind === "operator") {
          body.appendChild(el("div", "draft-card-caption",
            "Added on this page. Not sent."));
        }
        wrapper.appendChild(body);
      }
      messages.appendChild(wrapper);
    });

    if (state.busy && state.busySessionId === session.id) {
      var typing = el("div", "msg draft");
      var typingBubble = el("div", "bubble");
      var typingRow = el("div", "typing");
      typingRow.appendChild(el("span", null, "The application is working"));
      typingRow.appendChild(el("i"));
      typingRow.appendChild(el("i"));
      typingRow.appendChild(el("i"));
      typingBubble.appendChild(typingRow);
      typing.appendChild(typingBubble);
      messages.appendChild(typing);
    }

    messages.scrollTop = messages.scrollHeight;
  }

  function renderContext() {
    var session = activeSession();
    var reqBody = $("req-body");
    clear(reqBody);
    clear($("options"));
    clear($("unmet"));

    var dot = $("escalation-dot");
    var text = $("escalation-text");
    var banner = document.querySelector("#context .banner");
    if (banner) banner.remove();

    if (!session) {
      $("options-sub").textContent = "Select a conversation to begin";
      $("recommendation-rung").textContent = "Not available";
      $("recommendation-label").textContent = "";
      $("route-reason").textContent = "";
      $("next-action").textContent = "";
      $("unmet").appendChild(el("p", "context-sub", "No conversation selected"));
      dot.className = "dot";
      text.textContent = "No escalation";
      var emptyRow = el("tr");
      var cell = el("td", "unknown", "No conversation selected");
      cell.setAttribute("colspan", "3");
      emptyRow.appendChild(cell);
      reqBody.appendChild(emptyRow);
      return;
    }

    var refused = session.policy && session.policy.action === "refuse";
    if (refused) {
      dot.className = "dot danger";
      text.textContent = "Refused by policy";
    } else if (session.escalation) {
      dot.className = "dot warn";
      text.textContent = "Human review required";
    } else {
      dot.className = "dot";
      text.textContent = "No escalation";
    }

    if (refused || session.escalation) {
      var box = el("div", "banner " + (refused ? "danger" : "warning"));
      box.appendChild(el("div", null,
        refused ? "Refused by policy" : "Human review required"));
      var detail = session.reason || "";
      var policyReasons = (session.policy && session.policy.reasons) || [];
      if (policyReasons.length) detail = policyReasons.join("; ");
      if (detail) box.appendChild(el("div", "banner-detail", detail));
      var context = $("context");
      context.insertBefore(box, context.firstChild);
    }

    var fields = (session.state && session.state.fields) || {};
    FIELDS.forEach(function (field) {
      var entry = fields[field.key] || { value: null, status: "unknown" };
      var row = el("tr");

      var name = el("th", null, field.label);
      name.setAttribute("scope", "row");
      row.appendChild(name);

      var valueCell = el("td");
      var text = formatValue(field.key, entry.value);
      if (entry.status === "unknown" || !text) {
        valueCell.appendChild(el("span", "unknown", "Not provided"));
      } else {
        valueCell.appendChild(el("span", null, text));
      }
      row.appendChild(valueCell);

      var statusCell = el("td");
      var status = STATUS_TEXT[entry.status] || entry.status;
      var statusNode = el("span", entry.status === "unknown" ? "unknown" : null,
                           status);
      statusCell.appendChild(statusNode);
      if (entry.source_turn !== null && entry.source_turn !== undefined) {
        statusCell.appendChild(el("div", "meta", "Turn " + entry.source_turn));
      }
      row.appendChild(statusCell);

      reqBody.appendChild(row);
    });

    var rung = ladderRung(session);
    $("recommendation-rung").textContent = rung ? rung : "Not available";
    $("recommendation-label").textContent = session.nextAction && session.nextAction.label
      ? session.nextAction.label : "";

    /* the audit strip: the two final gates, in plain words */
    var gateStrip = $("gate-strip");
    if (gateStrip) {
      var gates = session.gates || {};
      if (gates.traceability_ok === true && gates.claim_guard_ok === true) {
        gateStrip.textContent = "Numbers verified · Claims checked · Privacy protected";
      } else if (session.messages.length) {
        gateStrip.textContent = "Gate status: not available";
      } else {
        gateStrip.textContent = "";
      }
    }

    if (session.options.length) {
      $("options-sub").textContent = "";
      session.options.forEach(function (option) {
        var card = el("div", "option-card");
        var head = el("div", "opt-head");
        head.appendChild(el("span", "cell",
          (option.block || "") + " - " + option.size_marla + " marla"));
        var matchType = session.route === "exact"
          ? { cls: "exact", text: "Exact match" }
          : { cls: "", text: "Verified alternative" };
        head.appendChild(el("span", "opt-match " + matchType.cls, matchType.text));
        card.appendChild(head);
        var reasons = option.reason || [];
        if (reasons.length) {
          var list = el("ul");
          reasons.forEach(function (reason) {
            list.appendChild(el("li", null, reason));
          });
          card.appendChild(list);
        }
        card.appendChild(el("div", "opt-foot",
          "Verified against the approved inventory by the application " +
          "before this draft was written."));
        card.appendChild(el("div", "opt-disclaimer",
          session.route === "exact"
            ? "Asking-price band is stated in the draft reply. Dealer asking prices, not confirmed sold prices."
            : "Price shared after human review. The application does not price an alternative on its own."));
        $("options").appendChild(card);
      });
    } else {
      $("options-sub").textContent = "No verified option was returned for this turn.";
    }

    $("route-reason").textContent = session.reason || "Not available";
    /* the next-action label is shown once, in the Recommendation block */
    $("next-action").textContent = "";

    if (session.unmet) {
      var parts = [];
      if (session.unmet.size_marla !== null && session.unmet.size_marla !== undefined) {
        parts.push(session.unmet.size_marla + " marla");
      }
      if (session.unmet.block) parts.push("Block " + session.unmet.block);
      if (session.unmet.budget_band) {
        parts.push("Budget band " + session.unmet.budget_band);
      }
      $("unmet").appendChild(el("p", "context-sub",
        parts.length ? parts.join(" · ") : "Recorded for this turn"));
    } else {
      $("unmet").appendChild(el("p", "context-sub",
        "No unmet demand recorded for this turn"));
    }
    if (state.unmetCount !== null) {
      $("unmet").appendChild(el("p", "context-sub",
        state.unmetCount + " requests in the unmet demand log"));
    }
  }

  function renderComposer() {
    var session = activeSession();
    var send = $("send-message");
    var copyBtn = $("draft-copy");
    var sendAsIs = $("draft-send-as-is");
    var saveEdit = $("draft-save-edit");
    var reject = $("draft-reject");
    var takeOverButton = $("take-over");
    var label = $("composer-label");

    var taken = !!(session && session.takenOver);
    var draft = session ? latestDraft(session) : null;
    var hasDraft = !!(draft && !taken);

    send.disabled = state.busy;
    copyBtn.disabled = !hasDraft || state.busy;
    sendAsIs.disabled = !hasDraft || state.busy;
    saveEdit.disabled = !hasDraft || state.busy;
    reject.disabled = !hasDraft || state.busy;
    takeOverButton.disabled = !session || taken || state.busy;

    if (taken) {
      label.textContent = "You are replying as the operator";
      send.textContent = "Add reply";
      $("composer-note").textContent =
        "You are answering this lead yourself. Nothing is sent to a dealer from this page.";
    } else {
      label.textContent = "Dealer's message";
      send.textContent = "Send message";
      $("composer-note").textContent =
        "The application drafts, a human sends. Nothing is sent to a dealer from this page.";
    }
  }

  /* The visible state of the conversation, in one glance: a chip row
     under the thread title, derived only from backend fields. */
  function renderStateStrip() {
    var strip = $("state-strip");
    if (!strip) return;
    clear(strip);
    var session = activeSession();
    if (!session) return;

    function chip(cls, text) {
      strip.appendChild(el("span", "state-chip " + cls, text));
    }
    if (session.takenOver) {
      chip("bad", "Taken over by operator");
    } else if (session.escalation) {
      chip("bad", "Human review required");
    } else if (session.route === "clarify") {
      chip("warn", "Clarification needed");
    } else if (session.route === "exact" || session.route === "alternative") {
      chip("ok", "AI draft ready for review");
    }
    if (session.unmet) chip("warn", "Thin inventory data");
  }

  /* The lead strip in the context panel: stage, temperature, score,
     follow-up - served by the backend's transparent arithmetic. */
  function renderLeadStrip() {
    var strip = $("lead-strip");
    if (!strip) return;
    var session = activeSession();
    var lead = session && session.pipeline;
    window.operatorDesk.activeLeadId = session ? session.id : null;
    if (!lead) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    $("lead-strip-line").textContent =
      lead.stage.replace("_", " ") + " · " + lead.temperature +
      " · Score " + lead.score.score + "/100 · " + lead.routing;
    $("lead-strip-actions").textContent =
      lead.follow_up && lead.follow_up.due_at
        ? "Follow-up due " + lead.follow_up.due_at.slice(0, 10) +
          (lead.follow_up.overdue ? " (overdue)" : "")
        : "No follow-up scheduled yet";
  }

  function renderAll() {
    renderRail();
    renderThread();
    renderContext();
    renderComposer();
    renderActivity();
    renderStateStrip();
    renderLeadStrip();
  }

  /* ---------------------------------------------------------------- */
  /* the server banner and the top bar data badge                      */
  /* ---------------------------------------------------------------- */
  function showServerBanner(text) {
    var banner = $("server-banner");
    banner.textContent = text + ". The desk cannot reach the application. Retry when it is back.";
    banner.hidden = false;
  }

  function loadDataBadge() {
    /* Stage 1: both chips come from the server's own resolution of the
       inventory it would actually serve - the active workspace version
       when one exists, otherwise the configured master. Each carries the
       real fingerprint, row count and observation-date range; the page
       never derives a range from per-cell maxima any more. */
    fetch("/api/inventory/current").then(function (response) {
      if (!response.ok) throw new Error("no inventory status");
      return response.json();
    }).then(function (data) {
      var stamp = data.stamp || {};
      var range = stamp.observation_range || {};
      var badge = $("data-badge");
      if (range.start && range.end) {
        badge.textContent = "Data " + range.start + " to " + range.end;
      } else {
        badge.textContent = "Data range not available";
      }
      badge.hidden = false;
      var env = $("env-badge");
      if (env && stamp.label) env.textContent = stamp.label;
    }).catch(function () {
      var badge = $("data-badge");
      badge.textContent = "Data not available";
      badge.hidden = false;
    });
  }

  function loadUnmetCount() {
    fetch("/api/unmet-demand?limit=1").then(function (response) {
      if (!response.ok) throw new Error("no unmet demand");
      return response.json();
    }).then(function (data) {
      state.unmetCount = data.count;
      renderContext();
    }).catch(function () {
      state.unmetCount = null;
    });
  }

  /* ---------------------------------------------------------------- */
  /* M12.2 - the persisted conversations and the activity view         */
  /* ---------------------------------------------------------------- */

  /* The rail starts from the backend list: the conversations the
     application has already handled survive a reload. A list that
     cannot be loaded is shown in the rail, never swallowed. */
  /* A rail title a human can read: the dealer's own words, capped.
     The raw session id stays on the button tooltip and in the state. */
  function friendlyLabel(item) {
    var text = (item.first_preview || item.preview || "").replace(/\s+/g, " ").trim();
    if (!text) return item.session_id;
    if (text.length > 46) text = text.slice(0, 46).replace(/\s+\S*$/, "") + "...";
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function loadConversations() {
    return fetch("/api/conversations").then(function (response) {
      if (!response.ok) throw new DeskError("HTTP " + response.status, "api");
      return response.json();
    }).then(function (data) {
      (data.conversations || []).forEach(function (item) {
        var existing = sessionById(item.session_id);
        if (existing) {
          /* re-sync a session this page already holds: the backend's
             record is the truth about its last activity */
          existing.route = item.route || existing.route;
          existing.escalation = !!item.escalation;
          existing.preview = item.preview || null;
          existing.lastActivity = item.last_activity || existing.lastActivity;
          if (item.taken_over_at) {
            existing.takenOver = true;
            existing.takenOverAt = item.taken_over_at;
          }
          return;
        }
        state.sessions.push({          id: item.session_id,
          label: friendlyLabel(item),
          messages: [],
          route: item.route || null,
          escalation: !!item.escalation,
          takenOver: !!item.taken_over_at,
          takenOverAt: item.taken_over_at || null,
          state: null,
          options: [],
          reason: "",
          nextAction: null,
          unmet: null,
          policy: null,
          gates: null,
          draftCounter: 0,
          restored: true,
          preview: item.preview || null,
          lastActivity: item.last_activity || null
        });
      });
      renderAll();
    }).catch(function () {
      var note = $("rail-empty");
      note.textContent = "The conversation list could not be loaded";
      note.hidden = false;
    });
  }

  /* The lead pipeline: every conversation as a trackable lead with a
     stage, a transparent temperature/score and a follow-up state -
     all computed by the backend from recorded data. */
  function loadLeads() {
    return fetch("/api/leads-pipeline").then(function (response) {
      if (!response.ok) throw new DeskError("HTTP " + response.status, "api");
      return response.json();
    }).then(function (data) {
      (data.leads || []).forEach(function (lead) {
        var existing = sessionById(lead.lead_id);
        if (!existing) {
          existing = {
            id: lead.lead_id, label: lead.label || lead.lead_id,
            messages: [], route: null, escalation: false,
            takenOver: false, takenOverAt: null, state: null, options: [],
            reason: "", nextAction: null, unmet: null, policy: null,
            gates: null, draftCounter: 0, restored: true,
            preview: lead.last_dealer_message
              ? lead.last_dealer_message.slice(0, 60) : null,
            lastActivity: lead.last_activity_at
          };
          state.sessions.push(existing);
        }
        existing.pipeline = lead;
      });
      renderAll();
    }).catch(function () {
      /* the desk still works without the pipeline layer; the lead
         strip stays hidden rather than lying */
    });
  }

  /* Open a persisted conversation: replay the recorded turns and the
     qualification state the backend holds. The thread is rebuilt from
     the backend's own record - the page invents nothing. */
  function openSession(session) {
    var transcriptRequest = fetch(
      "/api/conversation/" + encodeURIComponent(session.id) + "/transcript"
    ).then(function (response) {
      if (!response.ok) throw new DeskError("HTTP " + response.status, "api");
      return response.json();
    });
    var stateRequest = fetch(
      "/api/conversation/" + encodeURIComponent(session.id)
    ).then(function (response) {
      if (!response.ok) throw new DeskError("HTTP " + response.status, "api");
      return response.json();
    });

    transcriptRequest.then(function (data) {
      session.messages = [];
      session.draftCounter = 0;
      (data.turns || []).forEach(function (turn) {
        session.messages.push({
          kind: "dealer",
          text: turn.dealer_message
        });
        session.draftCounter += 1;
        session.messages.push({
          kind: "draft",
          id: "d" + session.draftCounter,
          text: turn.reply,
          status: "draft",
          checked: false,
          inventoryVersion: turn.inventory_version || null
        });
        session.route = turn.route;
        session.escalation = !!turn.escalation;
        /* Showcase readiness (2026-11-22): the replay carries the
           verified options the turn served, so a restored conversation
           shows the same panel a live turn does. The last turn wins -
           the same rule the route chip follows. */
        if (turn.options && turn.options.length) {
          session.options = turn.options;
        }
      });
      if (data.taken_over_at) {
        session.takenOver = true;
        session.takenOverAt = data.taken_over_at;
      }
      session.preview = null;
      announce("The conversation was loaded from the record.");
      renderAll();
    }).catch(function (error) {
      session.messages.push({
        kind: "error",
        text: "The transcript could not be loaded (" + error.message +
              "). The conversation is still recorded on the server.",
        retry: null
      });
      renderAll();
    });

    stateRequest.then(function (data) {
      session.state = data.lead_state || null;
      renderAll();
    }).catch(function () {
      /* the transcript is the record; a state panel that cannot be
         loaded shows the honest unknowns */
    });
  }

  function loadActivity() {
    return fetch("/api/operator-activity?limit=5").then(function (response) {
      if (!response.ok) throw new DeskError("HTTP " + response.status, "api");
      return response.json();
    }).then(function (data) {
      state.activity = data;
      renderActivity();
    }).catch(function () {
      state.activity = null;
      renderActivity();
    });
  }

  var ACTION_TEXT = {
    sent: "Sent as is",
    edited: "Edited",
    rejected: "Rejected",
    copied: "Copied",
    operator_reply: "Operator replies",
    taken_over: "Taken over"
  };

  function renderActivity() {
    var box = $("activity");
    if (!box) return;
    clear(box);
    if (!state.activity) {
      box.appendChild(el("p", "context-sub", "Not available"));
      return;
    }
    var counts = state.activity.counts || {};
    var parts = [];
    Object.keys(ACTION_TEXT).forEach(function (action) {
      if (counts[action]) {
        parts.push(ACTION_TEXT[action] + ": " + counts[action]);
      }
    });
    box.appendChild(el("p", "context-sub",
      parts.length ? parts.join(" · ") : "No operator actions recorded yet"));

    /* the pilot metrics the backend totals over the recorded turns -
       the founder's weekly review reads exactly these numbers */
    var totals = state.activity.totals || {};
    var totalsParts = [];
    if (totals.conversations !== undefined) {
      totalsParts.push("Conversations: " + totals.conversations);
    }
    if (totals.ai_drafts !== undefined) {
      totalsParts.push("AI drafts: " + totals.ai_drafts);
    }
    if (totals.escalations !== undefined) {
      totalsParts.push("Escalations: " + totals.escalations);
    }
    if (totals.unmet_demand !== undefined) {
      totalsParts.push("Unmet demand: " + totals.unmet_demand);
    }
    if (totalsParts.length) {
      box.appendChild(el("p", "context-sub", totalsParts.join(" · ")));
    }

    (state.activity.recent || []).forEach(function (event) {
      var line = (ACTION_TEXT[event.action] || event.action) +
        " · " + event.session_id;
      var time = shortTime(event.time);
      if (time) line += " · " + time;
      box.appendChild(el("p", "activity-event", line));
    });
  }

  /* ---------------------------------------------------------------- */
  /* the layout drawers                                                */
  /* ---------------------------------------------------------------- */
  function setupLayout() {
    var railToggle = $("toggle-rail");
    var contextToggle = $("toggle-context");
    var rail = $("rail");
    var context = $("context");
    var scrim = $("scrim");

    function railIsDrawer() {
      return window.matchMedia("(max-width: 1023px)").matches;
    }

    function contextIsOverlay() {
      return window.matchMedia("(max-width: 1279px)").matches;
    }

    function syncToggles() {
      railToggle.hidden = !railIsDrawer();
      contextToggle.hidden = !contextIsOverlay();
      if (!railIsDrawer()) rail.classList.remove("open");
      if (!contextIsOverlay()) context.classList.remove("open");
      syncScrim();
    }

    function syncScrim() {
      var open = rail.classList.contains("open") || context.classList.contains("open");
      scrim.hidden = !open;
      scrim.classList.toggle("visible", open);
    }

    railToggle.addEventListener("click", function () {
      var open = !rail.classList.contains("open");
      rail.classList.toggle("open", open);
      railToggle.setAttribute("aria-expanded", open ? "true" : "false");
      syncScrim();
    });

    contextToggle.addEventListener("click", function () {
      var open = !context.classList.contains("open");
      context.classList.toggle("open", open);
      contextToggle.setAttribute("aria-expanded", open ? "true" : "false");
      syncScrim();
    });

    scrim.addEventListener("click", function () {
      rail.classList.remove("open");
      context.classList.remove("open");
      railToggle.setAttribute("aria-expanded", "false");
      contextToggle.setAttribute("aria-expanded", "false");
      syncScrim();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        rail.classList.remove("open");
        context.classList.remove("open");
        syncScrim();
      }
    });

    window.addEventListener("resize", syncToggles);
    syncToggles();
  }

  /* ---------------------------------------------------------------- */
  /* wiring                                                            */
  /* ---------------------------------------------------------------- */
  function setup() {
    $("composer").addEventListener("submit", function (event) {
      event.preventDefault();
      var input = $("composer-input");
      var session = activeSession();
      if (session && session.takenOver) {
        var text = input.value.trim();
        if (!text) return;
        session.messages.push({ kind: "operator", text: text });
        recordAction(session, "operator_reply", "");
        input.value = "";
        renderAll();
        return;
      }
      var message = input.value.trim();
      if (!message) return;
      input.value = "";
      sendMessage(message);
    });

    $("composer-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        $("composer").requestSubmit
          ? $("composer").requestSubmit()
          : $("send-message").click();
      }
    });

    $("draft-send-as-is").addEventListener("click", function () { draftAction("sent"); });
    $("draft-save-edit").addEventListener("click", function () { draftAction("edited"); });
    $("draft-reject").addEventListener("click", function () { draftAction("rejected"); });
    $("draft-copy").addEventListener("click", copyDraft);
    $("take-over").addEventListener("click", takeOver);

    $("new-conversation").addEventListener("click", function () {
      createSession();
      renderAll();
    });

    $("filter-open").addEventListener("click", function () {
      state.filter = "open";
      $("filter-open").setAttribute("aria-pressed", "true");
      $("filter-taken").setAttribute("aria-pressed", "false");
      renderRail();
    });

    $("filter-taken").addEventListener("click", function () {
      state.filter = "taken";
      $("filter-open").setAttribute("aria-pressed", "false");
      $("filter-taken").setAttribute("aria-pressed", "true");
      renderRail();
    });

    Array.prototype.forEach.call(
      document.querySelectorAll(".filter-x[data-filter]"), function (btn) {
        btn.addEventListener("click", function () {
          state.filterX = btn.getAttribute("data-filter");
          Array.prototype.forEach.call(
            document.querySelectorAll(".filter-x[data-filter]"),
            function (other) {
              other.setAttribute("aria-pressed",
                other === btn ? "true" : "false");
            });
          renderRail();
        });
      });

    var railSource = $("rail-source");
    if (railSource) {
      ["OPERATOR_DESK", "DEMO", "MANUAL_ENTRY", "WHATSAPP_MANUAL",
       "WEBSITE", "REFERRAL", "OTHER"].forEach(function (source) {
        var option = document.createElement("option");
        option.value = source;
        option.textContent = source.replace("_", " ").toLowerCase();
        railSource.appendChild(option);
      });
      railSource.addEventListener("change", function () {
        state.sourceFilter = railSource.value;
        renderRail();
      });
    }

    var searchBox = $("lead-search");
    if (searchBox) {
      searchBox.addEventListener("input", function () {
        state.searchText = searchBox.value || "";
        renderRail();
      });
    }

    Array.prototype.forEach.call(document.querySelectorAll("[data-example]"), function (chip) {
      chip.addEventListener("click", function () {
        sendMessage(chip.getAttribute("data-example"));
      });
    });

    setupLayout();
    loadDataBadge();
    loadUnmetCount();
    loadConversations();
    loadLeads();
    loadActivity();
    renderAll();

    /* Stage 1: a conversation can be deep-linked (?session=<id>) so a
       screenshot or a shared link opens the exact turn, including its
       inventory-version stamp. Additive: without the parameter nothing
       changes. */
    var deepLink = "";
    try {
      var search = String(window.location.search || "");
      if (search.charAt(0) === "?") search = search.slice(1);
      search.split("&").forEach(function (pair) {
        var parts = pair.split("=");
        if (decodeURIComponent(parts[0] || "") === "session") {
          deepLink = decodeURIComponent((parts[1] || "").replace(/\+/g, " "));
        }
      });
    } catch (e) {
      deepLink = "";
    }
    if (deepLink) {
      var tries = 0;
      var timer = setInterval(function () {
        var session = sessionById(deepLink);
        if (session) {
          clearInterval(timer);
          state.activeId = session.id;
          if (session.restored && !session.messages.length) openSession(session);
          renderAll();
        } else if ((tries += 1) > 40) {
          clearInterval(timer);
        }
      }, 150);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setup);
  } else {
    setup();
  }

})();
