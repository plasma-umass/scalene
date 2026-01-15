"""Test script to verify PyTorch JIT profiling works with Scalene."""

import torch

@torch.jit.script
def compute_intensive(x: torch.Tensor) -> torch.Tensor:
    """A compute-intensive JIT-compiled function."""
    for _ in range(50):
        x = x @ x.T  # Line 9: matrix multiplication
        x = torch.relu(x)  # Line 10: relu
        x = x / x.max()  # Line 11: normalize
    return x


def main():
    print("Testing PyTorch JIT profiling with Scalene...")
    x = torch.randn(500, 500)

    print(f"Running compute_intensive on 500x500 tensor...")
    for i in range(100):
        result = compute_intensive(x)  # Line 21: call site

    print("Testing torch.jit.save/load...")
    torch.jit.save(torch.jit.script(compute_intensive), "/tmp/test_model.pt")
    loaded = torch.jit.load("/tmp/test_model.pt")
    test_result = loaded(torch.randn(10, 10))
    print(f"Loaded model output shape: {test_result.shape}")
    print("Done!")


if __name__ == "__main__":
    main()
