"""Build and run the game-free RADV submit-thread regression.

    python -I -B nx2/test_radv_submit_thread.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def check_integration():
    source = (ROOT / "gpu" / "vk" / "vk_main.cpp").read_text(encoding="utf-8")
    start = source.index("bool create_device() {")
    end = source.index("\n}\n", start)
    create_device = source[start:end]
    decide = create_device.index("radv_submit_thread::decide(")
    set_variable = create_device.index('setenv("MESA_VK_ENABLE_SUBMIT_THREAD", "1", 0)')
    create = create_device.index("vkCreateDevice(dev.physical, &ci, nullptr, &dev.device)")
    unset_variable = create_device.index('unsetenv("MESA_VK_ENABLE_SUBMIT_THREAD")')
    assert decide < set_variable < create < unset_variable
    assert "VK_DRIVER_ID_MESA_RADV" in create_device[decide : decide + 200]
    assert 'getenv("RX_VK_RADV_SUBMIT_THREAD")' in create_device[decide : decide + 300]
    assert create_device.rfind("#ifndef _WIN32", 0, decide) > create_device.rfind("#endif", 0, decide)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    check_integration()
    source = ROOT / "gpu" / "vk" / "tests" / "radv_submit_thread_test.cpp"
    with tempfile.TemporaryDirectory(prefix="radv-submit-thread-") as temporary:
        executable = Path(temporary) / "radv_submit_thread_test"
        subprocess.run(
            [args.cxx, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(executable)],
            check=True,
        )
        subprocess.run([str(executable)], check=True)
    print("radv_submit_thread: ok")


if __name__ == "__main__":
    main()
