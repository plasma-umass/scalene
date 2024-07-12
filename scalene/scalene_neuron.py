import os
import glob

from typing import Tuple

class NeuronMetrics:
    def __init__(self):
        self.total_flops = 0
        self.total_memory_consumption = 0
        self.metrics = self._get_neuron_metrics()

    def _read_metric(self, file_path):
        """Reads the metric value from the given sysfs file."""
        try:
            with open(file_path, 'r') as file:
                return int(file.read().strip())
        except IOError as e:
            print(f"Error reading {file_path}: {e}")
            return None

    def _get_core_metrics(self, core_path):
        """Retrieves the FLOPS and current memory consumption for a specific core."""
        core_metrics = {
            'flops': self._read_metric(os.path.join(core_path, 'stats', 'other_info', 'flop_count', 'total')),
            'current_memory_consumption': self._read_metric(os.path.join(core_path, 'stats', 'memory_usage', 'device_mem', 'total'))
        }
        return core_metrics

    def _get_neuron_metrics(self):
        """Retrieves FLOPS and current memory consumption for all Neuron devices and their cores, summing them for overall stats."""
        metrics = {}
        neuron_devices = glob.glob('/sys/devices/virtual/neuron_device/neuron*')
        
        for device in neuron_devices:
            device_id = os.path.basename(device)
            cores = glob.glob(os.path.join(device, 'neuron_core*'))
            core_metrics = {}

            for core in cores:
                core_id = os.path.basename(core)
                core_metrics[core_id] = self._get_core_metrics(core)
                self.total_flops += core_metrics[core_id]['flops'] if core_metrics[core_id]['flops'] else 0
                self.total_memory_consumption += core_metrics[core_id]['current_memory_consumption'] if core_metrics[core_id]['current_memory_consumption'] else 0
            
            metrics[device_id] = core_metrics
        
        return metrics

    def get_stats(self) -> Tuple[int, float]:
        """Returns a tuple of (FLOPS, memory in use)."""
        self._get_neuron_metrics()
        return (self.total_flops, self.total_memory_consumption)
        
    def display_metrics(self):
        """Prints the metrics for each core within each Neuron device."""
        for device_id, cores in self.metrics.items():
            print(f"Device: {device_id}")
            for core_id, metric in cores.items():
                print(f"  Core: {core_id}")
                print(f"    FLOPS: {metric['flops']}")
                print(f"    Current Memory Consumption: {metric['current_memory_consumption']} bytes")

        print("\nOverall Stats:")
        print(f"  Total FLOPS: {self.total_flops}")
        print(f"  Total Current Memory Consumption: {self.total_memory_consumption} bytes")


# Example usage
if __name__ == "__main__":
    neuron_metrics = NeuronMetrics()
    print(neuron_metrics.get_stats())
    # neuron_metrics.display_metrics()
