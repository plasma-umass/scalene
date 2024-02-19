import webbrowser
from typing import Optional


def find_browser(browserClass=None) -> Optional[str]:
    """Find the default system browser"""
    try:
        # Get the default browser object
        browser = webbrowser.get(browserClass)
        return browser.name
    except webbrowser.Error:
        # Return None if there is an error in getting the browser
        return None
