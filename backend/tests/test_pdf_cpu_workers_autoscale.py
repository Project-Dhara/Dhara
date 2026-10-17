"""PyMuPDF worker count scales with host CPUs/RAM; env override still wins."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import llm_prompts as lp


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("PDF_CPU_WORKERS", "5")
    assert lp.resolve_cpu_workers() == 5


def test_autoscale_uses_cpus_and_ram(monkeypatch):
    monkeypatch.delenv("PDF_CPU_WORKERS", raising=False)
    monkeypatch.setenv("PDF_CPU_WORKERS_MAX", "32")
    with mock.patch.object(lp.os, "cpu_count", return_value=16), mock.patch.object(
        lp, "_available_ram_mb", return_value=32000
    ):
        # 16 CPUs → leave 1 for API → 15; 32GB - 1.5GB reserve → ~29GB → 29 workers;
        # result capped by cpu_cap (15).
        assert lp._default_cpu_workers() == 15


def test_autoscale_ram_caps_small_hosts(monkeypatch):
    monkeypatch.delenv("PDF_CPU_WORKERS", raising=False)
    monkeypatch.setenv("PDF_CPU_WORKERS_MAX", "32")
    with mock.patch.object(lp.os, "cpu_count", return_value=8), mock.patch.object(
        lp, "_available_ram_mb", return_value=4096
    ):
        # 4GB available - 1.5GB reserve → ~2.5GB → 2 workers.
        assert lp._default_cpu_workers() == 2


def test_hard_max_env_ceiling(monkeypatch):
    monkeypatch.delenv("PDF_CPU_WORKERS", raising=False)
    monkeypatch.setenv("PDF_CPU_WORKERS_MAX", "6")
    with mock.patch.object(lp.os, "cpu_count", return_value=32), mock.patch.object(
        lp, "_available_ram_mb", return_value=64000
    ):
        assert lp._default_cpu_workers() == 6


def test_cgroup_limit_preferred_over_host_mem(monkeypatch):
    monkeypatch.delenv("PDF_CPU_WORKERS", raising=False)
    with mock.patch.object(lp, "_read_cgroup_memory_limit_mb", return_value=2048), mock.patch.object(
        lp, "_read_linux_meminfo_mb", return_value=(16000, 32000)
    ), mock.patch.object(lp, "_read_macos_mem_mb", return_value=(None, None)):
        # min(avail, cgroup)=2048, reclaim floor on total=min(32000,2048)=2048 → 2048
        assert lp._available_ram_mb() == 2048


def test_macos_low_free_uses_total_reclaim_floor(monkeypatch):
    monkeypatch.delenv("PDF_CPU_WORKERS", raising=False)
    with mock.patch.object(lp, "_read_cgroup_memory_limit_mb", return_value=None), mock.patch.object(
        lp, "_read_linux_meminfo_mb", return_value=(None, None)
    ), mock.patch.object(lp, "_read_macos_mem_mb", return_value=(1200, 8192)):
        # 45% of 8192 ≈ 3686 reclaim floor beats 1200 free pages.
        assert lp._available_ram_mb() == 3686
    with mock.patch.object(lp.os, "cpu_count", return_value=8), mock.patch.object(
        lp, "_available_ram_mb", return_value=3686
    ):
        # (3686 - 1536) // 1024 = 2 workers on an 8GB Mac.
        assert lp._default_cpu_workers() == 2
