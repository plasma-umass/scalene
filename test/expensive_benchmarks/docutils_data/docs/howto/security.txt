=============================
 Deploying Docutils Securely
=============================

:Author: David Goodger
:Contact: docutils-develop@lists.sourceforge.net
:Date: $Date$
:Revision: $Revision$
:Copyright: This document has been placed in the public domain.

.. contents::

Introduction
============

Initially, Docutils was intended for command-line tools and
single-user applications.  Through-the-web editing and processing was
not envisaged, therefore web security was not a consideration.  Once
Docutils/reStructuredText started being incorporated into an
ever-increasing number of web applications (blogs__, wikis__, content
management systems, and others), several security issues arose and
have been addressed.  Still, **Docutils does not come in a
through-the-web secure state**, because this would inconvenience
ordinary users.  This document provides pointers to help you secure
the Docutils software in your applications.

__ ../../FAQ.html#are-there-any-weblog-blog-projects-that-use-restructuredtext-syntax
__ ../../FAQ.html#are-there-any-wikis-that-use-restructuredtext-syntax


The Issues
==========

File Creation
-------------

Docutils does not do any checks before writing to a file:

* Existing **files are overwritten** without asking!
* Files may be **written to any location** accessible to the process.
* There are **no restrictions to** the **file names**.

Special care must be taken when allowing users to configure the *output
destination* or the `warning_stream`_, `record_dependencies`_, or
`_destination`_ settings.

.. _warning_stream: ../user/config.html#warning-stream
.. _record_dependencies: ../user/config.html#record-dependencies
.. _`_destination`: ../user/config.html#destination


External Data Insertion
-----------------------

There are several `reStructuredText directives`_ that can insert
external data (files and URLs) into the output document.  These
directives are:

* "include_", by its very nature,
* "raw_", through its ``:file:`` and ``:url:`` options,
* "csv-table_", through its ``:file:`` and ``:url:`` options,
* "image_", if `embed_images`_ is true.

The "include_" directive and the other directives' file insertion
features can be disabled by setting "file_insertion_enabled_" to
"false__".

__ ../user/config.html#configuration-file-syntax
.. _reStructuredText directives: ../ref/rst/directives.html
.. _include: ../ref/rst/directives.html#include
.. _raw: ../ref/rst/directives.html#raw-directive
.. _csv-table: ../ref/rst/directives.html#csv-table
.. _image: ../ref/rst/directives.html#image
.. _embed_images: ../user/config.html#embed-images
.. _file_insertion_enabled: ../user/config.html#file-insertion-enabled


Raw HTML Insertion
------------------

The "raw_" directive is intended for the insertion of
non-reStructuredText data that is passed untouched to the Writer.
This directive can be abused to bypass site features or insert
malicious JavaScript code into a web page.  The "raw_" directive can
be disabled by setting "raw_enabled_" to "false".

.. _raw_enabled: ../user/config.html#raw-enabled


CPU and memory utilization
--------------------------

Parsing **complex reStructuredText documents may require high
processing resources**. This enables `Denial of Service` attacks using
specially crafted input.

It is recommended to enforce limits for the computation time and
resource utilization of the Docutils process when processing
untrusted input. In addition, the "line_length_limit_" can be
adapted.

.. _line_length_limit: ../user/config.html#line-length-limit


Securing Docutils
=================

Programmatically Via Application Default Settings
-------------------------------------------------

If your application calls Docutils via one of the `convenience
functions`_, you can pass a dictionary of default settings that
override the component defaults::

    defaults = {'file_insertion_enabled': False,
                'raw_enabled': False}
    output = docutils.core.publish_string(
        ..., settings_overrides=defaults)

Note that these defaults can be overridden by configuration files (and
command-line options if applicable).  If this is not desired, you can
disable configuration file processing with the ``_disable_config``
setting::

    defaults = {'file_insertion_enabled': False,
                'raw_enabled': False,
                '_disable_config': True}
    output = docutils.core.publish_string(
        ..., settings_overrides=defaults)

.. _convenience functions: ../api/publisher.html


Via a Configuration File
------------------------

You may secure Docutils via a configuration file:

* if your application executes one of the `Docutils front-end tools`_
  as a separate process;
* if you cannot or choose not to alter the source code of your
  application or the component that calls Docutils; or
* if you want to secure all Docutils deployments system-wide.

If you call Docutils programmatically, it may be preferable to use the
methods described in the section above.

Docutils automatically looks in three places for a configuration file:

* ``/etc/docutils.conf``, for system-wide configuration,
* ``./docutils.conf`` (in the current working directory), for
  project-specific configuration, and
* ``~/.docutils`` (in the user's home directory), for user-specific
  configuration.

These locations can be overridden by the ``DOCUTILSCONFIG``
environment variable.  Details about configuration files, the purpose
of the various locations, and ``DOCUTILSCONFIG`` are available in the
`"Configuration Files"`_ section of `Docutils Configuration`_.

To fully secure a recent Docutils installation, the configuration file
should contain the following lines ::

    [general]
    file-insertion-enabled: off
    raw-enabled: no

and untrusted users must be prevented to modify or create local
configuration files that overwrite these settings.

.. _Docutils front-end tools: ../user/tools.html
.. _"Configuration Files": ../user/config.html#configuration-files
.. _Docutils Configuration: ../user/config.html


Version Applicability
=====================

The "file_insertion_enabled_" and "raw_enabled_" settings were added
to Docutils 0.3.9; previous versions will ignore these settings.

A bug existed in the configuration file handling of these settings in
Docutils 0.4 and earlier: the right-hand-side needed to be left blank
(no values)::

       [general]
       file-insertion-enabled:
       raw-enabled:

The bug was fixed with the 0.4.1 release on 2006-11-12.

The "line_length_limit_" is new in Docutils 0.17.


Related Documents
=================

`Docutils Runtime Settings`_ explains the relationship between
component settings specifications, application settings
specifications, configuration files, and command-line options

`Docutils Configuration`_ describes configuration files (locations,
structure, and syntax), and lists all settings and command-line
options.

.. _Docutils Runtime Settings: ../api/runtime-settings.html
