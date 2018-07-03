"""\
Convert error TADA REASON into short (10 char) ERRCODE.
"""

import re

# Table mapping REGEXP that matches a long-error to desired ERRCODE.
# ERRCODE max len = 10 char
ERRMAP = [ # (ERRCODE, MatchREGEX, Example), ...
    ('MISSFLD',
     re.compile(r"Missing FITS field "),
     'Missing FITS field \"DTPROPID\" in /home2/images/20161101/SO2016B-015.013'
    ),
]

def code_err(reason):
    for code, regex, example in ERRMAP:
        if regex.match(reason):
            return code[:10]
    return 'TADAERR'

    
