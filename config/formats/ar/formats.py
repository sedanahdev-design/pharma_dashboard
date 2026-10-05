"""Number formatting for the Arabic locale, overridden for this app.

Django's stock `ar` locale formats 29.83 as "29,83" - a comma decimal
separator. Every file this app reads and every report it is checked
against writes "29.83", so the stock format turns a quantity of 29.83
into something that reads at a glance as twenty-nine thousand. Grouping
is switched off for the same reason: a bare, unpunctuated number is
unambiguous next to the source spreadsheet.

Dates stay in the day/month/year order the pharmacy's own sheets use.
"""

DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
NUMBER_GROUPING = 0

DATE_FORMAT = "Y/m/d"
DATETIME_FORMAT = "Y/m/d H:i"
SHORT_DATE_FORMAT = "Y/m/d"
