"""(LaküenRecomp) The report: one zip a player sends in, with a short summary at the top that says what the game's log says.

lakuen_report.txt (the summary: device, profile, settings, frame rate over the run, RAM and swap, shaders, the GPU's costliest
work, the Effect finder's changes, warnings) beside the game's whole log, hookshot_options.ini, hookshot_env.txt and the
profile marker. No Tk here: the builder's button calls create(). Nothing leaves the device: the player sends the zip."""

import datetime
import os
import re
import zipfile

try:
    import lakuen_profiles
except ImportError:   # (tests import this from elsewhere)
    lakuen_profiles = None

LOG = "hookshot_log.txt"
FILES = ("hookshot_options.ini", "hookshot_env.txt", "lakuen_profile.txt")

_FPS = re.compile(r"vk: (\d+) presents, ([\d.]+) fps; a frame: ([\d.]+) draws \(([\d.]+) skipped\), ([\d.]+) dispatches, ([\d.]+) passes"
                  r".*?GPU-bound wait ([\d.]+) ms")
_REPLAY = re.compile(r"a frame's replay time \(ms\): submit ([\d.]+), present ([\d.]+), draw ([\d.]+)")
_GPU = re.compile(r"vk: GPU time ([\d.]+) ms a frame")
_MEM = re.compile(r"vk: memory: working set (\d+) MB \(peak (\d+)\), private (\d+) MB, staging (\d+) MB")
_MALLOC = re.compile(r"vk: malloc: (\d+) MB in arenas \((\d+) MB in use")
_RAMSHORT = re.compile(r"RAM short \((\d+) MB available")
_SYS = re.compile(r"lakuen-mem: (\d+) MB available, swap (\d+) of (\d+) MB used")
_WAITS = re.compile(r"a frame: ([\d.]+) draws left out \(not ready\), ([\d.]+) waits for shaders or pipelines \(([\d.]+) ms\)")
_SLOW = re.compile(r"slow present: ([\d.]+) ms")
_INTERVALS = re.compile(r"vi: present intervals: (.*)")

# (lines worth having as they are, once each: what the game started with)
_START = ("hookshot v", "oe: profile", "oe: output resolution", "boot: widescreen", "boot: image", "MB of swap", "vk: device 0:", "vk: vendor fixes",
          "vk: swapchain", "vk: program cache", "vk: precompile:", "vk: start-up:", "vk: shader preparation:",
          "applet: render target pool", "of VRAM allowed", "Profile set once", "Render resolution Auto set once", "vk: fsr3:",
          "frame interpolation ready", "vk: staging arenas", "GPU pass timing on", "vk: state list:", "RX_VK_SKIP_FILE")
_WARN = re.compile(r"device lost|VK_ERROR|crash|\bhang|fatal|out of memory|[1-9]\d* failed|failed to|NOT bound|timed out", re.I)
# (lines that only look like warnings: the frame line's "(0 failed)", the timing tables, the game's known unimplemented imports)
_NOT_WARN = re.compile(r"presents, [\d.]+ fps|^vk:   |unimplemented import")


def _num(v):
    return float(v)


def _short(line, n=220):
    line = line.rstrip("\n")
    return line if len(line) <= n else line[:n] + " ..."


