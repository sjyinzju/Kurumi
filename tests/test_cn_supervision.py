from datetime import date, timedelta
from math import exp, nextafter, sqrt

import duckdb

from kurumi.cn_prices import build_supervision
from kurumi.numeric_math import class_id_for_z, install_return_macros


def test_all_boundary_neighbors_match_sql():
    con = duckdb.connect()
    install_return_macros(con)
    for edge, classes in [
        (-1.5, (0, 1, 1)), (-0.5, (1, 2, 2)), (0.0, (2, 3, 4)),
        (0.5, (4, 4, 5)), (1.5, (5, 5, 6)),
    ]:
        for z, expected in zip((nextafter(edge, -10), edge, nextafter(edge, 10)), classes, strict=True):
            assert class_id_for_z(z) == expected
            assert con.execute("SELECT kurumi_class(?)", [z]).fetchone() == (expected,)
    assert con.sql("SELECT kurumi_log_ratio(1.0000000000002, 1.0)").fetchone() == (0.0,)


def test_supervision_uses_calendar_and_masks_boundaries():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE market_calendar (calendar_id VARCHAR, local_trade_date DATE, session_idx INTEGER);
        CREATE TABLE stock_base (
            instrument_id VARCHAR,issuer_id VARCHAR,market_id VARCHAR,local_trade_date DATE,
            asof_utc TIMESTAMPTZ,calendar_id VARCHAR,window_start_date DATE,sigma_60d DOUBLE,
            fundamental_snapshot_id VARCHAR,industry_system VARCHAR,classification_version VARCHAR,
            industry_code_asof VARCHAR,input_valid BOOLEAN,input_invalid_reason VARCHAR,
            session_idx INTEGER,adjusted_close DOUBLE,provenance_id VARCHAR,delisting_date DATE,
            suspension_verified BOOLEAN,quote_valid BOOLEAN);
    """)
    days = [date(2024, 6, 29)] + [date(2024, 7, 1) + timedelta(days=n) for n in range(22)]
    con.executemany("INSERT INTO market_calendar VALUES ('SSE',?,?)", [(d, n) for n, d in enumerate(days)])
    for n, d in enumerate(days):
        suspended = n == 6
        con.execute("""
            INSERT INTO stock_base VALUES
            ('CN-1','CN-1','CN',?,?::DATE+INTERVAL 15 HOUR,'SSE',DATE '2024-02-01',0.02,
              NULL,NULL,NULL,NULL,true,NULL,?,?,'src',NULL,?,?)
        """, [d, d, n, None if suspended else 20 * exp(n * 0.01), suspended, not suspended])
    build_supervision(con)
    no_cross_label = con.execute("""
        SELECT horizon,target_trade_date,invalid_reason,return_log
        FROM labels WHERE local_trade_date=? ORDER BY horizon
    """, [days[0]]).fetchall()
    assert no_cross_label == [(h, days[h], "cross_split", None) for h in (1, 5, 20)]
    labels = con.execute("""
        SELECT horizon,target_trade_date,invalid_reason,return_log,z
        FROM labels WHERE local_trade_date=? ORDER BY horizon
    """, [days[1]]).fetchall()
    assert labels[1] == (5, days[6], "target_suspended", None, None)
    assert abs(labels[0][3] - 0.01) < 1e-12
    assert abs(labels[2][4] - 0.2 / (0.02 * sqrt(20))) < 1e-12
    assert con.sql("SELECT count(*) FROM labels").fetchone()[0] == len(days) * 3
