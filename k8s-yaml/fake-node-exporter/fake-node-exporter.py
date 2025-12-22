#!/usr/bin/env python3
"""
Mock Node Exporter for Large-Scale Simulation (Optimized Version)
- Reduced metrics cardinality for better performance
- Smooth metric transitions for realistic curves
- Supports 1200+ nodes with efficient data generation
"""

import os
import re
import time
import random
import math
import logging
import yaml
import sys
from concurrent.futures import ThreadPoolExecutor
from prometheus_client import start_http_server, Gauge, Counter, REGISTRY
from multiprocessing import cpu_count

# Disable default collectors
try:
    from prometheus_client import PROCESS_COLLECTOR, PLATFORM_COLLECTOR, GC_COLLECTOR
    REGISTRY.unregister(PROCESS_COLLECTOR)
    REGISTRY.unregister(PLATFORM_COLLECTOR)
    REGISTRY.unregister(GC_COLLECTOR)
except Exception:
    pass

# Force stdout to flush immediately
sys.stdout.reconfigure(line_buffering=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

LABELS = ['nodename']

# ============================================================
# Metrics Definitions (Optimized: reduced labels/cardinality)
# ============================================================

# CPU - Only total, not per-core (reduces 64x data)
NODE_CPU_SECONDS_TOTAL = Counter('node_cpu_seconds_total', 'Seconds the CPUs spent in each mode.', LABELS + ['cpu', 'mode'])
NODE_CPU_CORE_THROTTLES = Counter('node_cpu_core_throttles_total', 'Number of times a CPU core has been throttled.', LABELS)

# Memory
NODE_MEMORY_MEMTOTAL = Gauge('node_memory_MemTotal_bytes', 'Total memory.', LABELS)
NODE_MEMORY_MEMAVAILABLE = Gauge('node_memory_MemAvailable_bytes', 'Available memory.', LABELS)
NODE_MEMORY_SWAPTOTAL = Gauge('node_memory_SwapTotal_bytes', 'Total swap memory.', LABELS)
NODE_MEMORY_SWAPFREE = Gauge('node_memory_SwapFree_bytes', 'Free swap memory.', LABELS)
NODE_MEMORY_BUFFERS = Gauge('node_memory_Buffers_bytes', 'Buffer memory.', LABELS)
NODE_MEMORY_CACHED = Gauge('node_memory_Cached_bytes', 'Cached memory.', LABELS)
NODE_MEMORY_MEMFREE = Gauge('node_memory_MemFree_bytes', 'Free memory.', LABELS)

# Disk I/O - Single device only
NODE_DISK_READ_BYTES = Counter('node_disk_read_bytes_total', 'Total read bytes.', LABELS + ['device'])
NODE_DISK_WRITTEN_BYTES = Counter('node_disk_written_bytes_total', 'Total written bytes.', LABELS + ['device'])
NODE_DISK_IO_NOW = Gauge('node_disk_io_now', 'The number of I/Os currently in progress.', LABELS + ['device'])
NODE_DISK_READS_COMPLETED = Counter('node_disk_reads_completed_total', 'Reads completed.', LABELS + ['device'])
NODE_DISK_WRITES_COMPLETED = Counter('node_disk_writes_completed_total', 'Writes completed.', LABELS + ['device'])
NODE_DISK_IO_TIME = Counter('node_disk_io_time_seconds_total', 'Total seconds spent doing I/Os.', LABELS + ['device'])

# Filesystem - Single mountpoint only
NODE_FILESYSTEM_SIZE = Gauge('node_filesystem_size_bytes', 'Filesystem size in bytes.', LABELS + ['device', 'mountpoint', 'fstype'])
NODE_FILESYSTEM_FREE = Gauge('node_filesystem_free_bytes', 'Filesystem free space in bytes.', LABELS + ['device', 'mountpoint', 'fstype'])
NODE_FILESYSTEM_AVAIL = Gauge('node_filesystem_avail_bytes', 'Filesystem available space in bytes.', LABELS + ['device', 'mountpoint', 'fstype'])
NODE_FILESYSTEM_FILES = Gauge('node_filesystem_files', 'Filesystem total file nodes.', LABELS + ['device', 'mountpoint', 'fstype'])
NODE_FILESYSTEM_FILES_FREE = Gauge('node_filesystem_files_free', 'Filesystem free file nodes.', LABELS + ['device', 'mountpoint', 'fstype'])

# Network - Single device only (eth0)
NODE_NETWORK_RECEIVE_BYTES = Counter('node_network_receive_bytes_total', 'Network device receive bytes.', LABELS + ['device'])
NODE_NETWORK_TRANSMIT_BYTES = Counter('node_network_transmit_bytes_total', 'Network device transmit bytes.', LABELS + ['device'])
NODE_NETWORK_RECEIVE_PACKETS = Counter('node_network_receive_packets_total', 'Network device receive packets.', LABELS + ['device'])
NODE_NETWORK_TRANSMIT_PACKETS = Counter('node_network_transmit_packets_total', 'Network device transmit packets.', LABELS + ['device'])
NODE_NETWORK_RECEIVE_ERRS = Counter('node_network_receive_errs_total', 'Network device receive errors.', LABELS + ['device'])
NODE_NETWORK_TRANSMIT_ERRS = Counter('node_network_transmit_errs_total', 'Network device transmit errors.', LABELS + ['device'])

# Load
NODE_LOAD1 = Gauge('node_load1', '1m load average.', LABELS)
NODE_LOAD5 = Gauge('node_load5', '5m load average.', LABELS)
NODE_LOAD15 = Gauge('node_load15', '15m load average.', LABELS)

# System
NODE_BOOT_TIME = Gauge('node_boot_time_seconds', 'Node boot time, in unixtime.', LABELS)
NODE_CONTEXT_SWITCHES = Counter('node_context_switches_total', 'Total number of context switches.', LABELS)
NODE_INTR = Counter('node_intr_total', 'Total number of interrupts serviced.', LABELS)

# Processes
NODE_PROCS_RUNNING = Gauge('node_procs_running', 'Number of processes in runnable state.', LABELS)
NODE_PROCS_BLOCKED = Gauge('node_procs_blocked', 'Number of processes blocked waiting for I/O.', LABELS)

# File Descriptors
NODE_FILEFD_ALLOCATED = Gauge('node_filefd_allocated', 'File descriptors allocated.', LABELS)
NODE_FILEFD_MAX = Gauge('node_filefd_maximum', 'File descriptors maximum.', LABELS)

# Socket/Network Stats
NODE_NETSTAT_TCP_CURRESTAB = Gauge('node_netstat_Tcp_CurrEstab', 'Current established TCP connections.', LABELS)
NODE_NF_CONNTRACK_ENTRIES = Gauge('node_nf_conntrack_entries', 'Number of entries in conntrack table.', LABELS)
NODE_NF_CONNTRACK_LIMIT = Gauge('node_nf_conntrack_entries_limit', 'Maximum entries in conntrack table.', LABELS)

# Time
NODE_TIME = Gauge('node_time_seconds', 'System time in seconds since epoch.', LABELS)
NODE_TIMEX_OFFSET = Gauge('node_timex_offset_seconds', 'Time offset.', LABELS)
NODE_TIMEX_ESTIMATED_ERROR = Gauge('node_timex_estimated_error_seconds', 'Estimated error in seconds.', LABELS)
NODE_TIMEX_MAXERROR = Gauge('node_timex_maxerror_seconds', 'Maximum error in seconds.', LABELS)

# Uname
NODE_UNAME_INFO = Gauge('node_uname_info', 'System information.',
    LABELS + ['domainname', 'kernel_release', 'kernel_version', 'machine', 'os', 'raw_uname', 'sysname'])


def expand_node_range(pattern: str) -> list:
    """Expand node range patterns like 'gpu-a100-[0001..0300]'."""
    match = re.search(r'\[(\d+)\.\.(\d+)\]', pattern)
    if not match:
        return [pattern]

    start_str, end_str = match.groups()
    start, end = int(start_str), int(end_str)
    width = len(start_str)
    prefix = pattern[:match.start()]
    suffix = pattern[match.end():]

    nodes = []
    for i in range(start, end + 1):
        node_name = f"{prefix}{str(i).zfill(width)}{suffix}"
        nodes.extend(expand_node_range(node_name))
    return nodes


def load_config(path: str) -> dict:
    """Load configuration from YAML file."""
    if not os.path.exists(path):
        logger.warning(f"Config file not found: {path}, using defaults")
        return {}
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}


