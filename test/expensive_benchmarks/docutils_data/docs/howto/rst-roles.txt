==================================================
 Creating reStructuredText Interpreted Text Roles
==================================================

:Authors: David Goodger
:Contact: docutils-develop@lists.sourceforge.net
:Date: $Date$
:Revision: $Revision$
:Copyright: This document has been placed in the public domain.

Interpreted text roles are an extension mechanism for inline markup in
reStructuredText.  This document aims to make the creation of new
roles as easy and understandable as possible.

Standard roles are described in `reStructuredText Interpreted Text
Roles`_.  See the `Interpreted Text`_ section in the `reStructuredText
Markup Specification`_ for syntax details.

.. _reStructuredText Interpreted Text Roles: ../ref/rst/roles.html
.. _Interpreted Text:
   ../ref/rst/restructuredtext.html#interpreted-text
.. _reStructuredText Markup Specification:
   ../ref/rst/restructuredtext.html


.. contents::


Define the Role Function
========================

The role function creates and returns inline elements (nodes) and does
any additional processing required.  Its signature is as follows::

    def role_fn(name, rawtext, text, lineno, inliner,
                options=None, content=None):
        code...

    # Optional function attributes for customization:
    role_fn.options = ...
    role_fn.content = ...

Function attributes are described below (see `Specify Role Function
Options and Content`_).  The role function parameters are as follows:

* ``name``: The local name of the interpreted role, the role name
  actually used in the document.

* ``rawtext``: A string containing the entire interpreted text input,
  including the role and markup.  Return it as a ``problematic`` node
  linked to a system message if a problem is encountered.

* ``text``: The interpreted text content.

* ``lineno``: The line number where the text block containing the
  interpreted text begins.

* ``inliner``: The ``docutils.parsers.rst.states.Inliner`` object that
  called role_fn.  It contains the several attributes useful for error
  reporting and document tree access.

* ``options``: A dictionary of directive options for customization
  (from the `"role" directive`_), to be interpreted by the role
  function.  Used for additional attributes for the generated elements
  and other functionality.

* ``content``: A list of strings, the directive content for
  customization (from the `"role" directive`_).  To be interpreted by
  the role function.

Role functions return a tuple of two values:

* A list of nodes which will be inserted into the document tree at the
  point where the interpreted role was encountered (can be an empty
  list).

* A list of system messages, which will be inserted into the document tree
  immediately after the end of the current block (can also be empty).


Specify Role Function Options and Content
=========================================

Function attributes are for customization, and are interpreted by the
`"role" directive`_.  If unspecified, role function attributes are
assumed to have the value ``None``.  Two function attributes are
recognized:

- ``options``: The option specification.  All role functions
  implicitly support the "class" option, unless disabled with an
  explicit ``{'class': None}``.

  An option specification must be defined detailing the options
  available to the "role" directive.  An option spec is a mapping of
  option name to conversion function; conversion functions are applied
  to each option value to check validity and convert them to the
  expected type.  Python's built-in conversion functions are often
  usable for this, such as ``int``, ``float``, and ``bool`` (included
  in Python from version 2.2.1).  Other useful conversion functions
  are included in the ``docutils.parsers.rst.directives`` package.
  For further details, see `Creating reStructuredText Directives`_.

- ``content``: A boolean; true if "role" directive content is allowed.
  Role functions must handle the case where content is required but
  not supplied (an empty content list will be supplied).

  As of this writing, no roles accept directive content.

Note that unlike directives, the "arguments" function attribute is not
supported for role customization.  Directive arguments are handled by
the "role" directive itself.

.. _"role" directive: ../ref/rst/directives.html#role
.. _Creating reStructuredText Directives:
   rst-directives.html#specify-directive-arguments-options-and-content


Register the Role
=================

If the role is a general-use addition to the Docutils core, it must be
registered with the parser and language mappings added:

1. Register the new role using the canonical name::

       from docutils.parsers.rst import roles
       roles.register_canonical_role(name, role_function)

   This code is normally placed immediately after the definition of
   the role function.

2. Add an entry to the ``roles`` dictionary in
   ``docutils/parsers/rst/languages/en.py`` for the role, mapping the
   English name to the canonical name (both lowercase).  Usually the
   English name and the canonical name are the same.  Abbreviations
   and other aliases may also be added here.

3. Update all the other language modules as well.  For languages in
   which you are proficient, please add translations.  For other
   languages, add the English role name plus "(translation required)".

If the role is application-specific, use the ``register_local_role``
function::

    from docutils.parsers.rst import roles
    roles.register_local_role(name, role_function)


Examples
========

For the most direct and accurate information, "Use the Source, Luke!".
All standard roles are documented in `reStructuredText Interpreted
Text Roles`_, and the source code implementing them is located in the
``docutils/parsers/rst/roles.py`` module.  Several representative
roles are described below.


Generic Roles
-------------

Many roles simply wrap a given element around the text.  There's a
special helper function, ``register_generic_role``, which generates a
role function from the canonical role name and node class::

    register_generic_role('emphasis', nodes.emphasis)

For the implementation of ``register_generic_role``, see the
``docutils.parsers.rst.roles`` module.


RFC Reference Role
------------------

This role allows easy references to RFCs_ (Request For Comments
documents) by automatically providing the base URL,
http://www.faqs.org/rfcs/, and appending the RFC document itself
(rfcXXXX.html, where XXXX is the RFC number).  For example::

    See :RFC:`2822` for information about email headers.

This is equivalent to::

    See `RFC 2822`__ for information about email headers.

    __ http://www.faqs.org/rfcs/rfc2822.html

Here is the implementation of the role::

    def rfc_reference_role(role, rawtext, text, lineno, inliner,
                           options=None, content=None):
        if "#" in text:
            rfcnum, section = utils.unescape(text).split("#", 1)
        else:
            rfcnum, section  = utils.unescape(text), None
        try:
            rfcnum = int(rfcnum)
            if rfcnum < 1:
                raise ValueError
        except ValueError:
            msg = inliner.reporter.error(
                'RFC number must be a number greater than or equal to 1; '
                '"%s" is invalid.' % text, line=lineno)
            prb = inliner.problematic(rawtext, rawtext, msg)
            return [prb], [msg]
        # Base URL mainly used by inliner.rfc_reference, so this is correct:
        ref = inliner.document.settings.rfc_base_url + inliner.rfc_url % rfcnum
        if section is not None:
            ref += "#"+section
        options = normalize_role_options(options)
        node = nodes.reference(rawtext, 'RFC ' + str(rfcnum), refuri=ref,
                               **options)
        return [node], []

    register_canonical_role('rfc-reference', rfc_reference_role)

Noteworthy in the code above are:

1. The interpreted text itself should contain the RFC number.  The
   ``try`` clause verifies by converting it to an integer.  If the
   conversion fails, the ``except`` clause is executed: a system
   message is generated, the entire interpreted text construct (in
   ``rawtext``) is wrapped in a ``problematic`` node (linked to the
   system message), and the two are returned.

2. The RFC reference itself is constructed from a stock URI, set as
   the "refuri" attribute of a "reference" element.

3. The ``options`` function parameter, a dictionary, may contain a
   "class" customization attribute; it is interpreted and replaced
   with a "classes" attribute by the ``set_classes()`` function.  The
   resulting "classes" attribute is passed through to the "reference"
   element node constructor.

.. _RFCs: http://foldoc.doc.ic.ac.uk/foldoc/foldoc.cgi?query=rfc&action=Search&sourceid=Mozilla-search
