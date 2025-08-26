import os
import subprocess
import sys


def set_nvidia_gpu_modes() -> bool:
    import pynvml

    try:
        # Initialize NVML
        pynvml.nvmlInit()

        # Get the number of GPUs
        device_count = pynvml.nvmlDeviceGetCount()

        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            # Enable persistence mode
            pynvml.nvmlDeviceSetPersistenceMode(handle, pynvml.NVML_FEATURE_ENABLED)

            # Enable accounting mode
            pynvml.nvmlDeviceSetAccountingMode(handle, pynvml.NVML_FEATURE_ENABLED)

        print("Persistence and accounting mode set for all GPUs.")
        return True

    except pynvml.NVMLError as e:
        print(f"An NVML error occurred: {e}")
        return False

    finally:
        # Shutdown NVML
        pynvml.nvmlShutdown()


if __name__ == "__main__":
    # Check if the script is running as root
    if os.geteuid() != 0:
        print("This script needs to be run as root. Attempting to rerun with sudo...")
        try:
            # Attempt to rerun the script with sudo
            subprocess.check_call(["sudo", sys.executable] + sys.argv)
        except subprocess.CalledProcessError as e:
            print(f"Failed to run as root: {e}")
            sys.exit(1)
    else:
        # Run the function if already root
        set_nvidia_gpu_modes()
