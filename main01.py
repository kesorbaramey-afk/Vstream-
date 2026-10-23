import json
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path


class _NullOut:
    """Safe stand-in when sys.stdout/stderr is missing on Android."""
    def write(self, *_a):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


for _name in ("stdout", "stderr"):
    if not callable(getattr(getattr(sys, _name, None), "write", None)):
        setattr(sys, _name, _NullOut())

# --- yt-dlp self-update support: an updated yt-dlp zip (downloaded by the
# --- Update button) is placed first on sys.path before importing yt_dlp.
BASE_DIR = Path(os.environ.get("ANDROID_PRIVATE") or (Path.home() / ".vstream"))
UPDATE_DIR = BASE_DIR / "vstream_updates"
UPDATE_FILE = UPDATE_DIR / "yt-dlp.zip"
if UPDATE_FILE.exists():
    sys.path.insert(0, str(UPDATE_FILE))
try:
    import yt_dlp
except Exception:
    if str(UPDATE_FILE) in sys.path:
        sys.path.remove(str(UPDATE_FILE))
    try:
        UPDATE_FILE.unlink()
    except Exception:
        pass
    for _m in [k for k in sys.modules if k.startswith("yt_dlp")]:
        del sys.modules[_m]
    import yt_dlp

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import platform, escape_markup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.image import AsyncImage, Image
from kivy.uix.popup import Popup
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.modalview import ModalView
from kivy.uix.behaviors import ButtonBehavior
from kivy.properties import NumericProperty
from kivy.graphics import Color, Line, RoundedRectangle

# ---------------------------------------------------------------- fonts
# English-only UI: everything uses the built-in Roboto font.
LATIN = "Roboto"
KH = LATIN


def _kind(ch):
    o = ord(ch)
    if o < 0x250 or 0x2000 <= o <= 0x206F:
        return "la"
    return None  # Hangul, emoji, etc. (not in our fonts) are dropped


def rich(text):
    """Markup text: Khmer runs use the Khmer font, everything else Roboto."""
    out, cur, buf = [], None, []
    for ch in str(text):
        kind = _kind(ch)
        if kind is None:
            continue
        if ch.isspace() and cur:
            kind = cur
        if kind != cur:
            if buf:
                out.append(f"[font={KH if cur == 'kh' else LATIN}]"
                           f"{escape_markup(''.join(buf))}[/font]")
            buf, cur = [], kind
        buf.append(ch)
    if buf:
        out.append(f"[font={KH if cur == 'kh' else LATIN}]"
                   f"{escape_markup(''.join(buf))}[/font]")
    if not out and str(text).strip():
        return f"[font={LATIN}](untitled)[/font]"
    return "".join(out)


def mix(khmer, latin=""):
    return rich(f"{khmer}{latin}")


# ------------------------------------------------------ yt-dlp helpers
class QuietLogger:
    """Keeps yt-dlp from writing to stdout/stderr (crashes on some Android builds)."""
    def __init__(self):
        self.last_error = ""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.last_error = str(msg)


def cookie_options(download_dir):
    """Use cookies.txt (Netscape format) if the user put one in the folder."""
    places = [BASE_DIR / "cookies.txt"]
    if download_dir:
        places += [Path(download_dir) / "cookies.txt", Path(download_dir).parent / "cookies.txt"]
    for place in places:
        try:
            if place.exists():
                UPDATE_DIR.mkdir(parents=True, exist_ok=True)
                private = UPDATE_DIR / "cookies_run.txt"
                shutil.copy(str(place), str(private))
                return {"cookiefile": str(private)}
        except Exception:
            continue
    return {}


def base_options(logger):
    return {"quiet": True, "no_warnings": True, "noprogress": True,
            "logger": logger, "color": {"stdout": "never", "stderr": "never"},
            "socket_timeout": 30}


# --------------------------------------------------------------- themes
THEMES = {
    "dark": dict(bg=(0.035, 0.055, 0.11, 1), card=(0.06, 0.09, 0.165, 1),
                 input=(0.05, 0.075, 0.145, 1), border=(0.11, 0.19, 0.34, 1),
                 btn=(0.09, 0.15, 0.29, 1), btn_border=(0.14, 0.25, 0.46, 1),
                 accent=(0.10, 0.46, 1.0, 1), text=(0.94, 0.96, 1.0, 1),
                 muted=(0.55, 0.62, 0.75, 1), danger=(0.85, 0.30, 0.30, 1),
                 ok=(0.30, 0.75, 0.45, 1)),
    "light": dict(bg=(0.94, 0.96, 0.99, 1), card=(1, 1, 1, 1),
                  input=(0.95, 0.97, 1.0, 1), border=(0.80, 0.86, 0.94, 1),
                  btn=(0.90, 0.94, 1.0, 1), btn_border=(0.74, 0.83, 0.97, 1),
                  accent=(0.13, 0.45, 0.90, 1), text=(0.10, 0.12, 0.16, 1),
                  muted=(0.40, 0.45, 0.52, 1), danger=(0.80, 0.22, 0.22, 1),
                  ok=(0.15, 0.60, 0.32, 1)),
}
T = dict(THEMES["dark"])

