import platform
import re
import subprocess
from typing import Tuple

class ScaleneAppleGPU:
    def __init__(self) -> None:
        assert platform.system() == "Darwin"
        self.cmd = (
            'DYLD_INSERT_LIBRARIES="" ioreg -r -d 1 -w 0 -c "IOAccelerator"'
        )
        self.regex1 = re.compile(r'"Device Utilization %"=(\d+)')
        self.regex2 = re.compile(r'"In use system memory"=(\d+)')
        pass

    def has_gpu(self) -> bool:
        # As far as I am aware, all Macs have had integrated GPUs for some time.
        return True

    def nvml_reinit(self) -> None:
        # Here for compatibility with the nvidia wrapper.
        pass

    def get_stats(self) -> Tuple[float, float]:
        if self.has_gpu():
            try:
                in_use = 0.0
                util = 0.0
                s = subprocess.Popen(self.cmd, shell=True, stdout=subprocess.PIPE)
                if s.stdout is not None:
                    s_return = s.stdout.readlines()
                    for line in s_return:
                        decoded_line = line.decode("utf-8")
                        if "In use system memory" in decoded_line:
                            in_use_re = self.regex2.search(decoded_line)
                            if in_use_re:
                                in_use = float(in_use_re.group(1))
                        if "Device Utilization %" in decoded_line:
                            util_re = self.regex1.search(decoded_line)
                            if util_re:
                                util = int(util_re.group(1)) / 1000
                        if util and in_use:
                            break
                    return (util, in_use)
            except:
                pass
        return (0.0, 0.0)
