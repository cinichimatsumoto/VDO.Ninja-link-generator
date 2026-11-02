#!/usr/bin/env python3
"""
VDO.Ninja link + QR generator for unmanned phone cameras  (GUI, tkinter)

What it does
  - You describe the event (room, password, number of phones...).
  - You pick options from a categorised, searchable catalogue of VDO.Ninja
    URL parameters, separately for: the PHONE links, the OBS links and the
    DIRECTOR link. Presets give you a sensible starting point.
  - It builds every link, a QR code per phone, a printable QR sheet and a
    links.txt, and saves everything to vdo_profile.json for next time.

Run
    pip install "qrcode[pil]"          (QR codes; links work without it)
    python vdo_link_generator_gui.py              -> opens the window
    python vdo_link_generator_gui.py --generate   -> no window: regenerate
                                                     files from the saved profile

Parameter reference: https://docs.vdo.ninja/advanced-settings
"""

import argparse
import base64
import io
import json
import os
import re
import secrets
import string
import subprocess
import sys
from html import escape
from pathlib import Path
from urllib.parse import quote

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # headless use (--generate) still works
    tk = None

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except ImportError:
    qrcode = None

PROFILE_PATH = Path(__file__).with_name("vdo_profile.json")
DEFAULT_BASE = "https://vdo.ninja"
SCOPES = ("phone", "obs", "director")
ID_OK = re.compile(r"^[A-Za-z0-9_]+$")


# ===========================================================================
# 1. PARAMETER CATALOGUE
#    scope   : phone | obs | director   (which link the option goes on)
#    kind    : flag   -> &key
#              value  -> &key=value       (free text)
#              choice -> &key=value       (suggested values, still editable)
#              label  -> &label=<per-phone label>
#    default : True = part of the recommended "unmanned crowd cams" setup
#    applies : (obs scope only) view | scene | both
# ===========================================================================
CATALOG = []


def opt(scope, group, key, desc, kind="flag", default=False, value="", choices=None, applies="both"):
    CATALOG.append(
        dict(scope=scope, group=group, key=key, desc=desc, kind=kind, default=default,
             value=value, choices=choices or [], applies=applies)
    )


# ---- PHONE ----------------------------------------------------------------
G = "Connection & setup"
opt("phone", G, "view", "Publish-only: the phone does not receive other guests' video or audio "
    "(written as a bare &view, never give it a value)", default=True)
opt("phone", G, "webcam", "Camera sharing only (no screen-share option)", default=True)
opt("phone", G, "autostart", "Skip the camera/microphone selection screen", default=True)
opt("phone", G, "label", "Show each phone's label (edit them on the Phones tab) in the Director",
    kind="label", default=True)
opt("phone", G, "facing", "Default camera: rear or front", kind="choice", value="rear",
    choices=["rear", "front"])
opt("phone", G, "videodevice", "Pre-select a camera by name or ID (0 turns video off)", kind="value")
opt("phone", G, "audiodevice", "Pre-select a microphone by name or ID (0 turns the phone's mic off)",
    kind="value", value="0", default=True)
opt("phone", G, "easyexit", "Don't ask for confirmation when leaving the page")
opt("phone", G, "safemode", "Load the camera in the simplest possible way (try if the camera won't start)")
opt("phone", G, "hidehome", "Hide VDO.Ninja homepage links")

G = "Camera & video"
opt("phone", G, "quality", "Resolution target: 0 = about 1080p, 1 = about 720p, 2 = about 360p, "
    "-1 = device default", kind="choice", value="0", choices=["0", "1", "2", "-1"], default=True)
opt("phone", G, "width", "Maximum video width in pixels (use with height for more than 1080p)", kind="value")
opt("phone", G, "height", "Maximum video height in pixels", kind="value")
opt("phone", G, "fps", "Target frame rate", kind="value", value="30", default=True)
opt("phone", G, "maxframerate", "Like fps, but accepts a lower rate if the requested one fails", kind="value")
opt("phone", G, "aspectratio", "Aspect ratio on the sending side (for example 1.7778)", kind="value")
opt("phone", G, "noscale", "Don't cap the publishing resolution")
opt("phone", G, "zoom", "Preset the camera's optical/driver zoom at start", kind="value")
opt("phone", G, "ptz", "Enable pan/tilt/zoom control if the camera supports it")
opt("phone", G, "forcelandscape", "Force landscape output however the phone is rotated")
opt("phone", G, "forceportrait", "Force portrait output however the phone is rotated")
opt("phone", G, "mirror", "Mirror the video")
opt("phone", G, "flip", "Flip the video upside down")
opt("phone", G, "rotate", "Rotate the camera (degrees)", kind="value")
opt("phone", G, "nopreview", "Hide the phone's local self-preview")
opt("phone", G, "whitebalance", "Preset the camera's white balance", kind="value")
opt("phone", G, "exposure", "Preset the camera's exposure", kind="value")
opt("phone", G, "saturation", "Preset the camera's saturation", kind="value")
opt("phone", G, "sharpness", "Preset the camera's sharpness", kind="value")
opt("phone", G, "contrast", "Preset the camera's contrast", kind="value")
opt("phone", G, "brightness", "Preset the camera's brightness", kind="value")

G = "Bitrate"
opt("phone", G, "outboundvideobitrate", "Default target video bitrate the phone sends (kbps)",
    kind="value", value="6000", default=True)
opt("phone", G, "maxvideobitrate", "Hard cap on the video bitrate the phone sends to each viewer (kbps)", kind="value")
opt("phone", G, "limittotalbitrate", "Cap the phone's total outbound video bitrate (kbps)", kind="value")

G = "Audio"
opt("phone", G, "mute", "Start with the microphone muted")
opt("phone", G, "automute", "Mute the mic whenever the phone isn't in an active OBS scene")
opt("phone", G, "stereo", "Stereo audio with quality-oriented defaults")
opt("phone", G, "proaudio", "Higher audio quality preset (stereo)")
opt("phone", G, "audiobitrate", "Audio bitrate (kbps)", kind="value", value="128")

G = "Mobile"
opt("phone", G, "flagship", "Treat the phone as a capable device and optimise for it")
opt("phone", G, "mobile", "Optimise for mobile to reduce CPU load")
opt("phone", G, "notmobile", "Favour video quality over CPU savings")
opt("phone", G, "androidfix", "H.264 compatibility tweak for Android")
opt("phone", G, "maxmobilebitrate", "Raise the normal mobile sender cap in director rooms (kbps)", kind="value")
opt("phone", G, "lowmobilebitrate", "Lower fallback mobile sender cap (kbps)", kind="value")
opt("phone", G, "nomobilebitratecap", "Remove only the mobile bitrate safety cap (watch phone heat)")

