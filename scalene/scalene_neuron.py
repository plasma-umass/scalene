import json
import subprocess
import threading
import time
import tempfile
import os

from typing import Tuple

class ScaleneNeuron:
    
    def __init__(self) -> None:
        self._process = None
        self._thread = None
        self._stop_event = threading.Event()
        self._has_neuron = False
        self._config_path = self._generate_config()
        self.cpu_utilization = 0.0
        self.memory_used_bytes = 0.0
        self.neuroncore_utilization = 0.0
        self.start()

    def nvml_reinit(self) -> None:
        """Here for compatibility with ScaleneGPU."""
        pass
    
    def _generate_config(self) -> None:
        config = {
            "period": "1s",
            "system_metrics": [
                {
                    "type": "vcpu_usage"
                },
                {
                    "type": "memory_info"
                }
            ],
            "neuron_runtimes": [
                {
                    "tag_filter": ".*",
                    "metrics": [
                        {
                            "type": "neuroncore_counters"
                        },
                        {
                            "type": "memory_used"
                        },
                        {
                            "type": "neuron_runtime_vcpu_usage"
                        }
                    ]
                }
            ]
        }
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
        with open(temp_file.name, 'w') as file:
            json.dump(config, file)
        return temp_file.name

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_monitor)
        self._thread.start()

    def has_gpu(self) -> bool:
        return self._has_neuron

    def _run_monitor(self):
        try:
            self._process = subprocess.Popen(
                ['neuron-monitor', '-c', self._config_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            sel = selectors.DefaultSelector()
            sel.register(self._process.stdout, selectors.EVENT_READ)
            
            while not self._stop_event.is_set():
                events = sel.select(timeout=1)
                for key, _ in events:
                    line = key.fileobj.readline().strip()
                    if line:
                        self._parse_and_print_output(line)
                time.sleep(1)
        except Exception as e:
            print(f"Error running neuron-monitor: {e}")
        finally:
            if self._process:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            if os.path.exists(self._config_path):
                os.remove(self._config_path)

    def _run_monitor_old(self) -> None:
        try:
            self._process = subprocess.Popen(
                ['neuron-monitor', '-c', self._config_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            self._has_neuron = True
            while not self._stop_event.is_set():
                output = self._process.stdout.readline().strip()
                if output:
                    self._parse_and_print_output(output)
                # time.sleep(1)
        except Exception as e:
            print(f"Error running neuron-monitor: {e}")
        finally:
            self._process.terminate()

    def _parse_and_print_output(self, output: str) -> None:
        try:
            data = json.loads(output)
            system_data = data.get('system_data', {})
            vcpu_usage = system_data.get('vcpu_usage', {})
            memory_info = system_data.get('memory_info', {})
            neuron_runtime_data = data.get('neuron_runtime_data', [])
            
            if vcpu_usage:
                total_idle = 0
                total_cores = 0
                for core, usage in vcpu_usage.get('usage_data', {}).items():
                    total_idle += usage.get('idle', 0)
                    total_cores += 1
                if total_cores > 0:
                    average_idle = total_idle / total_cores
                    self.cpu_utilization = 100 - average_idle

            # Disabled for now: host memory consumption
            # if memory_info:
            #    self.memory_used_bytes = memory_info.get('memory_used_bytes', 0)

            self.neuroncore_utilization = 0.0
            self.memory_used_bytes = 0.0
            
            if neuron_runtime_data:
                for per_core_info in neuron_runtime_data:
                    report = per_core_info.get('report', {})
                    neuroncore_counters = report.get('neuroncore_counters', {})
                    neuroncores_in_use = neuroncore_counters.get('neuroncores_in_use', {})

                    total_utilization = 0
                    total_neuroncores = 0

                    for core, counters in neuroncores_in_use.items():
                        total_utilization += counters.get('neuroncore_utilization', 0)
                        total_neuroncores += 1

                    if total_neuroncores > 0:
                        overall_utilization = total_utilization / total_neuroncores
                    else:
                        overall_utilization = 0
                        
                if total_neuroncores > 0:
                    average_utilization = (total_utilization / total_neuroncores)
                    self.neuroncore_utilization = average_utilization

                total_memory_used = 0.0
                for per_core_info in neuron_runtime_data:
                    report = per_core_info.get('report', {})
                    memory_info = (report
                                   .get('memory_used', {})
                                   .get('neuron_runtime_used_bytes', {})
                                   .get('usage_breakdown', {})
                                   .get('neuroncore_memory_usage', {}))
                    for core, mem_info in memory_info.items():
                        total_memory_used += sum(mem_info.values())
                        
                self.memory_used_bytes = total_memory_used

        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def stop(self) -> None:
        self._stop_event.set()

        # Try to ensure the thread terminates
        if self._thread:
            self._thread.join(timeout=2)

        # Ensure the process terminates
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()

        # Clean up the temporary file
        if os.path.exists(self._config_path):
            os.remove(self._config_path)


    def get_stats(self) -> Tuple[float, float]:
        return self.neuroncore_utilization, self.memory_used_bytes

if __name__ == "__main__":
    monitor = ScaleneNeuron()
    try:
        while True:
            print(monitor.get_stats())
            time.sleep(0.5)
    except KeyboardInterrupt:
        monitor.stop()