def generate_nodes_from_config(config: dict) -> list:
    """Generate node list from config."""
    nodes_config = config.get('nodes', [])
    if not nodes_config:
        logger.info("No nodes defined, generating 1200 default nodes")
        return [f"node-{str(i).zfill(4)}" for i in range(1, 1201)]

    all_nodes = []
    for pattern in nodes_config:
        all_nodes.extend(expand_node_range(pattern))
    return all_nodes


class SmoothValue:
    """
    Generates smooth, realistic metric values using:
    - Base trend (sine wave for daily patterns)
    - Random walk for gradual changes
    - Occasional spikes for realistic behavior
    """
    __slots__ = ['current', 'target', 'velocity', 'base', 'amplitude',
                 'phase_offset', 'noise_scale', 'spike_prob', 'spike_magnitude']

    def __init__(self, base: float, amplitude: float = 0.1, noise_scale: float = 0.02,
                 spike_prob: float = 0.001, spike_magnitude: float = 0.3):
        self.base = base
        self.amplitude = amplitude
        self.noise_scale = noise_scale
        self.spike_prob = spike_prob
        self.spike_magnitude = spike_magnitude
        self.phase_offset = random.uniform(0, 2 * math.pi)
        self.current = base
        self.target = base
        self.velocity = 0.0

    def next(self, dt: float = 1.0) -> float:
        """Get next smoothed value with realistic transitions."""
        now = time.time()

        # Daily pattern: sine wave with 24-hour period
        daily_factor = math.sin((now / 86400) * 2 * math.pi + self.phase_offset)
        trend = self.base + self.amplitude * daily_factor

        # Random walk towards trend
        noise = random.gauss(0, self.noise_scale * dt)
        self.target = trend + noise

        # Smooth transition (exponential smoothing)
        alpha = min(1.0, 0.1 * dt)  # Smoothing factor
        self.current = self.current * (1 - alpha) + self.target * alpha

        # Occasional spike
        if random.random() < self.spike_prob * dt:
            spike = random.uniform(0.5, 1.0) * self.spike_magnitude
            self.current += spike if random.random() > 0.5 else -spike * 0.5

        return max(0.0, min(1.0, self.current))


