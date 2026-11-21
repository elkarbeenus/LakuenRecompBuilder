"""The preload manager's choice hook (nx2/oot_patches.py patch_ocb_hold, from Longshot c88f7044 via HeyListen bbc47d1a): put
once after the label, kept on a second run, left out where the function differs; and host/oot_ocb_hold.h's rule.

python -I -B tests/test_ocb_hold_patch.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches as op  # noqa: E402

LIFT = ('#include "a64.h"\n'
        "void f_832b9880(Ctx *__restrict A64_NOESC c) {\n"
        "    c->x[21] = 3;\n"
        "L_832b9dc8:;\n"
        "    if (((c->x[21] >> 31) & 1)) { goto L_832b9e0c; }\n"
        "    c->x[0] = c->x[21];\n"
        "L_832b9e0c:;\n"
        "}\n"
        "void f_832b9990(Ctx *__restrict A64_NOESC c) {\n}\n")

FIXTURE = r'''
#include "oot_ocb_hold.h"
#include <stdio.h>
int main(void) {
    int fails = 0;
    OotOcbHold s = OOT_OCB_HOLD_INIT;
    const int64_t ms = 1000000;
    if (oot_ocb_pick(&s, 2, 1, 2000 * ms, 0) != 1) fails++, puts("FAIL a new choice is held at first");
    if (oot_ocb_pick(&s, 3, 1, 2000 * ms, 500 * ms) != 1) fails++, puts("FAIL another new choice restarts the hold");
    if (oot_ocb_pick(&s, 3, 1, 2000 * ms, 2600 * ms) != 3) fails++, puts("FAIL a choice that stayed 2 s is taken");
    if (oot_ocb_pick(&s, 2, -1, 2000 * ms, 0) != 2) fails++, puts("FAIL nothing held: the game's choice");
    if (oot_ocb_pick(&s, 2, 1, 0, 0) != 2) fails++, puts("FAIL hold 0: the game's choice");
    if (oot_ocb_hold_ms("off", 2000) != 0 || oot_ocb_hold_ms(0, 2000) != 2000 || oot_ocb_hold_ms("750", 2000) != 750 ||
        oot_ocb_hold_ms("x", 2000) != 2000) fails++, puts("FAIL the switch's value");
    return fails != 0;
}
'''


def main():
    out, n = op.patch_ocb_hold(LIFT)
    if n != 1 or out.count(op.OCB_CALL) != 1 or out.count(op.OCB_DECL) != 1:
        raise SystemExit("FAIL: the hook is put once with its declaration")
    if out.index(op.OCB_CALL) < out.index("L_832b9dc8:;") or out.index(op.OCB_CALL) > out.index("if (((c->x[21]"):
        raise SystemExit("FAIL: the hook goes between the label and the test")
    again, n2 = op.patch_ocb_hold(out)
    if n2 != 1 or again != out:
        raise SystemExit("FAIL: a second run keeps the hook as it is")
    other, n3 = op.patch_ocb_hold(LIFT.replace("goto L_832b9e0c", "goto L_832b9e10"))
    if n3 != 0 or op.OCB_CALL in other:
        raise SystemExit("FAIL: a function that differs is left as it is")
    cc = shutil.which("gcc") or shutil.which("clang")
    if cc:
        with tempfile.TemporaryDirectory(prefix="ocb-") as tmp:
            src = Path(tmp) / "t.c"
            src.write_text(FIXTURE, encoding="utf-8")
            exe = Path(tmp) / "t"
            b = subprocess.run([cc, "-I", str(ROOT / "host"), str(src), "-o", str(exe)], capture_output=True, text=True)
            if b.returncode:
                raise SystemExit("FAIL: build\n" + b.stderr)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            if r.returncode:
                raise SystemExit("FAIL\n" + r.stdout)
    print("PASS: preload hold")


if __name__ == "__main__":
    main()
