import webbrowser
from typing import Optional

def find_browser(browserClass=None) -> Optional[str]:
    """Find the default system browser, excluding text browsers.
    
    If you want a specific browser, pass its class as an argument."""
    text_browsers = [
        "browsh", "elinks", "links", "lynx", "w3m",
    ]

    try:
        # Get the default browser object
        browser = webbrowser.get(browserClass)
        return browser.name if browser.name not in text_browsers else None
    except webbrowser.Error:
        # Return None if there is an error in getting the browser
        return None
