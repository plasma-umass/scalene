"""Current version of Scalene; reported by --version."""

import datetime
import os
from inspect import getsourcefile

this_file = os.path.abspath(getsourcefile(lambda:0))

scalene_version = "1.5.13"
scalene_date = datetime.datetime.fromtimestamp(os.path.getmtime(this_file)).strftime("%Y/%m/%d")
