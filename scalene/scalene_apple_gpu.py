import platform
import random
import re
import subprocess
from typing import Tuple


class ScaleneAppleGPU:
    """Wrapper class for Apple integrated GPU statistics."""

    def __init__(self, sampling_frequency: int = 100) -> None:
        assert platform.system() == "Darwin"
        self.cmd = (
            'DYLD_INSERT_LIBRARIES="" ioreg -r -d 1 -w 0 -c "IOAccelerator"'
        )
        self.regex_util = re.compile(r'"Device Utilization %"=(\d+)')
        self.regex_inuse = re.compile(r'"In use system memory"=(\d+)')
        # Only actually get stats some fraction of the time, since it is costly.
        # Used in get_stats().
        self.gpu_sampling_frequency = sampling_frequency

    def has_gpu(self) -> bool:
        """Returns true: as far as I am aware, all Macs have had integrated GPUs for some time."""
        # Disabling Apple GPU, since it does not collect per-process statistics.
        return False

    def nvml_reinit(self) -> None:
        """A NOP, here for compatibility with the nvidia wrapper."""
        return

    def get_stats(self) -> Tuple[float, float]:
        """Returns a tuple of (utilization%, memory in use)"""
        if not self.has_gpu():
            return (0.0, 0.0)
        try:
            # Only periodically query the statistics for real (at a
            # rate of 1/self.gpu_sampling_frequency).  We do this to
            # amortize its cost, as it is shockingly expensive.
            if random.randint(0, self.gpu_sampling_frequency - 1) != 0:
                return (0.0, 0.0)
            in_use = 0.0
            util = 0.0
            read_process = subprocess.Popen(
                self.cmd, shell=True, stdout=subprocess.PIPE
            )
            if read_process.stdout is not None:
                read_process_return = read_process.stdout.readlines()
                for line in read_process_return:
                    decoded_line = line.decode("utf-8")
                    # print(decoded_line)
                    if "In use system memory" in decoded_line:
                        in_use_re = self.regex_inuse.search(decoded_line)
                        if in_use_re:
                            in_use = float(in_use_re.group(1))
                    if "Device Utilization %" in decoded_line:
                        util_re = self.regex_util.search(decoded_line)
                        if util_re:
                            util = int(util_re.group(1)) / 1000
                    if util and in_use:
                        break
                return (util, in_use)
        except Exception:
            pass
        return (0.0, 0.0)
