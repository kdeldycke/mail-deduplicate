---
orphan: true
---

# {octicon}`desktop-download` Binaries

All standalone executables published by this repository, one row per binary, newest release first. The version links to its GitHub release, the platform to the direct binary download, and the VirusTotal cell to the file's public analysis.

Compiled Python binaries are regularly flagged by heuristic antivirus engines, so every release is submitted to [VirusTotal](https://www.virustotal.com/): this seeds vendor databases with the new signatures and keeps false positives in check. The VirusTotal cell tracks those false positives: a green check marks binaries no engine flags, and flagged binaries show the share of engine verdicts flagging them, snapshotted minutes after publication and before false-positive reports get processed. The live analysis behind the link supersedes it.

## Development builds

Fresh binaries are compiled from every push to the default branch by the [release workflow](https://github.com/kdeldycke/mail-deduplicate/actions/workflows/release.yaml). To try the latest development build: open the most recent successful run and download the artifact matching your platform (a GitHub account is required, and the binary comes wrapped in a zip). The same builds are also attached to a rolling dev pre-release, a draft only visible to repository maintainers.

<!-- binaries-chart -->

## VirusTotal detections

Share of antivirus engine verdicts flagging the binaries of each release, at scan time. Colors follow the catalog shields: green for zero detections, amber below 10%, red from there up.

```{raw} html
<div style="height: 320px;"><canvas id="vt-trend"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.min.js"></script>
<script>
const VT_TREND = [{"date": "2026-07-27", "flagged": 21, "pct": 6.2, "tag": "v9.0.0", "total": 341}, {"date": "2026-08-01", "flagged": 16, "pct": 4.1, "tag": "v9.1.0", "total": 388}, {"date": "2026-08-07", "flagged": 18, "pct": 4.7, "tag": "v9.2.0", "total": 384}];
const VT_DANGER_PCT = 10;
const vtCss = getComputedStyle(document.documentElement);
const vtColor = (name, fallback) =>
    vtCss.getPropertyValue(name).trim() || fallback;
const vtTint = (p) => {
    if (p.pct === 0) { return vtColor("--sd-color-success", "#28a745"); }
    return p.pct >= VT_DANGER_PCT
        ? vtColor("--sd-color-danger", "#dc3545")
        : vtColor("--sd-color-warning", "#f0b37e");
};
new Chart(document.getElementById("vt-trend"), {
    type: "line",
    data: {
        datasets: [{
            data: VT_TREND.map((p) => ({x: Date.parse(p.date), y: p.pct})),
            borderColor: "#88888866",
            pointBackgroundColor: VT_TREND.map(vtTint),
            pointBorderColor: VT_TREND.map(vtTint),
            pointRadius: 4,
            tension: 0.2,
        }],
    },
    options: {
        maintainAspectRatio: false,
        plugins: {
            legend: {display: false},
            tooltip: {callbacks: {
                title: (items) => VT_TREND[items[0].dataIndex].tag,
                label: (item) => {
                    const p = VT_TREND[item.dataIndex];
                    return p.flagged + " / " + p.total
                        + " verdicts flagged (" + p.pct + "%)";
                },
            }},
        },
        scales: {
            x: {
                type: "linear",
                ticks: {
                    maxTicksLimit: 8,
                    callback: (value) =>
                        new Date(value).toISOString().slice(0, 10),
                },
            },
            y: {
                beginAtZero: true,
                title: {display: true, text: "Flagged verdicts (%)"},
            },
        },
    },
});
</script>
```

<!-- binaries-chart-end -->

## Catalog

The table is searchable and sortable on the documentation site; the raw data lives in [`binaries.csv`](assets/binaries.csv).

```{csv-table}
:file: assets/binaries.csv
:header-rows: 1
:class: sphinx-datatable
```
