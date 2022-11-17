===============================================
 Inside A Docutils Command-Line Front-End Tool
===============================================

:Author: David Goodger
:Contact: docutils-develop@lists.sourceforge.net
:Date: $Date$
:Revision: $Revision$
:Copyright: This document has been placed in the public domain.

`The Docutils Publisher`_ class was set up to make building
command-line tools easy.  All that's required is to choose components
and supply settings for variations.  Let's take a look at a typical
command-line front-end tool, ``tools/rst2html.py``, from top to
bottom.

On Unixish systems, it's best to make the file executable (``chmod +x
file``), and supply an interpreter on the first line, the "shebang" or
"hash-bang" line::

    #!/usr/bin/env python

Windows systems can be set up to associate the Python interpreter with
the ``.py`` extension.

Next are some comments providing metadata::

    # $Id$
    # Author: David Goodger <goodger@python.org>
    # Copyright: This module has been placed in the public domain.

The module docstring describes the purpose of the tool::

    """
    A minimal front end to the Docutils Publisher, producing HTML.
    """

This next block attempts to invoke locale support for
internationalization services, specifically text encoding.  It's not
supported on all platforms though, so it's forgiving::

    try:
        import locale
        locale.setlocale(locale.LC_ALL, '')
    except:
        pass

The real work will be done by the code that's imported here::

    from docutils.core import publish_cmdline, default_description

We construct a description of the tool, for command-line help::

    description = ('Generates (X)HTML documents from standalone '
                   'reStructuredText sources.  ' + default_description)

Now we call the Publisher convenience function, which takes over.
Most of its defaults are used ("standalone" Reader,
"reStructuredText" Parser, etc.).  The HTML Writer is chosen by name,
and a description for command-line help is passed in::

    publish_cmdline(writer_name='html', description=description)

That's it!  `The Docutils Publisher`_ takes care of the rest.

.. _The Docutils Publisher: ./publisher.html