G = "Stability (unattended)"
opt("phone", G, "retry", "Automatically re-establish lost connections", default=True)
opt("phone", G, "retrytimeout", "Delay between retries in ms (for example 5000)", kind="value")
opt("phone", G, "autoreload", "Reload the page every N seconds (for example 14400)", kind="value")
opt("phone", G, "autoreload24", "Reload the page daily at HH:MM (for example 04:00)", kind="value")

G = "Remote control & monitoring"
opt("phone", G, "consent", "Director may change this phone's camera, mic and URL without asking again", default=True)
opt("phone", G, "remote", "Allow remote zoom/focus (PTZ), rotate/mirror and stats access", default=True)
opt("phone", G, "signalmeter", "Show a packet-loss meter for this phone in the Director", default=True)
opt("phone", G, "batterymeter", "Show this phone's battery level in the Director", default=True)

G = "Lock-down (accidental taps)"
opt("phone", G, "nosettings", "Disable the settings button", default=True)
opt("phone", G, "nohangupbutton", "Hide the hang-up button", default=True)
opt("phone", G, "nomicbutton", "Hide the mic button")
opt("phone", G, "novideobutton", "Hide the video button")
opt("phone", G, "nospeakerbutton", "Hide the speaker button")
opt("phone", G, "hidemenu", "Hide the VDO.Ninja menu and header bar")
opt("phone", G, "cleanoutput", "Hide as much interface as possible")
opt("phone", G, "cleanish", "Cleaner interface, but less strict than cleanoutput")
opt("phone", G, "nomouseevents", "Ignore clicks/taps on the page (test first: it may interfere with prompts)")

# ---- OBS -------------------------------------------------------------------
G = "Source type"
opt("obs", G, "solo", "Per-phone links become solo links (the recommended pattern for one input per phone)",
    default=True, applies="view")

G = "Quality & codec"
opt("obs", G, "buffer", "Playback buffer in ms (higher = smoother but more delay)",
    kind="value", value="200", default=True)
opt("obs", G, "codec", "Preferred video codec requested from the phone. You can list several, in order of "
    "preference, separated by commas (for example h265,h264). h264 may trigger the phone's hardware encoder "
    "(hit-and-miss); h265 needs browser support on both ends",
    kind="choice", value="h264",
    choices=["h264", "h265", "h265,h264", "av1,h264", "h265,av1,h264,vp8", "vp8", "vp9", "av1"], default=True)
opt("obs", G, "videobitrate", "Target bitrate requested per incoming stream (kbps)",
    kind="value", value="6000", default=True, applies="view")
opt("obs", G, "totalscenebitrate", "Maximum total video bitrate for the whole scene (kbps)",
    kind="value", applies="scene")
opt("obs", G, "scale", "Scale incoming video resolution by a percentage", kind="value")
opt("obs", G, "sharper", "Request up to double the playback resolution")
opt("obs", G, "noaudio", "Video only: disable audio playback")

G = "Reconnect"
opt("obs", G, "retry", "Automatically re-establish lost connections", default=True)
opt("obs", G, "retrytimeout", "Delay between retries in ms (for example 5000)", kind="value")
opt("obs", G, "autoreload24", "Reload the source daily at HH:MM (for example 04:05)", kind="value")

G = "Appearance"
opt("obs", G, "cleanoutput", "Hide interface elements from the output", default=True)
opt("obs", G, "showlabels", "Show each camera's label as an overlay")
opt("obs", G, "cover", "Make videos fill their area, cropping if needed", applies="scene")
opt("obs", G, "fadein", "Fade videos in smoothly")
opt("obs", G, "nosignalpattern", "Show a built-in 'No Signal' pattern while no feed is active")
opt("obs", G, "waitmessage", "Message shown while waiting for the feed", kind="value")

# ---- DIRECTOR --------------------------------------------------------------
G = "Director link"
opt("director", G, "remote", "Enable remote control features on the Director side", default=True)
opt("director", G, "graphs", "Show bitrate / codec / resolution graphs in the Director", default=True)
opt("director", G, "cleandirector", "Hide the invite URL options in the Director room")
opt("director", G, "muteall", "Add a button to mute/unmute all guests")
opt("director", G, "blindall", "Add a button to blind all guests' video")

# ---- NETWORK (same options on all three link types) -------------------------
G = "Network (direct P2P)"
for _scope in SCOPES:
    opt(_scope, G, "lanonly", "Only connect to devices on the same local network: public IPs are blocked and "
        "STUN/TURN are disabled")
    opt(_scope, G, "stunonly", "Direct connections only: the TURN relay is blocked but STUN is still allowed "
        "(can fail behind strict firewalls)")
    opt(_scope, G, "turn", "off = remove TURN servers; nostun = remove STUN and TURN servers "
        "(direct/local connections can still work)", kind="choice", value="nostun", choices=["off", "nostun"])

NET_HINT = (
    "Media already travels directly between devices when it can. These options stop it from ever using "
    "STUN/TURN servers. The VDO.Ninja website and handshake server are still needed so the page loads and "
    "the devices can find each other. Use the same setting on the phone links, the OBS links and your Director "
    "link, and keep every device on the same local network (and make sure the Wi-Fi has no client isolation)."
)

GROUP_HINTS = {
    ("phone", "Network (direct P2P)"): NET_HINT,
    ("obs", "Network (direct P2P)"): NET_HINT,
    ("director", "Network (direct P2P)"): NET_HINT,
    ("phone", "Bitrate"):
        "Sender-side targets. What OBS asks for (OBS tab) matters too, so check both.",
    ("phone", "Mobile"):
        "In rooms with a director or scene connected, VDO.Ninja applies production-safe bitrate caps to "
        "mobile guests. If feeds look soft in OBS, open the stats panel first; then try these cap options "
        "carefully, because phones heat up.",
    ("phone", "Stability (unattended)"):
        "Auto-reload restarts the page and can briefly drop the feed. Leave it off unless you have "
        "tested it on your phones.",
    ("phone", "Remote control & monitoring"):
        "&consent: the Director can change the camera/mic/URL without asking again. The phone may ask "
        "once when it first connects, so do the first scan with someone standing at the phone.",
}


def catalog_for(scope):
    return [o for o in CATALOG if o["scope"] == scope]


def groups_for(scope):
    seen = []
    for o in catalog_for(scope):
        if o["group"] not in seen:
            seen.append(o["group"])
    return seen