class NodeState:
    """Holds state for a single node with smooth metric generation."""
    __slots__ = ['name', 'cpu_cores', 'memory_total', 'fs_size', 'boot_time',
                 'last_update', 'static_set', 'cpu_usage', 'mem_usage',
                 'io_rate', 'net_rate', 'load_factor', 'conntrack']

    def __init__(self, name: str, cpu_cores: int = 64,
                 memory_total: int = 512 * 1024**3, fs_size: int = 2000 * 1024**3,
                 base_cpu: float = 0.15, base_mem: float = 0.40):
        self.name = name
        self.cpu_cores = cpu_cores
        self.memory_total = memory_total
        self.fs_size = fs_size
        self.boot_time = time.time() - random.randint(86400, 864000)
        self.last_update = time.time()
        self.static_set = False

        # Smooth value generators for each metric type
        # Each node has slightly different patterns
        node_seed = hash(name) % 1000 / 1000.0

        self.cpu_usage = SmoothValue(
            base=base_cpu + node_seed * 0.1,
            amplitude=0.08,
            noise_scale=0.01,
            spike_prob=0.0005,
            spike_magnitude=0.25
        )

        self.mem_usage = SmoothValue(
            base=base_mem + node_seed * 0.15,
            amplitude=0.05,
            noise_scale=0.005,
            spike_prob=0.0001,
            spike_magnitude=0.1
        )

        self.io_rate = SmoothValue(
            base=0.3 + node_seed * 0.2,
            amplitude=0.15,
            noise_scale=0.05,
            spike_prob=0.002,
            spike_magnitude=0.5
        )

        self.net_rate = SmoothValue(
            base=0.2 + node_seed * 0.3,
            amplitude=0.1,
            noise_scale=0.03,
            spike_prob=0.001,
            spike_magnitude=0.4
        )

        self.load_factor = SmoothValue(
            base=0.2 + node_seed * 0.1,
            amplitude=0.1,
            noise_scale=0.02
        )

        self.conntrack = SmoothValue(
            base=0.15 + node_seed * 0.1,
            amplitude=0.05,
            noise_scale=0.01
        )


