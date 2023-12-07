import webbrowser
from typing import Optional

def find_browser() -> Optional[webbrowser.BaseBrowser]:
    """Find the default browser if possible and if compatible."""

    # Mostly taken from the standard library webbrowser module. Search "console browsers" in there.
    # In general, a browser belongs on this list of the scalene web GUI doesn't work in it.
    # See https://github.com/plasma-umass/scalene/issues/723.
    incompatible_browsers = {"www-browser", "links", "elinks", "lynx", "w3m", "links2", "links-g"}

    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return None

    return None if browser.name in incompatible_browsers else browser
