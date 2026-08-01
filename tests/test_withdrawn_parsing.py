"""Tests for the withdrawn-circulars parser.

These guard the single most dangerous failure mode in the project: silently
reading an *amendment* date as a document's *issue* date. Every temporal metric
we report is computed against issue dates, so a regression here would not crash
anything — it would just quietly make the headline number wrong.

Fixtures below are trimmed from real RBI pages (see docs/adr/0007).
"""

from ingestion.scrapers.rbi_circulars_withdrawn import (
    WithdrawnRecord,
    _fiscal_year_estimate,
    is_nbfc_relevant,
    issue_date_from_detail,
    parse_withdrawn_rows,
)

# Real layout: number, then ISSUE date, then newest-first amendment stamps.
CIC_PAGE = """Master Directions - Reserve Bank of India
RBI/DNBR/2016-17/39
DoR(NBFC).PD.003/03.10.119/2016-17
August 25, 2016
(
Updated as on August 01, 2025
)
(
Updated as on May 05, 2025
)
Master Direction - Core Investment Companies (Reserve Bank) Directions, 2016
"""

# Same content, but the page punctuates the number differently from the listing.
P2P_PAGE = """Master Directions - Reserve Bank of India
RBI/DNBR/2017-18/57
Master Direction DNBR (PD) 090/03.10.124/2017-18
October 04, 2017
(
Updated as on February 27, 2025
)
"""

# The failure mode we are guarding against: an amendment stamp appearing BEFORE
# the issue date in the raw text.
STAMP_FIRST_PAGE = """Notifications - Reserve Bank of India
(Updated as on July 17, 2025)
DoR.FIN.REC.No.45/03.10.119/2023-24
October 19, 2023
(Updated as on July 17, 2025)
"""


def test_reads_issue_date_not_the_newest_amendment():
    assert issue_date_from_detail(CIC_PAGE, "DoR(NBFC).PD.003/03.10.119/2016-17") == "2016-08-25"


def test_matches_when_page_punctuates_the_number_differently():
    # Listing says "DNBR.(PD).090/..."; the page says "DNBR (PD) 090/...".
    assert issue_date_from_detail(P2P_PAGE, "DNBR.(PD).090/03.10.124/2017-18") == "2017-10-04"


def test_ignores_updated_as_on_stamps():
    got = issue_date_from_detail(STAMP_FIRST_PAGE, "DoR.FIN.REC.No.45/03.10.119/2023-24")
    assert got == "2023-10-19", "an 'Updated as on' stamp was mistaken for the issue date"


def test_returns_none_when_the_number_is_absent():
    assert issue_date_from_detail(CIC_PAGE, "DOR.XXX.999/00.00.000/2099-00") is None


def test_fiscal_year_estimate_is_the_earliest_plausible_date():
    # RBI's fiscal year starts 1 April, so 2016-17 -> 2016-04-01 (a lower bound:
    # never later than the truth, so it cannot wrongly exclude a document).
    assert _fiscal_year_estimate("DNBR.PD.002/03.10.119/2016-17") == "2016-04-01"
    assert _fiscal_year_estimate("no-fiscal-year-here") is None


# ---- table parsing ----

INDEX_HTML = """
<html><body>
<table>
  <tr><th>S No.</th><th>Circular Number</th><th>Circular Name/Title</th><th>Date</th></tr>
  <tr><td>1.</td><td>DNBR.PD.002/03.10.119/2016-17</td>
      <td><a href="https://x/Notification.aspx?Id=1">MD - NBFC Acceptance of Public Deposits
      (Updated as on 27-02-2025)</a></td><td>February 27, 2025</td></tr>
  <tr><td>2.</td><td>DBOD.No.BC.61/12.05.001/94-95</td>
      <td>Advances against shares</td><td>July 1, 1994</td></tr>
  <tr><td>3.</td><td>DNBR.PD.002/03.10.119/2016-17</td>
      <td>MD - NBFC Acceptance of Public Deposits</td><td>March 1, 2020</td></tr>
</table>
<table>
  <tr><th>Sr. No.</th><th>Circular Number</th><th>Subject</th><th>Date</th></tr>
  <tr><td>1.</td><td>DoS.CO.PPG.SEC.1/11.01.005/2026-27</td>
      <td>Fair Practices Code</td><td>May 21, 2026</td></tr>
</table>
<table><tr><td>not</td><td>a circular table</td></tr></table>
</body></html>
"""


def test_parses_both_department_tables_and_labels_them():
    rows = parse_withdrawn_rows(INDEX_HTML)
    depts = {r.doc_number: r.department for r in rows}
    assert depts["DNBR.PD.002/03.10.119/2016-17"] == "DoR"
    assert depts["DoS.CO.PPG.SEC.1/11.01.005/2026-27"] == "DoS"


def test_deduplicates_circulars_listed_more_than_once():
    rows = parse_withdrawn_rows(INDEX_HTML)
    numbers = [r.doc_number for r in rows]
    assert numbers.count("DNBR.PD.002/03.10.119/2016-17") == 1


def test_strips_the_updated_as_on_suffix_from_titles():
    rows = parse_withdrawn_rows(INDEX_HTML)
    title = next(r.title for r in rows if r.doc_number.startswith("DNBR.PD.002"))
    assert "Updated as on" not in title
    assert title.endswith("Public Deposits")


def test_listing_date_is_captured_separately_from_issue_date():
    # The listing column is a LAST-UPDATED date; it must never be used as the
    # issue date, so the parser keeps it in its own field and leaves issue_date unset.
    rows = parse_withdrawn_rows(INDEX_HTML)
    row = next(r for r in rows if r.doc_number.startswith("DNBR.PD.002"))
    assert row.listing_date == "2025-02-27"
    assert row.issue_date is None
    assert row.date_source == "unknown"


def test_ignores_tables_that_are_not_circular_lists():
    rows = parse_withdrawn_rows(INDEX_HTML)
    assert all("not" != r.doc_number for r in rows)
    assert len(rows) == 3


def _rec(doc_number: str = "X", title: str = "Y") -> WithdrawnRecord:
    return WithdrawnRecord(doc_number, title, None, None, None, "unknown", "DoR")


def test_nbfc_filter_matches_on_number_or_title():
    assert is_nbfc_relevant(_rec(doc_number="DNBR.PD.002/03.10.119/2016-17"))
    assert is_nbfc_relevant(_rec(title="Master Direction - Core Investment Companies"))
    assert is_nbfc_relevant(_rec(title="Non-Banking Financial Company - Peer to Peer Lending"))
    assert not is_nbfc_relevant(_rec(doc_number="DPSS.CO.PD.1/02.14.006/2018-19",
                                     title="Prepaid Payment Instruments - Interoperability"))
