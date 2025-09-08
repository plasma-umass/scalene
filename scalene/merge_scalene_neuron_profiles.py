#!/usr/bin/env python3
import bisect
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def parse_debug_file_programmatic(
    debug_file: str, valid_filenames: List[str]
) -> Tuple[Optional[str], List[Tuple[int, str]]]:
    """Parse debug file programmatically to extract execution data"""
    if not Path(debug_file).exists():
        return None, []

    with open(debug_file) as f:
        content = f.read()

    # Extract PID
    import re

    pid_match = re.search(r"PID: (\d+)", content)
    pid = pid_match.group(1) if pid_match else None

    # Extract source locations
    executions = []
    sections = content.split("---")

    for section in sections:
        if not section.strip():
            continue

        lines = section.strip().split("\n")
        source_line = None
        kernel_name = None

        for line in lines:
            if line.startswith("SOURCE: "):
                source_info = line[8:]  # Remove 'SOURCE: '
                if ":" in source_info:
                    # Check if source matches any of the files in scalene profile
                    for filename in valid_filenames:
                        if filename in source_info:
                            source_line = int(source_info.split(":")[-1])
                            break
            elif line.startswith("KERNEL: "):
                kernel_name = line[8:]  # Remove 'KERNEL: '

        if source_line:
            executions.append((source_line, kernel_name or "unknown"))

    return pid, executions


def calculate_cpu_sample_overlap(
    cpu_samples_list: List[float],
    nc_intervals: List[Tuple[float, float]],
    start_time_absolute: float,
    start_time_perf: float,
) -> Tuple[int, int, float]:
    """Calculate overlap between CPU samples and nc_exec_running intervals

    Args:
        cpu_samples_list: List of CPU sample timestamps (perf_counter values)
        nc_intervals: List of (start_time, end_time) tuples for nc_exec_running events (in seconds)
        start_time_absolute: Absolute start time (Unix timestamp in seconds)
        start_time_perf: Performance counter start time (in seconds)

    Returns:
        tuple: (overlap_count, total_count, overlap_percent)
    """
    if not cpu_samples_list or not nc_intervals:
        return 0, len(cpu_samples_list), 0.0

    overlap_count = 0
    total_count = len(cpu_samples_list)

    # Sort intervals by start time for efficient searching
    sorted_intervals = sorted(nc_intervals, key=lambda x: x[0])

    for cpu_sample_perf in cpu_samples_list:
        # Convert CPU sample to absolute time
        cpu_sample_absolute = start_time_absolute + (cpu_sample_perf - start_time_perf)

        # Check if CPU sample overlaps with any interval (strict overlap)
        for start, end in sorted_intervals:
            # Check if CPU sample falls within interval exactly
            if start <= cpu_sample_absolute <= end:
                overlap_count += 1
                break

    overlap_percent = (overlap_count / total_count * 100) if total_count > 0 else 0.0
    return overlap_count, total_count, overlap_percent


