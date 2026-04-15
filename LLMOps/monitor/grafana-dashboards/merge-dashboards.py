#!/usr/bin/env python3
"""Merge three Grafana dashboard JSON files into one unified dashboard.

Uses Grafana expanded row pattern: child panels are placed at the top
level as siblings of the row panel, with "collapsed": false.
"""
import json
import copy
import re


def load_json(path):
    with open(path) as f:
        return json.load(f)


def reassign_ids(panels, id_start):
    """Reassign unique IDs to all panels (flat list)."""
    current_id = id_start
    for p in panels:
        p["id"] = current_id
        current_id += 1
    return current_id


def flatten_panels(panels):
    """Flatten panels: extract sub-panels from any existing collapsed rows
    so we get a flat list of actual content panels (no row wrappers)."""
    flat = []
    for p in copy.deepcopy(panels):
        if p.get("type") == "row":
            # Pull out nested panels from existing rows
            for sub in p.get("panels", []):
                flat.append(sub)
        else:
            flat.append(p)
    return flat


def normalize_gridpos(panels):
    """Re-normalize gridPos.y so panels start from y=1 (leaving y=0 for the row header)."""
    if not panels:
        return panels
    min_y = min(p.get("gridPos", {}).get("y", 0) for p in panels)
    for p in panels:
        if "gridPos" in p:
            p["gridPos"]["y"] = p["gridPos"]["y"] - min_y + 1
    return panels


def make_expanded_row(title, child_panels, row_y, row_id, id_start):
    """Create an expanded row with child panels as siblings.

    Grafana expanded row format:
    - Row panel at top level with collapsed=false and panels=[]
    - Child panels placed at the same top level (after the row)
    - Child gridPos.y values are absolute, starting from row_y + 1
    """
    children = flatten_panels(child_panels)
    children = normalize_gridpos(children)
    next_id = reassign_ids(children, id_start)

    # Offset children's y to be absolute (after the row header)
    for p in children:
        if "gridPos" in p:
            p["gridPos"]["y"] += row_y

    # Calculate max_y for the next section
    max_y = row_y + 1
    for p in children:
        if "gridPos" in p:
            bottom = p["gridPos"]["y"] + p["gridPos"].get("h", 8)
            if bottom > max_y:
                max_y = bottom

    row = {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": row_y},
        "id": row_id,
        "panels": [],
        "title": title,
        "type": "row"
    }
    return row, children, next_id, max_y


def rewrite_variable_refs(text, rename_map):
    if not isinstance(text, str):
        return text
    out = text
    for old, new in rename_map.items():
        out = re.sub(r"\$\{" + re.escape(old) + r"\}", "${" + new + "}", out)
        out = re.sub(r"\$" + re.escape(old) + r"(?![A-Za-z0-9_])", "$" + new, out)
    return out


def rewrite_in_place(obj, rename_map):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                obj[key] = rewrite_variable_refs(value, rename_map)
            else:
                rewrite_in_place(value, rename_map)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            if isinstance(value, str):
                obj[i] = rewrite_variable_refs(value, rename_map)
            else:
                rewrite_in_place(value, rename_map)


def namespace_dashboard_vars(dashboard, prefix, target_names):
    templating = dashboard.get("templating", {}).get("list", [])
    rename_map = {}
    for var in templating:
        name = var.get("name")
        if name in target_names:
            rename_map[name] = f"{prefix}_{name}"

    if not rename_map:
        return dashboard

    rewrite_in_place(dashboard.get("panels", []), rename_map)
    rewrite_in_place(templating, rename_map)

    for var in templating:
        name = var.get("name")
        if name in rename_map:
            var["name"] = rename_map[name]

    return dashboard


def merge_template_vars(all_vars_lists):
    """Merge template variable lists, deduplicating by variable name."""
    seen = {}
    merged = []
    for var_list in all_vars_lists:
        for v in var_list:
            name = v.get("name", "")
            if name not in seen:
                seen[name] = True
                merged.append(v)
    return merged


def main():
    sglang = load_json("sglang-dashboard-grafana.json")
    vllm_perf = load_json("vllm-performance_statistics.json")
    vllm_query = load_json("vllm-query_statistics.json")

    namespace_dashboard_vars(sglang, "sgl", {"model_name", "instance"})
    namespace_dashboard_vars(vllm_perf, "vllm", {"model_name", "instance"})
    namespace_dashboard_vars(vllm_query, "vllm", {"model_name", "instance"})

    all_panels = []
    next_id = 1
    current_y = 0

    # --- Section 1: SGLang Dashboard (expanded row) ---
    row_id_1 = next_id
    next_id += 1
    row1, children1, next_id, current_y = make_expanded_row(
        title="SGLang Dashboard",
        child_panels=sglang["panels"],
        row_y=current_y,
        row_id=row_id_1,
        id_start=next_id,
    )
    all_panels.append(row1)
    all_panels.extend(children1)

    # --- Section 2: vLLM Performance Statistics (expanded row) ---
    row_id_2 = next_id
    next_id += 1
    row2, children2, next_id, current_y = make_expanded_row(
        title="vLLM Performance Statistics",
        child_panels=vllm_perf["panels"],
        row_y=current_y,
        row_id=row_id_2,
        id_start=next_id,
    )
    all_panels.append(row2)
    all_panels.extend(children2)

    # --- Section 3: vLLM Query Statistics (expanded row) ---
    row_id_3 = next_id
    next_id += 1
    row3, children3, next_id, current_y = make_expanded_row(
        title="vLLM Query Statistics",
        child_panels=vllm_query["panels"],
        row_y=current_y,
        row_id=row_id_3,
        id_start=next_id,
    )
    all_panels.append(row3)
    all_panels.extend(children3)

    # Merge template variables from all three dashboards
    merged_vars = merge_template_vars([
        sglang.get("templating", {}).get("list", []),
        vllm_perf.get("templating", {}).get("list", []),
        vllm_query.get("templating", {}).get("list", []),
    ])

    # Build the merged dashboard
    merged = {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard"
                }
            ]
        },
        "description": "Unified LLM Monitoring Dashboard - SGLang + vLLM Performance + vLLM Query Statistics",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": all_panels,
        "preload": False,
        "refresh": "5s",
        "schemaVersion": 41,
        "tags": ["llm", "sglang", "vllm"],
        "templating": {"list": merged_vars},
        "time": {"from": "now-30m", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "LLM All-in-One Dashboard",
        "uid": "llm-all-in-one",
        "version": 1,
        "weekStart": ""
    }

    with open("../llm-all.json", "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    # Summary
    total_panels = len([p for p in all_panels if p.get("type") != "row"])
    print(f"Merged dashboard written to llm-all.json")
    print(f"Top-level rows: 3 (all expanded)")
    print(f"  - SGLang Dashboard: {len(children1)} panels")
    print(f"  - vLLM Performance Statistics: {len(children2)} panels")
    print(f"  - vLLM Query Statistics: {len(children3)} panels")
    print(f"Total content panels: {total_panels}")


if __name__ == "__main__":
    main()