def _stats(values):
    if not values:
        return "-"
    s = sorted(values)
    low = s[max(0, len(s) // 20)]   # (the 5th percentile: a few bad windows, not the single worst)
    return "min %.1f / 5%% %.1f / avg %.1f / max %.1f" % (s[0], low, sum(s) / len(s), s[-1])


def summarize(log_text, folder=None, device=None, version=None):
    """The summary's text from the log's text (and the folder's settings files, when folder is given)"""
    lines = log_text.splitlines()
    out = []
    w = out.append
    w("LaküenRecomp report - %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    w("=" * 72)
    if device:
        w("device (builder): %s" % device)
    if version:
        w("game build: %s" % version)
    w("log: %d lines" % len(lines))

    # settings
    if folder:
        for name in FILES:
            path = os.path.join(folder, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    body = [l.rstrip() for l in f if l.strip() and not l.lstrip().startswith(("#", ";"))]
            except OSError:
                body = None
            w("")
            w("--- %s %s" % (name, "(none)" if body is None else ""))
            for l in body or []:
                w("  " + l)

    # the start
    w("")
    w("--- start")
    seen = set()
    for l in lines:
        msg = l.split("] ", 1)[-1]
        for k in _START:
            if k in msg:
                key = re.sub(r"\d", "", msg)[:60]
                if key not in seen:
                    seen.add(key)
                    w("  " + _short(msg))
                break

    # frame rate over the run
    fps, rows = [], []
    replay = gpu = None
    waits = []
    for l in lines:
        m = _FPS.search(l)
        if m:
            f = _num(m.group(2))
            fps.append(f)
            rows.append((int(m.group(1)), f, _num(m.group(3)), _num(m.group(4)), _num(m.group(6)), _num(m.group(7)), replay, gpu))
            continue
        m = _REPLAY.search(l)
        if m:
            replay = (_num(m.group(1)), _num(m.group(2)), _num(m.group(3)))
            continue
        m = _GPU.search(l)
        if m:
            gpu = _num(m.group(1))
            continue
        m = _WAITS.search(l)
        if m:
            waits.append((_num(m.group(1)), _num(m.group(2)), _num(m.group(3))))
    w("")
    w("--- frame rate (%d windows of 120 presents): %s fps" % (len(fps), _stats(fps)))
    if rows:
        step = max(1, len(rows) // 60)
        w("  presents    fps   draws  skipped  passes  gpu-wait  | replay ms: submit present draw | GPU ms")
        for i, r in enumerate(rows):
            if i % step and i != len(rows) - 1 and not (r[1] < 25 and (i == 0 or rows[i - 1][1] >= 25)):
                continue   # (every step-th, the last, and each fall under 25 fps)
            rp = "%6.2f %7.2f %5.2f" % r[6] if r[6] else "      -       -     -"
            w("  %8d %6.1f %7.0f %8.0f %7.0f %8.1f  | %s | %s" % (r[0], r[1], r[2], r[3], r[4], r[5], rp,
                                                                   "%.1f" % r[7] if r[7] is not None else "-"))
    if waits:
        nr = [x[0] for x in waits]
        ms = [x[2] for x in waits]
        w("  shaders not ready: draws left out a frame %s; wait ms a frame %s" % (_stats(nr), _stats(ms)))
    slow = [_num(m.group(1)) for m in (_SLOW.search(l) for l in lines) if m]
    if slow:
        w("  slow presents: %d (longest %.0f ms)" % (len(slow), max(slow)))
    iv = [m.group(1) for m in (_INTERVALS.search(l) for l in lines) if m]
    if iv:
        w("  present intervals (last): %s" % iv[-1])

    # memory
    w("")
    w("--- memory")
    mem = [tuple(int(x) for x in m.groups()) for m in (_MEM.search(l) for l in lines) if m]
    if mem:
        w("  process: working set max %d MB (peak %d), private max %d MB, last %d MB; staging max %d MB" % (
            max(x[0] for x in mem), max(x[1] for x in mem), max(x[2] for x in mem), mem[-1][2], max(x[3] for x in mem)))
    mal = [tuple(int(x) for x in m.groups()) for m in (_MALLOC.search(l) for l in lines) if m]
    if mal:
        w("  malloc: in arenas max %d MB, in use max %d MB, last %d MB" % (max(x[0] for x in mal), max(x[1] for x in mal), mal[-1][1]))
    sysm = [tuple(int(x) for x in m.groups()) for m in (_SYS.search(l) for l in lines) if m]
    if sysm:
        w("  system: available min %d MB, last %d MB; swap used max %d of %d MB" % (
            min(x[0] for x in sysm), sysm[-1][0], max(x[1] for x in sysm), sysm[-1][2]))
    short = [int(m.group(1)) for m in (_RAMSHORT.search(l) for l in lines) if m]
    w("  RAM short: %s" % ("%d times, as low as %d MB available" % (len(short), min(short)) if short else "never"))
    for l in lines:
        if "malloc_trim:" in l:
            w("  " + _short(l.split("] ", 1)[-1]))

    # the GPU's costliest work: the last pass timing report, its kinds, spans and programs
    starts = [i for i, l in enumerate(lines) if "vk: GPU pass timing, " in l]
    if starts:
        i = starts[-1]
        w("")
        w("--- GPU pass timing (the last of %d reports)" % len(starts))
        j = i + 1
        while j < len(lines) and j < i + 80 and "vk:  " in lines[j]:
            msg = lines[j].split("] ", 1)[-1]
            if "spans that took the most" in msg or "programs whose runs" in msg or "by kind" in msg or re.search(r"\d", msg):
                w("  " + _short(msg, 160))
            j += 1

    # the Effect finder
    finder = [l.split("] ", 1)[-1] for l in lines if "lakuen-finder:" in l]
    if finder:
        w("")
        w("--- Effect finder")
        ranking = [l for l in finder if "ranking:" in l]
        if ranking:
            w("  last ranking: " + ranking[-1].split("ranking: ", 1)[1].replace("; ", "\n                "))
        for l in finder:
            if "ranking:" not in l:
                w("  " + l.replace("vk: ", ""))

    # the visual problems' clues (gpu/vk/lakuen_diag.cpp): the player's marks first, then the last 30 s summaries
    marks = [l.split("] ", 1)[-1] for l in lines if "lakuen-mark:" in l]
    diag = [l.split("] ", 1)[-1] for l in lines if "lakuen-diag:" in l and " on (LAKUEN_DIAG" not in l]
    par = [l for l in diag if "parallel recording:" in l]
    diag = [l for l in diag if "parallel recording:" not in l]
    if marks or diag or par:
        w("")
        w("--- visual problems: %d marks by the player" % sum(1 for l in marks if re.search(r"lakuen-mark: #\d+ at ", l)))
        for l in par[-1:]:
            w("  " + l.replace("lakuen-diag: ", ""))
        for l in marks[:120]:
            w("  " + _short(l.replace("lakuen-mark: ", ""), 200))
        if diag:
            heads = [i for i, l in enumerate(diag) if " frame " in l and "programs read zeros" in l]
            w("  run summaries: %d (the last one and the programs it named:)" % len(heads))
            if heads:
                for l in diag[heads[-1]:heads[-1] + 7]:
                    w("    " + _short(l.replace("lakuen-diag: ", ""), 200))
    elif any("lakuen-diag: on" in l for l in lines):
        w("")
        w("--- visual problems: no marks, no programs reading zeros, no write-back timeouts")

    # warnings, each kind once with its count
    counts, first = {}, {}
    for l in lines:
        msg = l.split("] ", 1)[-1]
        if _WARN.search(msg) and not _NOT_WARN.search(msg):
            key = re.sub(r"0x[0-9a-f]+|\d+", "#", msg)[:90]
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, msg)
    if counts:
        w("")
        w("--- warnings (%d kinds)" % len(counts))
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1])[:25]:
            w("  %5dx  %s" % (n, _short(first[key], 180)))
    w("")
    w("--- end of the log")
    for l in lines[-15:]:
        w("  " + _short(l, 200))
    return "\n".join(out) + "\n"


MASTER = "lakuen_master_log.txt"
MASTER_RUNS = 5


def update_master(folder, version=None):
    """(LaküenRecomp) lakuen_master_log.txt in the game folder: the summary of each of the last runs the game kept
    (hookshot_log.txt, then .1 to .4), newest first, one file to send. Made again when a log is newer than it; its path, or
    None without a log"""
    logs = [os.path.join(folder, LOG)] + [os.path.join(folder, "hookshot_log.%d.txt" % i) for i in range(1, MASTER_RUNS)]
    logs = [p for p in logs if os.path.isfile(p)]
    if not logs:
        return None
    master = os.path.join(folder, MASTER)
    try:
        if os.path.getmtime(master) >= max(os.path.getmtime(p) for p in logs):
            return master
    except OSError:
        pass
    device = None
    if lakuen_profiles:
        try:
            device = lakuen_profiles.load(lakuen_profiles.detect())["title"]
        except Exception:
            device = None
    parts = ["LaküenRecomp master log: the last %d run(s), newest first (made %s)\n" % (
        len(logs), datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))]
    for n, path in enumerate(logs):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        parts.append("\n" + "#" * 72 + "\n# run %d: %s (ended %s)\n" % (n + 1, os.path.basename(path), when) + "#" * 72 + "\n")
        parts.append(summarize(text, folder if n == 0 else None, device, version))
    tmp = master + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    os.replace(tmp, master)
    return master


def out_dir():
    home = os.path.expanduser("~")
    for d in ("Downloads", "Desktop"):
        if os.path.isdir(os.path.join(home, d)):
            return os.path.join(home, d)
    return home


def create(folder, dest=None, version=None):
    """The zip (LakuenReport-<date>.zip in Downloads, else the Desktop, else home): its path. ValueError without a log"""
    log_path = os.path.join(folder, LOG)
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    except OSError:
        raise ValueError("No game log yet: play once, then create the report.")
    device = None
    if lakuen_profiles:
        try:
            device = lakuen_profiles.load(lakuen_profiles.detect())["title"]
        except Exception:
            device = None
    summary = summarize(log_text, folder, device, version)
    dest = dest or out_dir()
    path = os.path.join(dest, "LakuenReport-%s.zip" % datetime.datetime.now().strftime("%Y%m%d-%H%M"))
    try:
        master = update_master(folder, version)
    except OSError:
        master = None
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lakuen_report.txt", summary)
        if master:
            z.write(master, MASTER)
        z.write(log_path, LOG)
        for name in FILES:
            p = os.path.join(folder, name)
            if os.path.exists(p):
                z.write(p, name)
    return path


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
            sys.stdout.write(summarize(f.read()))
    else:
        print(create(sys.argv[1] if len(sys.argv) > 1 else os.getcwd()))
