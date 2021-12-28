import platform
import re
import subprocess


class ScaleneAppleGPU:
    def __init__(self) -> None:
        assert platform.system() == "Darwin"
        self.cmd = (
            'DYLD_INSERT_LIBRARIES="" ioreg -r -d 1 -w 0 -c "IOAccelerator"'
        )
        self.regex = re.compile(r'"Device Utilization %"=(\d+)')
        self.last_load = 0.0
        self.sample_count = 0
        self.sample_interval = 10
        pass

    def has_gpu(self) -> bool:
        # As far as I am aware, all Macs have had integrated GPUs for some time.
        return True

    def nvml_reinit(self) -> None:
        # Here for compatibility with the nvidia wrapper.
        pass

    def load(self) -> float:
        if not self.has_gpu():
            return 0.0
        self.sample_count += 1
        if self.sample_count < self.sample_interval:
            return self.last_load
        try:
            s = subprocess.Popen(self.cmd, shell=True, stdout=subprocess.PIPE)
            s_return = s.stdout.readlines()
            for line in s_return:
                line = line.decode("utf-8")
                if "Device Utilization %" in line:
                    util = self.regex.search(line)
                    if util:
                        self.last_load = int(util.group(1)) / 100.0
                        self.sample_count = 0
                        if self.last_load < 0.15:
                            self.last_load = 0.0
                        return self.last_load
            return 0.0  # Fall-through case
        except:
            return 0.0

    def memory_used(self) -> int:
        """Not yet implemented."""
        return 0
