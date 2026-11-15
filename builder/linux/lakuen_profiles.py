"""(LaküenRecomp) Device profiles: one build for a PC, the Steam Deck and the Legion Go S.

The builder recognises the device, offers its profile (profiles/<name>.ini: menu options for hookshot_options.ini and switches
for hookshot_env.txt) and applies it only when the player agrees. What the files held before is kept beside them
(<file>.before-profile) and can be put back. lakuen_profile.txt in the game folder remembers the device, the profile's version
and the player's answer; a profile whose version went up is offered again. No Tk here: the builder asks, this does the work."""

import configparser
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(HERE, "profiles")
DEVICES = ("steamdeck", "legion_go_s", "pc")
MARKER = "lakuen_profile.txt"
OPTIONS = "hookshot_options.ini"
ENV = "hookshot_env.txt"
BACKUP = ".before-profile"
ENV_BEGIN = "# --- LaküenRecomp device profile: %s (lines between these two are the builder's) ---"
ENV_END = "# --- end of the device profile ---"


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def detect(dmi="/sys/class/dmi/id", cpuinfo="/proc/cpuinfo"):
    """steamdeck, legion_go_s or pc: by the firmware's product name, else by the CPU's name"""
    vendor = _read(os.path.join(dmi, "sys_vendor")).strip().lower()
    product = _read(os.path.join(dmi, "product_name")).strip().lower()
    family = _read(os.path.join(dmi, "product_family")).strip().lower()
    cpu = _read(cpuinfo)
    if (vendor.startswith("valve") and product in ("jupiter", "galileo")) or "Custom APU 0405" in cpu or "Custom APU 0932" in cpu:
        return "steamdeck"
    if "legion go s" in family or "legion go s" in product or "Ryzen Z2 Go" in cpu:
        return "legion_go_s"
    return "pc"


def load(device, directory=PROFILE_DIR):
    """{'title', 'version', 'options': {key: value}, 'env': {NAME: value}} of profiles/<device>.ini"""
    cp = configparser.ConfigParser(interpolation=None, comment_prefixes=("#", ";"), inline_comment_prefixes=None)
    cp.optionxform = str   # (keys as written: env names are upper case)
    cp.read(os.path.join(directory, device + ".ini"), encoding="utf-8")
    p = cp["profile"] if cp.has_section("profile") else {}
    return {
        "device": device,
        "title": p.get("title", device),
        "version": int(p.get("version", "1")),
        "options": dict(cp["options"]) if cp.has_section("options") else {},
        "env": dict(cp["env"]) if cp.has_section("env") else {},
    }


def read_marker(folder):
    out = {}
    for line in _read(os.path.join(folder, MARKER)).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def write_marker(folder, device, version, choice):
    with open(os.path.join(folder, MARKER), "w", encoding="utf-8") as f:
        f.write("device=%s\nversion=%d\nchoice=%s\n" % (device, version, choice))


def needs_prompt(folder, profile):
    """Whether to offer the profile: never answered here, another device, or a newer version of it"""
    m = read_marker(folder)
    if not m:
        return True
    if m.get("device") != profile["device"]:
        return True
    try:
        return int(m.get("version", "0")) < profile["version"]
    except ValueError:
        return True


def _set_options(text, options):
    """The options file's lines with each key's line(s) set to the profile's value (the last line of a key wins for the game)"""
    lines = text.splitlines()
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in options:
            if key in done:
                continue
            out.append("%s=%s" % (key, options[key]))
            done.add(key)
        else:
            out.append(line)
    for key, value in options.items():
        if key not in done:
            out.append("%s=%s" % (key, value))
    return "\n".join(out) + "\n"


def _set_env(text, title, env):
    """hookshot_env.txt with the builder's block replaced by the profile's switches (none: the block goes)"""
    lines = text.splitlines()
    out, inside = [], False
    for line in lines:
        if line.startswith("# --- LaküenRecomp device profile:"):
            inside = True
            continue
        if inside:
            if line == ENV_END:
                inside = False
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if env:
        if out:
            out.append("")
        out.append(ENV_BEGIN % title)
        out.extend("%s=%s" % (k, v) for k, v in env.items())
        out.append(ENV_END)
    return "\n".join(out) + ("\n" if out else "")


def apply(folder, profile):
    """The profile into the game folder's files, what they held before kept beside them first"""
    for name in (OPTIONS, ENV):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            shutil.copy2(path, path + BACKUP)
        else:   # (no file before: an empty backup, so restoring takes the profile's lines away again)
            with open(path + BACKUP, "w", encoding="utf-8"):
                pass
    opt = os.path.join(folder, OPTIONS)
    text = _set_options(_read(opt), profile["options"])   # (read before the file is opened for writing)
    with open(opt, "w", encoding="utf-8") as f:
        f.write(text)
    env_path = os.path.join(folder, ENV)
    text = _set_env(_read(env_path), profile["title"], profile["env"])
    if text or os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(text)
    write_marker(folder, profile["device"], profile["version"], "applied")


def sync_env(folder, profile):
    """(v0.3.7) A profile applied here at its current version gets its [env] switches written again, the options left as they
    are: a switch added to a profile (HOS_NATIVE_ZSTD) reaches the game without asking the player again or touching the
    settings. True when the file changed"""
    m = read_marker(folder)
    if m.get("device") != profile["device"] or m.get("choice") != "applied" or str(m.get("version")) != str(profile["version"]):
        return False
    env_path = os.path.join(folder, ENV)
    old = _read(env_path)
    text = _set_env(old, profile["title"], profile["env"])
    if text == old:
        return False
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def keep(folder, profile):
    """The player's own settings stay: not offered again until the profile's version goes up"""
    write_marker(folder, profile["device"], profile["version"], "kept")


def can_restore(folder):
    return os.path.exists(os.path.join(folder, OPTIONS + BACKUP))


def restore(folder):
    """The files as they were before the last profile; the marker keeps the answer (kept), so it is not offered again at once"""
    for name in (OPTIONS, ENV):
        path = os.path.join(folder, name)
        if os.path.exists(path + BACKUP):
            shutil.copy2(path + BACKUP, path)
            if os.path.getsize(path) == 0:
                os.remove(path)
    m = read_marker(folder)
    if m:
        write_marker(folder, m.get("device", "pc"), int(m.get("version", "1") or 1), "kept")


def status(folder):
    """A line for the launcher: the device and what was done with its profile"""
    m = read_marker(folder)
    if not m:
        return None
    title = load(m.get("device", "pc"))["title"] if m.get("device") in DEVICES else m.get("device")
    return "%s profile %s" % (title, "applied" if m.get("choice") == "applied" else "not applied (your own settings)")
