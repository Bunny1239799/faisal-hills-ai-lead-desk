/* Stage 1 - provisional inventory workspace UI.
 *
 * Talks to the same server the operator desk uses. No framework, no build
 * step, no fake data: every table is rendered from the API response.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function setMsg(id, text, cls) {
    var node = $(id);
    node.className = "inv-msg" + (cls ? " " + cls : "");
    node.textContent = text || "";
  }

  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  var currentVersionId = null;

  /* ---------------------------------------------------------------- */
  /* chip, versions, audit                                            */
  /* ---------------------------------------------------------------- */
  function refresh() {
    getJSON("/api/inventory/current").then(function (data) {
      if (data.stamp && data.stamp.label) $("inv-chip").textContent = data.stamp.label;
      renderVersions(data.versions || []);
      renderAudit(data.audit || []);
    }).catch(function (err) {
      setMsg("inv-version-msg", "Could not load the workspace: " + err.message, "err");
    });
  }

  function renderVersions(versions) {
    var body = $("inv-versions").querySelector("tbody");
    body.innerHTML = "";
    if (!versions.length) {
      var empty = el("tr");
      var td = el("td", "inv-note", "No versions yet. Upload a CSV to create the first one.");
      td.colSpan = 6;
      empty.appendChild(td);
      body.appendChild(empty);
      return;
    }
    versions.forEach(function (version) {
      var row = el("tr");
      row.appendChild(el("td", "mono", version.version_id));
      var status = el("td");
      status.appendChild(el("span", version.status === "active" ? "ok" : "", version.status || ""));
      row.appendChild(status);
      row.appendChild(el("td", null, version.rows === null || version.rows === undefined ? "—" : version.rows));
      var range = version.observation_range || {};
      row.appendChild(el("td", "mono", (range.start || "?") + " → " + (range.end || "?")));
      row.appendChild(el("td", null, version.source_filename || "—"));

      var actions = el("td");
      var approve = el("button", "inv-btn", "Approve");
      approve.type = "button";
      approve.disabled = version.status !== "pending_review";
      approve.addEventListener("click", function () {
        act("/api/inventory/approve", { version_id: version.version_id },
            "Approved " + version.version_id);
      });
      var activate = el("button", "inv-btn primary", "Activate");
      activate.type = "button";
      activate.disabled = !(version.status === "approved" || version.status === "active");
      activate.addEventListener("click", function () {
        act("/api/inventory/activate", { version_id: version.version_id },
            "Activated " + version.version_id);
      });
      var rollback = el("button", "inv-btn", "Roll back to this");
      rollback.type = "button";
      rollback.disabled = !(version.status === "approved" || version.status === "active");
      rollback.addEventListener("click", function () {
        act("/api/inventory/rollback", { version_id: version.version_id },
            "Rolled back to " + version.version_id);
      });
      actions.appendChild(approve);
      actions.appendChild(document.createTextNode(" "));
      actions.appendChild(activate);
      actions.appendChild(document.createTextNode(" "));
      actions.appendChild(rollback);
      row.appendChild(actions);
      body.appendChild(row);
    });
  }

  function act(url, payload, okText) {
    postJSON(url, payload).then(function (result) {
      if (!result.ok) {
        setMsg("inv-version-msg", (result.data && result.data.detail) || "Refused.", "err");
        return;
      }
      setMsg("inv-version-msg", okText, "ok");
      refresh();
    }).catch(function (err) {
      setMsg("inv-version-msg", "Request failed: " + err.message, "err");
    });
  }

  function renderAudit(records) {
    var body = $("inv-audit").querySelector("tbody");
    body.innerHTML = "";
    if (!records.length) {
      var empty = el("tr");
      var td = el("td", "inv-note", "No audit records yet.");
      td.colSpan = 5;
      empty.appendChild(td);
      body.appendChild(empty);
      return;
    }
    records.slice().reverse().forEach(function (record) {
      var row = el("tr");
      row.appendChild(el("td", "mono", (record.ts || "").replace("T", " ").slice(0, 19)));
      row.appendChild(el("td", null, record.action || ""));
      row.appendChild(el("td", "mono", record.version_id || "—"));
      row.appendChild(el("td", null, record.actor || ""));
      row.appendChild(el("td", "mono", JSON.stringify(record.detail || {}).slice(0, 120)));
      body.appendChild(row);
    });
  }

  /* ---------------------------------------------------------------- */
  /* upload + validation report                                       */
  /* ---------------------------------------------------------------- */
  function renderReport(result) {
    var versionId = result.version_id;
    currentVersionId = versionId;
    $("inv-version").textContent = versionId ? "· " + versionId : "";
    var report = result.validation || {};
    var wrap = $("inv-report");
    wrap.innerHTML = "";

    var summary = el("p", "inv-note");
    summary.textContent =
      (report.rows_read || 0) + " rows read · " + (report.accepted || 0) +
      " accepted · " + (report.rejected || 0) + " rejected · " +
      (report.flagged || 0) + " flagged · verdict " + (report.verdict || "—");
    wrap.appendChild(summary);

    if (report.errors && report.errors.length) {
      var head = el("h2", "err", "Rejected rows");
      wrap.appendChild(head);
      var table = el("table", "inv");
      table.innerHTML = "<thead><tr><th>Row</th><th>Identity</th><th>Reasons</th></tr></thead>";
      var body = el("tbody");
      report.errors.forEach(function (item) {
        var tr = el("tr");
        tr.appendChild(el("td", "mono", item.row));
        tr.appendChild(el("td", "mono", item.identity));
        tr.appendChild(el("td", "err", (item.reasons || []).join("; ")));
        body.appendChild(tr);
      });
      table.appendChild(body);
      var scroll = el("div", "inv-scroll");
      scroll.appendChild(table);
      wrap.appendChild(scroll);
    }

    if (report.warnings && report.warnings.length) {
      wrap.appendChild(el("h2", "warn", "Warnings (rows kept)"));
      var wtable = el("table", "inv");
      wtable.innerHTML = "<thead><tr><th>Row</th><th>Identity</th><th>Warnings</th></tr></thead>";
      var wbody = el("tbody");
      report.warnings.forEach(function (item) {
        var tr = el("tr");
        tr.appendChild(el("td", "mono", item.row));
        tr.appendChild(el("td", "mono", item.identity));
        tr.appendChild(el("td", "warn", (item.warnings || []).join("; ")));
        wbody.appendChild(tr);
      });
      wtable.appendChild(wbody);
      var wscroll = el("div", "inv-scroll");
      wscroll.appendChild(wtable);
      wrap.appendChild(wscroll);
    }

    if (report.thin_cells && report.thin_cells.length) {
      var thin = el("p", "inv-note");
      thin.textContent = "Cells below the " + (report.min_listings_for_answer || 3) +
        "-listing evidence threshold (will answer 'not enough data'): " +
        report.thin_cells.map(function (c) {
          return c.block + " / " + c.size_marla + " marla";
        }).join(", ");
      wrap.appendChild(thin);
    }
  }

  function upload() {
    var input = $("inv-file");
    if (!input.files || !input.files.length) {
      setMsg("inv-upload-msg", "Choose a CSV or JSONL file first.", "err");
      return;
    }
    var file = input.files[0];
    setMsg("inv-upload-msg", "Uploading and validating…");
    fetch("/api/inventory/upload?filename=" + encodeURIComponent(file.name), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    }).then(function (result) {
      if (!result.ok) {
        var detail = result.data && result.data.detail;
        setMsg("inv-upload-msg", typeof detail === "string" ? detail : "Upload refused.", "err");
        return;
      }
      setMsg("inv-upload-msg", "Stored as " + result.data.version_id +
        " — review the validation report, then approve.", "ok");
      renderReport(result.data);
      refresh();
    }).catch(function (err) {
      setMsg("inv-upload-msg", "Upload failed: " + err.message, "err");
    });
  }

  $("inv-upload").addEventListener("click", upload);

  /* Stage 1: ?version=<id> deep-links straight to a stored version's
     validation report, so a reviewed report can be shared or captured. */
  function requestedVersion() {
    try {
      var search = String(window.location.search || "");
      if (search.charAt(0) === "?") search = search.slice(1);
      var parts = search.split("&");
      for (var i = 0; i < parts.length; i += 1) {
        var pair = parts[i].split("=");
        if (decodeURIComponent(pair[0] || "") === "version") {
          return decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
        }
      }
      return "";
    } catch (e) {
      return "";
    }
  }

  function loadRequestedVersion() {
    var versionId = requestedVersion();
    if (!versionId) return;
    fetch("/api/inventory/preview/" + encodeURIComponent(versionId)).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      $("inv-version").textContent = "· " + data.version_id;
      renderReport({ version_id: data.version_id, validation: data.validation || {} });
      renderPreviewRows(data.rows_preview || []);
    }).catch(function (err) {
      setMsg("inv-version-msg", "Could not load that version: " + err.message, "err");
    });
  }

  function renderPreviewRows(rows) {
    if (!rows.length) return;
    var wrap = $("inv-report");
    wrap.appendChild(el("h2", null, "Row preview (escaped)"));
    var table = el("table", "inv");
    var columns = Object.keys(rows[0]).filter(function (key) {
      return key !== "inventory_origin";
    }).slice(0, 8);
    var head = el("thead");
    var headRow = el("tr");
    columns.forEach(function (key) { headRow.appendChild(el("th", "mono", key)); });
    head.appendChild(headRow);
    table.appendChild(head);
    var body = el("tbody");
    rows.slice(0, 25).forEach(function (row) {
      var tr = el("tr");
      columns.forEach(function (key) {
        tr.appendChild(el("td", "mono", row[key] === null || row[key] === undefined ? "" : row[key]));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    var scroll = el("div", "inv-scroll");
    scroll.appendChild(table);
    wrap.appendChild(scroll);
  }

  refresh();
  loadRequestedVersion();
})();
