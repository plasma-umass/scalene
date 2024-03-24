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
        browser_name = browser.name if browser.name else browser.__class__.__name__
        return browser_name if browser_name not in text_browsers else None
    except AttributeError:
        # https://github.com/plasma-umass/scalene/issues/790
        # https://github.com/python/cpython/issues/105545
        # MacOSXOSAScript._name was deprecated but for pre-Python 3.11,
        # we need to refer to it as such to prevent this error:
        #   'MacOSXOSAScript' object has no attribute 'name'
        browser = webbrowser.get(browserClass)
        return browser._name if browser._name not in text_browsers else None
    except webbrowser.Error:
        # Return None if there is an error in getting the browser
        return None