class MockNodeExporter:
    """Mock Node Exporter optimized for large-scale simulation with realistic data."""

    def __init__(self):
        logger.info("Starting MockNodeExporter v3.1 (Optimized + Smooth Curves)")
        config_path = os.getenv('MOCK_CONFIG_PATH', 'config.yaml')
        self.config = load_config(config_path)
        self.running = True

        # Get node list
        node_names = generate_nodes_from_config(self.config)
        logger.info(f"Total nodes: {len(node_names)}")

        # Get hardware specs
        spec = self.config.get('spec', {})
        cpu_cores = spec.get('cpu_cores', 64)
        memory_bytes = spec.get('memory_bytes', 512 * 1024**3)
        disk_bytes = spec.get('disk_bytes', 2000 * 1024**3)

        # Get baseline usage
        metrics = self.config.get('metrics', self.config.get('usage_profile', {}))
        base_cpu = metrics.get('cpu', metrics.get('cpu_percent', 15)) / 100.0
        base_mem = metrics.get('memory', metrics.get('memory_percent', 40)) / 100.0
        self.disk_usage_pct = metrics.get('disk', metrics.get('disk_percent', 35)) / 100.0

        # Initialize nodes
        self.nodes = {}
        for name in node_names:
            self.nodes[name] = NodeState(
                name=name,
                cpu_cores=cpu_cores,
                memory_total=memory_bytes,
                fs_size=disk_bytes,
                base_cpu=base_cpu,
                base_mem=base_mem
            )

        # Worker config
        runtime = self.config.get('runtime', {})
        self.num_workers = runtime.get('workers', min(8, cpu_count()))
        self.batch_size = runtime.get('batch_size', 150)
        self.update_interval = self.config.get('schedule', {}).get('interval_seconds', 15)

        # CPU reporting mode: 'aggregate' (single cpu=total) or 'sampled' (a few cores)
        self.cpu_mode = self.config.get('cpu_mode', 'aggregate')
        self.cpu_sample_count = min(4, cpu_cores)  # Only report 4 CPUs if sampled

        logger.info(f"Workers: {self.num_workers}, Batch: {self.batch_size}, "
                    f"Interval: {self.update_interval}s, CPU mode: {self.cpu_mode}")

    def update_static_metrics(self, state: NodeState):
        """Set static metrics once."""
        name = state.name

        NODE_BOOT_TIME.labels(nodename=name).set(state.boot_time)
        NODE_FILEFD_MAX.labels(nodename=name).set(1048576)
        NODE_NF_CONNTRACK_LIMIT.labels(nodename=name).set(262144)

        # Single filesystem
        NODE_FILESYSTEM_SIZE.labels(nodename=name, device='vda', mountpoint='/', fstype='ext4').set(state.fs_size)
        NODE_FILESYSTEM_FILES.labels(nodename=name, device='vda', mountpoint='/', fstype='ext4').set(state.fs_size / 4096 / 10)

        # Uname
        NODE_UNAME_INFO.labels(
            domainname="(none)",
            kernel_release="5.15.0-122-generic",
            kernel_version="#132-Ubuntu SMP",
            machine="x86_64",
            nodename=name,
            os="Linux",
            raw_uname=f"Linux {name} 5.15.0",
            sysname="Linux"
        ).set(1)

        state.static_set = True

    def update_dynamic_metrics(self, state: NodeState, dt: float):
        """Update dynamic metrics with smooth transitions."""
        name = state.name
        now = time.time()

        # Get smooth metric values
        cpu_pct = state.cpu_usage.next(dt)
        mem_pct = state.mem_usage.next(dt)
        io_factor = state.io_rate.next(dt)
        net_factor = state.net_rate.next(dt)
        load_pct = state.load_factor.next(dt)
        conn_pct = state.conntrack.next(dt)

        # === CPU ===
        num_cores = state.cpu_cores
        core_user = dt * cpu_pct * 0.6
        core_sys = dt * cpu_pct * 0.3
        core_iowait = dt * cpu_pct * 0.08
        core_steal = dt * 0.002
        core_idle = max(0, dt - core_user - core_sys - core_iowait - core_steal)

        if self.cpu_mode == 'aggregate':
            # Report as single "total" CPU (most efficient)
            NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu='total', mode='user').inc(core_user * num_cores)
            NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu='total', mode='system').inc(core_sys * num_cores)
            NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu='total', mode='idle').inc(core_idle * num_cores)
            NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu='total', mode='iowait').inc(core_iowait * num_cores)
            NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu='total', mode='steal').inc(core_steal * num_cores)
        else:
            # Report only a sample of CPUs
            for c in range(self.cpu_sample_count):
                cpu_str = str(c)
                NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu=cpu_str, mode='user').inc(core_user)
                NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu=cpu_str, mode='system').inc(core_sys)
                NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu=cpu_str, mode='idle').inc(core_idle)
                NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu=cpu_str, mode='iowait').inc(core_iowait)
                NODE_CPU_SECONDS_TOTAL.labels(nodename=name, cpu=cpu_str, mode='steal').inc(core_steal)

        # CPU throttles (rare)
        if random.random() < 0.0001 * dt:
            NODE_CPU_CORE_THROTTLES.labels(nodename=name).inc(1)

        # === Memory ===
        mem_total = state.memory_total
        mem_used = mem_total * mem_pct
        mem_avail = mem_total - mem_used
        mem_free = mem_avail * 0.15
        mem_cached = mem_avail * 0.55
        mem_buffers = mem_avail * 0.10
        swap_total = mem_total * 0.1
        swap_used = swap_total * mem_pct * 0.1

        NODE_MEMORY_MEMTOTAL.labels(nodename=name).set(mem_total)
        NODE_MEMORY_MEMAVAILABLE.labels(nodename=name).set(mem_avail)
        NODE_MEMORY_MEMFREE.labels(nodename=name).set(mem_free)
        NODE_MEMORY_CACHED.labels(nodename=name).set(mem_cached)
        NODE_MEMORY_BUFFERS.labels(nodename=name).set(mem_buffers)
        NODE_MEMORY_SWAPTOTAL.labels(nodename=name).set(swap_total)
        NODE_MEMORY_SWAPFREE.labels(nodename=name).set(swap_total - swap_used)

        # === Disk I/O ===
        io_base = 100 * 1024  # 100 KB/s base
        io_rate = io_base * (1 + io_factor * 10)  # Scale by factor

        NODE_DISK_READ_BYTES.labels(nodename=name, device='vda').inc(io_rate * dt)
        NODE_DISK_WRITTEN_BYTES.labels(nodename=name, device='vda').inc(io_rate * dt * 0.7)
        NODE_DISK_IO_NOW.labels(nodename=name, device='vda').set(int(io_factor * 15))

        ops = io_rate / 4096.0
        NODE_DISK_READS_COMPLETED.labels(nodename=name, device='vda').inc(ops * dt)
        NODE_DISK_WRITES_COMPLETED.labels(nodename=name, device='vda').inc(ops * dt * 0.7)
        NODE_DISK_IO_TIME.labels(nodename=name, device='vda').inc(ops * dt * 0.0003)

        # === Filesystem ===
        fs_free = state.fs_size * (1 - self.disk_usage_pct)
        NODE_FILESYSTEM_FREE.labels(nodename=name, device='vda', mountpoint='/', fstype='ext4').set(fs_free)
        NODE_FILESYSTEM_AVAIL.labels(nodename=name, device='vda', mountpoint='/', fstype='ext4').set(fs_free * 0.95)
        NODE_FILESYSTEM_FILES_FREE.labels(nodename=name, device='vda', mountpoint='/', fstype='ext4').set(
            (state.fs_size / 4096 / 10) * (1 - self.disk_usage_pct)
        )

        # === Network ===
        net_base = 500 * 1024  # 500 KB/s base
        rx_rate = net_base * (1 + net_factor * 5)
        tx_rate = rx_rate * 0.6

        NODE_NETWORK_RECEIVE_BYTES.labels(nodename=name, device='eth0').inc(rx_rate * dt)
        NODE_NETWORK_TRANSMIT_BYTES.labels(nodename=name, device='eth0').inc(tx_rate * dt)
        NODE_NETWORK_RECEIVE_PACKETS.labels(nodename=name, device='eth0').inc(rx_rate * dt / 1500)
        NODE_NETWORK_TRANSMIT_PACKETS.labels(nodename=name, device='eth0').inc(tx_rate * dt / 1500)

        # Errors (very rare)
        if random.random() < 0.00005 * dt:
            NODE_NETWORK_RECEIVE_ERRS.labels(nodename=name, device='eth0').inc(1)
            NODE_NETWORK_TRANSMIT_ERRS.labels(nodename=name, device='eth0').inc(1)

        # === Load Average ===
        load_base = num_cores * load_pct
        NODE_LOAD1.labels(nodename=name).set(load_base * (1 + random.gauss(0, 0.05)))
        NODE_LOAD5.labels(nodename=name).set(load_base * (1 + random.gauss(0, 0.03)))
        NODE_LOAD15.labels(nodename=name).set(load_base * (1 + random.gauss(0, 0.01)))

        # === System ===
        NODE_CONTEXT_SWITCHES.labels(nodename=name).inc(500 * dt * (1 + cpu_pct))
        NODE_INTR.labels(nodename=name).inc(300 * dt * (1 + cpu_pct * 0.5))

        # === Processes ===
        base_procs = 5 + int(load_pct * 20)
        NODE_PROCS_RUNNING.labels(nodename=name).set(base_procs + random.randint(-2, 3))
        NODE_PROCS_BLOCKED.labels(nodename=name).set(random.randint(0, 2) if io_factor > 0.5 else 0)

        # === File Descriptors ===
        fd_base = 15000 + int(conn_pct * 30000)
        NODE_FILEFD_ALLOCATED.labels(nodename=name).set(fd_base + random.randint(-500, 500))

        # === Network/Socket ===
        conn_base = 50 + int(conn_pct * 200)
        NODE_NETSTAT_TCP_CURRESTAB.labels(nodename=name).set(conn_base + random.randint(-10, 10))
        NODE_NF_CONNTRACK_ENTRIES.labels(nodename=name).set(int(conn_pct * 50000) + random.randint(-1000, 1000))

        # === Time ===
        NODE_TIME.labels(nodename=name).set(now)
        NODE_TIMEX_OFFSET.labels(nodename=name).set(random.gauss(0, 0.0002))
        NODE_TIMEX_ESTIMATED_ERROR.labels(nodename=name).set(abs(random.gauss(0, 0.00005)))
        NODE_TIMEX_MAXERROR.labels(nodename=name).set(abs(random.gauss(0.0001, 0.0001)))

    def update_node_batch(self, node_names: list):
        """Update a batch of nodes."""
        now = time.time()
        for name in node_names:
            state = self.nodes.get(name)
            if not state:
                continue

            dt = now - state.last_update
            if dt <= 0:
                continue
            state.last_update = now

            try:
                if not state.static_set:
                    self.update_static_metrics(state)
                self.update_dynamic_metrics(state, dt)
            except Exception as e:
                logger.error(f"Error updating {name}: {e}")

    def update_metrics_loop(self):
        """Main update loop with parallel processing."""
        logger.info(f"Starting metrics updater...")
        node_names = list(self.nodes.keys())

        while self.running:
            start_time = time.time()

            # Split into batches
            batches = [node_names[i:i + self.batch_size]
                      for i in range(0, len(node_names), self.batch_size)]

            # Process batches in parallel
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                futures = [executor.submit(self.update_node_batch, batch) for batch in batches]
                for future in futures:
                    try:
                        future.result(timeout=self.update_interval)
                    except Exception as e:
                        logger.error(f"Batch error: {e}")

            elapsed = time.time() - start_time
            logger.info(f"Updated {len(node_names)} nodes in {elapsed:.2f}s")

            sleep_time = max(0.1, self.update_interval - elapsed)
            time.sleep(sleep_time)

    def start(self):
        """Start the exporter."""
        from threading import Thread
        Thread(target=self.update_metrics_loop, daemon=True).start()

        port = int(os.getenv('PORT', 9100))
        start_http_server(port)
        logger.info(f"Server started on port {port}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
            logger.info("Stopping...")


if __name__ == '__main__':
    exporter = MockNodeExporter()
    exporter.start()
