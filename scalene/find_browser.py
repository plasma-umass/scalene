import webbrowser
from typing import Optional


def find_browser() -> Optional[webbrowser.BaseBrowser]:
    """Find the default browser if possible and if compatible."""
    # Names of known graphical browsers as per Python's webbrowser documentation
    graphical_browsers = [
        "windowsdefault",
        "macosx",
        "safari",
        "google-chrome",
        "chrome",
        "chromium",
        "firefox",
        "opera",
        "edge",
        "mozilla",
        "netscape",
    ]
    try:
        # Get the default browser object
        browser = webbrowser.get()
        # Check if the browser's class name matches any of the known graphical browsers
        browser_class_name = str(type(browser)).lower()
        if any(
            graphical_browser in browser_class_name
            for graphical_browser in graphical_browsers
        ):
            return browser
        else:
            return None
    except webbrowser.Error:
        # Return None if there is an error in getting the browser
        return None
