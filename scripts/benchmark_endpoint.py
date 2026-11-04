"""Measure a Cadence-compatible endpoint without involving the workbench.

Example:
  python scripts/benchmark_endpoint.py \
    --url https://xxxx.endpoints.huggingface.cloud \
    --audio data/audio/demo-seed/itm_x.mp3 \
    --token $env:HF_TOKEN --runs 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

PROMPT = (
    "请审听整首音频：给出 Caption、主曲风与次曲风、主要情绪与能量、BPM、调性、"
    "主要乐器、人声与语言、以及带秒数的结构段落。无法判断时说明原因。"
)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Endpoint base URL")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--token", default="")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=900)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        raise SystemExit(f"audio not found: {audio}")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    url = args.url.rstrip("/") + "/v1/annotate"
    latencies: list[float] = []
    results = []
    for index in range(args.runs):
        started = time.perf_counter()
        with audio.open("rb") as handle:
            response = httpx.post(
                url,
                headers=headers,
                data={"prompt": PROMPT, "max_new_tokens": str(args.max_new_tokens)},
                files={"audio": (audio.name, handle, "audio/mpeg")},
                timeout=900.0,
            )
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        record = {
            "run": index + 1,
            "status": response.status_code,
            "wall_seconds": round(elapsed, 2),
            "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:500],
        }
        results.append(record)
        print(f"run {index + 1}: HTTP {response.status_code} in {elapsed:.1f}s")

    report = {
        "url": args.url,
        "audio": str(audio),
        "audio_bytes": audio.stat().st_size,
        "runs": args.runs,
        "latency_seconds": [round(v, 2) for v in latencies],
        "p50_seconds": round(percentile(latencies, 50), 2),
        "p95_seconds": round(percentile(latencies, 95), 2),
        "mean_seconds": round(statistics.mean(latencies), 2) if latencies else 0,
        "results": results,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("wrote", args.out)
    print(f"P50 {report['p50_seconds']}s · P95 {report['p95_seconds']}s")
    return 0 if results and all(r["status"] == 200 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