# ===========================================================================
# 2. SELECTIONS, PRESETS, PROFILES (no GUI code)
# ===========================================================================
def default_selection():
    sel = {s: {} for s in SCOPES}
    for o in CATALOG:
        if o["default"]:
            sel[o["scope"]][o["key"]] = o["value"] if o["kind"] in ("value", "choice") else True
    return sel


def preset_minimal():
    return {
        "phone": {"view": True, "webcam": True, "autostart": True, "label": True,
                  "consent": True, "remote": True, "audiodevice": "0"},
        "obs": {"solo": True, "cleanoutput": True, "buffer": "200"},
        "director": {"remote": True},
    }


def preset_high_quality():
    sel = default_selection()
    sel["phone"]["outboundvideobitrate"] = "10000"
    sel["phone"]["flagship"] = True
    sel["obs"]["videobitrate"] = "10000"
    return sel


def preset_low_bandwidth():
    sel = default_selection()
    sel["phone"].update({"quality": "1", "fps": "24", "outboundvideobitrate": "2500", "mobile": True})
    sel["obs"]["videobitrate"] = "2500"
    return sel


def preset_local_only():
    sel = default_selection()
    for scope in SCOPES:
        sel[scope]["lanonly"] = True
    return sel


PRESETS = {
    "Unmanned crowd cams (recommended)": default_selection,
    "Local network only (no external servers)": preset_local_only,
    "Minimal": preset_minimal,
    "High quality (strong network)": preset_high_quality,
    "Low bandwidth": preset_low_bandwidth,
    "Everything off": lambda: {s: {} for s in SCOPES},
}


def state_from_selection(sel):
    """selection {scope:{key:value|True}} -> full state {scope:{key:{on,value}}}"""
    out = {s: {} for s in SCOPES}
    for o in CATALOG:
        chosen = sel.get(o["scope"], {})
        if o["key"] in chosen:
            v = chosen[o["key"]]
            out[o["scope"]][o["key"]] = {"on": True, "value": v if isinstance(v, str) else o["value"]}
        else:
            out[o["scope"]][o["key"]] = {"on": False, "value": o["value"]}
    return out


def selection_from_state(options):
    sel = {s: {} for s in SCOPES}
    for o in CATALOG:
        st = options[o["scope"]][o["key"]]
        if st["on"]:
            sel[o["scope"]][o["key"]] = st["value"] if o["kind"] in ("value", "choice") else True
    return sel


def auto_id(prefix, i, suffix, use_suffix):
    sfx = f"_{suffix}" if use_suffix and suffix else ""
    return f"{prefix}{i + 1}{sfx}"


def auto_label(prefix, i):
    return f"{prefix} {i + 1}".strip()


def random_suffix():
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))


def migrate_profile(p):
    """Accept profiles written by the first (command-line) version."""
    if "options" in p or "features" not in p:
        return p
    sel = default_selection()
    phone, obs = {}, sel["obs"]
    old = p["features"]
    phone_keys = {o["key"] for o in catalog_for("phone")}
    for key, val in old.items():
        if key == "noaudio":
            phone["audiodevice"] = "0"
        elif key == "videobitrate":
            phone["outboundvideobitrate"] = str(val)
            obs["videobitrate"] = str(val)
        elif key == "codec":
            obs["codec"] = str(val)
        elif key in phone_keys:
            phone[key] = val if isinstance(val, str) else True
        # anything else (for example the old 'wakelock') is not a documented parameter: dropped
    if "obs_buffer" in p:
        obs["buffer"] = str(p["obs_buffer"])
    sel["phone"] = phone
    q = dict(p)
    q["options"] = sel
    q.pop("features", None)
    return q


def profile_to_cfg(p):
    p = migrate_profile(p or {})
    prefix = p.get("id_prefix", "cam")
    label_prefix = p.get("label_prefix", "Cam")
    use_suffix = p.get("use_suffix", True)
    suffix = p.get("suffix") or random_suffix()
    count = max(1, min(99, int(p.get("phone_count", 4))))
    phones = []
    saved = p.get("phones") or []
    for i in range(count):
        a = {"id": auto_id(prefix, i, suffix, use_suffix), "label": auto_label(label_prefix, i)}
        if i < len(saved):
            a["id"] = saved[i].get("id") or a["id"]
            a["label"] = saved[i].get("label", a["label"])
        phones.append(a)
    sel = p["options"] if "options" in p else default_selection()
    extra = p.get("extra", {})
    return {
        "base_url": (p.get("base_url") or DEFAULT_BASE).rstrip("/"),
        "room": p.get("room", ""),
        "password": p.get("password", ""),
        "scene": str(p.get("scene", "1")),
        "output_dir": p.get("output_dir", ""),
        "setup": {"id_prefix": prefix, "label_prefix": label_prefix, "use_suffix": use_suffix,
                  "suffix": suffix, "phone_count": count},
        "options": state_from_selection(sel),
        "extra": {"phone": extra.get("phone", ""), "obs": extra.get("obs", "")},
        "phones": phones,
    }


def cfg_to_profile(cfg):
    s = cfg["setup"]
    return {
        "version": 2,
        "base_url": cfg["base_url"],
        "room": cfg["room"],
        "password": cfg["password"],
        "scene": cfg["scene"],
        "output_dir": cfg["output_dir"],
        "phone_count": len(cfg["phones"]),
        "id_prefix": s["id_prefix"],
        "label_prefix": s["label_prefix"],
        "use_suffix": s["use_suffix"],
        "suffix": s["suffix"],
        "phones": cfg["phones"],
        "options": selection_from_state(cfg["options"]),
        "extra": cfg["extra"],
    }


def load_profile_file(path, quiet=True):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        if not quiet and tk is not None:
            messagebox.showerror("Load failed", str(exc))
        else:
            print(f"! Could not read {path}: {exc}")
        return None


# ===========================================================================
# 3. LINK BUILDING
# ===========================================================================
def build_query(pairs):
    parts = []
    for key, value in pairs:
        parts.append(key if value is None else f"{key}={quote(str(value), safe=',')}")
    return "&".join(parts)


def clean_extra(text):
    tokens = [t.strip("&") for t in re.split(r"[&\s]+", text or "")]
    return "&".join(t for t in tokens if t)


def option_pairs(cfg, scope, link=None, phone=None):
    pairs = []
    for o in catalog_for(scope):
        st = cfg["options"][scope][o["key"]]
        if not st["on"]:
            continue
        if scope == "obs" and o["applies"] not in ("both", link):
            continue
        if o["kind"] == "flag":
            pairs.append((o["key"], None))
        elif o["kind"] == "label":
            if phone and phone["label"].strip():
                pairs.append(("label", phone["label"].strip()))
        else:
            v = st["value"].strip()
            if v:
                pairs.append((o["key"], v))
    return pairs