def merge_neuron_into_scalene_programmatic(
    scalene_file: str, neuron_file: str, output_file: str, target_rank: int = 0
) -> None:
    """Merge Neuron timing data into Scalene JSON using programmatic kernel execution data"""

    # Load Scalene data
    try:
        with open(scalene_file) as f:
            content = f.read().strip()
            if "<!DOCTYPE html>" in content:
                json_start = content.find("const profile = ") + len("const profile = ")
                if json_start > len("const profile = ") - 1:
                    brace_count = 0
                    json_end = json_start
                    for i, char in enumerate(content[json_start:]):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                json_end = json_start + i + 1
                                break
                    content = content[json_start:json_end]
            scalene_data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Error parsing {scalene_file}: {e}")
        return

    # Load Neuron trace data
    with open(neuron_file) as f:
        neuron_data = json.load(f)

    # Get timing information from Scalene
    start_time_absolute = scalene_data.get("start_time_absolute", 0)
    start_time_perf = scalene_data.get("start_time_perf", 0)

    # Extract valid filenames from Scalene data
    valid_filenames = []
    if "files" in scalene_data:
        for filename in scalene_data["files"]:
            # Extract just the basename for matching
            basename = Path(filename).name
            valid_filenames.append(basename)

    # Get kernel execution data programmatically
    debug_file = f"debug_rank_{target_rank}.txt"
    target_pid, spike_lines = parse_debug_file_programmatic(debug_file, valid_filenames)

    if not spike_lines:
        print(f"No kernel execution data found for rank {target_rank}")
        return

    # Extract events from Neuron trace
    events_list = (
        neuron_data
        if isinstance(neuron_data, list)
        else neuron_data.get("trace_event", [])
    )
    nrt_events = []
    kbl_events = []
    nc_events = []
    nc_intervals = []

    for event in events_list:
        event_pid = str(event.get("process_id", ""))
        if target_pid is None or event_pid == target_pid:
            if event.get("name") == "nrt_execute":
                nrt_events.append(
                    {
                        "name": event.get("name"),
                        "duration_ns": event.get("duration", 0),
                        "duration_ms": event.get("duration", 0) / 1000000,
                        "timestamp": event.get("timestamp", 0),
                        "process_id": event.get("process_id"),
                        "thread_id": event.get("thread_id"),
                    }
                )
            elif event.get("name") == "kbl_exec_pre":
                exec_id = event.get("args", {}).get("exec_id") or event.get("exec_id")
                kbl_events.append(
                    {
                        "name": event.get("name"),
                        "exec_id": exec_id,
                        "timestamp": event.get("timestamp", 0),
                        "process_id": event.get("process_id"),
                        "thread_id": event.get("thread_id"),
                    }
                )

        # Collect nc_exec_running events for target PID
        if event.get("name") == "nc_exec_running" and (
            target_pid is None or event_pid == target_pid
        ):
            timestamp_ns = event.get("timestamp", 0)
            duration_ns = event.get("duration", 0)

            start_time_sec = timestamp_ns / 1e9
            end_time_sec = (timestamp_ns + duration_ns) / 1e9

            nc_intervals.append((start_time_sec, end_time_sec))

            exec_id = event.get("args", {}).get("exec_id") or event.get("exec_id")
            nc_events.append(
                {
                    "name": event.get("name"),
                    "duration_ns": duration_ns,
                    "duration_ms": duration_ns / 1000000,
                    "timestamp": timestamp_ns,
                    "exec_id": exec_id,
                    "process_id": event.get("process_id"),
                    "thread_id": event.get("thread_id"),
                }
            )

    nrt_events.sort(key=lambda x: x["timestamp"])
    kbl_events.sort(key=lambda x: x["timestamp"])
    nc_events.sort(key=lambda x: x["timestamp"])

    # Create exec_id to nrt_execute mapping via kbl_exec_pre
    exec_id_to_nrt_index = {}
    for i, kbl_event in enumerate(kbl_events):
        if i < len(nrt_events) and kbl_event["exec_id"] is not None:
            exec_id_to_nrt_index[kbl_event["exec_id"]] = i

    # Map kernel executions to nrt events by timestamp order
    total_neuron_time = sum(event["duration_ms"] for event in nrt_events)
    total_nc_time = sum(event["duration_ms"] for event in nc_events)

    # Group spike lines by line number
    from collections import defaultdict

    line_to_events = defaultdict(list)
    line_to_nc_events = defaultdict(list)

    # Map nrt_execute events to spike lines consecutively
    for i, (spike_line, kernel_name) in enumerate(spike_lines):
        if i < len(nrt_events):
            line_to_events[spike_line].append((nrt_events[i], kernel_name))

    # Map nc_exec_running events to spike lines via exec_id
    for nc_event in nc_events:
        exec_id = nc_event.get("exec_id")
        if exec_id in exec_id_to_nrt_index:
            nrt_index = exec_id_to_nrt_index[exec_id]
            if nrt_index < len(spike_lines):
                spike_line, kernel_name = spike_lines[nrt_index]
                line_to_nc_events[spike_line].append((nc_event, kernel_name))

    # Process CPU sample overlap for all lines
    total_cpu_samples_with_overlap = 0
    total_cpu_samples = 0

    # Add neuron timing to scalene structure
    if "files" in scalene_data:
        for filename, file_data in scalene_data["files"].items():
            if "lines" in file_data:
                for line_data in file_data["lines"]:
                    lineno = line_data.get("lineno")
                    cpu_samples_list = line_data.get("cpu_samples_list", [])

                    # Calculate CPU sample overlap with nc_exec_running for ALL lines with CPU samples
                    if cpu_samples_list and nc_intervals:
                        overlap_count, total_count, overlap_percent = (
                            calculate_cpu_sample_overlap(
                                cpu_samples_list,
                                nc_intervals,
                                start_time_absolute,
                                start_time_perf,
                            )
                        )

                        line_data["cpu_samples_nc_overlap_count"] = overlap_count
                        line_data["cpu_samples_total_count"] = total_count
                        line_data["cpu_samples_nc_overlap_percent"] = overlap_percent

                        total_cpu_samples_with_overlap += overlap_count
                        total_cpu_samples += total_count
                    else:
                        line_data["cpu_samples_nc_overlap_count"] = 0
                        line_data["cpu_samples_total_count"] = len(cpu_samples_list)
                        line_data["cpu_samples_nc_overlap_percent"] = 0.0

                    # Check if this line has neuron events
                    basename = Path(filename).name
                    if basename in valid_filenames and lineno in line_to_events:
                        events_for_line = line_to_events[lineno]

                        # Sum all events for this line
                        total_time_ms = sum(
                            event["duration_ms"] for event, _ in events_for_line
                        )
                        all_events = [event for event, _ in events_for_line]
                        kernel_name = events_for_line[0][
                            1
                        ]  # Use first kernel name as reference

                        # Process nc_exec_running events for this line
                        nc_events_for_line = line_to_nc_events.get(lineno, [])
                        total_nc_time_ms = sum(
                            event["duration_ms"] for event, _ in nc_events_for_line
                        )
                        all_nc_events = [event for event, _ in nc_events_for_line]

                        # Add neuron timing fields
                        line_data["nrt_time_ms"] = total_time_ms
                        line_data["nrt_percent"] = (
                            (total_time_ms / total_neuron_time) * 100
                            if total_neuron_time > 0
                            else 0
                        )
                        line_data["nrt_execute_count"] = len(all_events)
                        line_data["nrt_events"] = all_events
                        line_data["nrt_source_code"] = kernel_name

                        # Add nc_exec_running data
                        line_data["nc_time_ms"] = total_nc_time_ms
                        line_data["nc_percent"] = (
                            (total_nc_time_ms / total_nc_time) * 100
                            if total_nc_time > 0
                            else 0
                        )
                        line_data["nc_execute_count"] = len(all_nc_events)
                        line_data["nc_events"] = all_nc_events

                        # Add ratio of nc_exec time to nrt_execute time
                        line_data["nc_nrt_ratio"] = (
                            total_nc_time_ms / total_time_ms if total_time_ms > 0 else 0
                        )

                        # Keep legacy field for backward compatibility
                        line_data["neuron_time_ms"] = total_time_ms

    # Add neuron metadata
    if len(nrt_events) > 0:
        scalene_data["neuron_total_time_ms"] = total_neuron_time
        scalene_data["neuron_total_nc_time_ms"] = total_nc_time
        scalene_data["neuron_event_count"] = len(nrt_events)
        scalene_data["neuron_nc_event_count"] = len(nc_events)
        scalene_data["cpu_samples_total_with_nc_overlap"] = (
            total_cpu_samples_with_overlap
        )
        scalene_data["cpu_samples_total"] = total_cpu_samples
        scalene_data["cpu_samples_nc_overlap_percent_overall"] = (
            (total_cpu_samples_with_overlap / total_cpu_samples * 100)
            if total_cpu_samples > 0
            else 0.0
        )

    # Write merged data
    with open(output_file, "w") as f:
        json.dump(scalene_data, f, indent=2)

    print(f"Merged data written to {output_file}")
    print(f"Total neuron time: {total_neuron_time:.2f}ms")
    print(f"Total nc_exec time: {total_nc_time:.2f}ms")
    print(
        f"Overall CPU sample overlap: {total_cpu_samples_with_overlap}/{total_cpu_samples} ({(total_cpu_samples_with_overlap/total_cpu_samples*100) if total_cpu_samples > 0 else 0:.1f}%)"
    )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python merge_scalene_neuron_programmatic_with_overlap.py <scalene_file> <neuron_file> <output_file>"
        )
        sys.exit(1)

    scalene_file, neuron_file, output_file = sys.argv[1:4]
    merge_neuron_into_scalene_programmatic(scalene_file, neuron_file, output_file)