# Small white PNG icons (base64) so no extra files are needed in the APK.
ICONS = {
    "link": (
        "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAAEf0lEQVR42u2bzYtcRRTFT3X3ZGIURcHJh8SVIrjwD3ARs/Br"
        "IyJZiG4M6CLZKILEjcSNa0FGN5qgSMCFGghEJ0TBIbrJSlRQ1EgGQYxK1Bi/0j3dPxdW6c31vZ7umY70q6kDTc+896qYOnPO"
        "vbfue08qKCgoKCgoKCgoKBgfoekLAP5ZQwiBQtC/pLQlDUIIg5WOrxsAAWi7Y21gDtjkjresurJXEBCShYAtknZJulvSTZI2"
        "SzonaUnS+5LeCCF8mIjKXk1AK353gH3ADwxHH3gN2GbH507ORuBtQ0Ivfi4AXfPdAwbxmq+Bm7MlyZAzCyzERXcjActD1DOI"
        "RAF8A2yP8auVTQxKsQOYlXRE0l2SepJmJPVjtjor6S1JX0qak3SbpFvMNMuSOpKOhhDuySYeOeUcM8rBKONFYKsb1wH2xGv6"
        "Tmk7UtbL1VaWnHlHSvqksQ8Zu6WYdDBdn5tyeo6keVP/tCrqpE78+QM37pQ5F3KzVRU5oWaeTiTqCTf2V+C6RhI0jq2GkeMI"
        "2u3GDxqZ8ldhq7DCfImgfW6O86ZwDOvKVjUx6KSb5/NGZbC02EnYysw5E7/3uCwG8FJjsljalQObDDmrtpUjJ8WeZVcH3dqY"
        "Oij9kbHYs6T0V0lOx5GTisQ07+HGBGdgQ1TQDqOcgVnUczbYrkI5voJeArbF/lBr2m3VMr8vmIUk5ZwANvggvgZbLQE3TL16"
        "rBKAe4FF85/G1Cl/AqeBZ4BrhsWMIbaqIqc9zeTYVP4qo+MUsLNqgSPaqnHk2CKwrpeTduF2e7DTzTWOrRpHTtctytqr535P"
        "C/4uNuVDik8jKqfTFHIWalK57wA+DOwHfjckpTEvmLmztRVmMa8DZ925I3Hc7dFafUPC+VgTPZizrS5SA/BeRZp/Mp7b6wgF"
        "eNPtzLOyVVUncJcrFFNMOgTcAfxoyBg4W2Zlq6q9VTsG3aPx3AVDBm68J6WXo60u2lul28LAFuATc22/ghgbzLvZ2spvPM3Y"
        "rcA7KxSNVlkngRuboJyw1k6g25s9AnwE/FZRIwF8Bjwa75NNPznRJhsrlNMds4ccnLKeNTEnpfozwJWjbmKnZlduguykOoG7"
        "gT9M2k/z7jdqne5+sml27b0E5FCRxT4FLp/U8z7/h3oCcBXwrbHA8oQ7gc3q51Qs6H4TJ9JiDq1ROc3cW9UQdNBsJgfAL8D1"
        "VY/ITaAT2KhbNSk4L7oK+PioNhjTVp0mkRNMHPrCEXQgBtHOurNVjYJOOIKOraSgbG1VY4+XXQw6F2+tBK+ieGwmS1sNIeiB"
        "iix2wF5nPiFrW9XUQVcD31fUQc8D17oxs8Bj2ZNTUUk/XtNrPhMt+BQwHzeZtvGVl61qVNSOWev4mI/mdrNVTs1u/grg3TEf"
        "7v4qa3Jq+kFPAz+t0PTqAa8Am5tETlgrSeYFk+2S7pN0p/5+wWRO0s+STktalHQ4hPBxqpfWzetKNa8odeLd0Mt8odm0J0zD"
        "BIlqSWrpvy+5VR5fdwRVxSfp0rwmWVBQUFBQUFBQUFAw7fgLe3O/lBkwHLUAAAAASUVORK5CYII="
    ),
    "gear": (
        "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"
    ),
    "paste": (
        "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAADnklEQVR42u2cS4sUVxTHf6e6Z0Y0KAYkIGKULIIbQd0YCGRh"
        "EhL8Ai5Esoiusg3JR8hXiAshLiXgRhBEDCHBrZD3Q/EVXSWoiM44M13/LPpcrJTdZrr7VnfNcA4UNVPM1Ln1u+fVxTkNISEh"
        "IbMTm5YiSeb6cugszUwbZhckFQ3cs7MhLEhSYWalW9BBYOuYupPFPAOumdliuve6txxJ70i6pnxyS9KJpqxzanAkmaRDkpb8"
        "wXqZjiTHpulujcQISRf8YZ5ltKAVSaWkm5IW3H0bkaIhOGZmPUnbgMMeP+Yyquj6+XVgn5mpKSvqZkrfHUBm1huwAYUH5CbS"
        "sg0C73GpAHqTlgPdSeOMZ5HVWXrzC9T6ayqTqw/YuObTfFIs6RXgBPAe8GbNbTvAXj83JbeBpRqwO8D3wBkzuzf1cqCSvt+S"
        "9JvaK39PmulsAss5DHwDbAJW/F7lEDcuGnSvlZcknxRCPjKzr8ZxNxsjIANsAX5w91nNEewbgpfi0wqwH/izH6LW7m6jPljH"
        "zFa9ik1wkukuAheBxxX4JXAE2OU/54pFpT/8IvB1baPngXeBHf57D1gAPjWzk41W3rXir5S07JXtI0lvD/mfD2sFXo4jVdOf"
        "DdG5R9INX2MqKq9PreKW9GutOj7n1+cldSvHvF8/JelB5kr6iyE6N/n1z/1vl/38VNLOUT+/jRs76rHrsSstzWx1QK10WtIF"
        "N/3tE+7PIvCtmf3uFftyTV8C8GTAmkdOSrmCa8dfaRSDijbPHveBs7lfowzcPdfZio8aw6rZ2oJ7lfI/S5BeQyZSmwD9v09W"
        "yv/1JOvzZVMACkABKAAFoJAAFIACUAAKQAEoAAWgABQSgAJQAApAASgABaAAFBKAAlAACkABKAAFoAAUkhWQtfDZrE2Aem0a"
        "bPN+7izNWrk6zDZ7X+CcNPNZ2673ci/UuU1jZ1Kf9MVan/Q/kg60yIJek/RLrU/6pqRu0xaU/PoS8AHPW2tfBa5IOk+/014z"
        "jDtzwFFgd2UdBnznljXSvMa4sxrbgJ+BnfRb/YsWBmrx33mNA8BPQDEKoJEsKI0+mtlDSceBy/TnL9K0j2ZoPYOST3q+T8zs"
        "x0mH68aJRe9LutviebEnkk5V1zy1WqEyN7YD+Jj+xOEbNDtduBa3AvgLuAp8aWZ/TDJxaJNaUtVkPbXOPBaZ2dKwNU692qxM"
        "PZdt+ZqInGuyBhZGCyxo43wzTEhISEjIcPkXJS0Gd/iDmBUAAAAASUVORK5CYII="
    ),
    "trash": (
        "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"
    ),
    "cloud": (
        "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"
    ),
    "moon": (
        "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAAE7klEQVR42u2bS4gcVRSGv1M9k0FEEyMy0ZhAMBON2Sm+Ig6o"
        "uHCvkNUYBYkQdB0ku0B0JwouBl24ihJwJYKIWejCF4y4cGNUElyMJIKZEQcx3VW/iz6X3BQ9Pf2q7upK/VDUPKtu//c/555z"
        "7rlQo0aNGjVq1KhRo0YHWFkGIum6sZiZbliCJCX+bgMyM8tueAW5QhpA2kkdknZE45GZrUmaNbNmpQlyYhIzS6Of7QMeAg4D"
        "9wLzwF4gAYKaLgMvAt+3La68KhuGnEb09R2Sjkn6StK/2hqvROZYOWKS4HQl3S3pLUmXcwS0JDX9nvp1VVImaSlPcOVU4yS9"
        "KulSjpSWk5BH0+8n/P9nq0jOTPAxks7lPnzWxZxafv80kJNf9qtEzjORarYiRv77VNK6pL2SrHJ+JyJnqYMqtkIwrTfjZ1WZ"
        "nOBwe0Hm15qk+cqpJ3LIT0fkZOodQT3vV27VCjPty/ifkS/pB+HvF109jaqQY5Iafn3Zp8/Jk7Mq6eZOCWsZMKi9h9ThGLAI"
        "tDzP6gchdVgxsw1JjbJk8EMR5KaVSboTOAWkQxAN8EPZSi/DKsh8pk8AOwEN+hy//1Zmd5L063vMLJW0E1hycgZ1rIGg38Pj"
        "q6CgQMZzwA73I8OaRqMyCooc69ERznirEgRJSswsk7QHeMCVM4xzDgTfXhUFBVN6FJjz1ctGQND+qqxi4QM8PmKneqgqCgr+"
        "5+CIZjy8+2FPeNNpJ0geJO4a4bvlJrbfzFTGTD7pkZkQHN4K7B4yTYmRAjMeNozqmRNd5m3EHyI866ikbZ7C2DQTVMT7U+Ae"
        "4IjvfTWmXUGjnmFzX3RS0pz7OpsqgtyBGvA38MeIl/mwm7oAvO5llJlpVJCZWQu4VEByGUztpKQnzaxZluJ9MsDfni+AIIuu"
        "M5IOmFmrDCQN4qS/LSg1CHHRLuALSQtO0uy0EBQi6a89A08KGk8K7AHOSToYzG0qdlrDvpWknwYs1PeK8Ny/JD0fvX9m3NF2"
        "3wUzj1XOFOCHrnuPK/Y24Kyk9yTtNrOWl1wagaxuyoomNBnGOfajoLgmdN7LHkWWKsS1mvcVYBlYNrOL+XF1mOzJtPZFu6kf"
        "5XZHi0RsyhuSzvpW94FuK52rZ0HS4aCoQhUUEZQB9wMrHtQlYyh4yd8bpyIt4ALtwv/PQDMy0fuAu7w885KZfeB7b+k4VfTG"
        "GFUUNzy0+lggPovMkMIVFEk1AW4CfvRkM5tA8qvclQ9J/gMeBH5lwEbQwVj1LWIz+wc44lLPGP/eVpiohpt6uAzYBhw3s19o"
        "b5VPxGGH3qCXJ2Bqm+Gq39+JxzjJ4DGQdDoaYDZhcj6Ouk8mH4F3ICkdoFdoWMfdjMhJPEgsR3oSNz9Jei1S0LhjpLeDakrZ"
        "yheR9JSkC7lledRIo+euS3ohmqzyJraRuc1LWo7UlPXYFtxLDBSb7yeSDoUJmpasPz6jsSjp8w6zHx9DyLr0T8dHFmKs5DL9"
        "6epvzDdlSnpE0rvek9itJTjrorIrkj6U9GzuyENh/mYcx6ES2ue/5N9vp90A8QTwGLCPdqfa9ty/bgBrwEXgOy/UfWNmq7Fq"
        "is6txnmgLvFwP839fA64hWvnxeTjWgXWzWxjE/PNxtH0aZMwvSj737JmE51U1LhImShBmxAQxmL5hLOMrcE1atSoUaNGjRo1"
        "avA/vNLEKFuCgGEAAAAASUVORK5CYII="
    ),
    "folder": (
        "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAADBUlEQVR42u2bTWsTURSGnzNJqgstFCrqRlCw4loFP3aCUnQj"
        "Lt3oD9B/4NqtIK5c1I2u3OpC6C8Q2m7FD0SEgoKIpZR+JHld5A6OsWYmyc0kU88LIbNI7sx57nvPnJs5AZfL5XK5XC6Xy+WK"
        "Liv6QUkG1CKdt21m7T1DUVJShTHH4iBJZmaSdAC4CRwH1I/7urQGvDSz95KSSjspnWVJc5LeKp42JN2ugpMsJ+cA7AOWgdPA"
        "NjBsQAIa4fismS1JqplZq2ruqYf3a2HWdyI6aDu8P8meaxJVxA1Hw6yPwrlHMq6aSBWZueYQCTl37LCULbOkR5dPzDQKQFbC"
        "RTdLvOlYP/lu3Gt/StJMKEBHnaRbZraWLV1iAdIIl/ZV4GMZ5gF2JK0AC2b2IrhJeaCKAGqM8MIbwE