def _finish(cfg, pairs, extra_key=None):
    q = build_query(pairs)
    extra = clean_extra(cfg["extra"].get(extra_key, "")) if extra_key else ""
    if extra:
        q += "&" + extra
    return f"{cfg['base_url']}/?{q}"


def _room_pairs(cfg):
    pairs = [("room", cfg["room"])]
    if cfg["password"]:
        pairs.append(("password", cfg["password"]))
    return pairs


def phone_url(cfg, i):
    ph = cfg["phones"][i]
    pairs = _room_pairs(cfg) + [("push", ph["id"])] + option_pairs(cfg, "phone", phone=ph)
    return _finish(cfg, pairs, "phone")


def director_url(cfg):
    pairs = [("director", cfg["room"])]
    if cfg["password"]:
        pairs.append(("password", cfg["password"]))
    return _finish(cfg, pairs + option_pairs(cfg, "director"))


def obs_view_url(cfg, i):
    pairs = [("view", cfg["phones"][i]["id"])] + _room_pairs(cfg) + option_pairs(cfg, "obs", link="view")
    return _finish(cfg, pairs, "obs")


def obs_scene_url(cfg):
    pairs = [("scene", cfg["scene"])] + _room_pairs(cfg) + option_pairs(cfg, "obs", link="scene")
    return _finish(cfg, pairs, "obs")


def problems(cfg):
    errors, warnings = [], []
    if not cfg["room"]:
        errors.append("Room name is empty.")
    elif not ID_OK.match(cfg["room"]):
        warnings.append("Room name works best with only letters, numbers and underscores.")
    ids = [p["id"] for p in cfg["phones"]]
    if any(not i for i in ids):
        errors.append("A stream ID is empty.")
    if len(set(ids)) != len(ids):
        errors.append("Two phones share the same stream ID.")
    if any(i and not ID_OK.match(i) for i in ids):
        warnings.append("Stream IDs work best with only letters, numbers and underscores.")
    if any(len(i) > 64 for i in ids):
        errors.append("Stream IDs must be 64 characters or fewer.")

    for scope in SCOPES:
        for o in catalog_for(scope):
            st = cfg["options"][scope][o["key"]]
            if st["on"] and o["kind"] in ("value", "choice") and not st["value"].strip():
                warnings.append(f"&{o['key']} ({scope}) is ticked but has no value, so it is left out.")

    ph = cfg["options"]["phone"]
    mic = ph["audiodevice"]
    if mic["on"] and mic["value"].strip() == "0":
        useless = [k for k in ("mute", "automute", "stereo", "proaudio", "audiobitrate") if ph[k]["on"]]
        if useless:
            warnings.append("The phone mic is off (&audiodevice=0), so audio options have no effect: "
                            + ", ".join("&" + k for k in useless) + ".")
    sized = any(ph[k]["on"] and ph[k]["value"].strip() for k in ("width", "height"))
    if ph["quality"]["on"] and ph["quality"]["value"].strip() and sized:
        warnings.append("&quality and &width/&height are both set; pick one approach.")
    if ph["mobile"]["on"] and ph["notmobile"]["on"]:
        warnings.append("&mobile and &notmobile are both ticked.")
    for key in ("lanonly", "stunonly"):
        used = [sc for sc in SCOPES if cfg["options"][sc][key]["on"]]
        if used and len(used) < len(SCOPES):
            missing = ", ".join(sc for sc in SCOPES if sc not in used)
            warnings.append(f"&{key} is set for {', '.join(used)} but not for {missing}; "
                            "use the same network setting on all three or the devices may not connect.")
    if cfg["options"]["phone"]["lanonly"]["on"] and cfg["options"]["phone"]["stunonly"]["on"]:
        warnings.append("&lanonly already blocks STUN and TURN, so &stunonly adds nothing.")
    if cfg["phones"] and len(phone_url(cfg, 0)) > 600:
        warnings.append("Phone links are long, so the QR codes will be dense. Print them larger.")
    return errors, warnings


