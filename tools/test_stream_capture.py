#!/usr/bin/env python3
"""Utility to exercise StreamSourceAdapter against one or more HTTP streams."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, TypedDict

# Ensure project root is on sys.path when executed from repository
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.ingest import AudioSourceConfig, AudioSourceType  # noqa: E402
from app_core.audio.sources import create_audio_source  # noqa: E402

logger = logging.getLogger("stream_test")


class StreamTestResult(TypedDict, total=False):
    status: str
    chunks: int
    empty_reads: int
    max_http_buffer: int
    max_pcm_buffer: int
    errors: List[str]
    metadata: Dict[str, object]


class StreamTestHarness:
    """Runs StreamSourceAdapter instances against real HTTP streams."""

    def __init__(self, duration: int, chunk_timeout: float) -> None:
        self.duration = duration
        self.chunk_timeout = chunk_timeout
        self._stop = False

    def run(self, configs: List[AudioSourceConfig]) -> Dict[str, StreamTestResult]:
        results: Dict[str, StreamTestResult] = {}
        for config in configs:
            result = self._run_single(config)
            results[config.name] = result
        return results

    def _run_single(self, config: AudioSourceConfig) -> StreamTestResult:
        logger.info("=== Testing %s (%s) ===", config.name, config.device_params.get("stream_url", "?"))
        source = create_audio_source(config)

        max_http_buffer = 0
        max_pcm_buffer = 0
        chunk_count = 0
        empty_reads = 0
        errors: List[str] = []

        def _signal_handler(signum, frame):  # type: ignore[override]
            logger.warning("Received signal %s, stopping stream test early", signum)
            self._stop = True

        original_handler = signal.signal(signal.SIGINT, _signal_handler)

        try:
            started = source.start()
            if not started:
                errors.append(source.error_message or "failed to start source")
                return StreamTestResult({
                    "status": "failed_to_start",
                    "errors": errors,
                    "chunks": 0,
                    "max_http_buffer": 0,
                    "max_pcm_buffer": 0,
                })

            start_time = time.time()
            while not self._stop and (time.time() - start_time) < self.duration:
                chunk = source.get_audio_chunk(timeout=self.chunk_timeout)
                if chunk is None:
                    empty_reads += 1
                else:
                    chunk_count += 1

                buffer_attr = getattr(source, "_buffer", None)
                if isinstance(buffer_attr, (bytes, bytearray)):
                    http_buffer = len(buffer_attr)
                else:
                    http_buffer = 0

                pcm_source = None
                for attr_name in ("_pcm_buffer", "_pcm_backlog"):
                    candidate = getattr(source, attr_name, None)
                    if isinstance(candidate, (bytes, bytearray)):
                        pcm_source = candidate
                        break

                pcm_buffer = len(pcm_source) if pcm_source is not None else 0
                if http_buffer > max_http_buffer:
                    max_http_buffer = http_buffer
                if pcm_buffer > max_pcm_buffer:
                    max_pcm_buffer = pcm_buffer

            status = source.status.value

        except Exception as exc:  # pragma: no cover - defensive logging
            errors.append(f"exception: {exc}")
            status = "error"
        finally:
            signal.signal(signal.SIGINT, original_handler)
            try:
                source.stop()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Error stopping source %s: %s", config.name, exc)

        logger.info(
            "Result %s: status=%s chunks=%s empty_reads=%s max_http_buffer=%s max_pcm_buffer=%s",
            config.name,
            status,
            chunk_count,
            empty_reads,
            max_http_buffer,
            max_pcm_buffer,
        )

        return StreamTestResult({
            "status": status,
            "chunks": chunk_count,
            "empty_reads": empty_reads,
            "max_http_buffer": max_http_buffer,
            "max_pcm_buffer": max_pcm_buffer,
            "errors": errors,
            "metadata": source.metrics.metadata or {},
        })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test StreamSourceAdapter against HTTP streams")
    parser.add_argument(
        "--stream",
        action="append",
        required=True,
        help="Stream specification. Accepts either URL or name=URL syntax.",
    )
    parser.add_argument("--duration", type=int, default=30, help="Seconds to capture per stream")
    parser.add_argument("--chunk-timeout", type=float, default=1.0, help="Timeout for queue get() calls")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate to request from decoder")
    parser.add_argument("--channels", type=int, default=1, help="Number of audio channels")
    parser.add_argument("--buffer-size", type=int, default=4096, help="PCM buffer size for adapter")
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Optional path to write JSON report summarizing all stream results.",
    )
    return parser.parse_args()


def build_configs(args: argparse.Namespace) -> List[AudioSourceConfig]:
    configs: List[AudioSourceConfig] = []
    for index, spec in enumerate(args.stream, start=1):
        if "=" in spec:
            name, url = spec.split("=", 1)
        else:
            name = f"stream_{index}"
            url = spec

        device_params = {"stream_url": url}
        config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name=name.strip() or f"stream_{index}",
            sample_rate=args.sample_rate,
            channels=args.channels,
            buffer_size=args.buffer_size,
            device_params=device_params,
        )
        configs.append(config)
    return configs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    configs = build_configs(args)
    harness = StreamTestHarness(duration=args.duration, chunk_timeout=args.chunk_timeout)
    results = harness.run(configs)

    if args.json_report:
        args.json_report.write_text(json.dumps(results, indent=2))
        logger.info("Wrote JSON report to %s", args.json_report)

    # Emit concise summary to stdout for CI usage
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