# ===========================================================================
# 4. OUTPUT FILES
# ===========================================================================
def slug(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "room"


def resolve_output_dir(cfg):
    if cfg["output_dir"].strip():
        return Path(cfg["output_dir"]).expanduser()
    return PROFILE_PATH.parent / f"vdo_links_{slug(cfg['room'])}"


def make_qr(url, box_size=10):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    return qr


def qr_png_bytes(url, box_size=10):
    img = make_qr(url, box_size).make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_png_fit(url, target=320):
    modules = make_qr(url, 1).modules_count + 8
    return qr_png_bytes(url, max(1, target // modules))


def write_html_sheet(path, cfg, urls):
    cards = []
    for i, url in enumerate(urls):
        ph = cfg["phones"][i]
        b64 = base64.b64encode(qr_png_bytes(url)).decode("ascii")
        cards.append(
            f'<div class="card"><h2>{escape(ph["label"] or ph["id"])}</h2>'
            f'<img src="data:image/png;base64,{b64}" alt="QR for {escape(ph["id"])}">'
            f'<p class="id">ID: {escape(ph["id"])}</p>'
            f'<p class="url">{escape(url)}</p></div>'
        )
    path.write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Phone QR codes - {escape(cfg['room'])}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 16px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
  .card {{ border: 1px solid #999; border-radius: 8px; padding: 12px; text-align: center; break-inside: avoid; }}
  .card img {{ width: 100%; max-width: 260px; height: auto; }}
  .id {{ font-weight: 600; margin: 4px 0; }}
  .url {{ font-size: 9px; word-break: break-all; color: #555; }}
</style></head><body>
<h1>Room: {escape(cfg['room'])}</h1>
<p>Scan with the phone's camera app. Keep this page private: the links contain the room password.</p>
<div class="grid">{''.join(cards)}</div>
</body></html>""",
        encoding="utf-8",
    )


def write_outputs(cfg, out):
    """Write links.txt, qr/*.png, qr_sheet.html. Returns a list of human-readable notes."""
    notes = []
    out.mkdir(parents=True, exist_ok=True)
    n = len(cfg["phones"])
    urls = [phone_url(cfg, i) for i in range(n)]
    name = lambda i: cfg["phones"][i]["label"] or cfg["phones"][i]["id"]  # noqa: E731

    lines = ["DIRECTOR (open on your laptop/tablet)", director_url(cfg), "", "PHONE LINKS (also the QR codes)"]
    lines += [f"{name(i)}: {urls[i]}" for i in range(n)]
    lines += ["", "OBS BROWSER SOURCES (one per phone, 1920x1080)"]
    lines += [f"{name(i)}: {obs_view_url(cfg, i)}" for i in range(n)]
    lines += ["", "OBS SCENE LINK (cameras chosen in the Director appear here)", obs_scene_url(cfg), ""]
    (out / "links.txt").write_text("\n".join(lines), encoding="utf-8")
    notes.append("links.txt")

    if qrcode is None:
        notes.append('QR codes skipped: pip install "qrcode[pil]"')
    else:
        try:
            qr_dir = out / "qr"
            qr_dir.mkdir(exist_ok=True)
            for i, p in enumerate(cfg["phones"]):
                (qr_dir / f"{p['id']}.png").write_bytes(qr_png_bytes(urls[i]))
            write_html_sheet(out / "qr_sheet.html", cfg, urls)
            notes += ["qr/*.png", "qr_sheet.html"]
        except Exception as exc:  # noqa: BLE001
            notes.append(f"QR generation failed: {exc}")
    return notes


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # noqa: BLE001
        if tk is not None:
            messagebox.showinfo("Folder", f"Could not open the folder automatically:\n{exc}\n\n{path}")


# ===========================================================================
# 5. GUI
# ===========================================================================
BaseTk = tk.Tk if tk is not None else object
BaseFrame = ttk.Frame if tk is not None else object


class ScrollFrame(BaseFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda _e: self._wheel_on(True))
        self.canvas.bind("<Leave>", lambda _e: self._wheel_on(False))

    def _wheel_on(self, on):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._wheel)
            self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
            self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(ev)

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


class OptionPanel(BaseFrame):
    """One tab: a filterable, grouped list of options for a scope."""

    def __init__(self, parent, app, scope, extra_var=None, intro=""):
        super().__init__(parent, padding=6)
        self.app, self.scope = app, scope
        self.rows = []
        self.group_frames = []

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.filter = tk.StringVar()
        ttk.Entry(bar, textvariable=self.filter, width=24).pack(side="left", padx=6)
        self.only_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show only enabled", variable=self.only_on,
                        command=self.apply_filter).pack(side="left", padx=6)
        ttk.Label(bar, text="\u2605 = part of the recommended unmanned setup", foreground="#666").pack(side="right")
        self.filter.trace_add("write", lambda *_: self.apply_filter())

        if intro:
            ttk.Label(self, text=intro, foreground="#666", wraplength=760, justify="left").pack(anchor="w", pady=(6, 0))

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, pady=(6, 0))
        inner = self.scroll.inner
        inner.columnconfigure(0, weight=1)

        for gi, group in enumerate(groups_for(scope)):
            lf = ttk.LabelFrame(inner, text=group, padding=6)
            lf.grid(row=gi, column=0, sticky="ew", padx=4, pady=4)
            lf.columnconfigure(0, weight=1)
            r = 0
            hint = GROUP_HINTS.get((scope, group))
            if hint:
                ttk.Label(lf, text=hint, foreground="#8a6d00", wraplength=740, justify="left").grid(
                    row=0, column=0, sticky="w", pady=(0, 4))
                r = 1
            entry = {"frame": lf, "rows": []}
            for o in [x for x in catalog_for(scope) if x["group"] == group]:
                rowf = ttk.Frame(lf)
                rowf.grid(row=r, column=0, sticky="ew")
                r += 1
                rowf.columnconfigure(2, weight=1)
                on = app.opt_on[scope][o["key"]]
                val = app.opt_val[scope][o["key"]]
                text = ("\u2605 " if o["default"] else "   ") + "&" + o["key"]
                ttk.Checkbutton(rowf, text=text, variable=on, width=28).grid(row=0, column=0, sticky="w")
                widget = None
                if o["kind"] == "choice":
                    widget = ttk.Combobox(rowf, textvariable=val, values=o["choices"], width=10)
                elif o["kind"] == "value":
                    widget = ttk.Entry(rowf, textvariable=val, width=12)
                if widget is not None:
                    widget.grid(row=0, column=1, padx=6)
                ttk.Label(rowf, text=o["desc"], foreground="#555", wraplength=520, justify="left").grid(
                    row=0, column=2, sticky="w")
                row = {"opt": o, "frame": rowf, "widget": widget, "on": on}
                on.trace_add("write", self._toggle_cb(row))
                self.rows.append(row)
                entry["rows"].append(row)
            self.group_frames.append(entry)

        if extra_var is not None:
            ex = ttk.Frame(self)
            ex.pack(fill="x", pady=(6, 0))
            ttk.Label(ex, text="Extra raw parameters:").pack(side="left")
            ttk.Entry(ex, textvariable=extra_var).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Label(ex, text="e.g. &width=1280&height=720", foreground="#666").pack(side="left")

    def _toggle_cb(self, row):
        def cb(*_):
            self._set_widget_state(row)
            if self.only_on.get():
                self.apply_filter()
        return cb

    @staticmethod
    def _set_widget_state(row):
        if row["widget"] is not None:
            row["widget"].configure(state="normal" if row["on"].get() else "disabled")

    def sync_states(self):
        for row in self.rows:
            self._set_widget_state(row)
        self.apply_filter()

    def apply_filter(self):
        text = self.filter.get().strip().lower().lstrip("&")
        only = self.only_on.get()
        for entry in self.group_frames:
            any_visible = False
            for row in entry["rows"]:
                o = row["opt"]
                show = (not text or text in o["key"] or text in o["desc"].lower()) and \
                       (not only or row["on"].get())
                if show:
                    row["frame"].grid()
                    any_visible = True
                else:
                    row["frame"].grid_remove()
            if any_visible:
                entry["frame"].grid()
            else:
                entry["frame"].grid_remove()


class App(BaseTk):
    def __init__(self, profile=None):
        super().__init__()
        self.title("VDO.Ninja phone link + QR generator")
        self.geometry("1320x860")
        self.minsize(1080, 700)

        self._lock = 0
        self._after_id = None
        self._qr_image = None
        self._built_rows = -1
        self.sel_index = 0
        self.rows = []  # per phone: {"id","label": StringVar, "id_manual","label_manual": bool}

        # --- event setup variables ---
        self.room = tk.StringVar()
        self.password = tk.StringVar()
        self.show_pw = tk.BooleanVar(value=False)
        self.count = tk.StringVar(value="4")
        self.id_prefix = tk.StringVar(value="cam")
        self.label_prefix = tk.StringVar(value="Cam")
        self.use_suffix = tk.BooleanVar(value=True)
        self.suffix = tk.StringVar(value=random_suffix())
        self.scene = tk.StringVar(value="1")
        self.output_dir = tk.StringVar()
        self.base_url = tk.StringVar(value=DEFAULT_BASE)
        self.extra_phone = tk.StringVar()
        self.extra_obs = tk.StringVar()
        self.preset = tk.StringVar(value=list(PRESETS)[0])

        # --- option variables ---
        self.opt_on = {s: {} for s in SCOPES}
        self.opt_val = {s: {} for s in SCOPES}
        for o in CATALOG:
            self.opt_on[o["scope"]][o["key"]] = tk.BooleanVar(value=o["default"])
            self.opt_val[o["scope"]][o["key"]] = tk.StringVar(value=o["value"])

        self.panels = []
        self._build_ui()

        for v in (self.count, self.id_prefix, self.label_prefix, self.suffix):
            v.trace_add("write", self._on_structure)
        self.use_suffix.trace_add("write", self._on_structure)
        for v in (self.room, self.password, self.scene, self.base_url, self.extra_phone, self.extra_obs):
            v.trace_add("write", self._on_change)
        for s in SCOPES:
            for k in self.opt_on[s]:
                self.opt_on[s][k].trace_add("write", self._on_change)
                self.opt_val[s][k].trace_add("write", self._on_change)

        self.apply_profile(profile if profile is not None else (load_profile_file(PROFILE_PATH) or {}))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        # top bar: presets + load/save
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Preset:").pack(side="left")
        ttk.Combobox(top, textvariable=self.preset, values=list(PRESETS), state="readonly", width=34).pack(
            side="left", padx=6)
        ttk.Button(top, text="Apply preset", command=self.on_apply_preset).pack(side="left")
        ttk.Label(top, text="Presets replace the ticked options on all three tabs.", foreground="#666").pack(
            side="left", padx=10)
        ttk.Button(top, text="Load\u2026", command=self.on_load).pack(side="right")
        ttk.Button(top, text="Save as\u2026", command=self.on_save_as).pack(side="right", padx=6)
        ttk.Button(top, text="Save settings", command=self.on_save).pack(side="right", padx=6)

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(panes)
        panes.add(left, weight=0)
        panes.add(right, weight=1)

        # --- left: event setup ---
        basics = ttk.LabelFrame(left, text="Event setup", padding=8)
        basics.pack(fill="x")
        basics.columnconfigure(1, weight=1)

        def row(r, text, widget):
            ttk.Label(basics, text=text).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="ew", pady=2)

        row(0, "Room name", ttk.Entry(basics, textvariable=self.room))
        pw = ttk.Frame(basics)
        self.pw_entry = ttk.Entry(pw, textvariable=self.password, show="\u2022")
        self.pw_entry.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(pw, text="show", variable=self.show_pw, command=self._toggle_pw).pack(side="left", padx=(6, 0))
        row(1, "Password", pw)
        row(2, "Number of phones", ttk.Spinbox(basics, from_=1, to=99, width=6, textvariable=self.count))
        row(3, "Stream ID prefix", ttk.Entry(basics, textvariable=self.id_prefix))
        row(4, "Label prefix", ttk.Entry(basics, textvariable=self.label_prefix))
        sfx = ttk.Frame(basics)
        ttk.Checkbutton(sfx, text="Random suffix:", variable=self.use_suffix).pack(side="left")
        ttk.Entry(sfx, textvariable=self.suffix, width=8).pack(side="left", padx=4)
        ttk.Button(sfx, text="New", width=5, command=lambda: self.suffix.set(random_suffix())).pack(side="left")
        row(5, "Stream ID suffix", sfx)
        row(6, "OBS scene number", ttk.Spinbox(basics, from_=1, to=99, width=6, textvariable=self.scene))
        out = ttk.Frame(basics)
        ttk.Entry(out, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(out, text="\u2026", width=3, command=self._browse_out).pack(side="left", padx=(4, 0))
        row(7, "Output folder", out)

        adv = ttk.LabelFrame(left, text="Advanced", padding=8)
        adv.pack(fill="x", pady=(8, 0))
        adv.columnconfigure(1, weight=1)
        ttk.Label(adv, text="Server URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(adv, textvariable=self.base_url).grid(row=0, column=1, sticky="ew")
        ttk.Label(adv, text="Only change this if you self-host VDO.Ninja.", foreground="#666").grid(
            row=1, column=1, sticky="w")

        tips = ttk.LabelFrame(left, text="Good to know", padding=8)
        tips.pack(fill="x", pady=(8, 0))
        ttk.Label(
            tips, foreground="#555", justify="left", wraplength=300,
            text=("\u2022 Phone options go on the QR/phone links; OBS options go on the OBS links; "
                  "Director options on your control link.\n"
                  "\u2022 Bitrate and codec are requested by the viewer (OBS side); the phone sets its own "
                  "targets. Both tabs matter.\n"
                  "\u2022 Do the first scan with someone at each phone: the camera permission and the "
                  "&consent prompt need one tap."),
        ).pack(anchor="w")

        # --- right: tabs ---
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        self.p_phone = OptionPanel(
            nb, self, "phone", self.extra_phone,
            intro="Options added to every phone link (and its QR code).")
        self.p_obs = OptionPanel(
            nb, self, "obs", self.extra_obs,
            intro="Options added to the OBS browser-source links (per-phone view links and the scene link).")
        self.p_dir = OptionPanel(nb, self, "director", None, intro="Options added to your Director link.")
        self.panels = [self.p_phone, self.p_obs, self.p_dir]
        nb.add(self.p_phone, text="Phone options")
        nb.add(self.p_obs, text="OBS options")
        nb.add(self.p_dir, text="Director options")

        tab_phones = ttk.Frame(nb, padding=8)
        nb.add(tab_phones, text="Phones")
        ttk.Label(tab_phones, foreground="#666",
                  text="Edit any label or stream ID. Rows you haven't touched follow the prefix and suffix.").pack(
            anchor="w", pady=(0, 6))
        self.rows_frame = ScrollFrame(tab_phones)
        self.rows_frame.pack(fill="both", expand=True)

        tab_links = ttk.Frame(nb, padding=8)
        nb.add(tab_links, text="Links & QR")
        pick = ttk.Frame(tab_links)
        pick.pack(fill="x")
        ttk.Label(pick, text="Preview phone:").pack(side="left")
        self.sel = tk.StringVar()
        self.combo = ttk.Combobox(pick, textvariable=self.sel, state="readonly", width=30)
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)

        body = ttk.Frame(tab_links)
        body.pack(fill="both", expand=True, pady=(8, 0))
        body.columnconfigure(0, weight=1)
        links = ttk.Frame(body)
        links.grid(row=0, column=0, sticky="nsew")
        self.t_phone = self._link_box(links, "Phone link (this is what the QR code contains)", 6)
        self.t_director = self._link_box(links, "Director link (you)", 3)
        self.t_obs = self._link_box(links, "OBS browser source for this phone", 4)
        self.t_scene = self._link_box(links, "OBS scene link (cameras picked in the Director)", 3)
        qr_frame = ttk.LabelFrame(body, text="QR preview", padding=8)
        qr_frame.grid(row=0, column=1, sticky="n", padx=(10, 0))
        self.qr_label = ttk.Label(qr_frame, text="", justify="center", wraplength=300)
        self.qr_label.pack()

        # --- bottom bar ---
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(bottom, text="", foreground="#b00020", wraplength=760, justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="Generate files", command=self.generate).pack(side="right", padx=(6, 0))
        ttk.Button(bottom, text="Copy all phone links", command=self.copy_all).pack(side="right", padx=(6, 0))

    def _link_box(self, parent, title, height):
        frame = ttk.LabelFrame(parent, text=title, padding=4)
        frame.pack(fill="x", pady=(0, 8))
        text = tk.Text(frame, height=height, wrap="char", font="TkFixedFont")
        text.pack(side="left", fill="x", expand=True)
        text.configure(state="disabled")
        ttk.Button(frame, text="Copy", width=6, command=lambda: self._copy(text)).pack(
            side="left", padx=(6, 0), anchor="n")
        return text

    def _copy(self, widget):
        self.clipboard_clear()
        self.clipboard_append(widget.get("1.0", "end").strip())

    @staticmethod
    def _set_text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _toggle_pw(self):
        self.pw_entry.configure(show="" if self.show_pw.get() else "\u2022")

    def _browse_out(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_dir.set(path)

    # ------------------------------------------------------------ phone rows
    def _new_row(self):
        row = {"id": tk.StringVar(), "label": tk.StringVar(), "id_manual": False, "label_manual": False}
        row["id"].trace_add("write", self._on_change)
        row["label"].trace_add("write", self._on_change)
        return row

    def get_count(self):
        try:
            return max(1, min(99, int(self.count.get())))
        except ValueError:
            return max(1, len(self.rows))

    def _auto_id(self, i):
        return auto_id(self.id_prefix.get().strip(), i, self.suffix.get().strip(), self.use_suffix.get())

    def _auto_label(self, i):
        return auto_label(self.label_prefix.get().strip(), i)

    def sync_rows(self):
        self._lock += 1
        try:
            n = self.get_count()
            while len(self.rows) < n:
                self.rows.append(self._new_row())
            del self.rows[n:]
            for i, r in enumerate(self.rows):
                if not r["id_manual"]:
                    r["id"].set(self._auto_id(i))
                if not r["label_manual"]:
                    r["label"].set(self._auto_label(i))
        finally:
            self._lock -= 1

    def rebuild_row_widgets(self):
        inner = self.rows_frame.inner
        for child in inner.winfo_children():
            child.destroy()
        for col, text in enumerate(("#", "Label", "Stream ID", "")):
            ttk.Label(inner, text=text, font="TkHeadingFont").grid(
                row=0, column=col, sticky="w", padx=4, pady=(0, 4))
        inner.columnconfigure(1, weight=1)
        inner.columnconfigure(2, weight=1)
        for i, r in enumerate(self.rows):
            ttk.Label(inner, text=str(i + 1)).grid(row=i + 1, column=0, padx=4, pady=2)
            e_label = ttk.Entry(inner, textvariable=r["label"], width=22)
            e_label.grid(row=i + 1, column=1, sticky="ew", padx=4, pady=2)
            e_label.bind("<KeyRelease>", lambda _e, rr=r: rr.__setitem__("label_manual", True))
            e_id = ttk.Entry(inner, textvariable=r["id"], width=26)
            e_id.grid(row=i + 1, column=2, sticky="ew", padx=4, pady=2)
            e_id.bind("<KeyRelease>", lambda _e, rr=r: rr.__setitem__("id_manual", True))
            ttk.Button(inner, text="Reset", width=6, command=lambda rr=r: self._reset_row(rr)).grid(
                row=i + 1, column=3, padx=4)
        self._built_rows = len(self.rows)

    def _reset_row(self, row):
        row["id_manual"] = row["label_manual"] = False
        self.sync_rows()
        self.schedule_refresh()

    # -------------------------------------------------------------- handlers
    def _on_structure(self, *_):
        if self._lock:
            return
        self.sync_rows()
        if len(self.rows) != self._built_rows:
            self.rebuild_row_widgets()
        self.schedule_refresh()

    def _on_change(self, *_):
        if self._lock:
            return
        self.schedule_refresh()

    def _on_pick(self, _event=None):
        self.sel_index = max(0, self.combo.current())
        self.refresh()

    def schedule_refresh(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(120, self.refresh)

    # ---------------------------------------------------------------- config
    def cfg(self):
        options = {
            s: {k: {"on": self.opt_on[s][k].get(), "value": self.opt_val[s][k].get()} for k in self.opt_on[s]}
            for s in SCOPES
        }
        return {
            "base_url": (self.base_url.get().strip() or DEFAULT_BASE).rstrip("/"),
            "room": self.room.get().strip(),
            "password": self.password.get().strip(),
            "scene": self.scene.get().strip() or "1",
            "output_dir": self.output_dir.get().strip(),
            "setup": {
                "id_prefix": self.id_prefix.get().strip(),
                "label_prefix": self.label_prefix.get().strip(),
                "use_suffix": self.use_suffix.get(),
                "suffix": self.suffix.get().strip(),
                "phone_count": len(self.rows),
            },
            "options": options,
            "extra": {"phone": self.extra_phone.get(), "obs": self.extra_obs.get()},
            "phones": [{"id": r["id"].get().strip(), "label": r["label"].get()} for r in self.rows],
        }

    def apply_profile(self, p):
        cfg = profile_to_cfg(p)
        s = cfg["setup"]
        self._lock += 1
        try:
            self.base_url.set(cfg["base_url"])
            self.room.set(cfg["room"])
            self.password.set(cfg["password"])
            self.scene.set(cfg["scene"])
            self.output_dir.set(cfg["output_dir"])
            self.count.set(str(s["phone_count"]))
            self.id_prefix.set(s["id_prefix"])
            self.label_prefix.set(s["label_prefix"])
            self.use_suffix.set(s["use_suffix"])
            self.suffix.set(s["suffix"])
            self.extra_phone.set(cfg["extra"]["phone"])
            self.extra_obs.set(cfg["extra"]["obs"])
            for sc in SCOPES:
                for k, st in cfg["options"][sc].items():
                    self.opt_on[sc][k].set(st["on"])
                    self.opt_val[sc][k].set(st["value"])
            self.rows = []
        finally:
            self._lock -= 1

        self.sync_rows()
        self._lock += 1
        try:
            for i, ph in enumerate(cfg["phones"]):
                r = self.rows[i]
                if ph["id"] != self._auto_id(i):
                    r["id"].set(ph["id"])
                    r["id_manual"] = True
                if ph["label"] != self._auto_label(i):
                    r["label"].set(ph["label"])
                    r["label_manual"] = True
        finally:
            self._lock -= 1
        self.rebuild_row_widgets()
        for p_ in self.panels:
            p_.sync_states()
        self.sel_index = 0
        self.refresh()

    def on_apply_preset(self):
        sel = PRESETS[self.preset.get()]()
        state = state_from_selection(sel)
        self._lock += 1
        try:
            for sc in SCOPES:
                for k, st in state[sc].items():
                    self.opt_on[sc][k].set(st["on"])
                    self.opt_val[sc][k].set(st["value"])
        finally:
            self._lock -= 1
        for p_ in self.panels:
            p_.sync_states()
        self.refresh()

    # --------------------------------------------------------------- refresh
    def refresh(self):
        self._after_id = None
        cfg = self.cfg()
        errors, warnings = problems(cfg)
        shown = errors + warnings
        text = "  \u2022  ".join(shown[:4]) + (f"  (+{len(shown) - 4} more)" if len(shown) > 4 else "")
        self.status.configure(text=text, foreground="#b00020" if errors else "#8a6d00")
        n = len(cfg["phones"])
        if not n:
            return
        labels = [f"{i + 1}. {p['label'] or p['id']}" for i, p in enumerate(cfg["phones"])]
        self.combo.configure(values=labels)
        self.sel_index = min(self.sel_index, n - 1)
        self._lock += 1
        try:
            self.sel.set(labels[self.sel_index])
        finally:
            self._lock -= 1
        url = phone_url(cfg, self.sel_index)
        self._set_text(self.t_phone, url)
        self._set_text(self.t_director, director_url(cfg))
        self._set_text(self.t_obs, obs_view_url(cfg, self.sel_index))
        self._set_text(self.t_scene, obs_scene_url(cfg))
        self._update_qr(url)

    def _update_qr(self, url):
        if qrcode is None:
            self._qr_image = None
            self.qr_label.configure(image="", text='Install the QR library:\npip install "qrcode[pil]"')
            return
        try:
            data = base64.b64encode(qr_png_fit(url)).decode("ascii")
            self._qr_image = tk.PhotoImage(data=data)
            self.qr_label.configure(image=self._qr_image, text="")
        except Exception as exc:  # noqa: BLE001
            self._qr_image = None
            self.qr_label.configure(image="", text=f"QR preview failed:\n{exc}")

    # ------------------------------------------------------------- save/load
    def on_save(self):
        try:
            PROFILE_PATH.write_text(json.dumps(cfg_to_profile(self.cfg()), indent=2), encoding="utf-8")
            messagebox.showinfo("Saved", f"Settings saved to:\n{PROFILE_PATH}")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    def on_save_as(self):
        room = slug(self.room.get().strip()) if self.room.get().strip() else ""
        path = filedialog.asksaveasfilename(
            title="Save settings as", defaultextension=".json",
            initialfile=f"vdo_profile_{room}.json" if room else "vdo_profile.json",
            filetypes=[("JSON", "*.json")], initialdir=str(PROFILE_PATH.parent))
        if path:
            try:
                Path(path).write_text(json.dumps(cfg_to_profile(self.cfg()), indent=2), encoding="utf-8")
                messagebox.showinfo("Saved", f"Settings saved to:\n{path}")
            except OSError as exc:
                messagebox.showerror("Save failed", str(exc))

    def on_load(self):
        path = filedialog.askopenfilename(
            title="Load settings", filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialdir=str(PROFILE_PATH.parent))
        if path:
            p = load_profile_file(path, quiet=False)
            if p is not None:
                self.apply_profile(p)

    # --------------------------------------------------------------- actions
    def copy_all(self):
        cfg = self.cfg()
        text = "\n".join(f"{p['label'] or p['id']}: {phone_url(cfg, i)}" for i, p in enumerate(cfg["phones"]))
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", f"Copied {len(cfg['phones'])} phone links to the clipboard.")

    def generate(self):
        cfg = self.cfg()
        errors, _ = problems(cfg)
        if errors:
            messagebox.showerror("Fix these first", "\n".join(errors))
            return
        out = resolve_output_dir(cfg)
        notes = write_outputs(cfg, out)
        try:
            PROFILE_PATH.write_text(json.dumps(cfg_to_profile(cfg), indent=2), encoding="utf-8")
        except OSError:
            pass
        if messagebox.askyesno(
            "Done",
            f"Files written to:\n{out.resolve()}\n\n" + "\n".join(f"- {n}" for n in notes) +
            "\n\nThe files contain the room password, so keep them private.\n\nOpen the folder?",
        ):
            open_folder(out.resolve())


# ===========================================================================
# 6. ENTRY POINT
# ===========================================================================
def run_headless(profile_path):
    p = load_profile_file(profile_path)
    if not p:
        print(f"No saved profile found at {profile_path}. Run without --generate to create one.")
        return 1
    cfg = profile_to_cfg(p)
    errors, warnings = problems(cfg)
    for w in warnings:
        print(f"! {w}")
    if errors:
        print("Cannot generate:\n  " + "\n  ".join(errors))
        return 1
    out = resolve_output_dir(cfg)
    notes = write_outputs(cfg, out)
    print(f"Director link:\n  {director_url(cfg)}\n")
    print(f"Files written to {out.resolve()}: " + ", ".join(notes))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="VDO.Ninja phone link + QR generator")
    ap.add_argument("--generate", action="store_true", help="no window: regenerate files from the saved profile")
    ap.add_argument("--profile", default=str(PROFILE_PATH), help="profile JSON to use (default: next to this script)")
    args = ap.parse_args(argv)
    if args.generate:
        return run_headless(args.profile)
    if tk is None:
        print("tkinter is not available in this Python. Install it, or use --generate with a saved profile.")
        return 1
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
